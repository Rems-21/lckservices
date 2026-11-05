from django.urls import path
from . import views

app_name = "finance"

urlpatterns = [
    path("", views.expense_list_view, name="expense_list"),
    path("nouvelle/", views.expense_create_view, name="expense_create"),
    path("<int:pk>/modifier/", views.expense_edit_view, name="expense_edit"),
    path("<int:pk>/supprimer/", views.expense_delete_view, name="expense_delete"),
    path("categories/", views.expense_category_list_view, name="categories"),
    path("repartition/dossier/<int:folder_id>/", views.folder_allocation_view, name="allocate_folder"),
    path("repartition/historique/", views.allocation_history_view, name="allocation_history"),
    path("repartition/<int:pk>/", views.allocation_detail_view, name="allocation_detail"),
]
