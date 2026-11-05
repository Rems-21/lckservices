from django.urls import path
from . import views

app_name = "billing"

urlpatterns = [
    path("factures/", views.invoice_list_view, name="invoice_list"),
    path("factures/nouvelle/", views.invoice_create_view, name="invoice_create"),
    path("factures/generer-dossier/<int:folder_id>/", views.generate_folder_invoices_view, name="generate_folder_invoices"),
    path("factures/<int:pk>/", views.invoice_detail_view, name="invoice_detail"),
    path("factures/<int:pk>/modifier/", views.invoice_edit_view, name="invoice_edit"),
    path("factures/<int:pk>/convertir-definitive/", views.convert_proforma_view, name="convert_proforma"),
    path("factures/<int:pk>/annuler/", views.invoice_cancel_view, name="invoice_cancel"),
    path("factures/<int:pk>/lignes/ajouter/", views.invoice_line_add_view, name="line_add"),
    path("factures/<int:pk>/lignes/<int:line_id>/supprimer/", views.invoice_line_delete_view, name="line_delete"),
    path("paiements/", views.payment_list_create_view, name="payment_list"),
    path("creances-et-credit/", views.receivables_and_credit_view, name="receivables"),
    path("creances-et-credit/<int:pk>/statut/", views.credit_status_toggle_view, name="credit_status"),
    path("partage/facture/", views.shared_invoice_view, name="shared_invoice"),
]
