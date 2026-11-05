"""Formulaires de gestion logistique : Tracking, Opérations d'entrepôt, Livraisons et Incidents (Section 2.5)."""
from django import forms
from accounts.forms import BootstrapFormMixin
from cargo.models import Parcel
from .models import Delivery, Incident, TrackingEvent, WarehouseOperation


class TrackingEventForm(BootstrapFormMixin, forms.ModelForm):
    propagate_status = forms.BooleanField(
        label="Mettre aussi à jour le statut du colis / des colis du dossier",
        required=False,
        initial=True,
    )

    class Meta:
        model = TrackingEvent
        fields = ["folder", "parcel", "stage", "location_text", "event_date", "description"]
        widgets = {
            "event_date": forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}),
            "description": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["event_date"].input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"]
        self._apply_bootstrap()


class WarehouseOperationForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = WarehouseOperation
        fields = [
            "operation_type",
            "folder",
            "warehouse_name",
            "operation_date",
            "parcels_checked_count",
            "total_weight_checked_kg",
            "condition_status",
            "notes",
        ]
        widgets = {
            "operation_date": forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["operation_date"].input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"]
        self._apply_bootstrap()


class DeliveryForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Delivery
        fields = [
            "folder",
            "client",
            "parcels",
            "invoice",
            "credit_authorization",
            "delivery_mode",
            "delivery_address",
            "recipient_name",
            "recipient_phone",
            "recipient_id_number",
            "delivered_at",
            "notes",
        ]
        widgets = {
            "delivered_at": forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}),
            "parcels": forms.SelectMultiple(attrs={"size": 6}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        folder_filter = kwargs.pop("folder_filter", None)
        client_filter = kwargs.pop("client_filter", None)
        super().__init__(*args, **kwargs)
        self.fields["delivered_at"].input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"]
        qs = Parcel.objects.exclude(status="LIVRE").select_related("client", "folder")
        if folder_filter:
            qs = qs.filter(folder_id=folder_filter)
        if client_filter:
            qs = qs.filter(client_id=client_filter)
        self.fields["parcels"].queryset = qs
        self._apply_bootstrap()

    def clean(self):
        cleaned = super().clean()
        client = cleaned.get("client")
        folder = cleaned.get("folder")
        parcels = cleaned.get("parcels")
        invoice = cleaned.get("invoice")
        credit_auth = cleaned.get("credit_authorization")

        if parcels and client:
            wrong_client = [p.parcel_code for p in parcels if p.client_id != client.id]
            if wrong_client:
                self.add_error(
                    "parcels",
                    f"Les colis suivants n'appartiennent pas au client sélectionné : {', '.join(wrong_client)}.",
                )

        # Contrôle strict du règlement ou d'une autorisation de livraison à crédit active
        if invoice:
            if invoice.client_id != (client.id if client else None):
                self.add_error("invoice", "Cette facture n'appartient pas au client sélectionné.")
            elif invoice.invoice_type != "DEFINITIVE":
                self.add_error("invoice", "Veuillez associer une facture Définitive (et non une Proforma) pour la livraison.")
            elif invoice.balance_due_fcfa > 0:
                valid_credit = (
                    credit_auth
                    and credit_auth.status == "ACTIVE"
                    and credit_auth.invoice_id == invoice.id
                ) or invoice.credit_authorizations.filter(status="ACTIVE").exists()
                if not valid_credit:
                    self.add_error(
                        "invoice",
                        f"Livraison bloquée : la facture {invoice.number} présente un solde impayé de {invoice.balance_due_fcfa} FCFA "
                        "sans autorisation de livraison à crédit active.",
                    )
        elif client and folder:
            # Vérifier s'il existe une facture définitive non soldée pour ce client dans ce dossier
            unpaid_invoices = client.invoices.filter(
                folder=folder,
                invoice_type="DEFINITIVE",
            ).exclude(status__in=["PAYEE", "ANNULEE"])
            for inv in unpaid_invoices:
                has_credit = inv.credit_authorizations.filter(status="ACTIVE").exists() or (
                    credit_auth and credit_auth.status == "ACTIVE" and credit_auth.invoice_id == inv.id
                )
                if not has_credit and inv.balance_due_fcfa > 0:
                    self.add_error(
                        None,
                        f"Livraison bloquée : le client possède une facture non soldée ({inv.number}, reste {inv.balance_due_fcfa} FCFA) sur ce dossier. "
                        "Veuillez encaisser le règlement ou émettre une autorisation de livraison à crédit.",
                    )
        return cleaned


class IncidentForm(BootstrapFormMixin, forms.ModelForm):
    mark_parcel_litige = forms.BooleanField(
        label="Passer le colis concerné au statut « En incident / Litige »",
        required=False,
        initial=True,
    )

    class Meta:
        model = Incident
        fields = [
            "folder",
            "parcel",
            "client",
            "incident_type",
            "severity",
            "status",
            "title",
            "description",
            "estimated_damage_fcfa",
            "compensation_fcfa",
            "resolution_notes",
            "attachment",
            "reported_at",
        ]
        widgets = {
            "reported_at": forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}),
            "description": forms.Textarea(attrs={"rows": 3}),
            "resolution_notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["reported_at"].input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"]
        self._apply_bootstrap()
