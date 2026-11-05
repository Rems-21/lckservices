"""Formulaires de saisie des dépenses multi-devises et catégories de frais (Section 2.6)."""
from django import forms
from accounts.forms import BootstrapFormMixin
from core.models import Currency
from .models import ExpenseCategory, FolderExpense


class ExpenseCategoryForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = ExpenseCategory
        fields = ["name", "code", "description"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap()


class FolderExpenseForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = FolderExpense
        fields = [
            "folder",
            "category",
            "label",
            "vendor_name",
            "expense_date",
            "amount_original",
            "currency",
            "exchange_rate",
            "receipt_file",
            "is_allocatable",
            "notes",
        ]
        widgets = {
            "expense_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["expense_date"].input_formats = ["%Y-%m-%d"]
        if not self.instance.pk and not self.initial.get("currency"):
            default_cur = Currency.objects.filter(is_base=True).first() or Currency.objects.first()
            if default_cur:
                self.initial["currency"] = default_cur.pk
                self.initial["exchange_rate"] = default_cur.rate_to_fcfa
        self._apply_bootstrap()
