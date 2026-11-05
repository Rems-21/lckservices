from django.urls import path
from . import views

app_name = "documents"

urlpatterns = [
    path("", views.document_list_create_view, name="list"),
    path("<int:pk>/supprimer/", views.document_delete_view, name="delete"),
    path("pdf/facture/<int:pk>/", views.invoice_pdf_view, name="invoice_pdf"),
    path("pdf/recu/<int:pk>/", views.receipt_pdf_view, name="receipt_pdf"),
    path("pdf/manifeste/<int:folder_id>/", views.manifest_pdf_view, name="manifest_pdf"),
    path("pdf/bon-livraison/<int:delivery_id>/", views.delivery_note_pdf_view, name="delivery_note_pdf"),
    path("pdf/etiquette-colis/<int:parcel_id>/", views.parcel_label_pdf_view, name="parcel_label_pdf"),
    path("verifier/<str:doc_kind>/<str:token>/", views.verify_document_qr_view, name="verify_qr"),
]
