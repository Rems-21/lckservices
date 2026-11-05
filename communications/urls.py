from django.urls import path
from . import views

app_name = "communications"

urlpatterns = [
    path("", views.communication_hub_view, name="hub"),
    path("modeles/", views.template_list_create_view, name="templates"),
]
