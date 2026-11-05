"""Formulaires de gestion des dossiers d'expédition et des ports/aéroports (Section 2.3)."""
from django import forms
from accounts.forms import BootstrapFormMixin
from .models import Location, ShipmentFolder


class LocationForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Location
        fields = ["name", "code", "city", "country", "location_type", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap()


class ShipmentFolderForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = ShipmentFolder
        fields = [
            "transport_mode",
            "operation_type",
            "title",
            "status",
            "origin",
            "destination",
            "shipping_line",
            "vessel_name",
            "voyage_number",
            "container_number",
            "container_type",
            "seal_number",
            "bl_number",
            "airline_name",
            "flight_number",
            "awb_number",
            "etd",
            "atd",
            "eta",
            "ata",
            "default_rate_per_cbm",
            "default_rate_per_kg",
            "notes",
        ]
        widgets = {
            "etd": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "atd": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "eta": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "ata": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for date_field in ("etd", "atd", "eta", "ata"):
            self.fields[date_field].input_formats = ["%Y-%m-%d"]
        self._apply_bootstrap()

    def clean(self):
        cleaned = super().clean()
        origin = cleaned.get("origin")
        destination = cleaned.get("destination")
        if origin and destination and origin == destination:
            self.add_error("destination", "Le lieu d'arrivée doit être différent du lieu de départ.")
        return cleaned
