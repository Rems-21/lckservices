"""Formulaire d'importation et d'indexation documentaire (Section 2.8)."""
from django import forms
from accounts.forms import BootstrapFormMixin
from .models import Document


class DocumentUploadForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Document
        fields = [
            "doc_type",
            "title",
            "external_number",
            "file",
            "folder",
            "parcel",
            "client",
            "invoice",
            "notes",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap()
