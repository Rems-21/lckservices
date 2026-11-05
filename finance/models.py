"""Modèles de dépenses multi-devises, répartition des coûts, marges et rentabilité (Section 2.6)."""
from decimal import Decimal, ROUND_HALF_UP
from django.conf import settings
from django.db import models
from django.utils import timezone
from core.models import Currency, TimeStampedModel
from core.utils import generate_sequence_code


class ExpenseCategory(TimeStampedModel):
    """Classification des frais opérationnels et douaniers."""

    name = models.CharField("Catégorie de frais", max_length=120, unique=True)
    code = models.CharField("Code analytique", max_length=25, blank=True, default="")
    description = models.CharField("Description", max_length=255, blank=True, default="")

    class Meta:
        verbose_name = "Catégorie de dépense"
        verbose_name_plural = "Catégories de dépenses"
        ordering = ["name"]

    def __str__(self):
        return self.name


class FolderExpense(TimeStampedModel):
    """Dépense engagée sur un dossier d'expédition, avec support multi-devises et justificatif."""

    reference = models.CharField("Référence dépense", max_length=35, unique=True, blank=True)
    folder = models.ForeignKey(
        "shipments.ShipmentFolder",
        verbose_name="Dossier d'expédition",
        on_delete=models.CASCADE,
        related_name="expenses",
    )
    category = models.ForeignKey(
        ExpenseCategory,
        verbose_name="Catégorie de frais",
        on_delete=models.PROTECT,
        related_name="expenses",
    )
    label = models.CharField("Libellé de la dépense", max_length=200)
    vendor_name = models.CharField("Prestataire / Bénéficiaire", max_length=150, blank=True, default="")
    expense_date = models.DateField("Date de la dépense", default=timezone.now, db_index=True)

    # Montant multi-devises converti en FCFA
    amount_original = models.DecimalField("Montant en devise", max_digits=14, decimal_places=2)
    currency = models.ForeignKey(
        Currency,
        verbose_name="Devise",
        on_delete=models.PROTECT,
        related_name="folder_expenses",
    )
    exchange_rate = models.DecimalField("Taux appliqué vers FCFA", max_digits=14, decimal_places=4, default=Decimal("0.0000"), blank=True)
    amount_fcfa = models.DecimalField("Montant converti (FCFA)", max_digits=15, decimal_places=2, default=Decimal("0.00"))

    receipt_file = models.FileField(
        "Pièce justificative",
        upload_to="expenses/%Y/%m/",
        blank=True,
        null=True,
    )
    is_paid = models.BooleanField("Frais déjà payé", default=True)
    payment_date = models.DateField("Date du paiement", null=True, blank=True)
    is_allocatable = models.BooleanField(
        "Inclure dans la répartition des coûts",
        default=True,
        help_text="Décochez uniquement s'il s'agit d'une charge non imputable aux colis.",
    )
    notes = models.TextField("Observations", blank=True, default="")
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Enregistré par",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recorded_expenses",
    )

    class Meta:
        verbose_name = "Dépense de dossier"
        verbose_name_plural = "Dépenses des dossiers"
        ordering = ["-expense_date", "-id"]

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = generate_sequence_code(FolderExpense, "reference", "DEP", pad=4)
        if self.currency_id:
            if self.currency.is_base:
                self.exchange_rate = Decimal("1.0000")
            elif not self.exchange_rate or self.exchange_rate <= 0:
                self.exchange_rate = self.currency.rate_to_fcfa
            self.amount_fcfa = (
                Decimal(str(self.amount_original or 0)) * Decimal(str(self.exchange_rate))
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.reference} — {self.label} ({self.amount_fcfa} FCFA)"


class CostAllocationRun(TimeStampedModel):
    """Historique horodaté d'une opération de répartition des coûts et calcul de rentabilité d'un dossier."""

    ALLOCATION_METHODS = [
        ("VOLUME", "Au prorata du volume (m³)"),
        ("WEIGHT", "Au prorata du poids (kg)"),
        ("VALUE", "Au prorata de la valeur déclarée (FCFA)"),
        ("FLAT", "Répartition forfaitaire (parts égales / manuel)"),
    ]

    MARGIN_TYPES = [
        ("PERCENT", "Marge en pourcentage (%) sur le coût"),
        ("FIXED_PARCEL", "Forfait de marge fixe par colis (FCFA)"),
        ("TARIFF_UNIT", "Tarification commerciale au m³ / kg"),
    ]

    reference = models.CharField("Référence répartition", max_length=35, unique=True, blank=True)
    folder = models.ForeignKey(
        "shipments.ShipmentFolder",
        verbose_name="Dossier d'expédition",
        on_delete=models.CASCADE,
        related_name="allocation_runs",
    )
    allocation_method = models.CharField("Clé de répartition", max_length=15, choices=ALLOCATION_METHODS, default="VOLUME")
    margin_type = models.CharField("Mode de marge commerciale", max_length=20, choices=MARGIN_TYPES, default="PERCENT")
    margin_value = models.DecimalField(
        "Valeur de marge (% ou FCFA / Tarif unitaire)",
        max_digits=14,
        decimal_places=2,
        default=Decimal("25.00"),
    )

    total_expenses_fcfa = models.DecimalField("Total dépenses à répartir (FCFA)", max_digits=15, decimal_places=2, default=Decimal("0.00"))
    total_allocated_cost_fcfa = models.DecimalField("Total coûts imputés (FCFA)", max_digits=15, decimal_places=2, default=Decimal("0.00"))
    total_commercial_fcfa = models.DecimalField("Total commercial recommandé (FCFA)", max_digits=15, decimal_places=2, default=Decimal("0.00"))
    expected_profit_fcfa = models.DecimalField("Rentabilité prévisionnelle (FCFA)", max_digits=15, decimal_places=2, default=Decimal("0.00"))

    is_active_run = models.BooleanField("Répartition active du dossier", default=True)
    notes = models.TextField("Commentaire financier", blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Calculée par",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="allocation_runs",
    )

    class Meta:
        verbose_name = "Répartition financière"
        verbose_name_plural = "Historique des répartitions financières"
        ordering = ["-created_at"]

    @property
    def margin_rate_percent(self) -> Decimal:
        if self.total_commercial_fcfa > 0:
            return ((self.expected_profit_fcfa / self.total_commercial_fcfa) * Decimal("100")).quantize(Decimal("0.01"))
        return Decimal("0.00")

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = generate_sequence_code(CostAllocationRun, "reference", "REP", pad=4)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.reference} — {self.folder.reference} ({self.get_allocation_method_display()})"


class ParcelCostAllocation(TimeStampedModel):
    """Quote-part détaillée d'un colis lors d'une répartition financière, avec ajustement manuel."""

    run = models.ForeignKey(
        CostAllocationRun,
        verbose_name="Répartition",
        on_delete=models.CASCADE,
        related_name="items",
    )
    parcel = models.ForeignKey(
        "cargo.Parcel",
        verbose_name="Colis",
        on_delete=models.CASCADE,
        related_name="cost_allocations",
    )
    basis_quantity = models.DecimalField("Valeur de base (m³/kg/FCFA)", max_digits=15, decimal_places=4, default=Decimal("0.0000"))
    share_percent = models.DecimalField("Quote-part (%)", max_digits=8, decimal_places=4, default=Decimal("0.0000"))
    theoretical_cost_fcfa = models.DecimalField("Coût automatique (FCFA)", max_digits=14, decimal_places=2, default=Decimal("0.00"))
    manual_adjustment_fcfa = models.DecimalField("Ajustement manuel coût (FCFA)", max_digits=14, decimal_places=2, default=Decimal("0.00"))
    final_cost_fcfa = models.DecimalField("Coût de revient retenu (FCFA)", max_digits=14, decimal_places=2, default=Decimal("0.00"))
    margin_amount_fcfa = models.DecimalField("Marge commerciale (FCFA)", max_digits=14, decimal_places=2, default=Decimal("0.00"))
    final_price_fcfa = models.DecimalField("Montant à facturer (FCFA)", max_digits=14, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        verbose_name = "Ligne de répartition colis"
        verbose_name_plural = "Lignes de répartition colis"
        unique_together = [("run", "parcel")]

    @property
    def profit_fcfa(self) -> Decimal:
        return self.final_price_fcfa - self.final_cost_fcfa

    def __str__(self):
        return f"{self.parcel.parcel_code} — Coût: {self.final_cost_fcfa} / Prix: {self.final_price_fcfa} FCFA"
