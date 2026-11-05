"""Vues de suivi logistique, tracking chronologique, opérations d'entrepôt, livraisons et incidents (Section 2.5)."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from accounts.services import log_audit
from cargo.models import Parcel
from shipments.models import ShipmentFolder
from .forms import DeliveryForm, IncidentForm, TrackingEventForm, WarehouseOperationForm
from .models import Delivery, Incident, TrackingEvent, WarehouseOperation


@login_required
def logistics_hub_view(request):
    code_query = request.GET.get("track", "").strip()
    tracked_parcel = None
    tracked_folder = None
    timeline = []

    if code_query:
        tracked_parcel = (
            Parcel.objects.select_related("folder", "folder__origin", "folder__destination", "client")
            .filter(parcel_code__iexact=code_query)
            .first()
        )
        if tracked_parcel:
            timeline = TrackingEvent.objects.filter(
                Q(parcel=tracked_parcel) | Q(folder=tracked_parcel.folder, parcel__isnull=True)
            ).select_related("recorded_by")
        else:
            tracked_folder = (
                ShipmentFolder.objects.select_related("origin", "destination")
                .filter(
                    Q(reference__iexact=code_query)
                    | Q(bl_number__iexact=code_query)
                    | Q(awb_number__iexact=code_query)
                    | Q(container_number__iexact=code_query)
                )
                .first()
            )
            if tracked_folder:
                timeline = tracked_folder.tracking_events.select_related("parcel", "recorded_by").all()

    recent_events = TrackingEvent.objects.select_related("folder", "parcel", "recorded_by")[:25]
    warehouse_ops = WarehouseOperation.objects.select_related("folder", "operator")[:10]
    open_incidents = Incident.objects.filter(status="EN_COURS").select_related("folder", "parcel", "client")[:8]
    recent_deliveries = Delivery.objects.select_related("client", "folder", "delivered_by")[:8]

    event_form = TrackingEventForm()
    return render(
        request,
        "logistics/hub.html",
        {
            "code_query": code_query,
            "tracked_parcel": tracked_parcel,
            "tracked_folder": tracked_folder,
            "timeline": timeline,
            "recent_events": recent_events,
            "warehouse_ops": warehouse_ops,
            "open_incidents": open_incidents,
            "recent_deliveries": recent_deliveries,
            "event_form": event_form,
        },
    )


@login_required
def tracking_event_add_view(request):
    if request.method == "POST":
        form = TrackingEventForm(request.POST)
        if form.is_valid():
            ev = form.save(commit=False)
            ev.recorded_by = request.user
            ev.save()

            if form.cleaned_data.get("propagate_status"):
                stage_to_parcel_status = {
                    "RECEPTION_ORIGINE": "RECU_ORIGINE",
                    "CHARGEMENT": "CHARGE",
                    "DEPART": "EN_TRANSIT",
                    "TRANSBORDEMENT": "EN_TRANSIT",
                    "ARRIVEE_PORT_AERO": "ARRIVE",
                    "RECEPTION_ENTREPOT": "DISPONIBLE_ENTREPOT",
                    "DISPONIBLE": "DISPONIBLE_ENTREPOT",
                    "LIVRAISON": "LIVRE",
                    "INCIDENT": "LITIGE",
                }
                new_p_status = stage_to_parcel_status.get(ev.stage)
                if new_p_status:
                    if ev.parcel_id:
                        ev.parcel.status = new_p_status
                        ev.parcel.save(update_fields=["status", "updated_at"])
                    else:
                        ev.folder.parcels.exclude(status="LIVRE").update(status=new_p_status)

            log_audit(
                "STATUS",
                "Tracking logistique",
                str(ev),
                str(ev.pk),
                f"Étape enregistrée : {ev.get_stage_display()} à {ev.location_text}.",
            )
            messages.success(request, "Mouvement d'acheminement enregistré dans l'historique.")
        else:
            messages.error(request, "Impossible d'enregistrer le mouvement : vérifiez les champs saisis.")
    next_url = request.POST.get("next") or "logistics:hub"
    return redirect(next_url)


@login_required
def warehouse_operation_list_create_view(request):
    initial = {}
    if request.GET.get("folder", "").isdigit():
        initial["folder"] = int(request.GET["folder"])

    form = WarehouseOperationForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        op = form.save(commit=False)
        op.operator = request.user
        op.save()

        stage_map = {
            "RECEPTION_ORIGINE": ("RECEPTION_ORIGINE", "RECU_ORIGINE"),
            "CHARGEMENT": ("CHARGEMENT", "CHARGE"),
            "RECEPTION_DESTINATION": ("RECEPTION_ENTREPOT", "DISPONIBLE_ENTREPOT"),
        }
        st_event, p_status = stage_map.get(op.operation_type, ("RECEPTION_ENTREPOT", None))
        TrackingEvent.objects.create(
            folder=op.folder,
            stage=st_event,
            location_text=op.warehouse_name,
            event_date=op.operation_date,
            description=f"{op.get_operation_type_display()} ({op.reference}) — {op.parcels_checked_count} colis pointés, État : {op.get_condition_status_display()}.",
            recorded_by=request.user,
        )
        if p_status:
            op.folder.parcels.exclude(status="LIVRE").update(status=p_status)
        if op.operation_type == "CHARGEMENT" and op.folder.status == "OUVERT":
            op.folder.status = "CHARGE"
            op.folder.save(update_fields=["status", "updated_at"])
        elif op.operation_type == "RECEPTION_DESTINATION":
            op.folder.status = "DISPONIBLE_ENTREPOT"
            op.folder.save(update_fields=["status", "updated_at"])

        log_audit("CREATE", "Opérations d'entrepôt", op.reference, str(op.pk), f"{op.get_operation_type_display()} sur {op.folder.reference}.")
        messages.success(request, f"Opération d'entrepôt « {op.reference} » enregistrée.")
        return redirect("logistics:warehouse")

    operations = WarehouseOperation.objects.select_related("folder", "operator").all()
    return render(request, "logistics/warehouse_list.html", {"operations": operations, "form": form})


@login_required
def delivery_list_view(request):
    q = request.GET.get("q", "").strip()
    qs = Delivery.objects.select_related("client", "folder", "invoice", "credit_authorization", "delivered_by").prefetch_related("parcels")
    if q:
        qs = qs.filter(
            Q(delivery_number__icontains=q)
            | Q(client__name__icontains=q)
            | Q(folder__reference__icontains=q)
            | Q(recipient_name__icontains=q)
        )
    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "logistics/delivery_list.html", {"page_obj": page_obj, "q": q})


@login_required
def delivery_create_view(request):
    folder_id = request.GET.get("folder") if request.GET.get("folder", "").isdigit() else None
    client_id = request.GET.get("client") if request.GET.get("client", "").isdigit() else None
    initial = {}
    if folder_id:
        initial["folder"] = int(folder_id)
    if client_id:
        initial["client"] = int(client_id)
    if request.GET.get("invoice", "").isdigit():
        initial["invoice"] = int(request.GET["invoice"])

    form = DeliveryForm(
        request.POST or None,
        initial=initial,
        folder_filter=folder_id,
        client_filter=client_id,
    )
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            delivery = form.save(commit=False)
            delivery.delivered_by = request.user
            if not delivery.credit_authorization and delivery.invoice_id:
                active_cred = delivery.invoice.credit_authorizations.filter(status="ACTIVE").first()
                if active_cred:
                    delivery.credit_authorization = active_cred
            delivery.save()
            form.save_m2m()

            selected_parcels = list(delivery.parcels.all())
            for p in selected_parcels:
                p.status = "LIVRE"
                p.save(update_fields=["status", "updated_at"])
                TrackingEvent.objects.create(
                    folder=delivery.folder,
                    parcel=p,
                    stage="LIVRAISON",
                    location_text=delivery.delivery_address or "Entrepôt LCK Services",
                    event_date=delivery.delivered_at,
                    description=f"Livré à {delivery.recipient_name} (Bon de livraison {delivery.delivery_number}).",
                    recorded_by=request.user,
                )

            log_audit(
                "CREATE",
                "Livraisons",
                delivery.delivery_number,
                str(delivery.pk),
                f"Livraison de {len(selected_parcels)} colis à {delivery.client.name} (Réceptionnaire : {delivery.recipient_name}).",
            )
            messages.success(
                request,
                f"Bon de livraison « {delivery.delivery_number} » enregistré ({len(selected_parcels)} colis remis).",
            )
            return redirect("logistics:delivery_detail", pk=delivery.pk)

    return render(request, "logistics/delivery_form.html", {"form": form})


@login_required
def delivery_detail_view(request, pk):
    delivery = get_object_or_404(
        Delivery.objects.select_related("client", "folder", "invoice", "credit_authorization", "delivered_by").prefetch_related("parcels"),
        pk=pk,
    )
    return render(request, "logistics/delivery_detail.html", {"delivery": delivery})


@login_required
def incident_list_view(request):
    status = request.GET.get("status", "").strip()
    severity = request.GET.get("severity", "").strip()
    qs = Incident.objects.select_related("folder", "parcel", "client", "reported_by").all()
    if status:
        qs = qs.filter(status=status)
    if severity:
        qs = qs.filter(severity=severity)
    return render(
        request,
        "logistics/incident_list.html",
        {
            "incidents": qs,
            "status": status,
            "severity": severity,
            "status_choices": Incident.STATUS_CHOICES,
            "severity_choices": Incident.SEVERITY_CHOICES,
        },
    )


@login_required
def incident_create_view(request):
    initial = {}
    if request.GET.get("folder", "").isdigit():
        initial["folder"] = int(request.GET["folder"])
    if request.GET.get("parcel", "").isdigit():
        p = Parcel.objects.filter(pk=int(request.GET["parcel"])).first()
        if p:
            initial["parcel"] = p.pk
            initial["folder"] = p.folder_id
            initial["client"] = p.client_id

    form = IncidentForm(request.POST or None, request.FILES or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        inc = form.save(commit=False)
        inc.reported_by = request.user
        if inc.status in ("RESOLU", "CLOS") and not inc.resolved_at:
            inc.resolved_at = timezone.now()
        inc.save()

        if inc.parcel_id and form.cleaned_data.get("mark_parcel_litige") and inc.status == "EN_COURS":
            inc.parcel.status = "LITIGE"
            inc.parcel.save(update_fields=["status", "updated_at"])

        TrackingEvent.objects.create(
            folder=inc.folder,
            parcel=inc.parcel,
            stage="INCIDENT",
            location_text=str(inc.folder.destination),
            event_date=inc.reported_at,
            description=f"Déclaration incident {inc.reference} ({inc.get_incident_type_display()}) : {inc.title}.",
            recorded_by=request.user,
        )
        log_audit("CREATE", "Incidents & Litiges", inc.reference, str(inc.pk), f"{inc.get_incident_type_display()} — {inc.title}.")
        messages.warning(request, f"Incident « {inc.reference} » enregistré.")
        return redirect("logistics:incident_list")
    return render(request, "logistics/incident_form.html", {"form": form, "is_edit": False})


@login_required
def incident_edit_view(request, pk):
    inc = get_object_or_404(Incident, pk=pk)
    form = IncidentForm(request.POST or None, request.FILES or None, instance=inc)
    if request.method == "POST" and form.is_valid():
        inc = form.save(commit=False)
        if inc.status in ("RESOLU", "CLOS") and not inc.resolved_at:
            inc.resolved_at = timezone.now()
        inc.save()
        log_audit("UPDATE", "Incidents & Litiges", inc.reference, str(inc.pk), f"Statut incident : {inc.get_status_display()}.")
        messages.success(request, f"Incident « {inc.reference} » mis à jour.")
        return redirect("logistics:incident_list")
    return render(request, "logistics/incident_form.html", {"form": form, "is_edit": True, "incident": inc})
