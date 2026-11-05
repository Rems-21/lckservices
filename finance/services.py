"""
Moteur métier de répartition des frais et de calcul de rentabilité par dossier et par colis (Section 2.6).
Prend en charge :
- Clés : Volume (m³), Poids (kg), Valeur déclarée (FCFA), Forfaitaire (parts égales).
- Ajustement manuel par colis sur le coût ou le montant commercial.
- Marges commerciales : Pourcentage (%), Forfait par colis (FCFA), ou Barème unitaire (m³/kg).
"""
from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction
from django.db.models import Sum
from core.utils import round_money, to_decimal
from .models import CostAllocationRun, ParcelCostAllocation


def compute_folder_allocation_rows(
    folder,
    allocation_method: str = "VOLUME",
    margin_type: str = "PERCENT",
    margin_value: Decimal = Decimal("25.00"),
    manual_cost_adjustments: dict = None,
    manual_prices: dict = None,
):
    """Calcule la simulation complète de répartition des dépenses et marges d'un dossier."""
    manual_cost_adjustments = manual_cost_adjustments or {}
    manual_prices = manual_prices or {}
    margin_val = to_decimal(margin_value, "0.00")

    total_expenses = (
        folder.expenses.filter(is_allocatable=True).aggregate(s=Sum("amount_fcfa"))["s"]
        or Decimal("0.00")
    )
    parcels = list(folder.parcels.select_related("client").order_by("parcel_code"))
    if not parcels:
        return {
            "total_expenses_fcfa": total_expenses,
            "total_allocated_cost_fcfa": Decimal("0.00"),
            "total_commercial_fcfa": Decimal("0.00"),
            "expected_profit_fcfa": Decimal("0.00"),
            "fallback_equal_used": False,
            "rows": [],
        }

    # Extraction de la valeur de base de chaque colis selon la clé choisie
    bases = []
    for p in parcels:
        if allocation_method == "VOLUME":
            b = Decimal(str(p.volume_cbm or 0))
        elif allocation_method == "WEIGHT":
            b = Decimal(str(p.weight_kg or 0))
        elif allocation_method == "VALUE":
            b = Decimal(str(p.declared_value_fcfa or 0))
        else:  # FLAT
            b = Decimal("1.0000")
        bases.append(b)

    total_basis = sum(bases, Decimal("0.0000"))
    fallback_equal = False
    if total_basis <= Decimal("0.0000"):
        fallback_equal = True
        bases = [Decimal("1.0000") for _ in parcels]
        total_basis = Decimal(str(len(parcels)))

    rows = []
    running_theoretical = Decimal("0.00")
    total_allocated = Decimal("0.00")
    total_commercial = Decimal("0.00")

    for idx, parcel in enumerate(parcels):
        basis = bases[idx]
        ratio = (basis / total_basis) if total_basis > 0 else Decimal("0")
        share_pct = (ratio * Decimal("100")).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

        if idx == len(parcels) - 1 and total_expenses > 0:
            theoretical_cost = round_money(total_expenses - running_theoretical)
        else:
            theoretical_cost = round_money(total_expenses * ratio)
            running_theoretical += theoretical_cost

        adj = round_money(manual_cost_adjustments.get(parcel.id, Decimal("0.00")))
        final_cost = max(round_money(theoretical_cost + adj), Decimal("0.00"))

        # Calcul du prix commercial suggéré selon le mode de marge
        if margin_type == "PERCENT":
            suggested_price = round_money(final_cost * (Decimal("1") + (margin_val / Decimal("100"))))
        elif margin_type == "FIXED_PARCEL":
            suggested_price = round_money(final_cost + margin_val)
        else:  # TARIFF_UNIT : tarif au m³ (maritime) ou au kg (aérien)
            unit_rate = margin_val
            if unit_rate <= 0:
                unit_rate = (
                    folder.default_rate_per_cbm
                    if folder.transport_mode == "MARITIME"
                    else folder.default_rate_per_kg
                )
            qty_metric = parcel.volume_cbm if folder.transport_mode == "MARITIME" else parcel.weight_kg
            suggested_price = round_money(Decimal(str(qty_metric or 0)) * Decimal(str(unit_rate or 0)))
            if suggested_price <= 0 and final_cost > 0:
                suggested_price = final_cost

        override_price = manual_prices.get(parcel.id)
        if override_price is not None and str(override_price).strip() != "":
            final_price = max(round_money(override_price), Decimal("0.00"))
        else:
            final_price = suggested_price

        margin_fcfa = round_money(final_price - final_cost)
        total_allocated += final_cost
        total_commercial += final_price

        rows.append(
            {
                "parcel": parcel,
                "basis_quantity": basis.quantize(Decimal("0.0001")),
                "share_percent": share_pct,
                "theoretical_cost_fcfa": theoretical_cost,
                "manual_adjustment_fcfa": adj,
                "final_cost_fcfa": final_cost,
                "margin_amount_fcfa": margin_fcfa,
                "final_price_fcfa": final_price,
                "profit_fcfa": margin_fcfa,
            }
        )

    return {
        "total_expenses_fcfa": round_money(total_expenses),
        "total_allocated_cost_fcfa": round_money(total_allocated),
        "total_commercial_fcfa": round_money(total_commercial),
        "expected_profit_fcfa": round_money(total_commercial - total_expenses),
        "fallback_equal_used": fallback_equal,
        "rows": rows,
    }


@transaction.atomic
def save_folder_allocation_run(
    folder,
    allocation_method: str,
    margin_type: str,
    margin_value: Decimal,
    manual_cost_adjustments: dict = None,
    manual_prices: dict = None,
    notes: str = "",
    user=None,
) -> CostAllocationRun:
    """Exécute et sauvegarde en base InnoDB la répartition des coûts et met à jour les colis du dossier."""
    calc = compute_folder_allocation_rows(
        folder=folder,
        allocation_method=allocation_method,
        margin_type=margin_type,
        margin_value=margin_value,
        manual_cost_adjustments=manual_cost_adjustments,
        manual_prices=manual_prices,
    )

    folder.allocation_runs.filter(is_active_run=True).update(is_active_run=False)

    run = CostAllocationRun.objects.create(
        folder=folder,
        allocation_method=allocation_method,
        margin_type=margin_type,
        margin_value=to_decimal(margin_value, "0.00"),
        total_expenses_fcfa=calc["total_expenses_fcfa"],
        total_allocated_cost_fcfa=calc["total_allocated_cost_fcfa"],
        total_commercial_fcfa=calc["total_commercial_fcfa"],
        expected_profit_fcfa=calc["expected_profit_fcfa"],
        is_active_run=True,
        notes=notes,
        created_by=user,
    )

    for row in calc["rows"]:
        parcel = row["parcel"]
        ParcelCostAllocation.objects.create(
            run=run,
            parcel=parcel,
            basis_quantity=row["basis_quantity"],
            share_percent=row["share_percent"],
            theoretical_cost_fcfa=row["theoretical_cost_fcfa"],
            manual_adjustment_fcfa=row["manual_adjustment_fcfa"],
            final_cost_fcfa=row["final_cost_fcfa"],
            margin_amount_fcfa=row["margin_amount_fcfa"],
            final_price_fcfa=row["final_price_fcfa"],
        )
        parcel.allocated_cost_fcfa = row["final_cost_fcfa"]
        parcel.suggested_price_fcfa = row["final_price_fcfa"]
        parcel.save(update_fields=["allocated_cost_fcfa", "suggested_price_fcfa", "updated_at"])

    return run
