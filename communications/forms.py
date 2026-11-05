"""Formulaires et générateur de messages personnalisés WhatsApp (Section 2.9)."""
from django import forms
from accounts.forms import BootstrapFormMixin
from .models import CommunicationLog, MessageTemplate


class SafeFormatDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def render_message_body(template_text: str, *, company=None, client=None, folder=None, parcel=None, invoice=None, doc_url: str = "") -> str:
    from core.utils import format_fcfa

    values = SafeFormatDict(
        societe=company.name if company else "LCK Services SARL",
        client_nom=client.name if client else "Cher client",
        dossier_ref=folder.reference if folder else (parcel.folder.reference if parcel else (invoice.folder.reference if (invoice and invoice.folder) else "N/A")),
        mode_transport=folder.get_transport_mode_display() if folder else (parcel.folder.get_transport_mode_display() if parcel else "International"),
        origine=folder.origin.city if folder else (parcel.folder.origin.city if parcel else ""),
        destination=folder.destination.city if folder else (parcel.folder.destination.city if parcel else ""),
        eta=folder.eta.strftime("%d/%m/%Y") if (folder and folder.eta) else "À confirmer",
        colis_code=parcel.parcel_code if parcel else "",
        volume_m3=str(parcel.volume_cbm) if parcel else (str(folder.total_volume_cbm) if folder else "0"),
        poids_kg=str(parcel.weight_kg) if parcel else (str(folder.total_weight_kg) if folder else "0"),
        facture_num=invoice.number if invoice else "",
        montant_total=format_fcfa(invoice.total_amount_fcfa) if invoice else "",
        montant_paye=format_fcfa(invoice.paid_amount_fcfa) if invoice else "",
        solde_restant=format_fcfa(invoice.balance_due_fcfa) if invoice else (format_fcfa(client.balance_due_fcfa) if client else "0 FCFA"),
        lien_document=doc_url or "",
    )
    return (template_text or "").format_map(values)


class MessageTemplateForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = MessageTemplate
        fields = ["code", "name", "category", "body_template", "is_active"]
        widgets = {
            "body_template": forms.Textarea(attrs={"rows": 5}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap()


class CommunicationComposeForm(BootstrapFormMixin, forms.ModelForm):
    template_choice = forms.ModelChoiceField(
        label="Modèle de message pré-rempli",
        queryset=MessageTemplate.objects.filter(is_active=True),
        required=False,
        empty_label="-- Choisir un modèle (ou rédiger librement) --",
    )

    class Meta:
        model = CommunicationLog
        fields = ["client", "folder", "parcel", "invoice", "recipient_phone", "subject", "message_body"]
        widgets = {
            "message_body": forms.Textarea(attrs={"rows": 6}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap()
