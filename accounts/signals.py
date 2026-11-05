"""Signaux d'authentification pour tracer automatiquement les connexions et déconnexions."""
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver
from .models import AuditLog


def _extract_ip(request):
    if not request:
        return None
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


@receiver(user_logged_in)
def on_user_logged_in(sender, request, user, **kwargs):
    AuditLog.objects.create(
        user=user,
        username_snapshot=user.username,
        action="LOGIN",
        module="Authentification",
        object_repr=user.display_name,
        object_id=str(user.pk),
        details="Connexion réussie à la plateforme.",
        ip_address=_extract_ip(request),
    )


@receiver(user_logged_out)
def on_user_logged_out(sender, request, user, **kwargs):
    if user:
        AuditLog.objects.create(
            user=user,
            username_snapshot=user.username,
            action="LOGOUT",
            module="Authentification",
            object_repr=user.display_name,
            object_id=str(user.pk),
            details="Déconnexion de la session.",
            ip_address=_extract_ip(request),
        )


@receiver(user_login_failed)
def on_user_login_failed(sender, credentials, request, **kwargs):
    uname = (credentials or {}).get("username", "inconnu")
    AuditLog.objects.create(
        user=None,
        username_snapshot=str(uname)[:150],
        action="LOGIN_FAILED",
        module="Authentification",
        object_repr=f"Tentative échouée ({uname})",
        details="Identifiants invalides ou compte désactivé.",
        ip_address=_extract_ip(request),
    )
