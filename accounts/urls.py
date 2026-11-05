from django.urls import path
from . import views

app_name = "accounts"

urlpatterns = [
    path("connexion/", views.LCKLoginView.as_view(), name="login"),
    path("deconnexion/", views.LCKLogoutView.as_view(), name="logout"),
    path("profil/", views.profile_view, name="profile"),
    path("utilisateurs/", views.user_list_view, name="user_list"),
    path("utilisateurs/nouveau/", views.user_create_view, name="user_create"),
    path("utilisateurs/enregistrer/", views.user_modal_save_view, name="user_modal_save"),
    path("utilisateurs/<int:pk>/modifier/", views.user_edit_view, name="user_edit"),
    path("utilisateurs/<int:pk>/statut/", views.user_toggle_active_view, name="user_toggle"),
    path("utilisateurs/<int:pk>/mot-de-passe/", views.user_reset_password_view, name="user_reset_password"),
    path("journal/", views.audit_log_list_view, name="audit_list"),
    path("journal/purger/", views.audit_clear_view, name="audit_clear"),
    path("administration/", views.settings_and_backups_view, name="settings_backups"),
    path("sauvegardes/<int:pk>/telecharger/", views.backup_download_view, name="backup_download"),
    path("sauvegardes/<int:pk>/supprimer/", views.backup_delete_view, name="backup_delete"),
]
