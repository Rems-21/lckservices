"""Formulaires d'authentification, gestion des comptes, mots de passe et paramètres (Sections 2.11 & 3)."""
from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from core.models import CompanySetting, Currency
from .models import User


class BootstrapFormMixin:
    """Applique automatiquement les classes Bootstrap 5.3 aux champs de formulaire."""

    def _apply_bootstrap(self):
        for name, field in self.fields.items():
            widget = field.widget
            css = widget.attrs.get("class", "")
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = f"{css} form-check-input".strip()
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                widget.attrs["class"] = f"{css} form-select".strip()
            else:
                widget.attrs["class"] = f"{css} form-control".strip()
            if isinstance(widget, forms.DateInput):
                widget.input_type = "date"
            elif isinstance(widget, forms.DateTimeInput):
                widget.input_type = "datetime-local"


class LoginForm(BootstrapFormMixin, AuthenticationForm):
    username = forms.CharField(
        label="Adresse email ou identifiant",
        widget=forms.TextInput(attrs={"placeholder": "nom@lckservices.com ou identifiant", "autofocus": True}),
    )
    password = forms.CharField(
        label="Mot de passe",
        widget=forms.PasswordInput(attrs={"placeholder": "••••••••"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap()

    def clean(self):
        identifier = (self.cleaned_data.get("username") or "").strip()
        if identifier and "@" in identifier and not User.objects.filter(username__iexact=identifier).exists():
            matched = User.objects.filter(email__iexact=identifier).order_by("-is_active", "id").first()
            if matched:
                self.cleaned_data["username"] = matched.username
        return super().clean()


class UserCreateForm(BootstrapFormMixin, forms.ModelForm):
    password = forms.CharField(
        label="Mot de passe initial",
        min_length=6,
        widget=forms.PasswordInput(attrs={"placeholder": "Minimum 6 caractères"}),
    )
    password_confirm = forms.CharField(
        label="Confirmer le mot de passe",
        widget=forms.PasswordInput(attrs={"placeholder": "Répétez le mot de passe"}),
    )

    class Meta:
        model = User
        fields = [
            "username",
            "first_name",
            "last_name",
            "email",
            "phone",
            "job_title",
            "is_active",
            "is_access_admin",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap()

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("password")
        p2 = cleaned.get("password_confirm")
        if p1 and p2 and p1 != p2:
            self.add_error("password_confirm", "Les mots de passe ne correspondent pas.")
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user


class UserEditForm(BootstrapFormMixin, forms.ModelForm):
    new_password = forms.CharField(
        label="Nouveau mot de passe (laisser vide pour ne pas modifier)",
        required=False,
        min_length=6,
        widget=forms.PasswordInput(attrs={"placeholder": "Optionnel — réinitialiser le mot de passe"}),
    )

    class Meta:
        model = User
        fields = [
            "username",
            "first_name",
            "last_name",
            "email",
            "phone",
            "job_title",
            "is_active",
            "is_access_admin",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap()

    def save(self, commit=True):
        user = super().save(commit=False)
        pwd = self.cleaned_data.get("new_password")
        if pwd:
            user.set_password(pwd)
        if commit:
            user.save()
        return user


class ProfileForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "phone", "job_title"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap()


class UserPasswordForm(BootstrapFormMixin, PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap()


class CompanySettingForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = CompanySetting
        fields = [
            "name",
            "slogan",
            "niu",
            "rccm",
            "phone",
            "whatsapp",
            "email",
            "address",
            "city",
            "country",
            "bank_details",
            "invoice_footer_note",
            "logo",
        ]
        widgets = {
            "bank_details": forms.Textarea(attrs={"rows": 3}),
            "invoice_footer_note": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap()


class CurrencyForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Currency
        fields = ["code", "name", "symbol", "rate_to_fcfa", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap()
