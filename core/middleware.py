"""Middleware de capture du contexte utilisateur et IP pour la journalisation (AuditLog)."""
import threading

_thread_locals = threading.local()


def get_current_user():
    return getattr(_thread_locals, "user", None)


def get_current_ip():
    return getattr(_thread_locals, "ip", None)


class AuditContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        _thread_locals.user = user if (user and user.is_authenticated) else None
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            _thread_locals.ip = x_forwarded_for.split(",")[0].strip()
        else:
            _thread_locals.ip = request.META.get("REMOTE_ADDR")
        try:
            response = self.get_response(request)
        finally:
            _thread_locals.user = None
            _thread_locals.ip = None
        return response
