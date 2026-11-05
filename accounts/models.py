"""Modèles Utilisateur (rôle unique Utilisateur + gestionnaire d'accès initial), AuditLog et Sauvegardes."""
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Compte utilisateur de la plateforme LCK Services SARL.
    Conformément à la section 3 du cahier des charges :
    - Un seul rôle fonctionnel : 'Utilisateur' (mêmes droits fonctionnels sur tous les modules).
    - 'is_access_admin' identifie le compte administrateur initial chargé de gérer les accès/comptes.
    """

    FUNCTIONAL_ROLE_LABEL = "Utilisateur"

    phone = models.CharField("Téléphone", max_length=40, blank=True, default="")
    job_title = models.CharField("Fonction / Poste", max_length=100, blank=True, default="Agent Opérationnel")
    is_access_admin = models.BooleanField(
        "Gestionnaire des accès (Compte administrateur initial)",
        default=False,
        help_text="Permet de créer, modifier, activer et désactiver les comptes utilisateurs.",
    )
    created_at = models.DateTimeField("Date de création", auto_now_add=True)
    updated_at = models.DateTimeField("Dernière mise à jour", auto_now=True)

    class Meta:
        verbose_name = "Utilisateur"
        verbose_name_plural = "Utilisateurs"
        ordering = ["username"]

    @property
    def display_name(self) -> str:
        full = self.get_full_name().strip()
        return full if full else self.username

    @property
    def initials(self) -> str:
        parts = [p for p in self.display_name.split() if p]
        if len(parts) >= 2:
            return (parts[0][0] + parts[1][0]).upper()
        if parts:
            return parts[0][:2].upper()
        return "U"

    @property
    def role_label(self) -> str:
        return self.FUNCTIONAL_ROLE_LABEL

    @property
    def can_manage_accounts(self) -> bool:
        return bool(self.is_access_admin or self.is_superuser)

    def __str__(self):
        return f"{self.display_name} ({self.username})"


class AuditLog(models.Model):
    """Journalisation chronologique de toutes les opérations sensibles et métiers."""

    ACTION_CHOICES = [
        ("LOGIN", "Connexion"),
        ("LOGOUT", "Déconnexion"),
        ("LOGIN_FAILED", "Échec de connexion"),
        ("CREATE", "Création"),
        ("UPDATE", "Modification"),
        ("DELETE", "Suppression"),
        ("STATUS", "Changement de statut"),
        ("ALLOCATION", "Répartition des frais"),
        ("PAYMENT", "Enregistrement paiement"),
        ("CREDIT_AUTH", "Autorisation crédit"),
        ("DOCUMENT", "Génération / Import document"),
        ("WHATSAPP", "Partage communication"),
        ("EXPORT", "Exportation rapport"),
        ("BACKUP", "Sauvegarde système"),
        ("ACCOUNT", "Gestion de compte"),
    ]

    user = models.ForeignKey(
        User,
        verbose_name="Utilisateur",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    username_snapshot = models.CharField("Identifiant", max_length=150, blank=True, default="")
    action = models.CharField("Action", max_length=30, choices=ACTION_CHOICES, db_index=True)
    module = models.CharField("Module", max_length=80, db_index=True)
    object_repr = models.CharField("Élément concerné", max_length=255)
    object_id = models.CharField("ID Objet", max_length=64, blank=True, default="")
    details = models.TextField("Détails de l'opération", blank=True, default="")
    ip_address = models.GenericIPAddressField("Adresse IP", null=True, blank=True)
    created_at = models.DateTimeField("Date & Heure", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Journal d'activité"
        verbose_name_plural = "Journal des opérations"
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.created_at:%d/%m/%Y %H:%M}] {self.username_snapshot} - {self.get_action_display()} ({self.module})"


class BackupRecord(models.Model):
    """Historique des sauvegardes de la base de données et des documents."""

    reference = models.CharField("Référence sauvegarde", max_length=60, unique=True)
    archive_file = models.FileField("Fichier d'archive (.zip)", upload_to="backups/")
    size_bytes = models.BigIntegerField("Taille (octets)", default=0)
    includes_media = models.BooleanField("Inclut les documents (media)", default=True)
    records_count = models.PositiveIntegerField("Nombre d'enregistrements", default=0)
    notes = models.CharField("Observation", max_length=255, blank=True, default="")
    created_by = models.ForeignKey(
        User,
        verbose_name="Réalisée par",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="backups_created",
    )
    created_at = models.DateTimeField("Date de sauvegarde", auto_now_add=True)

    class Meta:
        verbose_name = "Sauvegarde"
        verbose_name_plural = "Sauvegardes"
        ordering = ["-created_at"]

    @property
    def size_human(self) -> str:
        size = float(self.size_bytes or 0)
        for unit in ("o", "Ko", "Mo", "Go"):
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} To"

    def __str__(self):
        return f"{self.reference} ({self.size_human})"
