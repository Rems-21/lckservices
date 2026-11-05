"""Modèle central de Gestion Électronique des Documents (GED) — B/L, AWB, Contrats, Justificatifs (Section 2.8)."""
import os
from django.conf import settings
from django.db import models
from core.models import TimeStampedModel
from core.utils import generate_sequence_code


class Document(TimeStampedModel):
    DOCUMENT_TYPES = [
        ("BL_MARITIME", "Connaissement maritime (B/L)"),
        ("AWB_AERIEN", "Lettre de transport aérien (AWB)"),
        ("CONTRAT_TRANSPORT", "Contrat de transport"),
        ("PACKING_LIST", "Packing List / Liste de colisage"),
        ("FACTURE_FOURNISSEUR", "Facture commerciale marchandise"),
        ("DECLARATION_DOUANE", "Déclaration / Document douanier"),
        ("JUSTIFICATIF_DEPENSE", "Justificatif de dépense"),
        ("MANIFESTE", "Manifeste de chargement"),
        ("BON_LIVRAISON_SIGNE", "Bon de livraison signé"),
        ("AUTRE", "Autre pièce"),
    ]

    reference = models.CharField("Référence GED", max_length=35, unique=True, blank=True)
    doc_type = models.CharField("Type de document", max_length=30, choices=DOCUMENT_TYPES, default="AUTRE", db_index=True)
    title = models.CharField("Titre du document", max_length=200)
    external_number = models.CharField("N° officiel (B/L, AWB, Déclaration...)", max_length=100, blank=True, default="")
    file = models.FileField("Fichier numérique", upload_to="documents/%Y/%m/")

    folder = models.ForeignKey(
        "shipments.ShipmentFolder",
        verbose_name="Dossier associé",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="documents",
    )
    parcel = models.ForeignKey(
        "cargo.Parcel",
        verbose_name="Colis associé",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents",
    )
    client = models.ForeignKey(
        "clients.Client",
        verbose_name="Client associé",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents",
    )
    invoice = models.ForeignKey(
        "billing.Invoice",
        verbose_name="Facture associée",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents",
    )

    notes = models.CharField("Commentaire", max_length=255, blank=True, default="")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Importé par",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_documents",
    )

    class Meta:
        verbose_name = "Document"
        verbose_name_plural = "Documents"
        ordering = ["-created_at"]

    @property
    def filename(self) -> str:
        return os.path.basename(self.file.name) if self.file else ""

    @property
    def extension(self) -> str:
        _, ext = os.path.splitext(self.filename)
        return ext.lower().lstrip(".")

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = generate_sequence_code(Document, "reference", "DOC", pad=4)
        if self.parcel_id and not self.folder_id:
            self.folder_id = self.parcel.folder_id
        if self.parcel_id and not self.client_id:
            self.client_id = self.parcel.client_id
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.reference} — {self.title} ({self.get_doc_type_display()})"
