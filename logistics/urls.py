from django.urls import path
from . import views

app_name = "logistics"

urlpatterns = [
    path("", views.logistics_hub_view, name="hub"),
    path("tracking/ajouter/", views.tracking_event_add_view, name="tracking_add"),
    path("entrepot/", views.warehouse_operation_list_create_view, name="warehouse"),
    path("livraisons/", views.delivery_list_view, name="delivery_list"),
    path("livraisons/nouvelle/", views.delivery_create_view, name="delivery_create"),
    path("livraisons/<int:pk>/", views.delivery_detail_view, name="delivery_detail"),
    path("incidents/", views.incident_list_view, name="incident_list"),
    path("incidents/nouveau/", views.incident_create_view, name="incident_create"),
    path("incidents/<int:pk>/modifier/", views.incident_edit_view, name="incident_edit"),
]
