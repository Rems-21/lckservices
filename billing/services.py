"""Services de génération automatique des factures Proforma/Définitives et de conversion (Section 2.7)."""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from .models import Invoice, InvoiceLine


@transaction.atomic
def generate_folder_invoices(folder, invoice_type: str = "DEFINITIVE", client_id: int = None, user=None) -> list:
    """
    Génère automatiquement une facture (Proforma ou Définitive) par client ayant des colis dans le dossier,
    en exploitant les montants commerciaux issus de la répartition des coûts ou les tarifs indicatifs m³/kg.
    """
    parcels_qs = folder.parcels.select_related("client").order_by("parcel_code")
    if client_id:
        parcels_qs = parcels_qs.filter(client_id=client_id)

    grouped = defaultdict(list)
    for parcel in parcels_qs:
        # Éviter de facturer deux fois en Définitive un même colis déjà présent sur une facture définitive active
        if invoice_type == "DEFINITIVE":
            already_billed = parcel.invoice_lines.filter(
                invoice__invoice_type="DEFINITIVE",
            ).exclude(invoice__status="ANNULEE").exists()
            if already_billed:
                continue
        grouped[parcel.client].append(parcel)

    created_invoices = []
    today = timezone.localdate()

    for client, client_parcels in grouped.items():
        if not client_parcels:
            continue
        inv = Invoice.objects.create(
            invoice_type=invoice_type,
            status="PROFORMA" if invoice_type == "PROFORMA" else "EMISE",
            client=client,
            folder=folder,
            issue_date=today,
            due_date=today + timedelta(days=7),
            notes=f"Facturation automatique — Dossier {folder.reference} ({folder.get_transport_mode_display()} {folder.origin.city} -> {folder.destination.city}).",
            created_by=user,
        )

        for p in client_parcels:
            desc = (
                f"[{p.parcel_code}] {p.description} — {p.quantity} {p.get_packaging_type_display()} "
                f"({p.volume_cbm} m³ / {p.weight_kg} kg)"
            )
            if p.suggested_price_fcfa and p.suggested_price_fcfa > Decimal("0.00"):
                InvoiceLine.objects.create(
                    invoice=inv,
                    parcel=p,
                    description=desc,
                    quantity=Decimal("1.0000"),
                    unit_label="lot",
                    unit_price_fcfa=p.suggested_price_fcfa,
                )
            elif folder.transport_mode == "MARITIME" and folder.default_rate_per_cbm > 0 and p.volume_cbm > 0:
                InvoiceLine.objects.create(
                    invoice=inv,
                    parcel=p,
                    description=desc,
                    quantity=p.volume_cbm,
                    unit_label="m³",
                    unit_price_fcfa=folder.default_rate_per_cbm,
                )
            elif folder.transport_mode == "AERIEN" and folder.default_rate_per_kg > 0 and p.weight_kg > 0:
                InvoiceLine.objects.create(
                    invoice=inv,
                    parcel=p,
                    description=desc,
                    quantity=p.weight_kg,
                    unit_label="kg",
                    unit_price_fcfa=folder.default_rate_per_kg,
                )
            else:
                InvoiceLine.objects.create(
                    invoice=inv,
                    parcel=p,
                    description=desc,
                    quantity=Decimal("1.0000"),
                    unit_label="forfait",
                    unit_price_fcfa=p.allocated_cost_fcfa or Decimal("0.00"),
                )

        inv.recalculate_totals(save=True)
        created_invoices.append(inv)

    return created_invoices


@transaction.atomic
def convert_proforma_to_definitive(proforma: Invoice, user=None) -> Invoice:
    """Convertit une facture Proforma en facture Définitive officielle."""
    if hasattr(proforma, "converted_definitive") and proforma.converted_definitive:
        return proforma.converted_definitive

    today = timezone.localdate()
    definitive = Invoice.objects.create(
        invoice_type="DEFINITIVE",
        status="EMISE",
        client=proforma.client,
        folder=proforma.folder,
        source_proforma=proforma,
        issue_date=today,
        due_date=proforma.due_date or (today + timedelta(days=7)),
        discount_fcfa=proforma.discount_fcfa,
        tax_rate_percent=proforma.tax_rate_percent,
        notes=proforma.notes,
        created_by=user,
    )
    for line in proforma.lines.all():
        InvoiceLine.objects.create(
            invoice=definitive,
            parcel=line.parcel,
            description=line.description,
            quantity=line.quantity,
            unit_label=line.unit_label,
            unit_price_fcfa=line.unit_price_fcfa,
        )
    definitive.recalculate_totals(save=True)
    return definitive


@transaction.atomic
def sync_or_create_parcel_invoice(parcel, user=None, create_if_missing: bool = True):
    """
    Synchronise le montant facturé (suggested_price_fcfa / cost_share) d'un colis
    avec une facture Définitive rattachée (style MTsarl + conformité Cahier des Charges LCK).
    """
    line = (
        parcel.invoice_lines.select_related("invoice")
        .filter(invoice__invoice_type="DEFINITIVE")
        .exclude(invoice__status="ANNULEE")
        .first()
    )
    desc = (
        f"[{parcel.parcel_code}] {parcel.description} — {parcel.quantity} u. "
        f"({parcel.volume_cbm} m³ / {parcel.weight_kg} kg)"
    )
    price = Decimal(str(parcel.suggested_price_fcfa or "0.00"))

    if line:
        inv = line.invoice
        if inv.client_id != parcel.client_id and inv.lines.count() == 1:
            inv.client = parcel.client
            inv.save(update_fields=["client", "updated_at"])
        line.description = desc
        line.quantity = Decimal("1.0000")
        line.unit_label = "lot"
        line.unit_price_fcfa = price
        line.save()
        inv.recalculate_totals(save=True)
        parcel.recalculate_paid_amount(save=True)
        return inv

    if not create_if_missing:
        return None

    today = timezone.localdate()
    inv = (
        Invoice.objects.filter(
            folder=parcel.folder,
            client=parcel.client,
            invoice_type="DEFINITIVE",
        )
        .exclude(status="ANNULEE")
        .order_by("-id")
        .first()
    )
    if not inv:
        inv = Invoice.objects.create(
            invoice_type="DEFINITIVE",
            status="EMISE",
            client=parcel.client,
            folder=parcel.folder,
            issue_date=today,
            due_date=today + timedelta(days=7),
            notes=f"Facture de groupage — Dossier {parcel.folder.reference}.",
            created_by=user,
        )
    InvoiceLine.objects.create(
        invoice=inv,
        parcel=parcel,
        description=desc,
        quantity=Decimal("1.0000"),
        unit_label="lot",
        unit_price_fcfa=price,
    )
    inv.recalculate_totals(save=True)
    parcel.recalculate_paid_amount(save=True)
    return inv


@transaction.atomic
def record_parcel_payment(parcel, amount_fcfa: Decimal, payment_method: str, payment_date=None, user=None, notes: str = ""):
    """Enregistre un encaissement direct sur un article/colis depuis la fiche dossier (modale MTsarl)."""
    inv = sync_or_create_parcel_invoice(parcel, user=user, create_if_missing=True)
    pay_date = payment_date or timezone.localdate()
    payment = inv.payments.create(
        parcel=parcel,
        client=parcel.client,
        payment_date=pay_date,
        amount_fcfa=amount_fcfa,
        payment_method=payment_method,
        notes=notes or f"Encaissement colis {parcel.parcel_code}",
        received_by=user,
    )
    if inv.status == "PAYEE":
        inv.credit_authorizations.filter(status="ACTIVE").update(status="REGULARISEE")
    parcel.recalculate_paid_amount(save=True)
    return payment
