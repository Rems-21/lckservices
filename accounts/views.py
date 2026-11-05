"""Vues d'authentification, gestion des comptes, profil, journal des opérations et sauvegardes."""
import os
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from core.models import CompanySetting, Currency
from .forms import (
    CompanySettingForm,
    CurrencyForm,
    LoginForm,
    ProfileForm,
    UserCreateForm,
    UserEditForm,
    UserPasswordForm,
)
from .models import AuditLog, BackupRecord, User
from .services import create_full_backup, log_audit


class LCKLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        remember = bool(self.request.POST.get("remember_me"))
        response = super().form_valid(form)
        if not remember:
            self.request.session.set_expiry(0)
        else:
            self.request.session.set_expiry(60 * 60 * 24 * 30)
        return response


class LCKLogoutView(LogoutView):
    next_page = "accounts:login"


@login_required
def profile_view(request):
    profile_form = ProfileForm(instance=request.user)
    password_form = UserPasswordForm(user=request.user)

    if request.method == "POST":
        action_type = request.POST.get("form_type")
        if action_type == "profile":
            profile_form = ProfileForm(request.POST, instance=request.user)
            if profile_form.is_valid():
                profile_form.save()
                log_audit("UPDATE", "Compte personnel", request.user.display_name, str(request.user.pk), "Mise à jour du profil.")
                messages.success(request, "Vos informations personnelles ont été mises à jour.")
                return redirect("accounts:profile")
        elif action_type == "password":
            password_form = UserPasswordForm(user=request.user, data=request.POST)
            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)
                log_audit("ACCOUNT", "Sécurité", user.display_name, str(user.pk), "Changement du mot de passe personnel.")
                messages.success(request, "Votre mot de passe a été modifié avec succès.")
                return redirect("accounts:profile")
            else:
                messages.error(request, "Veuillez vérifier l'ancien mot de passe et la confirmation.")

    recent_logs = AuditLog.objects.filter(user=request.user)[:15]
    return render(
        request,
        "accounts/profile.html",
        {
            "profile_form": profile_form,
            "password_form": password_form,
            "recent_logs": recent_logs,
        },
    )


def _check_account_admin(request):
    """Vérifie que l'utilisateur dispose du droit de gestion des comptes (compte administrateur initial)."""
    if not request.user.can_manage_accounts:
        messages.error(
            request,
            "La création et la gestion des comptes utilisateurs sont réservées au compte administrateur de gestion des accès.",
        )
        return False
    return True


@login_required
def user_list_view(request):
    users = User.objects.all().order_by("-is_active", "username")
    q = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "").strip()
    if q:
        users = users.filter(
            Q(username__icontains=q)
            | Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(email__icontains=q)
            | Q(job_title__icontains=q)
        )
    if status_filter == "active":
        users = users.filter(is_active=True)
    elif status_filter == "inactive":
        users = users.filter(is_active=False)

    return render(
        request,
        "accounts/user_list.html",
        {
            "users": users,
            "q": q,
            "status_filter": status_filter,
        },
    )


@login_required
def user_modal_save_view(request):
    """Création ou modification rapide d'un compte utilisateur depuis la modale #userModal façon MTsarl."""
    if request.method != "POST":
        return redirect("accounts:user_list")
    if not _check_account_admin(request):
        return redirect("accounts:user_list")

    user_id = request.POST.get("user_id", "").strip()
    username = request.POST.get("username", "").strip()
    email = request.POST.get("email", "").strip()
    first_name = request.POST.get("first_name", "").strip()
    last_name = request.POST.get("last_name", "").strip()
    phone = request.POST.get("phone", "").strip()
    job_title = request.POST.get("job_title", "Agent de transit").strip() or "Agent de transit"
    is_active = bool(request.POST.get("is_active", True))

    if user_id.isdigit():
        target = get_object_or_404(User, pk=int(user_id))
        if target.pk == request.user.pk and not is_active:
            messages.error(request, "Vous ne pouvez pas désactiver votre propre compte en cours de session.")
            return redirect("accounts:user_list")
        if username and User.objects.exclude(pk=target.pk).filter(username__iexact=username).exists():
            messages.error(request, f"L'identifiant « {username} » est déjà utilisé.")
            return redirect("accounts:user_list")
        if username:
            target.username = username
        target.email = email
        target.first_name = first_name
        target.last_name = last_name
        target.phone = phone
        target.job_title = job_title
        target.is_active = is_active
        new_pwd = request.POST.get("password", "").strip()
        if new_pwd:
            if len(new_pwd) < 6:
                messages.error(request, "Le mot de passe doit contenir au moins 6 caractères.")
                return redirect("accounts:user_list")
            target.set_password(new_pwd)
        target.save()
        log_audit("ACCOUNT", "Gestion des utilisateurs", target.display_name, str(target.pk), f"Modification du compte '{target.username}'.")
        messages.success(request, f"Le compte « {target.username} » a été mis à jour.")
    else:
        password = request.POST.get("password", "").strip()
        if not username or not password:
            messages.error(request, "L'identifiant et le mot de passe sont obligatoires.")
            return redirect("accounts:user_list")
        if len(password) < 6:
            messages.error(request, "Le mot de passe doit contenir au moins 6 caractères.")
            return redirect("accounts:user_list")
        if User.objects.filter(username__iexact=username).exists():
            messages.error(request, f"L'identifiant « {username} » existe déjà.")
            return redirect("accounts:user_list")
        new_user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            job_title=job_title,
            is_active=True,
        )
        log_audit(
            "ACCOUNT",
            "Gestion des utilisateurs",
            new_user.display_name,
            str(new_user.pk),
            f"Création du compte utilisateur '{new_user.username}' (Rôle unique : Utilisateur).",
        )
        messages.success(request, f"Compte utilisateur « {new_user.username} » créé avec succès.")
    return redirect("accounts:user_list")


@login_required
def user_reset_password_view(request, pk):
    if request.method != "POST":
        return redirect("accounts:user_list")
    if not _check_account_admin(request):
        return redirect("accounts:user_list")
    target = get_object_or_404(User, pk=pk)
    new_pwd = request.POST.get("new_password", "").strip()
    if len(new_pwd) < 6:
        messages.error(request, "Le nouveau mot de passe doit contenir au moins 6 caractères.")
        return redirect("accounts:user_list")
    target.set_password(new_pwd)
    target.save(update_fields=["password", "updated_at"])
    if target.pk == request.user.pk:
        update_session_auth_hash(request, target)
    log_audit("ACCOUNT", "Gestion des utilisateurs", target.display_name, str(target.pk), f"Réinitialisation mot de passe de '{target.username}'.")
    messages.success(request, f"Mot de passe de « {target.username} » mis à jour.")
    return redirect("accounts:user_list")


@login_required
def user_create_view(request):
    if not _check_account_admin(request):
        return redirect("accounts:user_list")

    form = UserCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        new_user = form.save()
        log_audit(
            "ACCOUNT",
            "Gestion des utilisateurs",
            new_user.display_name,
            str(new_user.pk),
            f"Création du compte utilisateur '{new_user.username}' (Rôle : Utilisateur).",
        )
        messages.success(request, f"Le compte utilisateur « {new_user.username} » a été créé avec succès.")
        return redirect("accounts:user_list")
    return render(request, "accounts/user_form.html", {"form": form, "is_edit": False})


@login_required
def user_edit_view(request, pk):
    if not _check_account_admin(request):
        return redirect("accounts:user_list")

    target_user = get_object_or_404(User, pk=pk)
    form = UserEditForm(request.POST or None, instance=target_user)
    if request.method == "POST" and form.is_valid():
        if target_user.pk == request.user.pk and not form.cleaned_data.get("is_active"):
            messages.error(request, "Vous ne pouvez pas désactiver votre propre session active.")
            return redirect("accounts:user_edit", pk=pk)
        updated = form.save()
        log_audit(
            "ACCOUNT",
            "Gestion des utilisateurs",
            updated.display_name,
            str(updated.pk),
            f"Modification du compte '{updated.username}' (Actif={updated.is_active}).",
        )
        messages.success(request, f"Le compte « {updated.username} » a été mis à jour.")
        return redirect("accounts:user_list")
    return render(request, "accounts/user_form.html", {"form": form, "is_edit": True, "target_user": target_user})


@login_required
def user_toggle_active_view(request, pk):
    if request.method != "POST":
        return redirect("accounts:user_list")
    if not _check_account_admin(request):
        return redirect("accounts:user_list")

    target_user = get_object_or_404(User, pk=pk)
    if target_user.pk == request.user.pk:
        messages.error(request, "Impossible de désactiver votre propre compte en cours d'utilisation.")
        return redirect("accounts:user_list")

    target_user.is_active = not target_user.is_active
    target_user.save(update_fields=["is_active", "updated_at"])
    state_txt = "activé" if target_user.is_active else "désactivé"
    log_audit(
        "ACCOUNT",
        "Gestion des utilisateurs",
        target_user.display_name,
        str(target_user.pk),
        f"Compte '{target_user.username}' {state_txt}.",
    )
    messages.success(request, f"Le compte « {target_user.username} » a été {state_txt}.")
    return redirect("accounts:user_list")


@login_required
def audit_log_list_view(request):
    logs = AuditLog.objects.select_related("user").all()
    q = request.GET.get("q", "").strip()
    action_filter = request.GET.get("action", "").strip()
    module_filter = request.GET.get("module", "").strip()

    if q:
        logs = logs.filter(
            Q(username_snapshot__icontains=q)
            | Q(object_repr__icontains=q)
            | Q(details__icontains=q)
        )
    if action_filter:
        logs = logs.filter(action=action_filter)
    if module_filter:
        logs = logs.filter(module__icontains=module_filter)

    paginator = Paginator(logs, 30)
    page_obj = paginator.get_page(request.GET.get("page"))

    modules_list = AuditLog.objects.values_list("module", flat=True).distinct().order_by("module")
    return render(
        request,
        "accounts/audit_list.html",
        {
            "page_obj": page_obj,
            "q": q,
            "action_filter": action_filter,
            "module_filter": module_filter,
            "action_choices": AuditLog.ACTION_CHOICES,
            "modules_list": modules_list,
        },
    )


@login_required
def audit_clear_view(request):
    """Purge sécurisée du journal d'audit avec vérification du mot de passe administrateur façon MTsarl."""
    if request.method == "POST":
        if not _check_account_admin(request):
            return redirect("accounts:audit_list")
        admin_pwd = request.POST.get("admin_password", "")
        if not request.user.check_password(admin_pwd):
            messages.error(request, "Mot de passe administrateur incorrect. Purge annulée.")
            return redirect("accounts:audit_list")
        count = AuditLog.objects.count()
        AuditLog.objects.all().delete()
        log_audit("DELETE", "Journal d'audit", "Purge du journal", "", f"{count} entrées purgées après validation administrateur.")
        messages.success(request, f"Journal d'audit purgé ({count} entrées supprimées).")
    return redirect("accounts:audit_list")


@login_required
def settings_and_backups_view(request):
    company = CompanySetting.get_solo()
    company_form = CompanySettingForm(instance=company)
    currency_form = CurrencyForm()

    if request.method == "POST":
        form_type = request.POST.get("form_type")
        if form_type == "company":
            company_form = CompanySettingForm(request.POST, request.FILES, instance=company)
            if company_form.is_valid():
                company_form.save()
                log_audit("UPDATE", "Paramètres société", company.name, str(company.pk), "Mise à jour des coordonnées LCK Services.")
                messages.success(request, "Les informations de LCK Services SARL ont été enregistrées.")
                return redirect("accounts:settings_backups")
        elif form_type == "currency_update":
            cur_id = request.POST.get("currency_id")
            rate_val = request.POST.get("rate_to_fcfa")
            cur = get_object_or_404(Currency, pk=cur_id)
            if not cur.is_base and rate_val:
                from core.utils import to_decimal

                new_rate = to_decimal(rate_val, default=str(cur.rate_to_fcfa))
                if new_rate > 0:
                    cur.rate_to_fcfa = new_rate
                    cur.save(update_fields=["rate_to_fcfa", "updated_at"])
                    log_audit("UPDATE", "Devises", cur.code, str(cur.pk), f"Nouveau taux : 1 {cur.code} = {cur.rate_to_fcfa} FCFA.")
                    messages.success(request, f"Taux {cur.code} actualisé à {cur.rate_to_fcfa} FCFA.")
            return redirect("accounts:settings_backups")
        elif form_type == "currency_add":
            currency_form = CurrencyForm(request.POST)
            if currency_form.is_valid():
                cur = currency_form.save(commit=False)
                cur.code = cur.code.upper().strip()
                cur.save()
                log_audit("CREATE", "Devises", cur.code, str(cur.pk), f"Ajout devise {cur.code} ({cur.rate_to_fcfa} FCFA).")
                messages.success(request, f"Devise {cur.code} ajoutée.")
                return redirect("accounts:settings_backups")
        elif form_type == "backup":
            include_media = bool(request.POST.get("include_media"))
            notes = request.POST.get("notes", "").strip()
            record = create_full_backup(user=request.user, include_media=include_media, notes=notes)
            messages.success(request, f"Sauvegarde {record.reference} générée avec succès ({record.size_human}).")
            return redirect("accounts:settings_backups")

    currencies = Currency.objects.all()
    backups = BackupRecord.objects.select_related("created_by").all()[:20]
    total_size_bytes = sum((b.size_bytes or 0) for b in backups)
    return render(
        request,
        "accounts/settings_backups.html",
        {
            "company_form": company_form,
            "currency_form": currency_form,
            "currencies": currencies,
            "backups": backups,
            "backups_count": BackupRecord.objects.count(),
            "backups_total_mb": round(total_size_bytes / (1024 * 1024), 2),
        },
    )


@login_required
def backup_download_view(request, pk):
    record = get_object_or_404(BackupRecord, pk=pk)
    if not record.archive_file:
        raise Http404("Fichier d'archive introuvable.")
    log_audit("BACKUP", "Sauvegardes", record.reference, str(record.pk), "Téléchargement de l'archive de sauvegarde.")
    return FileResponse(record.archive_file.open("rb"), as_attachment=True, filename=f"{record.reference}.zip")


@login_required
def backup_delete_view(request, pk):
    record = get_object_or_404(BackupRecord, pk=pk)
    if request.method == "POST":
        ref = record.reference
        if record.archive_file and os.path.exists(record.archive_file.path):
            try:
                os.remove(record.archive_file.path)
            except OSError:
                pass
        record.delete()
        log_audit("DELETE", "Sauvegardes", ref, str(pk), "Suppression d'une archive de sauvegarde.")
        messages.success(request, f"Sauvegarde « {ref} » supprimée.")
    return redirect("accounts:settings_backups")
