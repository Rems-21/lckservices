"""Modèles transverses : Paramètres société et Devises multi-taux (FCFA par défaut)."""
from decimal import Decimal, ROUND_HALF_UP
from django.conf import settings
from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField("Créé le", auto_now_add=True)
    updated_at = models.DateTimeField("Modifié le", auto_now=True)

    class Meta:
        abstract = True


class CompanySetting(TimeStampedModel):
    """Paramètres généraux de LCK Services SARL pour les en-têtes documentaires et la facturation."""

    name = models.CharField("Raison sociale", max_length=150, default="LCK Services SARL")
    slogan = models.CharField(
        "Domaine / Slogan",
        max_length=255,
        default="Transit, Transport International & Groupage Maritime et Aérien",
    )
    niu = models.CharField("NIU / Identifiant fiscal", max_length=80, blank=True, default="")
    rccm = models.CharField("RCCM", max_length=80, blank=True, default="")
    phone = models.CharField("Téléphone principal", max_length=50, default="+237 600 00 00 00")
    whatsapp = models.CharField("Numéro WhatsApp", max_length=50, blank=True, default="+237 600 00 00 00")
    email = models.EmailField("Email", blank=True, default="contact@lckservices.com")
    address = models.CharField("Adresse", max_length=255, default="Douala, Cameroun")
    city = models.CharField("Ville", max_length=100, default="Douala")
    country = models.CharField("Pays", max_length=100, default="Cameroun")
    default_currency = models.CharField("Devise principale", max_length=10, default="FCFA")
    bank_details = models.TextField("Coordonnées bancaires / Mobile Money", blank=True, default="")
    invoice_footer_note = models.TextField(
        "Mentions de pied de facture",
        blank=True,
        default="Les marchandises voyagent aux risques et périls du destinataire sauf assurance souscrite. Merci de votre confiance.",
    )
    logo = models.ImageField("Logo société", upload_to="company/", blank=True, null=True)

    class Meta:
        verbose_name = "Paramètre société"
        verbose_name_plural = "Paramètres société"

    def __str__(self):
        return self.name

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={
                "name": settings.COMPANY_DEFAULTS["name"],
                "slogan": settings.COMPANY_DEFAULTS["slogan"],
                "phone": settings.COMPANY_DEFAULTS["phone"],
                "whatsapp": settings.COMPANY_DEFAULTS["phone"],
                "email": settings.COMPANY_DEFAULTS["email"],
                "address": settings.COMPANY_DEFAULTS["address"],
                "default_currency": settings.COMPANY_DEFAULTS["default_currency"],
            },
        )
        return obj


class Currency(TimeStampedModel):
    """Référentiel des devises avec taux de conversion vers le FCFA."""

    code = models.CharField("Code devise", max_length=10, unique=True)
    name = models.CharField("Libellé", max_length=80)
    symbol = models.CharField("Symbole", max_length=15, default="FCFA")
    rate_to_fcfa = models.DecimalField(
        "Taux vers FCFA (1 unité = X FCFA)",
        max_digits=14,
        decimal_places=4,
        default=Decimal("1.0000"),
    )
    is_base = models.BooleanField("Devise principale (FCFA)", default=False)
    is_active = models.BooleanField("Active", default=True)

    class Meta:
        verbose_name = "Devise"
        verbose_name_plural = "Devises"
        ordering = ["-is_base", "code"]

    def __str__(self):
        if self.is_base:
            return f"{self.code} (Devise de base)"
        return f"{self.code} (1 {self.code} = {self.rate_to_fcfa} FCFA)"

    def to_fcfa(self, amount, custom_rate=None) -> Decimal:
        val = Decimal(str(amount or 0))
        rate = Decimal(str(custom_rate)) if custom_rate else self.rate_to_fcfa
        return (val * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @classmethod
    def get_default(cls):
        cur, _ = cls.objects.get_or_create(
            code="FCFA",
            defaults={
                "name": "Franc CFA",
                "symbol": "FCFA",
                "rate_to_fcfa": Decimal("1.0000"),
                "is_base": True,
                "is_active": True,
            },
        )
        return cur

    @classmethod
    def get_base(cls):
        return cls.objects.filter(is_base=True).first() or cls.get_default()
