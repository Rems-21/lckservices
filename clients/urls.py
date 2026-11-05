from django.urls import path
from . import views

app_name = "clients"

urlpatterns = [
    path("", views.client_list_view, name="list"),
    path("nouveau/", views.client_create_view, name="create"),
    path("quick-create/", views.client_quick_create_view, name="quick_create"),
    path("detail/", views.client_detail_query_view, name="detail_query"),
    path("<int:pk>/", views.client_detail_view, name="detail"),
    path("<int:pk>/modifier/", views.client_edit_view, name="edit"),
    path("<int:pk>/quick-update/", views.client_quick_update_view, name="quick_update"),
    path("<int:pk>/supprimer/", views.client_delete_view, name="delete"),
    path("<int:pk>/contacts/ajouter/", views.client_contact_add_view, name="contact_add"),
    path("<int:pk>/contacts/<int:contact_id>/supprimer/", views.client_contact_delete_view, name="contact_delete"),
]
