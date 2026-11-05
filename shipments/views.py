"""Vues de gestion des dossiers de groupage maritime/aérien et cockpit tout-en-un façon MTsarl (Sections 2.3 à 2.9)."""
from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import quote
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from accounts.services import log_audit
from billing.models import CreditDeliveryAuthorization, Invoice, Payment
from billing.services import record_parcel_payment, sync_or_create_parcel_invoice
from cargo.models import CargoCategory, Parcel
from clients.models import Client
from core.models import CompanySetting, Currency
from core.utils import format_fcfa, generate_qr_base64, to_decimal
from documents.models import Document
from finance.models import ExpenseCategory, FolderExpense
from finance.services import save_folder_allocation_run
from logistics.models import Delivery, Incident, TrackingEvent, WarehouseOperation
from .forms import LocationForm, ShipmentFolderForm
from .models import Location, ShipmentFolder


def _parse_date_opt(raw_val):
    if not raw_val:
        return None
    try:
        return datetime.strptime(str(raw_val).strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _build_wa_url(phone: str, text: str) -> str:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if len(digits) == 9 and digits.startswith("6"):
        digits = f"237{digits}"
    encoded = quote(text or "")
    return f"https://wa.me/{digits}?text={encoded}" if digits else f"https://wa.me/?text={encoded}"


@login_required
def folder_list_view(request):
    q = request.GET.get("q", "").strip()
    mode = request.GET.get("mode", "").strip().upper()
    if mode not in ("MARITIME", "AERIEN"):
        mode = ""
    status = request.GET.get("status", "").strip()

    qs = (
        ShipmentFolder.objects.select_related("origin", "destination", "created_by")
        .annotate(
            parcels_total=Count("parcels", distinct=True),
            cbm_sum=Coalesce(
                Sum("parcels__volume_cbm"),
                Value(Decimal("0.0000")),
                output_field=DecimalField(max_digits=12, decimal_places=4),
            ),
            weight_sum=Coalesce(
                Sum("parcels__weight_kg"),
                Value(Decimal("0.000")),
                output_field=DecimalField(max_digits=12, decimal_places=3),
            ),
            frais_sum=Coalesce(
                Sum("expenses__amount_fcfa"),
                Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            ),
        )
        .order_by("-created_at")
    )

    if q:
        qs = qs.filter(
            Q(reference__icontains=q)
            | Q(title__icontains=q)
            | Q(container_number__icontains=q)
            | Q(vessel_name__icontains=q)
            | Q(bl_number__icontains=q)
            | Q(flight_number__icontains=q)
            | Q(awb_number__icontains=q)
            | Q(forwarder__icontains=q)
            | Q(origin__name__icontains=q)
            | Q(origin__city__icontains=q)
            | Q(destination__name__icontains=q)
            | Q(destination__city__icontains=q)
        )
    if mode:
        qs = qs.filter(transport_mode=mode)
    if status:
        qs = qs.filter(status=status)

    paginator = Paginator(qs, 15)
    page_obj = paginator.get_page(request.GET.get("page"))

    stats = {
        "total": ShipmentFolder.objects.count(),
        "active": ShipmentFolder.objects.exclude(status__in=["CLOTURE", "ANNULE"]).count(),
        "maritime": ShipmentFolder.objects.filter(transport_mode="MARITIME").count(),
        "aerien": ShipmentFolder.objects.filter(transport_mode="AERIEN").count(),
    }
    locations = Location.objects.filter(is_active=True).order_by("city", "name")
    return render(
        request,
        "shipments/folder_list.html",
        {
            "page_obj": page_obj,
            "q": q,
            "mode": mode,
            "status": status,
            "status_choices": ShipmentFolder.STATUS_CHOICES,
            "container_types": ShipmentFolder.CONTAINER_TYPES,
            "locations": locations,
            "stats": stats,
        },
    )


@login_required
def folder_quick_create_view(request):
    """Création rapide de dossier depuis la modale #addDossierModal façon MTsarl."""
    if request.method != "POST":
        return redirect("shipments:list")

    mode = request.POST.get("transport_mode", "MARITIME").strip().upper()
    if mode not in ("MARITIME", "AERIEN"):
        mode = "MARITIME"

    origin_raw = request.POST.get("origin_port", "").strip()
    dest_raw = request.POST.get("destination_port", "").strip()
    if not origin_raw or not dest_raw:
        messages.error(request, "Veuillez renseigner le lieu de départ et le lieu de destination.")
        return redirect("shipments:list")

    origin = Location.resolve_from_text(origin_raw, mode)
    destination = Location.resolve_from_text(dest_raw, mode)

    title = request.POST.get("title", "").strip()
    if not title:
        title = f"Groupage {'Maritime' if mode == 'MARITIME' else 'Aérien'} {origin.city} → {destination.city}"

    forwarder = request.POST.get("forwarder", "").strip()
    folder = ShipmentFolder(
        transport_mode=mode,
        title=title,
        origin=origin,
        destination=destination,
        etd=_parse_date_opt(request.POST.get("departure_date")),
        eta=_parse_date_opt(request.POST.get("arrival_estimated_date")),
        forwarder=forwarder,
        status="OUVERT",
        notes=request.POST.get("notes", "").strip(),
        created_by=request.user,
    )
    if mode == "MARITIME":
        folder.container_type = request.POST.get("container_type", "40HC").strip()
        folder.container_number = request.POST.get("container_number", "").strip()
        folder.vessel_name = request.POST.get("vessel_name", "").strip()
        folder.shipping_line = request.POST.get("shipping_line", "").strip() or forwarder
        folder.bl_number = request.POST.get("bl_number", "").strip()
    else:
        folder.airline_name = request.POST.get("airline_name", "").strip() or forwarder
        folder.flight_number = request.POST.get("flight_number", "").strip()
        folder.awb_number = request.POST.get("awb_number", "").strip()

    folder.save()
    TrackingEvent.objects.create(
        folder=folder,
        stage="RECEPTION_ORIGINE",
        status_before="Création",
        status_after=folder.get_status_display(),
        location_text=str(origin),
        description=f"Ouverture du dossier {folder.reference} ({folder.get_transport_mode_display()}).",
        recorded_by=request.user,
    )
    log_audit("CREATE", "Dossiers d'expédition", folder.reference, str(folder.pk), f"Création dossier {folder.get_transport_mode_display()}.")
    messages.success(request, f"Dossier « {folder.reference} » créé avec succès.")
    return redirect("shipments:detail", pk=folder.pk)


@login_required
def folder_quick_update_view(request, pk):
    """Modification rapide des informations du dossier depuis la modale #editDossierModal."""
    folder = get_object_or_404(ShipmentFolder, pk=pk)
    if request.method != "POST":
        return redirect("shipments:detail", pk=pk)

    mode = request.POST.get("transport_mode", folder.transport_mode).strip().upper()
    if mode in ("MARITIME", "AERIEN"):
        folder.transport_mode = mode

    origin_raw = request.POST.get("origin_port", "").strip()
    dest_raw = request.POST.get("destination_port", "").strip()
    if origin_raw:
        folder.origin = Location.resolve_from_text(origin_raw, folder.transport_mode)
    if dest_raw:
        folder.destination = Location.resolve_from_text(dest_raw, folder.transport_mode)

    title = request.POST.get("title", "").strip()
    if title:
        folder.title = title

    folder.departure_date = _parse_date_opt(request.POST.get("departure_date"))
    folder.arrival_estimated_date = _parse_date_opt(request.POST.get("arrival_estimated_date"))
    folder.arrival_actual_date = _parse_date_opt(request.POST.get("arrival_actual_date"))
    folder.forwarder = request.POST.get("forwarder", "").strip()
    folder.notes = request.POST.get("notes", "").strip()

    if folder.transport_mode == "MARITIME":
        folder.container_type = request.POST.get("container_type", folder.container_type).strip()
        folder.container_number = request.POST.get("container_number", "").strip()
        folder.vessel_name = request.POST.get("vessel_name", "").strip()
        folder.shipping_line = request.POST.get("shipping_line", "").strip() or folder.forwarder
        folder.bl_number = request.POST.get("bl_number", "").strip()
    else:
        folder.airline_name = request.POST.get("airline_name", "").strip() or folder.forwarder
        folder.flight_number = request.POST.get("flight_number", "").strip()
        folder.awb_number = request.POST.get("awb_number", "").strip()

    folder.save()
    log_audit("UPDATE", "Dossiers d'expédition", folder.reference, str(folder.pk), "Mise à jour rapide des informations du dossier.")
    messages.success(request, f"Informations du dossier « {folder.reference} » mises à jour.")
    return redirect("shipments:detail", pk=folder.pk)


@login_required
def folder_delete_view(request, pk):
    folder = get_object_or_404(ShipmentFolder, pk=pk)
    if request.method == "POST":
        has_payments = Payment.objects.filter(Q(invoice__folder=folder) | Q(parcel__folder=folder)).exists()
        has_deliveries = folder.deliveries.exists()
        if has_payments or has_deliveries:
            messages.error(
                request,
                f"Impossible de supprimer le dossier « {folder.reference} » car des paiements ou bons de livraison y sont enregistrés.",
            )
            return redirect("shipments:detail", pk=folder.pk)

        with transaction.atomic():
            ref = folder.reference
            folder.invoices.all().delete()
            folder.parcels.all().delete()
            folder.delete()
            log_audit("DELETE", "Dossiers d'expédition", ref, str(pk), "Suppression complète du dossier de groupage.")
            messages.success(request, f"Le dossier « {ref} » a été supprimé.")
    return redirect("shipments:list")


@login_required
def folder_create_view(request):
    initial = {}
    if request.GET.get("mode") in ("MARITIME", "AERIEN"):
        initial["transport_mode"] = request.GET["mode"]
    form = ShipmentFolderForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        folder = form.save(commit=False)
        folder.created_by = request.user
        folder.save()
        TrackingEvent.objects.create(
            folder=folder,
            stage="RECEPTION_ORIGINE",
            status_before="Création",
            status_after=folder.get_status_display(),
            location_text=str(folder.origin),
            description=f"Ouverture du dossier {folder.reference} ({folder.get_transport_mode_display()}).",
            recorded_by=request.user,
        )
        log_audit("CREATE", "Dossiers d'expédition", folder.reference, str(folder.pk), f"Création dossier {folder.get_transport_mode_display()}.")
        messages.success(request, f"Le dossier « {folder.reference} » a été créé avec succès.")
        return redirect("shipments:detail", pk=folder.pk)
    return render(request, "shipments/folder_form.html", {"form": form, "is_edit": False})


@login_required
def folder_edit_view(request, pk):
    folder = get_object_or_404(ShipmentFolder, pk=pk)
    form = ShipmentFolderForm(request.POST or None, instance=folder)
    if request.method == "POST" and form.is_valid():
        folder = form.save(commit=False)
        if folder.status == "CLOTURE" and not folder.closed_at:
            folder.closed_at = timezone.now()
        folder.save()
        log_audit("UPDATE", "Dossiers d'expédition", folder.reference, str(folder.pk), "Mise à jour des informations du dossier.")
        messages.success(request, f"Dossier « {folder.reference} » mis à jour.")
        return redirect("shipments:detail", pk=folder.pk)
    return render(request, "shipments/folder_form.html", {"form": form, "is_edit": True, "folder": folder})


@login_required
def folder_detail_query_view(request):
    """Alias compatible avec /groupage/dossier/detail?id=<pk> façon MTsarl."""
    pk = request.GET.get("id", "")
    if pk.isdigit():
        return redirect("shipments:detail", pk=int(pk))
    return redirect("shipments:list")


@login_required
def folder_detail_view(request, pk):
    folder = get_object_or_404(
        ShipmentFolder.objects.select_related("origin", "destination", "created_by"),
        pk=pk,
    )
    parcels = list(
        folder.parcels.select_related("client", "category", "declared_currency").order_by("parcel_code")
    )
    expenses = list(folder.expenses.select_related("category", "currency", "recorded_by").order_by("-expense_date", "-id"))
    allocation_runs = list(folder.allocation_runs.select_related("created_by").order_by("-created_at"))
    active_run = next((r for r in allocation_runs if r.is_active_run), None)
    invoices = list(folder.invoices.select_related("client").order_by("-issue_date", "-id"))
    tracking_events = list(folder.tracking_events.select_related("parcel", "recorded_by")[:30])
    warehouse_ops = list(folder.warehouse_operations.select_related("operator")[:15])
    incidents = list(folder.incidents.select_related("parcel", "client")[:15])
    documents = list(folder.documents.select_related("uploaded_by")[:20])
    deliveries = list(folder.deliveries.select_related("client", "invoice", "credit_authorization", "delivered_by").prefetch_related("parcels")[:20])

    folder_payments = list(
        Payment.objects.filter(Q(invoice__folder=folder) | Q(parcel__folder=folder))
        .select_related("client", "invoice", "parcel", "received_by")
        .distinct()
        .order_by("-payment_date", "-id")
    )

    # Indexation des factures, livraisons, autorisations crédit et liens WhatsApp par colis
    parcel_invoices = {}
    for inv in invoices:
        if inv.status == "ANNULEE":
            continue
        for line in inv.lines.all():
            if line.parcel_id and (
                line.parcel_id not in parcel_invoices or inv.invoice_type == "DEFINITIVE"
            ):
                parcel_invoices[line.parcel_id] = inv

    parcel_deliveries = {}
    for d in deliveries:
        for dp in d.parcels.all():
            if dp.id not in parcel_deliveries:
                parcel_deliveries[dp.id] = d

    active_credit_by_inv = {
        ca.invoice_id: ca
        for ca in CreditDeliveryAuthorization.objects.filter(folder=folder, status="ACTIVE")
    }

    company = CompanySetting.get_solo()
    parcel_whatsapp_urls = {}
    parcel_share_urls = {}
    parcel_credit_auths = {}
    for p in parcels:
        share_rel = f"{reverse('billing:shared_invoice')}?item={p.pk}&token={p.share_token}"
        share_abs = request.build_absolute_uri(share_rel)
        parcel_share_urls[p.pk] = share_rel

        inv_p = parcel_invoices.get(p.pk)
        if inv_p and inv_p.id in active_credit_by_inv:
            parcel_credit_auths[p.pk] = active_credit_by_inv[inv_p.id]

        billed = p.suggested_price_fcfa or Decimal("0.00")
        paid = p.paid_amount_fcfa or Decimal("0.00")
        rem = p.balance_due_fcfa
        wa_msg = (
            f"Bonjour {p.client.name},\n"
            f"*{company.name}* — Suivi Groupage *{folder.reference}* ({folder.origin.city} → {folder.destination.city})\n"
            f"Colis *{p.parcel_code}* : {p.description}\n"
            f"• Quantité : {p.quantity} | Volume : {p.volume_cbm} m³ | Poids : {p.weight_kg} kg\n"
            f"• Statut : {p.get_status_display()}\n"
            f"• Montant facturé : {format_fcfa(billed)}\n"
            f"• Déjà réglé : {format_fcfa(paid)} | Reste à payer : *{format_fcfa(rem)}*\n\n"
            f"Consultez et téléchargez votre facture sécurisée ici :\n{share_abs}"
        )
        parcel_whatsapp_urls[p.pk] = _build_wa_url(p.client.whatsapp or p.client.phone, wa_msg)

    total_frais = sum((e.amount_fcfa for e in expenses), Decimal("0.00"))
    total_cost_share = sum((p.suggested_price_fcfa for p in parcels), Decimal("0.00"))
    definitive_billed = sum(
        (i.total_amount_fcfa for i in invoices if i.invoice_type == "DEFINITIVE" and i.status != "ANNULEE"),
        Decimal("0.00"),
    )
    effective_billed = total_cost_share if total_cost_share > 0 else definitive_billed
    total_encaisse = sum((pay.amount_fcfa for pay in folder_payments), Decimal("0.00"))
    reste_recouvrer = max(effective_billed - total_encaisse, Decimal("0.00"))
    benefice_latent = effective_billed - total_frais
    benefice_cash = total_encaisse - total_frais

    currencies = list(Currency.objects.filter(is_active=True))
    base_currency = next((c for c in currencies if c.is_base), currencies[0] if currencies else None)

    return render(
        request,
        "shipments/folder_detail.html",
        {
            "folder": folder,
            "parcels": parcels,
            "expenses": expenses,
            "allocation_runs": allocation_runs,
            "active_run": active_run,
            "invoices": invoices,
            "tracking_events": tracking_events,
            "warehouse_ops": warehouse_ops,
            "incidents": incidents,
            "documents": documents,
            "deliveries": deliveries,
            "folder_payments": folder_payments,
            "parcel_invoices": parcel_invoices,
            "parcel_deliveries": parcel_deliveries,
            "parcel_credit_auths": parcel_credit_auths,
            "parcel_whatsapp_urls": parcel_whatsapp_urls,
            "parcel_share_urls": parcel_share_urls,
            "total_frais": total_frais,
            "total_cost_share": effective_billed,
            "total_encaisse": total_encaisse,
            "reste_recouvrer": reste_recouvrer,
            "benefice_latent": benefice_latent,
            "benefice_cash": benefice_cash,
            "clients": Client.objects.filter(is_active=True).order_by("name"),
            "categories": CargoCategory.objects.all(),
            "currencies": currencies,
            "base_currency": base_currency,
            "expense_categories": ExpenseCategory.objects.all(),
            "locations": Location.objects.filter(is_active=True).order_by("city", "name"),
            "container_types": ShipmentFolder.CONTAINER_TYPES,
            "status_choices": ShipmentFolder.STATUS_CHOICES,
            "item_type_choices": Parcel.ITEM_TYPE_CHOICES,
            "payment_method_choices": Payment.PAYMENT_METHODS,
            "warehouse_op_types": WarehouseOperation.OPERATION_TYPES,
            "condition_choices": WarehouseOperation.CONDITION_CHOICES,
            "incident_types": Incident.INCIDENT_TYPES,
            "severity_choices": Incident.SEVERITY_CHOICES,
            "doc_types": Document.DOCUMENT_TYPES,
            "today_iso": timezone.localdate().strftime("%Y-%m-%d"),
            "default_credit_due_iso": (timezone.localdate() + timedelta(days=15)).strftime("%Y-%m-%d"),
        },
    )


@login_required
def folder_status_update_view(request, pk):
    folder = get_object_or_404(ShipmentFolder, pk=pk)
    if request.method == "POST":
        new_status = request.POST.get("status", "").strip()
        propagate = bool(request.POST.get("propagate_parcels"))
        location_note = request.POST.get("location_text", "").strip()
        comment_note = request.POST.get("notes", "").strip()
        valid_statuses = dict(ShipmentFolder.STATUS_CHOICES)

        if new_status in valid_statuses:
            old_label = folder.get_status_display()
            folder.status = new_status
            if new_status == "CLOTURE" and not folder.closed_at:
                folder.closed_at = timezone.now()
            if new_status == "ARRIVE" and not folder.arrival_actual_date:
                folder.arrival_actual_date = timezone.localdate()
            folder.save()

            parcel_status_map = {
                "OUVERT": "RECU_ORIGINE",
                "CHARGE": "CHARGE",
                "EN_TRANSIT": "EN_TRANSIT",
                "ARRIVE": "ARRIVE",
                "DEDOUANEMENT": "ARRIVE",
                "DISPONIBLE_ENTREPOT": "DISPONIBLE_ENTREPOT",
            }
            stage_map = {
                "BROUILLON": "RECEPTION_ORIGINE",
                "OUVERT": "RECEPTION_ORIGINE",
                "CHARGE": "CHARGEMENT",
                "EN_TRANSIT": "DEPART",
                "ARRIVE": "ARRIVEE_PORT_AERO",
                "DEDOUANEMENT": "DEDOUANEMENT",
                "DISPONIBLE_ENTREPOT": "RECEPTION_ENTREPOT",
                "CLOTURE": "LIVRAISON",
            }
            if propagate and new_status in parcel_status_map:
                folder.parcels.exclude(status="LIVRE").update(status=parcel_status_map[new_status])

            loc = location_note or (
                str(folder.origin) if new_status in ("BROUILLON", "OUVERT", "CHARGE", "EN_TRANSIT") else str(folder.destination)
            )
            desc = comment_note or f"Passage du statut dossier de « {old_label} » à « {folder.get_status_display()} »."
            TrackingEvent.objects.create(
                folder=folder,
                stage=stage_map.get(new_status, "DEPART"),
                status_before=old_label,
                status_after=folder.get_status_display(),
                location_text=loc,
                description=desc,
                recorded_by=request.user,
            )

            log_audit(
                "STATUS",
                "Dossiers d'expédition",
                folder.reference,
                str(folder.pk),
                f"Statut changé : {old_label} -> {folder.get_status_display()} (Propagation colis={propagate}).",
            )
            messages.success(request, f"Statut du dossier mis à jour : {folder.get_status_display()}.")
    return redirect("shipments:detail", pk=folder.pk)


@login_required
@transaction.atomic
def folder_add_items_view(request, pk):
    """Ajout multi-articles dans un dossier (#addItemModal façon MTsarl : client existant/nouveau + 1..N articles + contrat + facturation auto)."""
    folder = get_object_or_404(ShipmentFolder, pk=pk)
    if request.method != "POST":
        return redirect("shipments:detail", pk=pk)

    client_mode = request.POST.get("client_type", "existing").strip()
    if client_mode == "new":
        new_name = request.POST.get("new_client_name", "").strip()
        new_phone = request.POST.get("new_client_phone", "").strip()
        if not new_name:
            messages.error(request, "Veuillez saisir le nom du nouveau client.")
            return redirect("shipments:detail", pk=pk)
        client = Client.objects.create(
            name=new_name,
            phone=new_phone or "+237 600 00 00 00",
            whatsapp=request.POST.get("new_client_whatsapp", "").strip() or new_phone,
            email=request.POST.get("new_client_email", "").strip(),
            city=request.POST.get("new_client_city", "Douala").strip() or "Douala",
            client_type=request.POST.get("new_client_kind", "PARTICULIER").strip() or "PARTICULIER",
        )
        log_audit("CREATE", "Clients", f"{client.code} - {client.name}", str(client.pk), "Client créé à la volée depuis le dossier de groupage.")
    else:
        cid = request.POST.get("client_id", "").strip()
        if not cid.isdigit():
            messages.error(request, "Veuillez sélectionner un client existant ou créer un nouveau client.")
            return redirect("shipments:detail", pk=pk)
        client = get_object_or_404(Client, pk=int(cid))

    descriptions = request.POST.getlist("item_description[]")
    item_types = request.POST.getlist("item_type[]")
    chassis_list = request.POST.getlist("item_chassis[]")
    cat_ids = request.POST.getlist("item_category[]")
    qtys = request.POST.getlist("item_qty[]")
    lengths = request.POST.getlist("item_length[]")
    widths = request.POST.getlist("item_width[]")
    heights = request.POST.getlist("item_height[]")
    volumes = request.POST.getlist("item_volume[]")
    weights = request.POST.getlist("item_weight[]")
    decl_vals = request.POST.getlist("item_declared_val[]")
    curr_ids = request.POST.getlist("item_currency[]")
    cost_shares = request.POST.getlist("item_cost_share[]")
    item_notes = request.POST.getlist("item_notes[]")

    base_currency = Currency.get_base()
    contract_upload = request.FILES.get("colis_contract")
    created_parcels = []

    for idx, raw_desc in enumerate(descriptions):
        desc = (raw_desc or "").strip()
        if not desc:
            continue

        itype = item_types[idx] if idx < len(item_types) and item_types[idx] in dict(Parcel.ITEM_TYPE_CHOICES) else "MARCHANDISE"
        chassis = (chassis_list[idx] if idx < len(chassis_list) else "").strip()
        cat_raw = cat_ids[idx] if idx < len(cat_ids) else ""
        cat_obj = CargoCategory.objects.filter(pk=int(cat_raw)).first() if str(cat_raw).isdigit() else None

        qty_val = max(1, int(to_decimal(qtys[idx] if idx < len(qtys) else "1", "1")))
        l_cm = to_decimal(lengths[idx] if idx < len(lengths) else "0", "0")
        w_cm = to_decimal(widths[idx] if idx < len(widths) else "0", "0")
        h_cm = to_decimal(heights[idx] if idx < len(heights) else "0", "0")
        vol_manual = to_decimal(volumes[idx] if idx < len(volumes) else "0", "0")
        wt_kg = to_decimal(weights[idx] if idx < len(weights) else "0", "0")
        decl_val = to_decimal(decl_vals[idx] if idx < len(decl_vals) else "0", "0")
        cur_raw = curr_ids[idx] if idx < len(curr_ids) else ""
        cur_obj = Currency.objects.filter(pk=int(cur_raw)).first() if str(cur_raw).isdigit() else base_currency
        cost_share = to_decimal(cost_shares[idx] if idx < len(cost_shares) else "0", "0")
        note_txt = (item_notes[idx] if idx < len(item_notes) else "").strip()

        parcel = Parcel(
            folder=folder,
            client=client,
            category=cat_obj,
            item_type=itype,
            chassis_number=chassis,
            description=desc,
            quantity=qty_val,
            weight_kg=wt_kg,
            length_cm=l_cm,
            width_cm=w_cm,
            height_cm=h_cm,
            volume_cbm=vol_manual if (l_cm <= 0 or w_cm <= 0 or h_cm <= 0) else Decimal("0.0000"),
            declared_value=decl_val,
            declared_currency=cur_obj,
            suggested_price_fcfa=cost_share,
            status="RECU_ORIGINE",
            notes=note_txt,
        )
        if contract_upload and idx == 0:
            parcel.contract_file = contract_upload
        parcel.save()
        created_parcels.append(parcel)

        if cost_share > 0:
            sync_or_create_parcel_invoice(parcel, user=request.user, create_if_missing=True)

    if not created_parcels:
        messages.error(request, "Veuillez renseigner au moins une désignation d'article/colis.")
        return redirect("shipments:detail", pk=pk)

    if contract_upload and created_parcels:
        first_p = created_parcels[0]
        Document.objects.create(
            doc_type="CONTRAT",
            title=f"Contrat de groupage — {client.name} ({first_p.parcel_code})",
            file=first_p.contract_file,
            folder=folder,
            parcel=first_p,
            client=client,
            uploaded_by=request.user,
        )

    TrackingEvent.objects.create(
        folder=folder,
        parcel=created_parcels[0] if len(created_parcels) == 1 else None,
        stage="RECEPTION_ORIGINE",
        status_before="—",
        status_after="Reçu à l'origine",
        location_text=str(folder.origin),
        description=f"Enregistrement de {len(created_parcels)} colis pour {client.name} ({', '.join(p.parcel_code for p in created_parcels)}).",
        recorded_by=request.user,
    )
    log_audit(
        "CREATE",
        "Marchandises & Colis",
        folder.reference,
        str(folder.pk),
        f"Ajout de {len(created_parcels)} article(s) pour {client.name}.",
    )
    messages.success(request, f"{len(created_parcels)} colis enregistré(s) pour « {client.name} » dans le dossier {folder.reference}.")
    return redirect("shipments:detail", pk=folder.pk)


@login_required
@transaction.atomic
def folder_update_item_view(request, pk, item_id):
    """Modification d'un colis depuis la modale #editItemModal{id}."""
    folder = get_object_or_404(ShipmentFolder, pk=pk)
    parcel = get_object_or_404(Parcel, pk=item_id, folder=folder)
    if request.method != "POST":
        return redirect("shipments:detail", pk=pk)

    cid = request.POST.get("client_id", "").strip()
    if cid.isdigit():
        parcel.client = get_object_or_404(Client, pk=int(cid))

    desc = request.POST.get("description", "").strip()
    if desc:
        parcel.description = desc

    itype = request.POST.get("item_type", parcel.item_type).strip()
    if itype in dict(Parcel.ITEM_TYPE_CHOICES):
        parcel.item_type = itype
    parcel.chassis_number = request.POST.get("chassis_number", "").strip()

    cat_raw = request.POST.get("category_id", "").strip()
    parcel.category = CargoCategory.objects.filter(pk=int(cat_raw)).first() if cat_raw.isdigit() else None

    parcel.quantity = max(1, int(to_decimal(request.POST.get("quantity", "1"), "1")))
    parcel.length_cm = to_decimal(request.POST.get("length_cm", "0"), "0")
    parcel.width_cm = to_decimal(request.POST.get("width_cm", "0"), "0")
    parcel.height_cm = to_decimal(request.POST.get("height_cm", "0"), "0")
    if parcel.length_cm <= 0 or parcel.width_cm <= 0 or parcel.height_cm <= 0:
        parcel.volume_cbm = to_decimal(request.POST.get("volume_cbm", str(parcel.volume_cbm)), "0")
    parcel.weight_kg = to_decimal(request.POST.get("weight_kg", str(parcel.weight_kg)), "0")
    parcel.declared_value = to_decimal(request.POST.get("declared_value", str(parcel.declared_value)), "0")

    cur_raw = request.POST.get("currency_id", "").strip()
    if cur_raw.isdigit():
        parcel.declared_currency = Currency.objects.filter(pk=int(cur_raw)).first()

    parcel.suggested_price_fcfa = to_decimal(request.POST.get("cost_share", str(parcel.suggested_price_fcfa)), "0")
    parcel.notes = request.POST.get("notes", "").strip()

    new_status = request.POST.get("status", "").strip()
    if new_status in dict(Parcel.STATUS_CHOICES):
        parcel.status = new_status

    if request.FILES.get("colis_contract"):
        parcel.contract_file = request.FILES["colis_contract"]

    parcel.save()
    sync_or_create_parcel_invoice(parcel, user=request.user, create_if_missing=(parcel.suggested_price_fcfa > 0))
    parcel.recalculate_paid_amount(save=True)

    log_audit("UPDATE", "Marchandises & Colis", parcel.parcel_code, str(parcel.pk), f"Modification colis dans {folder.reference}.")
    messages.success(request, f"Colis « {parcel.parcel_code} » mis à jour.")
    return redirect("shipments:detail", pk=folder.pk)


@login_required
@transaction.atomic
def folder_delete_item_view(request, pk, item_id):
    folder = get_object_or_404(ShipmentFolder, pk=pk)
    parcel = get_object_or_404(Parcel, pk=item_id, folder=folder)
    if request.method == "POST":
        if parcel.paid_amount_fcfa > 0 or parcel.deliveries.exists():
            messages.error(
                request,
                f"Impossible de supprimer le colis « {parcel.parcel_code} » car un paiement ou une livraison y est déjà rattaché.",
            )
            return redirect("shipments:detail", pk=folder.pk)

        affected_invoices = list(Invoice.objects.filter(lines__parcel=parcel).distinct())
        code = parcel.parcel_code
        parcel.delete()
        for inv in affected_invoices:
            if inv.lines.count() == 0 and inv.paid_amount_fcfa <= 0:
                inv.delete()
            else:
                inv.recalculate_totals(save=True)

        log_audit("DELETE", "Marchandises & Colis", code, str(item_id), f"Suppression du colis dans {folder.reference}.")
        messages.success(request, f"Colis « {code} » supprimé.")
    return redirect("shipments:detail", pk=folder.pk)


@login_required
@transaction.atomic
def folder_pay_item_view(request, pk, item_id):
    """Encaissement d'un paiement partiel ou total sur un colis (#payItemModal{id}) avec génération du reçu REC-..."""
    folder = get_object_or_404(ShipmentFolder, pk=pk)
    parcel = get_object_or_404(Parcel, pk=item_id, folder=folder)
    if request.method == "POST":
        amount = to_decimal(request.POST.get("amount_fcfa", "0"), "0")
        method = request.POST.get("payment_method", "ESPECES").strip()
        if method not in dict(Payment.PAYMENT_METHODS):
            method = "ESPECES"
        pay_date = _parse_date_opt(request.POST.get("payment_date")) or timezone.localdate()
        ext_ref = request.POST.get("reference", "").strip()
        notes = request.POST.get("notes", "").strip()
        if ext_ref:
            notes = f"Réf: {ext_ref} — {notes}".strip(" —")

        if amount <= 0:
            messages.error(request, "Veuillez saisir un montant d'encaissement supérieur à 0 FCFA.")
            return redirect("shipments:detail", pk=folder.pk)

        payment = record_parcel_payment(
            parcel=parcel,
            amount_fcfa=amount,
            payment_method=method,
            payment_date=pay_date,
            user=request.user,
            notes=notes,
        )
        if payment:
            if ext_ref:
                payment.transaction_reference = ext_ref
                payment.save(update_fields=["transaction_reference"])
            log_audit(
                "PAYMENT",
                "Paiements & Reçus",
                payment.receipt_number,
                str(payment.pk),
                f"Encaissement de {format_fcfa(payment.amount_fcfa)} sur colis {parcel.parcel_code} ({folder.reference}).",
            )
            messages.success(
                request,
                f"Paiement enregistré ! Reçu « {payment.receipt_number} » généré ({format_fcfa(payment.amount_fcfa)}).",
            )
    return redirect("shipments:detail", pk=folder.pk)


@login_required
@transaction.atomic
def folder_delete_payment_view(request, pk, payment_id):
    folder = get_object_or_404(ShipmentFolder, pk=pk)
    payment = get_object_or_404(Payment, pk=payment_id)
    if request.method == "POST":
        rec_no = payment.receipt_number
        payment.delete()
        log_audit("DELETE", "Paiements & Reçus", rec_no, str(payment_id), f"Annulation/suppression reçu sur dossier {folder.reference}.")
        messages.warning(request, f"Le paiement « {rec_no} » a été supprimé et les soldes ont été recalculés.")
    return redirect("shipments:detail", pk=folder.pk)


@login_required
@transaction.atomic
def folder_deliver_item_view(request, pk, item_id):
    """Livraison d'un colis (#deliverItemModal{id}) avec contrôle de solde ou autorisation de livraison à crédit."""
    folder = get_object_or_404(ShipmentFolder, pk=pk)
    parcel = get_object_or_404(Parcel, pk=item_id, folder=folder)
    if request.method != "POST":
        return redirect("shipments:detail", pk=pk)

    inv = sync_or_create_parcel_invoice(parcel, user=request.user, create_if_missing=(parcel.suggested_price_fcfa > 0))
    parcel.refresh_from_db()

    unpaid_balance = max(parcel.balance_due_fcfa, inv.balance_due_fcfa if inv else Decimal("0.00"))
    credit_auth = None
    if unpaid_balance > 0 and inv:
        credit_auth = inv.credit_authorizations.filter(status="ACTIVE").first()
        if not credit_auth:
            authorize_now = bool(request.POST.get("authorize_credit"))
            promised_due = _parse_date_opt(request.POST.get("promised_due_date"))
            credit_reason = request.POST.get("credit_reason", "").strip()
            if not authorize_now or not promised_due:
                messages.error(
                    request,
                    f"Livraison bloquée : un solde de {format_fcfa(unpaid_balance)} reste impayé. Encaissez le solde ou cochez « Autoriser la livraison à crédit » avec une date d'échéance.",
                )
                return redirect("shipments:detail", pk=folder.pk)

            credit_auth = CreditDeliveryAuthorization.objects.create(
                client=parcel.client,
                invoice=inv,
                folder=folder,
                authorized_balance_fcfa=unpaid_balance,
                promised_due_date=promised_due,
                reason=credit_reason or f"Autorisation accordée lors de la remise du colis {parcel.parcel_code}.",
                status="ACTIVE",
                approved_by=request.user,
            )
            log_audit(
                "CREDIT_AUTH",
                "Autorisations de crédit",
                credit_auth.reference,
                str(credit_auth.pk),
                f"Autorisation livraison à crédit accordée à {parcel.client.name} ({format_fcfa(unpaid_balance)}).",
            )

    recipient_name = request.POST.get("recipient_name", "").strip() or parcel.client.name
    delivery = Delivery.objects.create(
        folder=folder,
        client=parcel.client,
        invoice=inv,
        credit_authorization=credit_auth,
        delivery_mode=request.POST.get("delivery_mode", "ENLEVEMENT_ENTREPOT").strip() or "ENLEVEMENT_ENTREPOT",
        delivery_address=request.POST.get("delivery_address", "").strip() or str(folder.destination),
        recipient_name=recipient_name,
        recipient_phone=request.POST.get("recipient_phone", "").strip() or parcel.client.phone,
        recipient_id_number=request.POST.get("recipient_id_number", "").strip(),
        notes=request.POST.get("notes", "").strip(),
        delivered_by=request.user,
    )
    delivery.parcels.add(parcel)

    old_p_status = parcel.get_status_display()
    parcel.status = "LIVRE"
    parcel.save(update_fields=["status", "updated_at"])

    TrackingEvent.objects.create(
        folder=folder,
        parcel=parcel,
        stage="LIVRAISON",
        status_before=old_p_status,
        status_after="Livré au client",
        location_text=delivery.delivery_address or str(folder.destination),
        description=f"Bon de livraison {delivery.delivery_number} remis à {recipient_name}.",
        recorded_by=request.user,
    )
    log_audit("CREATE", "Livraisons", delivery.delivery_number, str(delivery.pk), f"Livraison du colis {parcel.parcel_code}.")
    messages.success(request, f"Colis « {parcel.parcel_code} » marqué livré ! Bon de livraison « {delivery.delivery_number} » généré.")
    return redirect("shipments:detail", pk=folder.pk)


@login_required
@transaction.atomic
def folder_expense_add_view(request, pk):
    """Ajout rapide d'un frais de groupage (#addDepenseModal) avec support multi-devises et justificatif."""
    folder = get_object_or_404(ShipmentFolder, pk=pk)
    if request.method == "POST":
        cat_id = request.POST.get("category_id", "").strip()
        category = ExpenseCategory.objects.filter(pk=int(cat_id)).first() if cat_id.isdigit() else ExpenseCategory.objects.first()
        if not category:
            category = ExpenseCategory.objects.create(name="Frais de transit & logistique", code="TRN")

        cur_id = request.POST.get("currency_id", "").strip()
        currency = Currency.objects.filter(pk=int(cur_id)).first() if cur_id.isdigit() else Currency.get_base()
        amount_orig = to_decimal(request.POST.get("amount_original", "0"), "0")
        ex_rate = to_decimal(request.POST.get("exchange_rate", "0"), "0")

        if amount_orig <= 0:
            messages.error(request, "Veuillez saisir un montant de dépense valide.")
            return redirect("shipments:detail", pk=folder.pk)

        label = request.POST.get("label", "").strip() or category.name
        is_paid = bool(request.POST.get("is_paid"))
        exp_date = _parse_date_opt(request.POST.get("expense_date")) or timezone.localdate()
        pay_date = _parse_date_opt(request.POST.get("payment_date")) or (exp_date if is_paid else None)

        exp = FolderExpense(
            folder=folder,
            category=category,
            label=label,
            vendor_name=request.POST.get("vendor_name", "").strip(),
            expense_date=exp_date,
            amount_original=amount_orig,
            currency=currency,
            exchange_rate=ex_rate if ex_rate > 0 else currency.rate_to_fcfa,
            is_paid=is_paid,
            payment_date=pay_date,
            is_allocatable=True,
            notes=request.POST.get("notes", "").strip(),
            recorded_by=request.user,
        )
        if request.FILES.get("receipt_file"):
            exp.receipt_file = request.FILES["receipt_file"]
        exp.save()

        log_audit("CREATE", "Dépenses", exp.reference, str(exp.pk), f"Dépense {exp.label} ({format_fcfa(exp.amount_fcfa)}) sur {folder.reference}.")
        messages.success(request, f"Frais « {exp.label} » ({format_fcfa(exp.amount_fcfa)}) ajouté au dossier.")
    return redirect("shipments:detail", pk=folder.pk)


@login_required
@transaction.atomic
def folder_expense_update_view(request, pk, exp_id):
    folder = get_object_or_404(ShipmentFolder, pk=pk)
    exp = get_object_or_404(FolderExpense, pk=exp_id, folder=folder)
    if request.method == "POST":
        cat_id = request.POST.get("category_id", "").strip()
        if cat_id.isdigit():
            exp.category = get_object_or_404(ExpenseCategory, pk=int(cat_id))
        cur_id = request.POST.get("currency_id", "").strip()
        if cur_id.isdigit():
            exp.currency = get_object_or_404(Currency, pk=int(cur_id))

        exp.label = request.POST.get("label", exp.label).strip() or exp.category.name
        exp.vendor_name = request.POST.get("vendor_name", "").strip()
        exp.expense_date = _parse_date_opt(request.POST.get("expense_date")) or exp.expense_date
        exp.amount_original = to_decimal(request.POST.get("amount_original", str(exp.amount_original)), "0")
        ex_rate = to_decimal(request.POST.get("exchange_rate", "0"), "0")
        exp.exchange_rate = ex_rate if ex_rate > 0 else exp.currency.rate_to_fcfa
        exp.is_paid = bool(request.POST.get("is_paid"))
        exp.payment_date = _parse_date_opt(request.POST.get("payment_date")) or (exp.expense_date if exp.is_paid else None)
        exp.notes = request.POST.get("notes", "").strip()
        if request.FILES.get("receipt_file"):
            exp.receipt_file = request.FILES["receipt_file"]
        exp.save()

        log_audit("UPDATE", "Dépenses", exp.reference, str(exp.pk), f"Mise à jour frais {exp.label} ({format_fcfa(exp.amount_fcfa)}).")
        messages.success(request, f"Frais « {exp.label} » mis à jour.")
    return redirect("shipments:detail", pk=folder.pk)


@login_required
@transaction.atomic
def folder_expense_delete_view(request, pk, exp_id):
    folder = get_object_or_404(ShipmentFolder, pk=pk)
    exp = get_object_or_404(FolderExpense, pk=exp_id, folder=folder)
    if request.method == "POST":
        lbl = exp.label
        ref = exp.reference
        exp.delete()
        log_audit("DELETE", "Dépenses", ref, str(exp_id), f"Suppression frais {lbl} sur {folder.reference}.")
        messages.success(request, f"Frais « {lbl} » supprimé.")
    return redirect("shipments:detail", pk=folder.pk)


@login_required
@transaction.atomic
def folder_recalculate_allocation_view(request, pk):
    """Recalcul automatique des coûts et quote-parts clients (#recalculerRepartitionModal)."""
    folder = get_object_or_404(ShipmentFolder, pk=pk)
    if request.method == "POST":
        if not folder.parcels.exists():
            messages.warning(request, "Ajoutez d'abord des colis au dossier avant de lancer la répartition des frais.")
            return redirect("shipments:detail", pk=folder.pk)

        method = request.POST.get("allocation_method", "VOLUME").strip()
        if method not in ("VOLUME", "WEIGHT", "VALUE", "FLAT"):
            method = "VOLUME"
        margin_type = request.POST.get("margin_type", "PERCENT").strip()
        if margin_type not in ("PERCENT", "FIXED_PARCEL", "TARIFF_UNIT"):
            margin_type = "PERCENT"
        margin_val = to_decimal(request.POST.get("margin_value", "0"), "0")
        sync_inv = bool(request.POST.get("sync_invoices"))

        run = save_folder_allocation_run(
            folder=folder,
            allocation_method=method,
            margin_type=margin_type,
            margin_value=margin_val,
            notes=request.POST.get("notes", "").strip() or "Répartition calculée depuis le cockpit du dossier.",
            user=request.user,
        )
        if sync_inv:
            for p in folder.parcels.select_related("client").all():
                if p.suggested_price_fcfa > 0:
                    sync_or_create_parcel_invoice(p, user=request.user, create_if_missing=True)

        log_audit(
            "ALLOCATION",
            "Répartition financière",
            run.reference,
            str(run.pk),
            f"Répartition {run.get_allocation_method_display()} (Marge: {margin_val}) sur {folder.reference}.",
        )
        messages.success(
            request,
            f"Répartition « {run.reference} » appliquée ({run.get_allocation_method_display()}) ! Total commercial : {format_fcfa(run.total_commercial_fcfa)}.",
        )
    return redirect("shipments:detail", pk=folder.pk)


@login_required
def folder_quick_warehouse_op_view(request, pk):
    folder = get_object_or_404(ShipmentFolder, pk=pk)
    if request.method == "POST":
        op_type = request.POST.get("operation_type", "RECEPTION_ORIGINE").strip()
        if op_type not in dict(WarehouseOperation.OPERATION_TYPES):
            op_type = "RECEPTION_ORIGINE"
        wh_name = request.POST.get("warehouse_name", "").strip() or str(folder.origin if op_type != "RECEPTION_DESTINATION" else folder.destination)
        op = WarehouseOperation.objects.create(
            operation_type=op_type,
            folder=folder,
            warehouse_name=wh_name,
            parcels_checked_count=max(0, int(to_decimal(request.POST.get("parcels_checked_count", "0"), "0"))),
            total_weight_checked_kg=to_decimal(request.POST.get("total_weight_checked_kg", "0"), "0"),
            condition_status=request.POST.get("condition_status", "CONFORME").strip() or "CONFORME",
            notes=request.POST.get("notes", "").strip(),
            operator=request.user,
        )
        stage_map = {
            "RECEPTION_ORIGINE": "RECEPTION_ORIGINE",
            "CHARGEMENT": "CHARGEMENT",
            "RECEPTION_DESTINATION": "RECEPTION_ENTREPOT",
        }
        TrackingEvent.objects.create(
            folder=folder,
            stage=stage_map.get(op_type, "RECEPTION_ENTREPOT"),
            status_before=folder.get_status_display(),
            status_after=op.get_operation_type_display(),
            location_text=wh_name,
            description=f"{op.reference} — {op.get_condition_status_display()}. {op.notes}".strip(),
            recorded_by=request.user,
        )
        log_audit("CREATE", "Logistique Entrepôt", op.reference, str(op.pk), f"Opération {op.get_operation_type_display()} sur {folder.reference}.")
        messages.success(request, f"Opération d'entrepôt « {op.reference} » enregistrée.")
    return redirect("shipments:detail", pk=folder.pk)


@login_required
def folder_quick_incident_view(request, pk):
    folder = get_object_or_404(ShipmentFolder, pk=pk)
    if request.method == "POST":
        parcel_id = request.POST.get("parcel_id", "").strip()
        parcel = Parcel.objects.filter(pk=int(parcel_id), folder=folder).first() if parcel_id.isdigit() else None
        title = request.POST.get("title", "").strip()
        desc = request.POST.get("description", "").strip()
        if not title:
            messages.error(request, "Veuillez préciser l'objet de l'incident.")
            return redirect("shipments:detail", pk=folder.pk)

        inc = Incident(
            folder=folder,
            parcel=parcel,
            client=parcel.client if parcel else None,
            incident_type=request.POST.get("incident_type", "AVARIE").strip() or "AVARIE",
            severity=request.POST.get("severity", "MOYENNE").strip() or "MOYENNE",
            title=title,
            description=desc or title,
            estimated_damage_fcfa=to_decimal(request.POST.get("estimated_damage_fcfa", "0"), "0"),
            reported_by=request.user,
        )
        if request.FILES.get("attachment"):
            inc.attachment = request.FILES["attachment"]
        inc.save()

        TrackingEvent.objects.create(
            folder=folder,
            parcel=parcel,
            stage="INCIDENT",
            status_before=folder.get_status_display(),
            status_after=f"Incident ({inc.get_severity_display()})",
            location_text=str(folder.destination),
            description=f"{inc.reference} — {inc.title}",
            recorded_by=request.user,
        )
        log_audit("CREATE", "Incidents & Litiges", inc.reference, str(inc.pk), f"Signalement incident sur {folder.reference}.")
        messages.warning(request, f"Incident « {inc.reference} » signalé et ajouté au journal du dossier.")
    return redirect("shipments:detail", pk=folder.pk)


@login_required
def folder_quick_document_view(request, pk):
    folder = get_object_or_404(ShipmentFolder, pk=pk)
    if request.method == "POST" and request.FILES.get("file"):
        dtype = request.POST.get("doc_type", "BL").strip()
        if dtype not in dict(Document.DOCUMENT_TYPES):
            dtype = "AUTRE"
        title = request.POST.get("title", "").strip() or f"{dict(Document.DOCUMENT_TYPES).get(dtype, 'Document')} — {folder.reference}"
        doc = Document.objects.create(
            doc_type=dtype,
            title=title,
            external_number=request.POST.get("external_number", "").strip(),
            file=request.FILES["file"],
            folder=folder,
            notes=request.POST.get("notes", "").strip(),
            uploaded_by=request.user,
        )
        log_audit("DOCUMENT", "Gestion documentaire", doc.reference, str(doc.pk), f"Archivage pièce {doc.get_doc_type_display()} sur {folder.reference}.")
        messages.success(request, f"Document « {doc.title} » rattaché au dossier.")
    return redirect("shipments:detail", pk=folder.pk)


@login_required
def folder_print_fiche_view(request, pk):
    """Fiche récapitulative A4 imprimable du dossier de groupage façon MTsarl print_fiche + QR Code."""
    folder = get_object_or_404(
        ShipmentFolder.objects.select_related("origin", "destination", "created_by"),
        pk=pk,
    )
    parcels = list(folder.parcels.select_related("client", "category", "declared_currency").order_by("parcel_code"))
    expenses = list(folder.expenses.select_related("category", "currency").order_by("expense_date"))
    payments = list(
        Payment.objects.filter(Q(invoice__folder=folder) | Q(parcel__folder=folder))
        .select_related("client", "invoice", "parcel")
        .distinct()
        .order_by("payment_date")
    )
    company = CompanySetting.get_solo()
    verify_url = request.build_absolute_uri(
        reverse("documents:verify_qr", kwargs={"doc_kind": "manifeste", "token": folder.reference})
    )
    qr_code = generate_qr_base64(verify_url)

    total_frais = sum((e.amount_fcfa for e in expenses), Decimal("0.00"))
    total_billed = sum((p.suggested_price_fcfa for p in parcels), Decimal("0.00"))
    total_paid = sum((pay.amount_fcfa for pay in payments), Decimal("0.00"))

    return render(
        request,
        "shipments/print_fiche.html",
        {
            "company": company,
            "folder": folder,
            "parcels": parcels,
            "expenses": expenses,
            "payments": payments,
            "total_frais": total_frais,
            "total_billed": total_billed,
            "total_paid": total_paid,
            "reste_recouvrer": max(total_billed - total_paid, Decimal("0.00")),
            "benefice_latent": total_billed - total_frais,
            "qr_code": qr_code,
            "generated_at": timezone.localtime(),
        },
    )


@login_required
def location_list_create_view(request):
    form = LocationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        loc = form.save()
        log_audit("CREATE", "Ports & Aéroports", str(loc), str(loc.pk), "Ajout d'un port/aéroport au référentiel.")
        messages.success(request, f"Lieu « {loc.name} ({loc.code}) » ajouté au référentiel.")
        return redirect("shipments:locations")
    locations = Location.objects.all()
    return render(request, "shipments/location_list.html", {"locations": locations, "form": form})
