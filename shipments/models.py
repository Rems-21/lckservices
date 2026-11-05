"""Modèles des ports/aéroports et dossiers d'expédition maritime et aérien (Section 2.3)."""
from decimal import Decimal
from django.conf import settings
from django.db import models
from django.db.models import Sum
from core.models import TimeStampedModel
from core.utils import generate_sequence_code


class Location(TimeStampedModel):
    """Port maritime, aéroport international ou plateforme logistique."""

    LOCATION_TYPES = [
        ("PORT", "Port Maritime"),
        ("AEROPORT", "Aéroport International"),
        ("MIXTE", "Plateforme / Ville Mixte"),
    ]

    name = models.CharField("Nom du port / aéroport", max_length=150)
    code = models.CharField("Code UN/LOCODE ou IATA", max_length=20, unique=True)
    city = models.CharField("Ville", max_length=100)
    country = models.CharField("Pays", max_length=100)
    location_type = models.CharField("Type", max_length=20, choices=LOCATION_TYPES, default="MIXTE")
    is_active = models.BooleanField("Actif", default=True)

    class Meta:
        verbose_name = "Port / Aéroport"
        verbose_name_plural = "Ports & Aéroports"
        ordering = ["country", "name"]

    def __str__(self):
        return f"{self.name} ({self.code}) — {self.country}"

    @classmethod
    def resolve_from_text(cls, raw_text: str, transport_mode: str = "MARITIME"):
        """Résout ou crée automatiquement un port/aéroport à partir d'un texte libre (style MTsarl)."""
        cleaned = (raw_text or "").strip()
        if not cleaned:
            fallback = cls.objects.filter(is_active=True).first()
            if fallback:
                return fallback
            return cls.objects.create(
                name="Douala",
                code="CMDLA",
                city="Douala",
                country="Cameroun",
                location_type="PORT" if transport_mode == "MARITIME" else "AEROPORT",
            )

        existing = (
            cls.objects.filter(models.Q(code__iexact=cleaned) | models.Q(name__iexact=cleaned) | models.Q(city__iexact=cleaned)).first()
            or cls.objects.filter(models.Q(name__icontains=cleaned) | models.Q(city__icontains=cleaned)).first()
        )
        if existing:
            return existing

        # Construction d'un code unique propre
        alpha = "".join(ch for ch in cleaned.upper() if ch.isalnum())[:8] or "LOC"
        code_candidate = alpha
        idx = 1
        while cls.objects.filter(code=code_candidate).exists():
            idx += 1
            code_candidate = f"{alpha[:6]}{idx}"

        loc_type = "AEROPORT" if transport_mode == "AERIEN" else "PORT"
        parts = [p.strip() for p in cleaned.replace("—", ",").split(",") if p.strip()]
        city_val = parts[0][:100]
        country_val = parts[1][:100] if len(parts) > 1 else "International"
        return cls.objects.create(
            name=cleaned[:150],
            code=code_candidate,
            city=city_val,
            country=country_val,
            location_type=loc_type,
        )


class ShipmentFolder(TimeStampedModel):
    """Dossier d'expédition ou de groupage maritime / aérien."""

    TRANSPORT_MODES = [
        ("MARITIME", "Maritime"),
        ("AERIEN", "Aérien"),
    ]

    OPERATION_TYPES = [
        ("GROUPAGE", "Groupage (LCL / Consolidé)"),
        ("COMPLET", "Conteneur complet (FCL) / Lot dédié"),
        ("TRANSIT", "Transit & Dédouanement direct"),
    ]

    CONTAINER_TYPES = [
        ("", "Non applicable / Aérien"),
        ("20GP", "20 Pieds (20' GP)"),
        ("40GP", "40 Pieds (40' GP)"),
        ("40HC", "40 HC (High Cube)"),
        ("LCL", "Groupage partagé (LCL)"),
        ("VRAC", "Vrac / Roro"),
        ("AUTRE", "Autre"),
    ]

    STATUS_CHOICES = [
        ("BROUILLON", "Brouillon"),
        ("OUVERT", "Ouvert (Collecte & Réception)"),
        ("CHARGE", "Chargé / Empoté"),
        ("EN_TRANSIT", "En transit international"),
        ("ARRIVE", "Arrivé au port / aéroport"),
        ("DEDOUANEMENT", "En formalités douanières"),
        ("DISPONIBLE_ENTREPOT", "Réceptionné en entrepôt (Dégroupé)"),
        ("CLOTURE", "Clôturé"),
        ("ANNULE", "Annulé"),
    ]

    reference = models.CharField("Référence dossier", max_length=35, unique=True, blank=True, db_index=True)
    title = models.CharField("Intitulé / Campagne de groupage", max_length=180, blank=True, default="")
    transport_mode = models.CharField("Mode de transport", max_length=15, choices=TRANSPORT_MODES, default="MARITIME", db_index=True)
    operation_type = models.CharField("Type d'opération", max_length=20, choices=OPERATION_TYPES, default="GROUPAGE")
    status = models.CharField("Statut du dossier", max_length=25, choices=STATUS_CHOICES, default="OUVERT", db_index=True)

    # Origine et destination
    origin = models.ForeignKey(
        Location,
        verbose_name="Port / Aéroport de départ",
        on_delete=models.PROTECT,
        related_name="departing_folders",
    )
    destination = models.ForeignKey(
        Location,
        verbose_name="Port / Aéroport d'arrivée",
        on_delete=models.PROTECT,
        related_name="arriving_folders",
    )

    # Informations transport maritime
    shipping_line = models.CharField("Compagnie maritime", max_length=120, blank=True, default="")
    vessel_name = models.CharField("Nom du navire", max_length=120, blank=True, default="")
    voyage_number = models.CharField("N° de voyage", max_length=60, blank=True, default="")
    container_number = models.CharField("N° de conteneur", max_length=60, blank=True, default="", db_index=True)
    container_type = models.CharField("Type de conteneur", max_length=15, choices=CONTAINER_TYPES, blank=True, default="")
    seal_number = models.CharField("N° de plomb / scellé", max_length=60, blank=True, default="")
    bl_number = models.CharField("N° Connaissement (B/L)", max_length=80, blank=True, default="", db_index=True)

    # Informations transport aérien
    airline_name = models.CharField("Compagnie aérienne", max_length=120, blank=True, default="")
    flight_number = models.CharField("N° de vol", max_length=60, blank=True, default="")
    awb_number = models.CharField("N° Lettre de transport aérien (AWB)", max_length=80, blank=True, default="", db_index=True)

    # Transitaire / Armateur (parité MTsarl)
    forwarder = models.CharField("Transitaire / Armateur", max_length=150, blank=True, default="")

    # Dates clés
    etd = models.DateField("Date de départ prévue (ETD)", null=True, blank=True)
    atd = models.DateField("Date de départ réelle (ATD)", null=True, blank=True)
    eta = models.DateField("Date d'arrivée prévue (ETA)", null=True, blank=True)
    ata = models.DateField("Date d'arrivée réelle (ATA)", null=True, blank=True)
    closed_at = models.DateTimeField("Date de clôture", null=True, blank=True)

    @property
    def departure_date(self):
        return self.etd

    @departure_date.setter
    def departure_date(self, val):
        self.etd = val

    @property
    def arrival_estimated_date(self):
        return self.eta

    @arrival_estimated_date.setter
    def arrival_estimated_date(self, val):
        self.eta = val

    @property
    def arrival_actual_date(self):
        return self.ata

    @arrival_actual_date.setter
    def arrival_actual_date(self, val):
        self.ata = val

    # Tarifs indicatifs de référence du dossier (optionnels pour aider à la facturation)
    default_rate_per_cbm = models.DecimalField(
        "Tarif indicatif au m³ (FCFA)",
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    default_rate_per_kg = models.DecimalField(
        "Tarif indicatif au kg (FCFA)",
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    notes = models.TextField("Observations opérationnelles", blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Créé par",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_folders",
    )

    class Meta:
        verbose_name = "Dossier d'expédition"
        verbose_name_plural = "Dossiers d'expédition"
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.reference:
            prefix = "MAR" if self.transport_mode == "MARITIME" else "AER"
            self.reference = generate_sequence_code(ShipmentFolder, "reference", prefix, pad=4)
        super().save(*args, **kwargs)

    @property
    def is_active_folder(self) -> bool:
        return self.status not in ("CLOTURE", "ANNULE")

    @property
    def transport_doc_ref(self) -> str:
        if self.transport_mode == "MARITIME":
            return f"B/L: {self.bl_number or 'N/A'}"
        return f"AWB: {self.awb_number or 'N/A'}"

    @property
    def carrier_summary(self) -> str:
        if self.transport_mode == "MARITIME":
            parts = [p for p in (self.shipping_line, self.vessel_name, self.container_number) if p]
            return " • ".join(parts) if parts else "Maritime"
        parts = [p for p in (self.airline_name, self.flight_number) if p]
        return " • ".join(parts) if parts else "Aérien"

    @property
    def total_parcels_count(self) -> int:
        return self.parcels.count()

    @property
    def total_units_count(self) -> int:
        return self.parcels.aggregate(s=Sum("quantity"))["s"] or 0

    @property
    def total_weight_kg(self) -> Decimal:
        return self.parcels.aggregate(s=Sum("weight_kg"))["s"] or Decimal("0.000")

    @property
    def total_volume_cbm(self) -> Decimal:
        return self.parcels.aggregate(s=Sum("volume_cbm"))["s"] or Decimal("0.0000")

    @property
    def total_declared_value_fcfa(self) -> Decimal:
        return self.parcels.aggregate(s=Sum("declared_value_fcfa"))["s"] or Decimal("0.00")

    @property
    def total_expenses_fcfa(self) -> Decimal:
        return self.expenses.aggregate(s=Sum("amount_fcfa"))["s"] or Decimal("0.00")

    @property
    def total_invoiced_fcfa(self) -> Decimal:
        return (
            self.invoices.filter(invoice_type="DEFINITIVE")
            .exclude(status="ANNULEE")
            .aggregate(s=Sum("total_amount_fcfa"))["s"]
            or Decimal("0.00")
        )

    @property
    def total_paid_fcfa(self) -> Decimal:
        return (
            self.invoices.filter(invoice_type="DEFINITIVE")
            .exclude(status="ANNULEE")
            .aggregate(s=Sum("paid_amount_fcfa"))["s"]
            or Decimal("0.00")
        )

    @property
    def total_cost_share_fcfa(self) -> Decimal:
        """Total des montants facturés aux clients sur les colis du dossier."""
        inv_sum = self.total_invoiced_fcfa
        parcel_sum = self.parcels.aggregate(s=Sum("suggested_price_fcfa"))["s"] or Decimal("0.00")
        return inv_sum if inv_sum >= parcel_sum else parcel_sum

    @property
    def net_profit_fcfa(self) -> Decimal:
        return self.total_cost_share_fcfa - self.total_expenses_fcfa

    @property
    def margin_percent(self) -> Decimal:
        rev = self.total_invoiced_fcfa
        if rev > 0:
            return ((self.net_profit_fcfa / rev) * Decimal("100")).quantize(Decimal("0.01"))
        return Decimal("0.00")

    def __str__(self):
        label = f" — {self.title}" if self.title else ""
        return f"{self.reference} ({self.get_transport_mode_display()}){label}"
