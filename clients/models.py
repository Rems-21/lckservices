"""Modèles de gestion des clients et de leurs contacts (Section 2.2)."""
from decimal import Decimal
from django.db import models
from django.db.models import Sum
from core.models import TimeStampedModel
from core.utils import generate_sequence_code


class Client(TimeStampedModel):
    CLIENT_TYPES = [
        ("ENTREPRISE", "Entreprise / Société"),
        ("PARTICULIER", "Particulier / Commerçant"),
    ]

    code = models.CharField("Code client", max_length=30, unique=True, blank=True)
    client_type = models.CharField("Type de client", max_length=20, choices=CLIENT_TYPES, default="ENTREPRISE")
    name = models.CharField("Nom complet / Raison sociale", max_length=180, db_index=True)
    tax_id = models.CharField("NIU / RCCM / Pièce d'identité", max_length=80, blank=True, default="")
    phone = models.CharField("Téléphone principal", max_length=40, db_index=True)
    whatsapp = models.CharField("Numéro WhatsApp", max_length=40, blank=True, default="")
    email = models.EmailField("Adresse e-mail", blank=True, default="")
    address = models.CharField("Adresse", max_length=255, blank=True, default="")
    city = models.CharField("Ville", max_length=100, default="Douala")
    country = models.CharField("Pays", max_length=100, default="Cameroun")
    credit_allowed = models.BooleanField("Éligible au crédit", default=False)
    credit_limit_fcfa = models.DecimalField(
        "Plafond de crédit indicatif (FCFA)",
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    notes = models.TextField("Notes / Instructions spéciales", blank=True, default="")
    is_active = models.BooleanField("Client actif", default=True)

    class Meta:
        verbose_name = "Client"
        verbose_name_plural = "Clients"
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = generate_sequence_code(Client, "code", "CLI", pad=4)
        if not self.whatsapp and self.phone:
            self.whatsapp = self.phone
        super().save(*args, **kwargs)

    @property
    def initials(self) -> str:
        parts = [p for p in (self.name or "").strip().split() if p]
        if len(parts) >= 2:
            return (parts[0][0] + parts[1][0]).upper()
        if parts:
            return parts[0][:2].upper()
        return "CL"

    @property
    def whatsapp_clean(self) -> str:
        raw = self.whatsapp or self.phone or ""
        digits = "".join(ch for ch in raw if ch.isdigit())
        if len(digits) == 9 and digits.startswith("6"):
            return f"237{digits}"
        return digits

    @property
    def total_invoiced_fcfa(self) -> Decimal:
        val = (
            self.invoices.filter(invoice_type="DEFINITIVE")
            .exclude(status="ANNULEE")
            .aggregate(s=Sum("total_amount_fcfa"))["s"]
        )
        return val or Decimal("0.00")

    @property
    def total_paid_fcfa(self) -> Decimal:
        val = (
            self.invoices.filter(invoice_type="DEFINITIVE")
            .exclude(status="ANNULEE")
            .aggregate(s=Sum("paid_amount_fcfa"))["s"]
        )
        return val or Decimal("0.00")

    @property
    def balance_due_fcfa(self) -> Decimal:
        return self.total_invoiced_fcfa - self.total_paid_fcfa

    def __str__(self):
        return f"{self.code} — {self.name}"


class ClientContact(TimeStampedModel):
    """Interlocuteurs et contacts additionnels rattachés à un client."""

    client = models.ForeignKey(Client, verbose_name="Client", on_delete=models.CASCADE, related_name="contacts")
    full_name = models.CharField("Nom complet", max_length=150)
    role = models.CharField("Fonction / Lien", max_length=100, blank=True, default="")
    phone = models.CharField("Téléphone", max_length=40)
    whatsapp = models.CharField("WhatsApp", max_length=40, blank=True, default="")
    email = models.EmailField("Email", blank=True, default="")
    is_primary = models.BooleanField("Contact principal", default=False)

    class Meta:
        verbose_name = "Contact client"
        verbose_name_plural = "Contacts clients"
        ordering = ["-is_primary", "full_name"]

    def __str__(self):
        return f"{self.full_name} ({self.client.name})"
