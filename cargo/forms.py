"""Formulaires de gestion des marchandises, colis et catégories (Section 2.4)."""
from django import forms
from accounts.forms import BootstrapFormMixin
from core.models import Currency
from .models import CargoCategory, Parcel


class CargoCategoryForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = CargoCategory
        fields = ["name", "code", "is_fragile_or_special", "description"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap()


class ParcelForm(BootstrapFormMixin, forms.ModelForm):
    attachment_file = forms.FileField(
        label="Document joint à la marchandise (Packing list, Facture achat, Photo...)",
        required=False,
    )
    attachment_title = forms.CharField(
        label="Titre du document joint",
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Ex: Packing list fournisseur Yiwu"}),
    )

    class Meta:
        model = Parcel
        fields = [
            "folder",
            "client",
            "category",
            "description",
            "supplier_name",
            "supplier_tracking",
            "packaging_type",
            "quantity",
            "weight_kg",
            "length_cm",
            "width_cm",
            "height_cm",
            "manual_volume",
            "volume_cbm",
            "declared_value",
            "declared_currency",
            "exchange_rate",
            "status",
            "storage_location",
            "notes",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk and not self.initial.get("declared_currency"):
            default_cur = Currency.objects.filter(is_base=True).first() or Currency.objects.first()
            if default_cur:
                self.initial["declared_currency"] = default_cur.pk
                self.initial["exchange_rate"] = default_cur.rate_to_fcfa
        self._apply_bootstrap()
