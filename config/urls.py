"""Routage principal URL — Plateforme LCK Services SARL (avec alias /groupage/ et /accounting/groupage/)."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from billing import views as billing_views
from clients import views as clients_views
from reports import views as reports_views
from shipments import views as shipments_views

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("", include("reports.urls")),
    path("accounts/", include("accounts.urls")),
    path("clients/", include("clients.urls")),
    path("dossiers/", include("shipments.urls")),
    path("marchandises/", include("cargo.urls")),
    path("logistique/", include("logistics.urls")),
    path("depenses/", include("finance.urls")),
    path("facturation/", include("billing.urls")),
    path("documents/", include("documents.urls")),
    path("communication/", include("communications.urls")),
    # Alias ergonomiques directs façon MTsarl (/groupage/*, /accounting/groupage/, /partage/facture/)
    path("groupage/", reports_views.dashboard_view, name="groupage_dashboard_alias"),
    path("groupage/dossiers/", shipments_views.folder_list_view, name="groupage_dossiers_alias"),
    path("groupage/dossier/detail", shipments_views.folder_detail_query_view, name="groupage_dossier_detail_query"),
    path("groupage/dossier/<int:pk>/", shipments_views.folder_detail_view, name="groupage_dossier_detail_alias"),
    path("groupage/clients/", clients_views.client_list_view, name="groupage_clients_alias"),
    path("groupage/clients/detail", clients_views.client_detail_query_view, name="groupage_client_detail_query"),
    path("accounting/groupage/", reports_views.reports_hub_view, name="accounting_groupage_alias"),
    path("partage/facture/", billing_views.shared_invoice_view, name="shared_invoice_root"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])
