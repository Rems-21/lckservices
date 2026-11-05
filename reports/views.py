"""Vues du Tableau de bord (Section 2.1), Recherche Live API, Notifications et Rapports/Comptabilité (Section 2.10)."""
import calendar
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, DecimalField, F, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from accounts.services import log_audit
from billing.models import CreditDeliveryAuthorization, Invoice, Payment
from cargo.models import Parcel
from clients.models import Client
from core.models import CompanySetting
from core.utils import format_fcfa
from documents.models import Document
from documents.pdf_service import build_pdf_response
from finance.models import FolderExpense
from logistics.models import Incident, TrackingEvent
from shipments.models import ShipmentFolder
from .excel_service import build_excel_response


MONTH_NAMES_FR = [
    "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
    "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
]
MONTH_SHORT_FR = ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"]


def _parse_date(val):
    if not val:
        return None
    try:
        return datetime.strptime(val, "%Y-%m-%d").date()
    except ValueError:
        return None


def _resolve_period_filter(request):
    """Résout le filtre temporel façon MTsarl (Ce mois, Cette année, Tout l'historique, Mois, Année, Plage)."""
    today = timezone.localdate()
    filter_type = request.GET.get("filter_type", "").strip()
    sel_month = int(request.GET.get("month", today.month) or today.month)
    sel_year = int(request.GET.get("year", today.year) or today.year)
    sel_month = max(1, min(12, sel_month))

    # Rétrocompatibilité avec date_from / date_to directs
    legacy_from = _parse_date(request.GET.get("date_from", ""))
    legacy_to = _parse_date(request.GET.get("date_to", ""))
    start_date_param = _parse_date(request.GET.get("start_date", "")) or legacy_from
    end_date_param = _parse_date(request.GET.get("end_date", "")) or legacy_to

    if not filter_type:
        if start_date_param or end_date_param:
            filter_type = "range"
        else:
            filter_type = "all"

    date_from = None
    date_to = None
    if filter_type == "this_month":
        date_from = date(today.year, today.month, 1)
        last_day = calendar.monthrange(today.year, today.month)[1]
        date_to = date(today.year, today.month, last_day)
    elif filter_type == "this_year":
        date_from = date(today.year, 1, 1)
        date_to = date(today.year, 12, 31)
    elif filter_type == "month":
        date_from = date(sel_year, sel_month, 1)
        last_day = calendar.monthrange(sel_year, sel_month)[1]
        date_to = date(sel_year, sel_month, last_day)
    elif filter_type == "year":
        date_from = date(sel_year, 1, 1)
        date_to = date(sel_year, 12, 31)
    elif filter_type == "range":
        date_from = start_date_param
        date_to = end_date_param
    else:
        filter_type = "all"

    return {
        "filter_type": filter_type,
        "month": sel_month,
        "year": sel_year,
        "date_from": date_from,
        "date_to": date_to,
        "start_date_str": date_from.strftime("%Y-%m-%d") if date_from else "",
        "end_date_str": date_to.strftime("%Y-%m-%d") if date_to else "",
        "years_choices": list(range(today.year + 1, today.year - 5, -1)),
        "months_choices": [(i + 1, MONTH_NAMES_FR[i]) for i in range(12)],
    }


def _build_report_dataset(date_from=None, date_to=None, transport_mode=""):
    folders_qs = ShipmentFolder.objects.select_related("origin", "destination", "created_by").all()
    parcels_qs = Parcel.objects.select_related("folder", "client").all()
    expenses_qs = FolderExpense.objects.select_related("folder", "category", "currency").all()
    invoices_qs = Invoice.objects.filter(invoice_type="DEFINITIVE").exclude(status="ANNULEE").select_related("client", "folder")
    payments_qs = Payment.objects.select_related("invoice", "invoice__folder", "client", "parcel").all()

    if date_from:
        folders_qs = folders_qs.filter(created_at__date__gte=date_from)
        parcels_qs = parcels_qs.filter(created_at__date__gte=date_from)
        expenses_qs = expenses_qs.filter(expense_date__gte=date_from)
        invoices_qs = invoices_qs.filter(issue_date__gte=date_from)
        payments_qs = payments_qs.filter(payment_date__gte=date_from)
    if date_to:
        folders_qs = folders_qs.filter(created_at__date__lte=date_to)
        parcels_qs = parcels_qs.filter(created_at__date__lte=date_to)
        expenses_qs = expenses_qs.filter(expense_date__lte=date_to)
        invoices_qs = invoices_qs.filter(issue_date__lte=date_to)
        payments_qs = payments_qs.filter(payment_date__lte=date_to)
    if transport_mode in ("MARITIME", "AERIEN"):
        folders_qs = folders_qs.filter(transport_mode=transport_mode)
        parcels_qs = parcels_qs.filter(folder__transport_mode=transport_mode)
        expenses_qs = expenses_qs.filter(folder__transport_mode=transport_mode)
        invoices_qs = invoices_qs.filter(folder__transport_mode=transport_mode)
        payments_qs = payments_qs.filter(
            Q(invoice__folder__transport_mode=transport_mode) | Q(parcel__folder__transport_mode=transport_mode)
        )

    invoiced_fcfa = invoices_qs.aggregate(s=Sum("total_amount_fcfa"))["s"] or Decimal("0.00")
    paid_on_invoices = invoices_qs.aggregate(s=Sum("paid_amount_fcfa"))["s"] or Decimal("0.00")
    collected_fcfa = payments_qs.aggregate(s=Sum("amount_fcfa"))["s"] or Decimal("0.00")
    expenses_fcfa = expenses_qs.aggregate(s=Sum("amount_fcfa"))["s"] or Decimal("0.00")
    receivables_fcfa = max(invoiced_fcfa - paid_on_invoices, Decimal("0.00"))

    parcel_agg = parcels_qs.aggregate(
        cnt=Count("id"),
        cbm=Sum("volume_cbm"),
        kg=Sum("weight_kg"),
    )

    profitability_rows = []
    for f in folders_qs.order_by("-created_at"):
        exp_val = f.total_expenses_fcfa
        inv_val = f.total_invoiced_fcfa
        if inv_val <= 0:
            inv_val = f.total_cost_share_fcfa
        paid_val = f.total_paid_fcfa
        prof_val = inv_val - exp_val
        pct_val = ((prof_val / inv_val) * Decimal("100")).quantize(Decimal("0.01")) if inv_val > 0 else Decimal("0.00")
        profitability_rows.append(
            {
                "folder": f,
                "reference": f.reference,
                "mode": f.get_transport_mode_display(),
                "route": f"{f.origin.city} -> {f.destination.city}",
                "status": f.get_status_display(),
                "status_code": f.status,
                "parcels_count": f.total_parcels_count,
                "volume_cbm": f.total_volume_cbm,
                "weight_kg": f.total_weight_kg,
                "expenses_fcfa": exp_val,
                "invoiced_fcfa": inv_val,
                "paid_fcfa": paid_val,
                "balance_fcfa": max(inv_val - paid_val, Decimal("0.00")),
                "profit_fcfa": prof_val,
                "margin_pct": pct_val,
            }
        )

    exp_by_type_qs = (
        expenses_qs.values("category__name")
        .annotate(cnt=Count("id"), total=Sum("amount_fcfa"))
        .order_by("-total")
    )
    expenses_by_type = []
    for row in exp_by_type_qs:
        tot = row["total"] or Decimal("0.00")
        pct = ((tot / expenses_fcfa) * Decimal("100")).quantize(Decimal("0.1")) if expenses_fcfa > 0 else Decimal("0.0")
        expenses_by_type.append(
            {
                "name": row["category__name"] or "Autres frais",
                "count": row["cnt"],
                "total_fcfa": tot,
                "percent": pct,
            }
        )

    # Série sur 12 mois (pour le graphique Comptabilité — Groupage façon MTsarl)
    chart_year = date_to.year if date_to else timezone.localdate().year
    monthly_labels = MONTH_SHORT_FR[:]
    monthly_rev = []
    monthly_col = []
    monthly_exp = []
    for m_idx in range(1, 13):
        m_start = date(chart_year, m_idx, 1)
        m_end = date(chart_year, m_idx, calendar.monthrange(chart_year, m_idx)[1])
        r_m = (
            Invoice.objects.filter(invoice_type="DEFINITIVE", issue_date__gte=m_start, issue_date__lte=m_end)
            .exclude(status="ANNULEE")
            .aggregate(s=Sum("total_amount_fcfa"))["s"]
            or Decimal("0")
        )
        c_m = (
            Payment.objects.filter(payment_date__gte=m_start, payment_date__lte=m_end)
            .aggregate(s=Sum("amount_fcfa"))["s"]
            or Decimal("0")
        )
        e_m = (
            FolderExpense.objects.filter(expense_date__gte=m_start, expense_date__lte=m_end)
            .aggregate(s=Sum("amount_fcfa"))["s"]
            or Decimal("0")
        )
        monthly_rev.append(float(r_m))
        monthly_col.append(float(c_m))
        monthly_exp.append(float(e_m))

    by_mode = [
        {
            "mode": "Maritime",
            "folders": folders_qs.filter(transport_mode="MARITIME").count(),
            "parcels": parcels_qs.filter(folder__transport_mode="MARITIME").count(),
            "cbm": parcels_qs.filter(folder__transport_mode="MARITIME").aggregate(s=Sum("volume_cbm"))["s"] or Decimal("0.0000"),
            "kg": parcels_qs.filter(folder__transport_mode="MARITIME").aggregate(s=Sum("weight_kg"))["s"] or Decimal("0.000"),
        },
        {
            "mode": "Aérien",
            "folders": folders_qs.filter(transport_mode="AERIEN").count(),
            "parcels": parcels_qs.filter(folder__transport_mode="AERIEN").count(),
            "cbm": parcels_qs.filter(folder__transport_mode="AERIEN").aggregate(s=Sum("volume_cbm"))["s"] or Decimal("0.0000"),
            "kg": parcels_qs.filter(folder__transport_mode="AERIEN").aggregate(s=Sum("weight_kg"))["s"] or Decimal("0.000"),
        },
    ]

    if date_from and date_to:
        period_label = f"Du {date_from:%d/%m/%Y} au {date_to:%d/%m/%Y}"
    elif date_from:
        period_label = f"Depuis le {date_from:%d/%m/%Y}"
    elif date_to:
        period_label = f"Jusqu'au {date_to:%d/%m/%Y}"
    else:
        period_label = "Tout l'historique"

    return {
        "period_label": period_label,
        "chart_year": chart_year,
        "chart_json": json.dumps(
            {
                "labels": monthly_labels,
                "revenues": monthly_rev,
                "collections": monthly_col,
                "expenses": monthly_exp,
            }
        ),
        "summary": {
            "folders_count": folders_qs.count(),
            "maritime_count": folders_qs.filter(transport_mode="MARITIME").count(),
            "aerien_count": folders_qs.filter(transport_mode="AERIEN").count(),
            "parcels_count": parcel_agg["cnt"] or 0,
            "volume_cbm": parcel_agg["cbm"] or Decimal("0.0000"),
            "weight_kg": parcel_agg["kg"] or Decimal("0.000"),
            "invoiced_fcfa": invoiced_fcfa,
            "collected_fcfa": collected_fcfa,
            "expenses_fcfa": expenses_fcfa,
            "net_profit_fcfa": invoiced_fcfa - expenses_fcfa,
            "cash_profit_fcfa": collected_fcfa - expenses_fcfa,
            "receivables_fcfa": receivables_fcfa,
        },
        "by_mode": by_mode,
        "expenses_by_type": expenses_by_type,
        "profitability_rows": profitability_rows,
        "expenses": list(expenses_qs[:150]),
        "invoices": list(invoices_qs[:150]),
        "payments": list(payments_qs[:150]),
    }


@login_required
def dashboard_view(request):
    """Tableau de bord Groupage & Transit façon MTsarl + indicateurs LCK Section 2.1."""
    total_folders_count = ShipmentFolder.objects.exclude(status="ANNULE").count()
    active_folders_count = ShipmentFolder.objects.exclude(status__in=["CLOTURE", "ANNULE"]).count()
    closed_folders_count = ShipmentFolder.objects.filter(status="CLOTURE").count()
    in_transit_count = ShipmentFolder.objects.filter(status="EN_TRANSIT").count()
    maritime_folders_count = ShipmentFolder.objects.filter(transport_mode="MARITIME").exclude(status="ANNULE").count()
    aerien_folders_count = ShipmentFolder.objects.filter(transport_mode="AERIEN").exclude(status="ANNULE").count()

    total_clients = Client.objects.filter(is_active=True).count()
    parcels_agg = Parcel.objects.aggregate(
        total=Count("id"),
        cbm=Sum("volume_cbm"),
        kg=Sum("weight_kg"),
    )

    definitive_invoices = Invoice.objects.filter(invoice_type="DEFINITIVE").exclude(status="ANNULEE")
    inv_agg = definitive_invoices.aggregate(
        invoiced=Sum("total_amount_fcfa"),
        paid=Sum("paid_amount_fcfa"),
    )
    total_invoiced = inv_agg["invoiced"] or Decimal("0.00")
    total_paid = inv_agg["paid"] or Decimal("0.00")
    total_unpaid = max(total_invoiced - total_paid, Decimal("0.00"))
    total_expenses = FolderExpense.objects.aggregate(s=Sum("amount_fcfa"))["s"] or Decimal("0.00")
    net_result = total_invoiced - total_expenses

    today = timezone.localdate()
    months_labels = []
    monthly_revenues = []
    monthly_collections = []
    monthly_expenses = []

    for offset in range(5, -1, -1):
        y = today.year
        m = today.month - offset
        while m <= 0:
            m += 12
            y -= 1
        start_m = date(y, m, 1)
        end_m = date(y, m, calendar.monthrange(y, m)[1])

        months_labels.append(f"{MONTH_SHORT_FR[m - 1]} {y}")
        rev_m = (
            definitive_invoices.filter(issue_date__gte=start_m, issue_date__lte=end_m)
            .aggregate(s=Sum("total_amount_fcfa"))["s"]
            or Decimal("0")
        )
        col_m = (
            Payment.objects.filter(payment_date__gte=start_m, payment_date__lte=end_m)
            .aggregate(s=Sum("amount_fcfa"))["s"]
            or Decimal("0")
        )
        exp_m = (
            FolderExpense.objects.filter(expense_date__gte=start_m, expense_date__lte=end_m)
            .aggregate(s=Sum("amount_fcfa"))["s"]
            or Decimal("0")
        )
        monthly_revenues.append(float(rev_m))
        monthly_collections.append(float(col_m))
        monthly_expenses.append(float(exp_m))

    status_map = dict(ShipmentFolder.STATUS_CHOICES)
    folders_by_status = list(
        ShipmentFolder.objects.values("status").annotate(cnt=Count("id")).order_by("-cnt")
    )

    chart_payload = {
        "months": months_labels,
        "revenues": monthly_revenues,
        "collections": monthly_collections,
        "expenses": monthly_expenses,
        "modes": [maritime_folders_count, aerien_folders_count],
        "status_labels": [status_map.get(x["status"], x["status"]) for x in folders_by_status],
        "status_values": [x["cnt"] for x in folders_by_status],
    }

    recent_folders = (
        ShipmentFolder.objects.select_related("origin", "destination", "created_by")
        .annotate(
            parcels_total=Count("parcels", distinct=True),
            frais_sum=Coalesce(
                Sum("expenses__amount_fcfa"),
                Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            ),
        )
        .order_by("-created_at")[:6]
    )
    unpaid_invoices = (
        definitive_invoices.annotate(rem=F("total_amount_fcfa") - F("paid_amount_fcfa"))
        .filter(rem__gt=0)
        .select_related("client", "folder")
        .order_by("-rem")[:5]
    )
    open_incidents = Incident.objects.filter(status="EN_COURS").select_related("folder", "parcel")[:5]

    return render(
        request,
        "reports/dashboard.html",
        {
            "kpi": {
                "total_folders": total_folders_count,
                "active_folders": active_folders_count,
                "in_transit": in_transit_count,
                "closed_folders": closed_folders_count,
                "maritime_folders": maritime_folders_count,
                "aerien_folders": aerien_folders_count,
                "total_clients": total_clients,
                "total_parcels": parcels_agg["total"] or 0,
                "total_cbm": parcels_agg["cbm"] or Decimal("0.0000"),
                "total_kg": parcels_agg["kg"] or Decimal("0.000"),
                "total_invoiced": total_invoiced,
                "total_paid": total_paid,
                "total_unpaid": total_unpaid,
                "total_expenses": total_expenses,
                "net_result": net_result,
            },
            "chart_json": json.dumps(chart_payload),
            "recent_folders": recent_folders,
            "unpaid_invoices": unpaid_invoices,
            "open_incidents": open_incidents,
        },
    )


@login_required
def reports_hub_view(request):
    period = _resolve_period_filter(request)
    mode = request.GET.get("mode", "").strip()
    report_data = _build_report_dataset(
        date_from=period["date_from"],
        date_to=period["date_to"],
        transport_mode=mode,
    )
    return render(
        request,
        "reports/reports_hub.html",
        {
            "report": report_data,
            "period": period,
            "date_from": period["start_date_str"],
            "date_to": period["end_date_str"],
            "mode": mode,
        },
    )


@login_required
def reports_export_pdf_view(request):
    period = _resolve_period_filter(request)
    mode = request.GET.get("mode", "").strip()

    report_data = _build_report_dataset(
        date_from=period["date_from"],
        date_to=period["date_to"],
        transport_mode=mode,
    )
    company = CompanySetting.get_solo()
    log_audit("EXPORT", "Rapports", f"Rapport PDF ({report_data['period_label']})", "", "Exportation PDF des rapports d'activité et rentabilité.")
    return build_pdf_response(
        "pdf/report_pdf.html",
        {
            "company": company,
            "report": report_data,
            "generated_at": timezone.localtime(),
        },
        filename=f"RAPPORT_LCK_{timezone.localdate():%Y%m%d}.pdf",
        as_attachment=True,
        base_url=request.build_absolute_uri("/"),
    )


@login_required
def reports_export_excel_view(request):
    period = _resolve_period_filter(request)
    mode = request.GET.get("mode", "").strip()

    report_data = _build_report_dataset(
        date_from=period["date_from"],
        date_to=period["date_to"],
        transport_mode=mode,
    )
    log_audit("EXPORT", "Rapports", f"Rapport Excel ({report_data['period_label']})", "", "Exportation Excel OpenPyXL multi-feuilles.")
    return build_excel_response(
        report_data,
        filename=f"RAPPORT_LCK_{timezone.localdate():%Y%m%d}.xlsx",
    )


@login_required
def global_search_view(request):
    q = request.GET.get("q", "").strip()
    clients = []
    folders = []
    parcels = []
    invoices = []
    documents = []

    if q:
        clients = Client.objects.filter(
            Q(code__icontains=q) | Q(name__icontains=q) | Q(phone__icontains=q)
        )[:10]
        folders = ShipmentFolder.objects.select_related("origin", "destination").filter(
            Q(reference__icontains=q)
            | Q(title__icontains=q)
            | Q(bl_number__icontains=q)
            | Q(awb_number__icontains=q)
            | Q(container_number__icontains=q)
            | Q(flight_number__icontains=q)
        )[:10]
        parcels = Parcel.objects.select_related("client", "folder").filter(
            Q(parcel_code__icontains=q)
            | Q(description__icontains=q)
            | Q(chassis_number__icontains=q)
            | Q(supplier_tracking__icontains=q)
        )[:10]
        invoices = Invoice.objects.select_related("client", "folder").filter(
            Q(number__icontains=q) | Q(client__name__icontains=q)
        )[:10]
        documents = Document.objects.select_related("folder", "client").filter(
            Q(reference__icontains=q) | Q(title__icontains=q) | Q(external_number__icontains=q)
        )[:10]

    return render(
        request,
        "reports/global_search.html",
        {
            "q": q,
            "clients": clients,
            "folders": folders,
            "parcels": parcels,
            "invoices": invoices,
            "documents": documents,
        },
    )


@login_required
def search_api_view(request):
    """API JSON de recherche instantanée dans la barre supérieure (Ctrl+K) façon MTsarl."""
    q = request.GET.get("q", "").strip()
    if len(q) < 2:
        return JsonResponse({"groups": []})

    groups = []

    folders = ShipmentFolder.objects.select_related("origin", "destination").filter(
        Q(reference__icontains=q)
        | Q(title__icontains=q)
        | Q(container_number__icontains=q)
        | Q(bl_number__icontains=q)
        | Q(awb_number__icontains=q)
        | Q(flight_number__icontains=q)
    )[:5]
    if folders:
        groups.append(
            {
                "title": "Dossiers de Groupage",
                "items": [
                    {
                        "label": f"{f.reference} — {f.origin.city} → {f.destination.city}",
                        "sub": f"{f.get_transport_mode_display()} • {f.get_status_display()}",
                        "url": reverse("shipments:detail", kwargs={"pk": f.pk}),
                        "icon": "ship" if f.transport_mode == "MARITIME" else "plane",
                    }
                    for f in folders
                ],
            }
        )

    parcels = Parcel.objects.select_related("client", "folder").filter(
        Q(parcel_code__icontains=q)
        | Q(description__icontains=q)
        | Q(chassis_number__icontains=q)
        | Q(client__name__icontains=q)
    )[:5]
    if parcels:
        groups.append(
            {
                "title": "Colis & Marchandises",
                "items": [
                    {
                        "label": f"{p.parcel_code} — {p.description[:45]}",
                        "sub": f"{p.client.name} • Dossier {p.folder.reference}",
                        "url": f"{reverse('shipments:detail', kwargs={'pk': p.folder_id})}#item-{p.pk}",
                        "icon": "package",
                    }
                    for p in parcels
                ],
            }
        )

    clients = Client.objects.filter(
        Q(code__icontains=q) | Q(name__icontains=q) | Q(phone__icontains=q) | Q(city__icontains=q)
    )[:5]
    if clients:
        groups.append(
            {
                "title": "Clients",
                "items": [
                    {
                        "label": f"{c.name} ({c.code})",
                        "sub": f"{c.phone} • {c.city}",
                        "url": reverse("clients:detail", kwargs={"pk": c.pk}),
                        "icon": "user",
                    }
                    for c in clients
                ],
            }
        )

    invoices = Invoice.objects.select_related("client", "folder").filter(
        Q(number__icontains=q) | Q(client__name__icontains=q)
    )[:5]
    if invoices:
        groups.append(
            {
                "title": "Factures",
                "items": [
                    {
                        "label": f"{inv.number} — {inv.client.name}",
                        "sub": f"{format_fcfa(inv.total_amount_fcfa)} • {inv.get_status_display()}",
                        "url": reverse("billing:invoice_detail", kwargs={"pk": inv.pk}),
                        "icon": "file-text",
                    }
                    for inv in invoices
                ],
            }
        )

    return JsonResponse({"groups": groups})


def _collect_operational_notifications(request):
    """Génère les alertes opérationnelles intelligentes (ETA proche/dépassée, impayés, crédits, incidents)."""
    today = timezone.localdate()
    soon = today + timedelta(days=5)
    read_keys = set(request.session.get("read_notif_keys", []))
    items = []

    # 1. Dossiers en transit arrivant sous 5 jours ou en retard d'ETA
    eta_folders = ShipmentFolder.objects.select_related("origin", "destination").filter(
        status__in=["CHARGE", "EN_TRANSIT"],
        eta__isnull=False,
        eta__lte=soon,
    )[:10]
    for f in eta_folders:
        key = f"eta-{f.pk}-{f.eta}"
        overdue = f.eta < today
        items.append(
            {
                "key": key,
                "category": "Arrivée Groupage",
                "title": f"ETA dépassée : {f.reference}" if overdue else f"Arrivée imminente : {f.reference}",
                "message": f"{f.get_transport_mode_display()} {f.origin.city} → {f.destination.city} prévu le {f.eta:%d/%m/%Y}.",
                "icon": "ship" if f.transport_mode == "MARITIME" else "plane",
                "color": "danger" if overdue else "info",
                "url": reverse("shipments:detail", kwargs={"pk": f.pk}),
                "date_label": f.eta.strftime("%d/%m/%Y"),
                "is_read": key in read_keys,
            }
        )

    # 2. Incidents logistiques ouverts
    for inc in Incident.objects.filter(status="EN_COURS").select_related("folder")[:8]:
        key = f"inc-{inc.pk}"
        items.append(
            {
                "key": key,
                "category": "Incident / Avarie",
                "title": f"{inc.reference} — {inc.title}",
                "message": f"Dossier {inc.folder.reference} • Gravité : {inc.get_severity_display()}",
                "icon": "alert-triangle",
                "color": "danger" if inc.severity == "CRITIQUE" else "warning",
                "url": reverse("shipments:detail", kwargs={"pk": inc.folder_id}),
                "date_label": inc.reported_at.strftime("%d/%m/%Y"),
                "is_read": key in read_keys,
            }
        )

    # 3. Autorisations de livraison à crédit actives proches d'échéance
    for auth_obj in CreditDeliveryAuthorization.objects.filter(status="ACTIVE").select_related("client", "invoice")[:8]:
        key = f"cred-{auth_obj.pk}"
        overdue = auth_obj.promised_due_date < today
        items.append(
            {
                "key": key,
                "category": "Livraison à crédit",
                "title": f"Crédit client : {auth_obj.client.name}",
                "message": f"Solde autorisé {format_fcfa(auth_obj.authorized_balance_fcfa)} sur {auth_obj.invoice.number} (échéance {auth_obj.promised_due_date:%d/%m/%Y}).",
                "icon": "shield-alert",
                "color": "danger" if overdue else "warning",
                "url": reverse("billing:receivables"),
                "date_label": auth_obj.promised_due_date.strftime("%d/%m/%Y"),
                "is_read": key in read_keys,
            }
        )

    # 4. Factures définitives avec solde impayé
    unpaid_qs = (
        Invoice.objects.filter(invoice_type="DEFINITIVE")
        .exclude(status__in=["PAYEE", "ANNULEE"])
        .annotate(rem=F("total_amount_fcfa") - F("paid_amount_fcfa"))
        .filter(rem__gt=0)
        .select_related("client", "folder")
        .order_by("-rem")[:8]
    )
    for inv in unpaid_qs:
        key = f"inv-{inv.pk}-{int(inv.rem)}"
        items.append(
            {
                "key": key,
                "category": "Créance Client",
                "title": f"Solde à recouvrer : {inv.number}",
                "message": f"{inv.client.name} — Reste à payer : {format_fcfa(inv.rem)}",
                "icon": "wallet",
                "color": "primary",
                "url": reverse("shipments:detail", kwargs={"pk": inv.folder_id}) if inv.folder_id else reverse("billing:invoice_detail", kwargs={"pk": inv.pk}),
                "date_label": inv.issue_date.strftime("%d/%m/%Y"),
                "is_read": key in read_keys,
            }
        )

    unread_count = sum(1 for x in items if not x["is_read"])
    return items, unread_count


@login_required
def notifications_count_api_view(request):
    _, unread_count = _collect_operational_notifications(request)
    return JsonResponse({"unread": unread_count})


@login_required
def notifications_view(request):
    items, unread_count = _collect_operational_notifications(request)
    if request.method == "POST":
        action = request.POST.get("action", "")
        read_keys = set(request.session.get("read_notif_keys", []))
        if action == "mark_all_read":
            for it in items:
                read_keys.add(it["key"])
            request.session["read_notif_keys"] = list(read_keys)
            messages.success(request, "Toutes les notifications ont été marquées comme lues.")
        elif action == "mark_one" and request.POST.get("key"):
            read_keys.add(request.POST["key"])
            request.session["read_notif_keys"] = list(read_keys)
        return redirect("reports:notifications")

    filter_mode = request.GET.get("filter", "all")
    displayed = [x for x in items if not x["is_read"]] if filter_mode == "unread" else items
    return render(
        request,
        "reports/notifications.html",
        {
            "notifications": displayed,
            "total_count": len(items),
            "unread_count": unread_count,
            "filter_mode": filter_mode,
        },
    )
