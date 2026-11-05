from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import AuditLog, BackupRecord, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Informations LCK Services", {"fields": ("phone", "job_title", "is_access_admin")}),
    )
    list_display = ("username", "first_name", "last_name", "email", "job_title", "is_active", "is_access_admin")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "username_snapshot", "action", "module", "object_repr", "ip_address")
    list_filter = ("action", "module")
    search_fields = ("username_snapshot", "object_repr", "details")


@admin.register(BackupRecord)
class BackupRecordAdmin(admin.ModelAdmin):
    list_display = ("reference", "created_at", "size_bytes", "records_count", "created_by")
