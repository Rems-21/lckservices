"""Vues d'enregistrement, consultation et classification des marchandises et colis (Section 2.4)."""
from decimal import Decimal
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from accounts.services import log_audit
from core.models import Currency
from core.utils import generate_qr_base64
from documents.models import Document
from logistics.models import TrackingEvent
from .forms import CargoCategoryForm, ParcelForm
from .models import CargoCategory, Parcel


@login_required
def parcel_list_view(request):
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    folder_id = request.GET.get("folder", "").strip()
    category_id = request.GET.get("category", "").strip()

    qs = Parcel.objects.select_related("folder", "client", "category", "declared_currency").order_by("-created_at")

    if q:
        qs = qs.filter(
            Q(parcel_code__icontains=q)
            | Q(description__icontains=q)
            | Q(client__name__icontains=q)
            | Q(client__code__icontains=q)
            | Q(folder__reference__icontains=q)
            | Q(supplier_name__icontains=q)
            | Q(supplier_tracking__icontains=q)
        )
    if status:
        qs = qs.filter(status=status)
    if folder_id.isdigit():
        qs = qs.filter(folder_id=int(folder_id))
    if category_id.isdigit():
        qs = qs.filter(category_id=int(category_id))

    agg = qs.aggregate(
        total_parcels=Count("id"),
        total_units=Sum("quantity"),
        total_weight=Sum("weight_kg"),
        total_volume=Sum("volume_cbm"),
    )

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    categories = CargoCategory.objects.all()
    return render(
        request,
        "cargo/parcel_list.html",
        {
            "page_obj": page_obj,
            "q": q,
            "status": status,
            "folder_id": folder_id,
            "category_id": category_id,
            "status_choices": Parcel.PARCEL_STATUS_CHOICES,
            "categories": categories,
            "agg": agg,
        },
    )


@login_required
def parcel_create_view(request):
    initial = {}
    if request.GET.get("folder", "").isdigit():
        initial["folder"] = int(request.GET["folder"])
    if request.GET.get("client", "").isdigit():
        initial["client"] = int(request.GET["client"])

    form = ParcelForm(request.POST or None, request.FILES or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        parcel = form.save(commit=False)
        parcel.created_by = request.user
        parcel.save()

        # Enregistrement automatique d'un document joint à la marchandise si fourni
        uploaded = form.cleaned_data.get("attachment_file")
        if uploaded:
            doc_title = form.cleaned_data.get("attachment_title") or f"Pièce marchandise {parcel.parcel_code}"
            Document.objects.create(
                doc_type="PACKING_LIST",
                title=doc_title,
                file=uploaded,
                folder=parcel.folder,
                parcel=parcel,
                client=parcel.client,
                uploaded_by=request.user,
            )

        # Premier mouvement de tracking du colis
        TrackingEvent.objects.create(
            folder=parcel.folder,
            parcel=parcel,
            stage="RECEPTION_ORIGINE",
            location_text=str(parcel.folder.origin),
            description=f"Enregistrement du colis {parcel.parcel_code} ({parcel.quantity} {parcel.get_packaging_type_display()}, {parcel.volume_cbm} m³, {parcel.weight_kg} kg).",
            recorded_by=request.user,
        )

        log_audit(
            "CREATE",
            "Marchandises & Colis",
            parcel.parcel_code,
            str(parcel.pk),
            f"Colis rattaché au dossier {parcel.folder.reference} pour {parcel.client.name} ({parcel.volume_cbm} m³).",
        )
        messages.success(
            request,
            f"Colis « {parcel.parcel_code} » enregistré avec succès (Volume calculé : {parcel.volume_cbm} m³).",
        )
        return redirect("cargo:detail", pk=parcel.pk)

    currencies = Currency.objects.filter(is_active=True)
    return render(
        request,
        "cargo/parcel_form.html",
        {"form": form, "is_edit": False, "currencies_rates": {c.id: str(c.rate_to_fcfa) for c in currencies}},
    )


@login_required
def parcel_edit_view(request, pk):
    parcel = get_object_or_404(Parcel, pk=pk)
    form = ParcelForm(request.POST or None, request.FILES or None, instance=parcel)
    if request.method == "POST" and form.is_valid():
        parcel = form.save()
        uploaded = form.cleaned_data.get("attachment_file")
        if uploaded:
            doc_title = form.cleaned_data.get("attachment_title") or f"Pièce marchandise {parcel.parcel_code}"
            Document.objects.create(
                doc_type="PACKING_LIST",
                title=doc_title,
                file=uploaded,
                folder=parcel.folder,
                parcel=parcel,
                client=parcel.client,
                uploaded_by=request.user,
            )
        log_audit("UPDATE", "Marchandises & Colis", parcel.parcel_code, str(parcel.pk), f"Mise à jour colis ({parcel.volume_cbm} m³, {parcel.weight_kg} kg).")
        messages.success(request, f"Colis « {parcel.parcel_code} » mis à jour.")
        return redirect("cargo:detail", pk=parcel.pk)

    currencies = Currency.objects.filter(is_active=True)
    return render(
        request,
        "cargo/parcel_form.html",
        {
            "form": form,
            "is_edit": True,
            "parcel": parcel,
            "currencies_rates": {c.id: str(c.rate_to_fcfa) for c in currencies},
        },
    )


@login_required
def parcel_detail_view(request, pk):
    parcel = get_object_or_404(
        Parcel.objects.select_related("folder", "folder__origin", "folder__destination", "client", "category", "declared_currency"),
        pk=pk,
    )
    verify_url = request.build_absolute_uri(
        reverse("documents:verify_qr", kwargs={"doc_kind": "colis", "token": str(parcel.verification_token)})
    )
    qr_data_uri = generate_qr_base64(verify_url)
    events = TrackingEvent.objects.filter(Q(parcel=parcel) | Q(folder=parcel.folder, parcel__isnull=True)).select_related("recorded_by")
    docs = parcel.documents.select_related("uploaded_by").all()
    incidents = parcel.incidents.all()
    allocations = parcel.cost_allocations.select_related("run").order_by("-run__created_at")

    return render(
        request,
        "cargo/parcel_detail.html",
        {
            "parcel": parcel,
            "qr_data_uri": qr_data_uri,
            "verify_url": verify_url,
            "events": events,
            "docs": docs,
            "incidents": incidents,
            "allocations": allocations,
        },
    )


@login_required
def category_list_create_view(request):
    form = CargoCategoryForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        cat = form.save()
        log_audit("CREATE", "Classification marchandises", cat.name, str(cat.pk), "Nouvelle catégorie de marchandise.")
        messages.success(request, f"Catégorie « {cat.name} » créée.")
        return redirect("cargo:categories")
    categories = CargoCategory.objects.annotate(parcels_count=Count("parcels")).order_by("name")
    return render(request, "cargo/category_list.html", {"categories": categories, "form": form})
