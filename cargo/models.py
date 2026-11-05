"""Modèles de classification des marchandises et gestion des colis avec calcul automatique du volume en m³ (Section 2.4)."""
import hashlib
import hmac
import uuid
from decimal import Decimal, ROUND_HALF_UP
from django.conf import settings
from django.db import models
from django.db.models import Sum
from core.models import Currency, TimeStampedModel
from core.utils import generate_sequence_code


class CargoCategory(TimeStampedModel):
    """Classification des marchandises (Électronique, Textile, Pièces détachées, etc.)."""

    name = models.CharField("Catégorie de marchandise", max_length=120, unique=True)
    code = models.CharField("Code interne / SH indicatif", max_length=30, blank=True, default="")
    is_fragile_or_special = models.BooleanField("Manutention fragile / spéciale", default=False)
    description = models.CharField("Description", max_length=255, blank=True, default="")

    class Meta:
        verbose_name = "Catégorie de marchandise"
        verbose_name_plural = "Catégories de marchandises"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Parcel(TimeStampedModel):
    """Colis ou lot de marchandises associé à un client et un dossier d'expédition."""

    ITEM_TYPE_CHOICES = [
        ("MARCHANDISE", "Marchandise / Colis"),
        ("VEHICULE", "Véhicule"),
        ("PIECE", "Pièce détachée"),
        ("AUTRE", "Autre"),
    ]

    PACKAGING_CHOICES = [
        ("CARTON", "Carton(s)"),
        ("PALETTE", "Palette(s)"),
        ("CAISSE", "Caisse(s) bois/métal"),
        ("BALLOT", "Ballot(s)"),
        ("SAC", "Sac(s)"),
        ("FUT", "Fût(s) / Bidon(s)"),
        ("COLIS_HORS_GABARIT", "Hors gabarit / Machine"),
        ("AUTRE", "Autre emballage"),
    ]

    PARCEL_STATUS_CHOICES = [
        ("RECU_ORIGINE", "Réceptionné à l'origine"),
        ("CHARGE", "Chargé / Empoté"),
        ("EN_TRANSIT", "En transit"),
        ("ARRIVE", "Arrivé destination"),
        ("DISPONIBLE_ENTREPOT", "Disponible en entrepôt"),
        ("LIVRE", "Livré au client"),
        ("LITIGE", "En incident / Litige"),
    ]

    parcel_code = models.CharField("Code unique colis", max_length=35, unique=True, blank=True, db_index=True)
    verification_token = models.UUIDField("Jeton QR de vérification", default=uuid.uuid4, editable=False, unique=True)

    folder = models.ForeignKey(
        "shipments.ShipmentFolder",
        verbose_name="Dossier d'expédition",
        on_delete=models.CASCADE,
        related_name="parcels",
    )
    client = models.ForeignKey(
        "clients.Client",
        verbose_name="Client destinataire",
        on_delete=models.PROTECT,
        related_name="parcels",
    )
    category = models.ForeignKey(
        CargoCategory,
        verbose_name="Classification marchandise",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="parcels",
    )

    description = models.CharField("Désignation de la marchandise", max_length=255)
    item_type = models.CharField("Type d'article", max_length=20, choices=ITEM_TYPE_CHOICES, default="MARCHANDISE")
    chassis_number = models.CharField("Numéro de châssis (si véhicule)", max_length=80, blank=True, default="")
    contract_file = models.FileField("Contrat / Document attaché", upload_to="contracts/%Y/%m/", null=True, blank=True)
    supplier_name = models.CharField("Fournisseur / Expéditeur d'origine", max_length=150, blank=True, default="")
    supplier_tracking = models.CharField("Réf. fournisseur / Tracking local", max_length=100, blank=True, default="")
    packaging_type = models.CharField("Conditionnement", max_length=25, choices=PACKAGING_CHOICES, default="CARTON")

    # Quantités, poids et dimensions
    quantity = models.PositiveIntegerField("Nombre d'unités / colis", default=1)
    weight_kg = models.DecimalField("Poids total brut (kg)", max_digits=12, decimal_places=3, default=Decimal("0.000"))
    length_cm = models.DecimalField("Longueur unitaire (cm)", max_digits=10, decimal_places=2, default=Decimal("0.00"))
    width_cm = models.DecimalField("Largeur unitaire (cm)", max_digits=10, decimal_places=2, default=Decimal("0.00"))
    height_cm = models.DecimalField("Hauteur unitaire (cm)", max_digits=10, decimal_places=2, default=Decimal("0.00"))
    manual_volume = models.BooleanField(
        "Saisie manuelle du volume m³",
        default=False,
        help_text="Cochez uniquement si le volume total m³ est mesuré globalement sans dimensions L×l×H unitaires.",
    )
    volume_cbm = models.DecimalField("Volume total (m³)", max_digits=12, decimal_places=4, default=Decimal("0.0000"))

    # Valeur déclarée multi-devises -> FCFA
    declared_value = models.DecimalField("Valeur déclarée", max_digits=14, decimal_places=2, default=Decimal("0.00"))
    declared_currency = models.ForeignKey(
        Currency,
        verbose_name="Devise valeur déclarée",
        on_delete=models.PROTECT,
        related_name="declared_parcels",
    )
    exchange_rate = models.DecimalField("Taux appliqué vers FCFA", max_digits=14, decimal_places=4, default=Decimal("0.0000"), blank=True)
    declared_value_fcfa = models.DecimalField("Valeur déclarée (FCFA)", max_digits=15, decimal_places=2, default=Decimal("0.00"))

    # Coûts et facturation rattachés (mis à jour lors de la répartition des frais)
    allocated_cost_fcfa = models.DecimalField("Coût de revient réparti (FCFA)", max_digits=14, decimal_places=2, default=Decimal("0.00"))
    suggested_price_fcfa = models.DecimalField("Montant commercial calculé (FCFA)", max_digits=14, decimal_places=2, default=Decimal("0.00"))
    paid_amount_fcfa = models.DecimalField("Montant encaissé sur cet article (FCFA)", max_digits=14, decimal_places=2, default=Decimal("0.00"))

    status = models.CharField("Statut du colis", max_length=25, choices=PARCEL_STATUS_CHOICES, default="RECU_ORIGINE", db_index=True)
    storage_location = models.CharField("Emplacement entrepôt / Travée", max_length=80, blank=True, default="")
    notes = models.TextField("Remarques / État à réception", blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Enregistré par",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="registered_parcels",
    )

    class Meta:
        verbose_name = "Colis / Marchandise"
        verbose_name_plural = "Colis & Marchandises"
        ordering = ["-created_at"]

    @staticmethod
    def compute_volume_cbm(length_cm, width_cm, height_cm, quantity=1) -> Decimal:
        """Calcule (L × l × H / 1 000 000) × quantité avec précision à 4 décimales."""
        l_val = Decimal(str(length_cm or 0))
        w_val = Decimal(str(width_cm or 0))
        h_val = Decimal(str(height_cm or 0))
        qty = Decimal(str(max(int(quantity or 1), 1)))
        if l_val > 0 and w_val > 0 and h_val > 0:
            cbm = (l_val * w_val * h_val * qty) / Decimal("1000000")
            return cbm.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        return Decimal("0.0000")

    @property
    def volumetric_weight_air_kg(self) -> Decimal:
        """Poids volumétrique aérien standard IATA : 1 m³ = 166.67 kg (ou L×l×H / 6000)."""
        return (self.volume_cbm * Decimal("1000000") / Decimal("6000")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    @property
    def estimated_margin_fcfa(self) -> Decimal:
        return self.suggested_price_fcfa - self.allocated_cost_fcfa

    @property
    def balance_due_fcfa(self) -> Decimal:
        diff = (self.suggested_price_fcfa or Decimal("0.00")) - (self.paid_amount_fcfa or Decimal("0.00"))
        return diff if diff > Decimal("0.00") else Decimal("0.00")

    @property
    def share_token(self) -> str:
        msg = f"lck-shared-invoice-{self.pk}-{self.verification_token}".encode("utf-8")
        return hmac.new(settings.SECRET_KEY.encode("utf-8"), msg, hashlib.sha256).hexdigest()

    def verify_share_token(self, token: str) -> bool:
        return bool(token) and hmac.compare_digest(self.share_token, str(token))

    def recalculate_paid_amount(self, save=True) -> Decimal:
        direct_sum = self.direct_payments.aggregate(s=Sum("amount_fcfa"))["s"]
        if direct_sum is not None:
            paid = direct_sum.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        else:
            # Fallback : si une facture mono-ligne couvre ce colis
            line = (
                self.invoice_lines.select_related("invoice")
                .filter(invoice__invoice_type="DEFINITIVE")
                .exclude(invoice__status="ANNULEE")
                .first()
            )
            if line and line.invoice.lines.count() == 1:
                paid = line.invoice.paid_amount_fcfa
            else:
                paid = Decimal("0.00")
        self.paid_amount_fcfa = paid
        if save:
            Parcel.objects.filter(pk=self.pk).update(paid_amount_fcfa=paid)
        return paid

    def save(self, *args, **kwargs):
        if not self.parcel_code:
            self.parcel_code = generate_sequence_code(Parcel, "parcel_code", "COL", pad=5)
        if not self.manual_volume:
            computed = self.compute_volume_cbm(self.length_cm, self.width_cm, self.height_cm, self.quantity)
            if computed > 0 or self.volume_cbm == 0:
                self.volume_cbm = computed
        if self.declared_currency_id:
            if not self.exchange_rate or self.exchange_rate <= 0:
                self.exchange_rate = self.declared_currency.rate_to_fcfa
            if self.declared_currency.is_base:
                self.exchange_rate = Decimal("1.0000")
            self.declared_value_fcfa = (
                Decimal(str(self.declared_value or 0)) * Decimal(str(self.exchange_rate))
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.parcel_code} — {self.description} ({self.client.name})"
