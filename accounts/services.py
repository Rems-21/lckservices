"""Services de journalisation (AuditLog) et de sauvegarde complète (Base + Documents)."""
import io
import json
import os
import zipfile
from pathlib import Path
from django.apps import apps
from django.conf import settings
from django.core import serializers
from django.core.files.base import ContentFile
from django.utils import timezone
from core.middleware import get_current_ip, get_current_user
from .models import AuditLog, BackupRecord


def log_audit(
    action: str,
    module: str,
    object_repr: str,
    object_id: str = "",
    details: str = "",
    user=None,
    ip_address: str = None,
):
    """Enregistre une entrée dans le journal des opérations."""
    actor = user or get_current_user()
    ip = ip_address or get_current_ip()
    username = actor.username if (actor and getattr(actor, "is_authenticated", False)) else "Système"
    return AuditLog.objects.create(
        user=actor if (actor and getattr(actor, "is_authenticated", False)) else None,
        username_snapshot=username,
        action=action,
        module=module,
        object_repr=str(object_repr)[:255],
        object_id=str(object_id)[:64],
        details=details or "",
        ip_address=ip,
    )


def create_full_backup(user=None, include_media: bool = True, notes: str = "") -> BackupRecord:
    """
    Crée une archive ZIP horodatée contenant :
    1. L'export JSON intégral de toutes les tables métiers et utilisateurs (compatible loaddata).
    2. Un manifeste récapitulatif de contrôle d'intégrité.
    3. L'ensemble des documents stockés dans MEDIA_ROOT (hors dossier backups/).
    """
    now = timezone.localtime()
    reference = f"BKP-{now:%Y%m%d-%H%M%S}"
    target_apps = [
        "core",
        "accounts",
        "clients",
        "shipments",
        "cargo",
        "logistics",
        "finance",
        "billing",
        "documents",
        "communications",
    ]

    all_objects = []
    summary_counts = {}
    for app_label in target_apps:
        app_config = apps.get_app_config(app_label)
        for model in app_config.get_models():
            if model is BackupRecord:
                continue
            qs = model.objects.all()
            count = qs.count()
            summary_counts[f"{app_label}.{model.__name__}"] = count
            all_objects.extend(list(qs))

    serialized_db = serializers.serialize("json", all_objects, indent=2)

    zip_buffer = io.BytesIO()
    media_files_count = 0
    media_root = Path(settings.MEDIA_ROOT)

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("database/lck_services_dump.json", serialized_db.encode("utf-8"))

        if include_media and media_root.exists():
            for root, dirs, files in os.walk(media_root):
                rel_root = Path(root).relative_to(media_root)
                if rel_root.parts and rel_root.parts[0] == "backups":
                    continue
                for fname in files:
                    fpath = Path(root) / fname
                    arcname = str(Path("media") / rel_root / fname).replace("\\", "/")
                    zf.write(fpath, arcname)
                    media_files_count += 1

        manifest = {
            "reference": reference,
            "company": "LCK Services SARL",
            "created_at": now.isoformat(),
            "created_by": user.username if user else "system",
            "records_total": len(all_objects),
            "media_files_included": media_files_count,
            "tables": summary_counts,
            "notes": notes,
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8"))

    content_bytes = zip_buffer.getvalue()
    record = BackupRecord(
        reference=reference,
        size_bytes=len(content_bytes),
        includes_media=include_media,
        records_count=len(all_objects),
        notes=notes or "Sauvegarde manuelle complète",
        created_by=user,
    )
    record.archive_file.save(f"{reference}.zip", ContentFile(content_bytes), save=True)

    log_audit(
        action="BACKUP",
        module="Administration & Sécurité",
        object_repr=reference,
        object_id=str(record.pk),
        details=f"Archive créée ({record.size_human}, {len(all_objects)} enregistrements, {media_files_count} fichiers).",
        user=user,
    )
    return record
