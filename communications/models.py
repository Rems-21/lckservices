"""Modèles de génération de messages personnalisés et historique de partage WhatsApp (Section 2.9)."""
from urllib.parse import quote
from django.conf import settings
from django.db import models
from core.models import TimeStampedModel


class MessageTemplate(TimeStampedModel):
    """Modèle de message pré-formaté pour WhatsApp / Notification client."""

    CATEGORIES = [
        ("RECEPTION", "Confirmation de réception colis"),
        ("DEPART", "Avis de départ expédition"),
        ("ARRIVEE", "Avis d'arrivée & disponibilité entrepôt"),
        ("FACTURATION", "Envoi de facture Proforma / Définitive"),
        ("RELANCE", "Relance de solde impayé"),
        ("LIVRAISON", "Confirmation de livraison"),
        ("GENERAL", "Information générale"),
    ]

    code = models.SlugField("Code modèle", max_length=50, unique=True)
    name = models.CharField("Intitulé du modèle", max_length=150)
    category = models.CharField("Catégorie", max_length=25, choices=CATEGORIES, default="GENERAL")
    body_template = models.TextField(
        "Contenu du message",
        help_text=(
            "Variables disponibles : {client_nom}, {dossier_ref}, {mode_transport}, {origine}, {destination}, "
            "{eta}, {colis_code}, {volume_m3}, {poids_kg}, {facture_num}, {montant_total}, {montant_paye}, "
            "{solde_restant}, {lien_document}, {societe}"
        ),
    )
    is_active = models.BooleanField("Actif", default=True)

    class Meta:
        verbose_name = "Modèle de message"
        verbose_name_plural = "Modèles de messages"
        ordering = ["category", "name"]

    def __str__(self):
        return f"{self.name} ({self.get_category_display()})"


class CommunicationLog(TimeStampedModel):
    """Historique des messages générés et partagés aux clients via WhatsApp."""

    CHANNELS = [
        ("WHATSAPP", "WhatsApp"),
        ("MESSAGE_DIRECT", "Copie / Message direct"),
    ]

    client = models.ForeignKey(
        "clients.Client",
        verbose_name="Client destinataire",
        on_delete=models.CASCADE,
        related_name="communications",
    )
    folder = models.ForeignKey(
        "shipments.ShipmentFolder",
        verbose_name="Dossier lié",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="communications",
    )
    parcel = models.ForeignKey(
        "cargo.Parcel",
        verbose_name="Colis lié",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="communications",
    )
    invoice = models.ForeignKey(
        "billing.Invoice",
        verbose_name="Facture liée",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="communications",
    )

    channel = models.CharField("Canal", max_length=20, choices=CHANNELS, default="WHATSAPP")
    recipient_phone = models.CharField("Numéro WhatsApp utilisé", max_length=40)
    subject = models.CharField("Objet", max_length=160, blank=True, default="")
    message_body = models.TextField("Contenu du message généré")
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Généré par",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_communications",
    )

    class Meta:
        verbose_name = "Message envoyé"
        verbose_name_plural = "Historique des communications"
        ordering = ["-created_at"]

    @property
    def whatsapp_link(self) -> str:
        digits = "".join(ch for ch in (self.recipient_phone or "") if ch.isdigit())
        if len(digits) == 9 and digits.startswith("6"):
            digits = f"237{digits}"
        encoded_msg = quote(self.message_body or "")
        if digits:
            return f"https://wa.me/{digits}?text={encoded_msg}"
        return f"https://wa.me/?text={encoded_msg}"

    def __str__(self):
        return f"WhatsApp -> {self.client.name} ({self.created_at:%d/%m/%Y %H:%M})"
