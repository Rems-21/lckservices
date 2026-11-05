"""Modèles de facturation (Proforma & Définitive), paiements, reçus, créances et crédit (Section 2.7)."""
import uuid
from decimal import Decimal, ROUND_HALF_UP
from django.conf import settings
from django.db import models
from django.db.models import Sum
from django.utils import timezone
from core.models import TimeStampedModel
from core.utils import generate_sequence_code


class Invoice(TimeStampedModel):
    """Facture Proforma ou Définitive libellée en FCFA."""

    INVOICE_TYPES = [
        ("PROFORMA", "Facture Proforma"),
        ("DEFINITIVE", "Facture Définitive"),
    ]

    STATUS_CHOICES = [
        ("PROFORMA", "Proforma (Devis / Pré-facture)"),
        ("EMISE", "Émise — En attente de paiement"),
        ("PARTIELLEMENT_PAYEE", "Partiellement payée"),
        ("PAYEE", "Payée intégralement"),
        ("ANNULEE", "Annulée"),
    ]

    number = models.CharField("Numéro de facture", max_length=35, unique=True, blank=True, db_index=True)
    verification_token = models.UUIDField("Jeton QR d'authenticité", default=uuid.uuid4, editable=False, unique=True)
    invoice_type = models.CharField("Type de facture", max_length=15, choices=INVOICE_TYPES, default="DEFINITIVE", db_index=True)
    status = models.CharField("Statut", max_length=25, choices=STATUS_CHOICES, default="EMISE", db_index=True)

    client = models.ForeignKey(
        "clients.Client",
        verbose_name="Client",
        on_delete=models.PROTECT,
        related_name="invoices",
    )
    folder = models.ForeignKey(
        "shipments.ShipmentFolder",
        verbose_name="Dossier d'expédition",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoices",
    )
    source_proforma = models.OneToOneField(
        "self",
        verbose_name="Proforma d'origine",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="converted_definitive",
    )

    issue_date = models.DateField("Date d'émission", default=timezone.now, db_index=True)
    due_date = models.DateField("Date d'échéance", null=True, blank=True)

    subtotal_fcfa = models.DecimalField("Sous-total HT (FCFA)", max_digits=15, decimal_places=2, default=Decimal("0.00"))
    discount_fcfa = models.DecimalField("Remise commerciale (FCFA)", max_digits=14, decimal_places=2, default=Decimal("0.00"))
    tax_rate_percent = models.DecimalField("Taux TVA / Taxe (%)", max_digits=5, decimal_places=2, default=Decimal("0.00"))
    tax_amount_fcfa = models.DecimalField("Montant Taxe (FCFA)", max_digits=14, decimal_places=2, default=Decimal("0.00"))
    total_amount_fcfa = models.DecimalField("Net à payer TTC (FCFA)", max_digits=15, decimal_places=2, default=Decimal("0.00"))
    paid_amount_fcfa = models.DecimalField("Montant encaissé (FCFA)", max_digits=15, decimal_places=2, default=Decimal("0.00"))

    notes = models.TextField("Conditions / Notes figurant sur la facture", blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Émise par",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_invoices",
    )

    class Meta:
        verbose_name = "Facture"
        verbose_name_plural = "Factures"
        ordering = ["-issue_date", "-id"]

    @property
    def balance_due_fcfa(self) -> Decimal:
        if self.status == "ANNULEE" or self.invoice_type == "PROFORMA":
            return Decimal("0.00")
        diff = self.total_amount_fcfa - self.paid_amount_fcfa
        return diff if diff > Decimal("0.00") else Decimal("0.00")

    @property
    def is_settled_for_delivery(self) -> bool:
        """Indique si la facture permet la livraison (soldée ou couverte par une autorisation de crédit active)."""
        if self.invoice_type == "DEFINITIVE" and self.status == "PAYEE":
            return True
        return self.credit_authorizations.filter(status="ACTIVE").exists()

    @property
    def is_overdue(self) -> bool:
        if self.due_date and self.balance_due_fcfa > 0:
            return self.due_date < timezone.localdate()
        return False

    def save(self, *args, **kwargs):
        if not self.number:
            prefix = "PRO" if self.invoice_type == "PROFORMA" else "FAC"
            self.number = generate_sequence_code(Invoice, "number", prefix, pad=4)
        if self.invoice_type == "PROFORMA" and self.status == "EMISE":
            self.status = "PROFORMA"
        super().save(*args, **kwargs)

    def recalculate_totals(self, save=True):
        """Recalcule automatiquement les montants HT/TTC, les encaissements et le statut."""
        lines_sum = self.lines.aggregate(s=Sum("line_total_fcfa"))["s"] or Decimal("0.00")
        self.subtotal_fcfa = lines_sum.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        taxable_base = max(self.subtotal_fcfa - (self.discount_fcfa or Decimal("0.00")), Decimal("0.00"))
        self.tax_amount_fcfa = (
            taxable_base * Decimal(str(self.tax_rate_percent or 0)) / Decimal("100")
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        self.total_amount_fcfa = (taxable_base + self.tax_amount_fcfa).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        paid_sum = self.payments.aggregate(s=Sum("amount_fcfa"))["s"] or Decimal("0.00")
        self.paid_amount_fcfa = paid_sum.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        if self.status != "ANNULEE":
            if self.invoice_type == "PROFORMA":
                self.status = "PROFORMA"
            else:
                if self.total_amount_fcfa > 0 and self.paid_amount_fcfa >= self.total_amount_fcfa:
                    self.status = "PAYEE"
                elif self.paid_amount_fcfa > 0:
                    self.status = "PARTIELLEMENT_PAYEE"
                else:
                    self.status = "EMISE"

        if save:
            self.save()
        return self

    def __str__(self):
        return f"{self.number} — {self.client.name} ({self.total_amount_fcfa} FCFA)"


class InvoiceLine(models.Model):
    """Ligne de facturation (colis de groupage, prestation douanière, livraison, frais dossier)."""

    invoice = models.ForeignKey(Invoice, verbose_name="Facture", on_delete=models.CASCADE, related_name="lines")
    parcel = models.ForeignKey(
        "cargo.Parcel",
        verbose_name="Colis rattaché",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoice_lines",
    )
    description = models.CharField("Désignation", max_length=255)
    quantity = models.DecimalField("Quantité / Volume / Poids", max_digits=12, decimal_places=4, default=Decimal("1.0000"))
    unit_label = models.CharField("Unité", max_length=20, default="forfait")
    unit_price_fcfa = models.DecimalField("Prix unitaire (FCFA)", max_digits=14, decimal_places=2, default=Decimal("0.00"))
    line_total_fcfa = models.DecimalField("Montant total ligne (FCFA)", max_digits=15, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        verbose_name = "Ligne de facture"
        verbose_name_plural = "Lignes de facture"
        ordering = ["id"]

    def save(self, *args, **kwargs):
        self.line_total_fcfa = (
            Decimal(str(self.quantity or 0)) * Decimal(str(self.unit_price_fcfa or 0))
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.description} ({self.line_total_fcfa} FCFA)"


class Payment(TimeStampedModel):
    """Règlement partiel ou total d'une facture donnant lieu à un Reçu de paiement numéroté."""

    PAYMENT_METHODS = [
        ("ESPECES", "Espèces (Caisse)"),
        ("MOBILE_MONEY", "Mobile Money (Orange Money / MTN MoMo)"),
        ("VIREMENT", "Virement bancaire"),
        ("CHEQUE", "Chèque bancaire"),
        ("AUTRE", "Autre mode de règlement"),
    ]

    receipt_number = models.CharField("Numéro de reçu", max_length=35, unique=True, blank=True, db_index=True)
    verification_token = models.UUIDField("Jeton QR Reçu", default=uuid.uuid4, editable=False, unique=True)
    invoice = models.ForeignKey(Invoice, verbose_name="Facture réglée", on_delete=models.CASCADE, related_name="payments")
    parcel = models.ForeignKey(
        "cargo.Parcel",
        verbose_name="Colis rattaché",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="direct_payments",
    )
    client = models.ForeignKey("clients.Client", verbose_name="Client", on_delete=models.PROTECT, related_name="payments")
    payment_date = models.DateField("Date de paiement", default=timezone.now, db_index=True)
    amount_fcfa = models.DecimalField("Montant encaissé (FCFA)", max_digits=15, decimal_places=2)
    payment_method = models.CharField("Mode de paiement", max_length=20, choices=PAYMENT_METHODS, default="ESPECES")
    transaction_reference = models.CharField("Réf. transaction / N° Chèque / Bordereau", max_length=100, blank=True, default="")
    notes = models.CharField("Observation", max_length=255, blank=True, default="")
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Encaissé par",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="received_payments",
    )

    class Meta:
        verbose_name = "Paiement / Reçu"
        verbose_name_plural = "Paiements & Reçus"
        ordering = ["-payment_date", "-id"]

    def save(self, *args, **kwargs):
        if not self.receipt_number:
            self.receipt_number = generate_sequence_code(Payment, "receipt_number", "REC", pad=4)
        if self.invoice_id and not self.client_id:
            self.client_id = self.invoice.client_id
        if not self.parcel_id and self.invoice_id:
            only_lines = list(self.invoice.lines.filter(parcel__isnull=False)[:2])
            if len(only_lines) == 1:
                self.parcel_id = only_lines[0].parcel_id
        super().save(*args, **kwargs)
        if self.invoice_id:
            self.invoice.recalculate_totals(save=True)
        if self.parcel_id:
            self.parcel.recalculate_paid_amount(save=True)

    def delete(self, *args, **kwargs):
        inv = self.invoice
        pcl = self.parcel
        super().delete(*args, **kwargs)
        if inv:
            inv.recalculate_totals(save=True)
        if pcl:
            pcl.recalculate_paid_amount(save=True)

    def __str__(self):
        return f"{self.receipt_number} — {self.amount_fcfa} FCFA ({self.get_payment_method_display()})"


class CreditDeliveryAuthorization(TimeStampedModel):
    """Autorisation exceptionnelle de livraison à crédit lorsque la facture n'est pas encore intégralement soldée."""

    STATUS_CHOICES = [
        ("ACTIVE", "Active — Livraison autorisée"),
        ("REGULARISEE", "Régularisée (Facture soldée)"),
        ("REVOQUEE", "Révoquée / Expirée"),
    ]

    reference = models.CharField("N° Autorisation", max_length=35, unique=True, blank=True)
    client = models.ForeignKey(
        "clients.Client",
        verbose_name="Client bénéficiaire",
        on_delete=models.PROTECT,
        related_name="credit_authorizations",
    )
    invoice = models.ForeignKey(
        Invoice,
        verbose_name="Facture concernée",
        on_delete=models.CASCADE,
        related_name="credit_authorizations",
    )
    folder = models.ForeignKey(
        "shipments.ShipmentFolder",
        verbose_name="Dossier d'expédition",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="credit_authorizations",
    )
    authorized_balance_fcfa = models.DecimalField("Solde autorisé à crédit (FCFA)", max_digits=15, decimal_places=2)
    promised_due_date = models.DateField("Échéance de règlement engagée")
    reason = models.TextField("Motif / Garantie commerciale")
    status = models.CharField("Statut", max_length=20, choices=STATUS_CHOICES, default="ACTIVE")
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Accordée par",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_credits",
    )

    class Meta:
        verbose_name = "Autorisation de livraison à crédit"
        verbose_name_plural = "Autorisations de livraison à crédit"
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = generate_sequence_code(CreditDeliveryAuthorization, "reference", "CRD", pad=4)
        if self.invoice_id and not self.folder_id:
            self.folder_id = self.invoice.folder_id
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.reference} — {self.client.name} ({self.authorized_balance_fcfa} FCFA)"
