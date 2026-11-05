"""Modèles logistiques : Tracking chronologique, Opérations entrepôt, Livraisons et Incidents/Avaries (Section 2.5)."""
import uuid
from decimal import Decimal
from django.conf import settings
from django.db import models
from django.utils import timezone
from core.models import TimeStampedModel
from core.utils import generate_sequence_code


class TrackingEvent(TimeStampedModel):
    """Événement chronologique de suivi d'acheminement (dossier ou colis)."""

    STAGE_CHOICES = [
        ("RECEPTION_ORIGINE", "Réception entrepôt d'origine"),
        ("CONTROLE_EMBALLAGE", "Contrôle, pesée & étiquetage"),
        ("CHARGEMENT", "Chargement / Empotage conteneur ou palette"),
        ("DEPART", "Départ international (Navire / Vol)"),
        ("TRANSBORDEMENT", "Escale / Transbordement"),
        ("ARRIVEE_PORT_AERO", "Arrivée au port / aéroport de destination"),
        ("DEDOUANEMENT", "Opérations de transit & dédouanement"),
        ("RECEPTION_ENTREPOT", "Réception & dégroupage en entrepôt LCK"),
        ("DISPONIBLE", "Mise à disposition pour enlèvement/livraison"),
        ("LIVRAISON", "Livraison effectuée au client"),
        ("INCIDENT", "Incident / Alerte logistique"),
    ]

    folder = models.ForeignKey(
        "shipments.ShipmentFolder",
        verbose_name="Dossier d'expédition",
        on_delete=models.CASCADE,
        related_name="tracking_events",
    )
    parcel = models.ForeignKey(
        "cargo.Parcel",
        verbose_name="Colis spécifique (optionnel si global dossier)",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="tracking_events",
    )
    stage = models.CharField("Étape d'acheminement", max_length=30, choices=STAGE_CHOICES, db_index=True)
    status_before = models.CharField("Statut avant", max_length=60, blank=True, default="")
    status_after = models.CharField("Statut après", max_length=60, blank=True, default="")
    location_text = models.CharField("Lieu / Localisation", max_length=150)
    event_date = models.DateTimeField("Date et heure du mouvement", default=timezone.now, db_index=True)
    description = models.TextField("Détails / Commentaire opérationnel", blank=True, default="")
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Enregistré par",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recorded_tracking_events",
    )

    class Meta:
        verbose_name = "Mouvement de tracking"
        verbose_name_plural = "Historique des mouvements"
        ordering = ["-event_date", "-id"]

    def __str__(self):
        target = self.parcel.parcel_code if self.parcel_id else self.folder.reference
        return f"[{self.event_date:%d/%m/%Y %H:%M}] {target} — {self.get_stage_display()}"


class WarehouseOperation(TimeStampedModel):
    """Opérations physiques de réception origine, chargement/empotage et réception entrepôt destination."""

    OPERATION_TYPES = [
        ("RECEPTION_ORIGINE", "Réception à l'entrepôt d'origine"),
        ("CHARGEMENT", "Opération de chargement / Empotage"),
        ("RECEPTION_DESTINATION", "Arrivée & Réception en entrepôt de destination (Dépotage)"),
    ]

    CONDITION_CHOICES = [
        ("CONFORME", "Conforme — Bon état apparent"),
        ("ECART_QTE", "Écart de quantité constaté"),
        ("ENDOMMAGE", "Emballage abîmé / Avarie partielle"),
        ("RESERVE", "Réception sous réserve"),
    ]

    reference = models.CharField("N° Opération", max_length=35, unique=True, blank=True)
    operation_type = models.CharField("Type d'opération", max_length=30, choices=OPERATION_TYPES)
    folder = models.ForeignKey(
        "shipments.ShipmentFolder",
        verbose_name="Dossier concerné",
        on_delete=models.CASCADE,
        related_name="warehouse_operations",
    )
    warehouse_name = models.CharField("Entrepôt / Quai / Terminal", max_length=150)
    operation_date = models.DateTimeField("Date & Heure", default=timezone.now)
    parcels_checked_count = models.PositiveIntegerField("Nombre de colis pointés", default=0)
    total_weight_checked_kg = models.DecimalField(
        "Poids total constaté (kg)", max_digits=12, decimal_places=3, default=Decimal("0.000")
    )
    condition_status = models.CharField("État constaté", max_length=20, choices=CONDITION_CHOICES, default="CONFORME")
    notes = models.TextField("Observations / Pointage contradictoire", blank=True, default="")
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Agent / Magasinier",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="warehouse_operations",
    )

    class Meta:
        verbose_name = "Opération d'entrepôt"
        verbose_name_plural = "Opérations d'entrepôt"
        ordering = ["-operation_date"]

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = generate_sequence_code(WarehouseOperation, "reference", "ENT", pad=4)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.reference} — {self.get_operation_type_display()} ({self.folder.reference})"


class Delivery(TimeStampedModel):
    """Bon de livraison / Sortie de marchandises remise au client."""

    delivery_number = models.CharField("N° Bon de livraison", max_length=35, unique=True, blank=True, db_index=True)
    verification_token = models.UUIDField("Jeton QR", default=uuid.uuid4, editable=False, unique=True)

    folder = models.ForeignKey(
        "shipments.ShipmentFolder",
        verbose_name="Dossier d'expédition",
        on_delete=models.PROTECT,
        related_name="deliveries",
    )
    client = models.ForeignKey(
        "clients.Client",
        verbose_name="Client",
        on_delete=models.PROTECT,
        related_name="deliveries",
    )
    parcels = models.ManyToManyField(
        "cargo.Parcel",
        verbose_name="Colis livrés",
        related_name="deliveries",
    )
    invoice = models.ForeignKey(
        "billing.Invoice",
        verbose_name="Facture associée",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deliveries",
    )
    credit_authorization = models.ForeignKey(
        "billing.CreditDeliveryAuthorization",
        verbose_name="Autorisation de livraison à crédit",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deliveries",
    )

    delivery_mode = models.CharField(
        "Mode de remise",
        max_length=25,
        choices=[
            ("ENLEVEMENT_ENTREPOT", "Enlèvement sur site (Entrepôt LCK)"),
            ("LIVRAISON_DOMICILE", "Livraison à l'adresse du client"),
        ],
        default="ENLEVEMENT_ENTREPOT",
    )
    delivery_address = models.CharField("Lieu de remise / Adresse", max_length=255, blank=True, default="")
    recipient_name = models.CharField("Nom du réceptionnaire", max_length=150)
    recipient_phone = models.CharField("Téléphone du réceptionnaire", max_length=40, blank=True, default="")
    recipient_id_number = models.CharField("N° CNI / Passeport réceptionnaire", max_length=80, blank=True, default="")
    delivered_at = models.DateTimeField("Date et heure de livraison", default=timezone.now)
    notes = models.TextField("Réserves éventuelles / Observations", blank=True, default="")
    delivered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Délivré par",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="processed_deliveries",
    )

    class Meta:
        verbose_name = "Livraison"
        verbose_name_plural = "Livraisons"
        ordering = ["-delivered_at"]

    def save(self, *args, **kwargs):
        if not self.delivery_number:
            self.delivery_number = generate_sequence_code(Delivery, "delivery_number", "BL", pad=4)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.delivery_number} — {self.client.name}"


class Incident(TimeStampedModel):
    """Gestion des incidents, avaries, manquants et litiges (Section 2.5)."""

    INCIDENT_TYPES = [
        ("AVARIE", "Avarie / Marchandise endommagée"),
        ("MANQUANT", "Perte partielle ou colis manquant"),
        ("RETARD", "Retard d'acheminement majeur"),
        ("BLOCAGE_DOUANE", "Blocage / Inspection douanière"),
        ("LITIGE_CLIENT", "Litige commercial / Réclamation client"),
        ("AUTRE", "Autre incident"),
    ]

    SEVERITY_CHOICES = [
        ("FAIBLE", "Faible"),
        ("MOYENNE", "Moyenne"),
        ("CRITIQUE", "Critique"),
    ]

    STATUS_CHOICES = [
        ("EN_COURS", "Ouvert / En cours de traitement"),
        ("RESOLU", "Résolu / Indemnisé"),
        ("CLOS", "Clôturé sans suite"),
    ]

    reference = models.CharField("Référence incident", max_length=35, unique=True, blank=True)
    folder = models.ForeignKey(
        "shipments.ShipmentFolder",
        verbose_name="Dossier concerné",
        on_delete=models.CASCADE,
        related_name="incidents",
    )
    parcel = models.ForeignKey(
        "cargo.Parcel",
        verbose_name="Colis concerné",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="incidents",
    )
    client = models.ForeignKey(
        "clients.Client",
        verbose_name="Client impacté",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="incidents",
    )

    incident_type = models.CharField("Nature de l'incident", max_length=25, choices=INCIDENT_TYPES, default="AVARIE")
    severity = models.CharField("Gravité", max_length=15, choices=SEVERITY_CHOICES, default="MOYENNE")
    status = models.CharField("Statut", max_length=15, choices=STATUS_CHOICES, default="EN_COURS", db_index=True)

    title = models.CharField("Objet de l'incident", max_length=180)
    description = models.TextField("Constat détaillé")
    estimated_damage_fcfa = models.DecimalField(
        "Préjudice estimé (FCFA)", max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    compensation_fcfa = models.DecimalField(
        "Montant dédommagement / prise en charge (FCFA)", max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    resolution_notes = models.TextField("Actions correctives / Résolution", blank=True, default="")
    attachment = models.FileField("Photo / Constat joint", upload_to="incidents/%Y/%m/", blank=True, null=True)
    reported_at = models.DateTimeField("Date du constat", default=timezone.now)
    resolved_at = models.DateTimeField("Date de résolution", null=True, blank=True)
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Déclaré par",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reported_incidents",
    )

    class Meta:
        verbose_name = "Incident / Litige"
        verbose_name_plural = "Incidents, Avaries & Litiges"
        ordering = ["-reported_at"]

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = generate_sequence_code(Incident, "reference", "INC", pad=4)
        if self.parcel_id and not self.client_id:
            self.client_id = self.parcel.client_id
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.reference} — {self.title}"
