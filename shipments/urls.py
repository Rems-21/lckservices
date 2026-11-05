from django.urls import path
from . import views

app_name = "shipments"

urlpatterns = [
    path("", views.folder_list_view, name="list"),
    path("nouveau/", views.folder_create_view, name="create"),
    path("quick-create/", views.folder_quick_create_view, name="quick_create"),
    path("detail/", views.folder_detail_query_view, name="detail_query"),
    path("ports-aeroports/", views.location_list_create_view, name="locations"),
    path("<int:pk>/", views.folder_detail_view, name="detail"),
    path("<int:pk>/modifier/", views.folder_edit_view, name="edit"),
    path("<int:pk>/quick-update/", views.folder_quick_update_view, name="quick_update"),
    path("<int:pk>/supprimer/", views.folder_delete_view, name="delete"),
    path("<int:pk>/statut/", views.folder_status_update_view, name="status_update"),
    path("<int:pk>/fiche/", views.folder_print_fiche_view, name="print_fiche"),
    path("<int:pk>/items/add/", views.folder_add_items_view, name="add_items"),
    path("<int:pk>/items/<int:item_id>/update/", views.folder_update_item_view, name="update_item"),
    path("<int:pk>/items/<int:item_id>/delete/", views.folder_delete_item_view, name="delete_item"),
    path("<int:pk>/items/<int:item_id>/pay/", views.folder_pay_item_view, name="pay_item"),
    path("<int:pk>/items/<int:item_id>/deliver/", views.folder_deliver_item_view, name="deliver_item"),
    path("<int:pk>/payments/<int:payment_id>/delete/", views.folder_delete_payment_view, name="delete_payment"),
    path("<int:pk>/expenses/add/", views.folder_expense_add_view, name="expense_add"),
    path("<int:pk>/expenses/<int:exp_id>/update/", views.folder_expense_update_view, name="expense_update"),
    path("<int:pk>/expenses/<int:exp_id>/delete/", views.folder_expense_delete_view, name="expense_delete"),
    path("<int:pk>/recalculate-allocation/", views.folder_recalculate_allocation_view, name="recalculate_allocation"),
    path("<int:pk>/logistics/quick-op/", views.folder_quick_warehouse_op_view, name="quick_warehouse_op"),
    path("<int:pk>/incidents/quick-add/", views.folder_quick_incident_view, name="quick_incident_add"),
    path("<int:pk>/documents/quick-add/", views.folder_quick_document_view, name="quick_document_add"),
]
