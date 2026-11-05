"""Formulaires de gestion des clients et de leurs contacts (Section 2.2)."""
from django import forms
from accounts.forms import BootstrapFormMixin
from .models import Client, ClientContact


class ClientForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Client
        fields = [
            "client_type",
            "name",
            "tax_id",
            "phone",
            "whatsapp",
            "email",
            "address",
            "city",
            "country",
            "credit_allowed",
            "credit_limit_fcfa",
            "notes",
            "is_active",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3, "placeholder": "Instructions habituelles de livraison, préférences..."}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap()


class ClientContactForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = ClientContact
        fields = ["full_name", "role", "phone", "whatsapp", "email", "is_primary"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap()
