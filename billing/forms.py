"""Formulaires de facturation, lignes, paiements et autorisations de livraison à crédit (Section 2.7)."""
from django import forms
from accounts.forms import BootstrapFormMixin
from .models import CreditDeliveryAuthorization, Invoice, InvoiceLine, Payment


class InvoiceForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Invoice
        fields = [
            "invoice_type",
            "client",
            "folder",
            "issue_date",
            "due_date",
            "discount_fcfa",
            "tax_rate_percent",
            "notes",
        ]
        widgets = {
            "issue_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "due_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for df in ("issue_date", "due_date"):
            self.fields[df].input_formats = ["%Y-%m-%d"]
        self._apply_bootstrap()


class InvoiceLineForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = InvoiceLine
        fields = ["parcel", "description", "quantity", "unit_label", "unit_price_fcfa"]

    def __init__(self, *args, **kwargs):
        folder = kwargs.pop("folder", None)
        client = kwargs.pop("client", None)
        super().__init__(*args, **kwargs)
        if client:
            qs = client.parcels.all()
            if folder:
                qs = qs.filter(folder=folder)
            self.fields["parcel"].queryset = qs
        self._apply_bootstrap()


class PaymentForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Payment
        fields = ["invoice", "payment_date", "amount_fcfa", "payment_method", "transaction_reference", "notes"]
        widgets = {
            "payment_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["payment_date"].input_formats = ["%Y-%m-%d"]
        self.fields["invoice"].queryset = Invoice.objects.filter(
            invoice_type="DEFINITIVE",
        ).exclude(status="ANNULEE").select_related("client")
        self._apply_bootstrap()

    def clean_amount_fcfa(self):
        amt = self.cleaned_data.get("amount_fcfa")
        if not amt or amt <= 0:
            raise forms.ValidationError("Le montant encaissé doit être strictement positif.")
        return amt


class CreditAuthorizationForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = CreditDeliveryAuthorization
        fields = ["client", "invoice", "promised_due_date", "reason"]
        widgets = {
            "promised_due_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "reason": forms.Textarea(attrs={"rows": 3, "placeholder": "Accord commercial, bon de commande signé, chèque de garantie..."}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["promised_due_date"].input_formats = ["%Y-%m-%d"]
        self.fields["invoice"].queryset = Invoice.objects.filter(
            invoice_type="DEFINITIVE",
        ).exclude(status__in=["PAYEE", "ANNULEE"]).select_related("client")
        self._apply_bootstrap()

    def clean(self):
        cleaned = super().clean()
        inv = cleaned.get("invoice")
        cli = cleaned.get("client")
        if inv and cli and inv.client_id != cli.id:
            self.add_error("invoice", "Cette facture n'appartient pas au client sélectionné.")
        if inv and inv.balance_due_fcfa <= 0:
            self.add_error("invoice", "Cette facture est déjà intégralement soldée.")
        return cleaned
