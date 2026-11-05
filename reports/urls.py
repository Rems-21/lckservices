from django.urls import path
from . import views

app_name = "reports"

urlpatterns = [
    path("", views.dashboard_view, name="dashboard"),
    path("rapports/", views.reports_hub_view, name="hub"),
    path("rapports/export/pdf/", views.reports_export_pdf_view, name="export_pdf"),
    path("rapports/export/excel/", views.reports_export_excel_view, name="export_excel"),
    path("recherche/", views.global_search_view, name="global_search"),
    path("search/api/", views.search_api_view, name="search_api"),
    path("api/notifications/count/", views.notifications_count_api_view, name="notifications_count_api"),
    path("notifications/", views.notifications_view, name="notifications"),
]
