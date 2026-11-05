from django.urls import path
from . import views

app_name = "cargo"

urlpatterns = [
    path("", views.parcel_list_view, name="list"),
    path("nouveau/", views.parcel_create_view, name="create"),
    path("categories/", views.category_list_create_view, name="categories"),
    path("<int:pk>/", views.parcel_detail_view, name="detail"),
    path("<int:pk>/modifier/", views.parcel_edit_view, name="edit"),
]
