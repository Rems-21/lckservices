"""Vues de gestion documentaire (GED), génération PDF (Factures, Reçus, Manifestes, BL) et vérification QR Code."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from accounts.services import log_audit
from billing.models import Invoice, Payment
from cargo.models import Parcel
from core.models import CompanySetting
from core.utils import generate_qr_base64
from logistics.models import Delivery
from shipments.models import ShipmentFolder
from .forms import DocumentUploadForm
from .models import Document
from .pdf_service import build_pdf_response


@login_required
def document_list_create_view(request):
    initial = {}
    if request.GET.get("folder", "").isdigit():
        initial["folder"] = int(request.GET["folder"])
    if request.GET.get("client", "").isdigit():
        initial["client"] = int(request.GET["client"])
    if request.GET.get("parcel", "").isdigit():
        initial["parcel"] = int(request.GET["parcel"])
    if request.GET.get("type"):
        initial["doc_type"] = request.GET["type"]

    form = DocumentUploadForm(request.POST or None, request.FILES or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        doc = form.save(commit=False)
        doc.uploaded_by = request.user
        doc.save()
        log_audit(
            "DOCUMENT",
            "Gestion documentaire",
            f"{doc.reference} - {doc.title}",
            str(doc.pk),
            f"Importation document ({doc.get_doc_type_display()}).",
        )
        messages.success(request, f"Document « {doc.title} » ({doc.reference}) archivé avec succès.")
        return redirect("documents:list")

    q = request.GET.get("q", "").strip()
    dtype = request.GET.get("doc_type", "").strip()
    qs = Document.objects.select_related("folder", "parcel", "client", "invoice", "uploaded_by").all()

    if q:
        qs = qs.filter(
            Q(reference__icontains=q)
            | Q(title__icontains=q)
            | Q(external_number__icontains=q)
            | Q(folder__reference__icontains=q)
            | Q(client__name__icontains=q)
        )
    if dtype:
        qs = qs.filter(doc_type=dtype)

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "documents/document_list.html",
        {
            "page_obj": page_obj,
            "form": form,
            "q": q,
            "dtype": dtype,
            "doc_types": Document.DOCUMENT_TYPES,
        },
    )


@login_required
def document_delete_view(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    if request.method == "POST":
        ref = doc.reference
        title = doc.title
        doc.delete()
        log_audit("DELETE", "Gestion documentaire", f"{ref} - {title}", str(pk), "Suppression de pièce GED.")
        messages.success(request, f"Document « {ref} » supprimé.")
    return redirect("documents:list")


@login_required
def invoice_pdf_view(request, pk):
    invoice = get_object_or_404(
        Invoice.objects.select_related("client", "folder", "folder__origin", "folder__destination", "created_by"),
        pk=pk,
    )
    company = CompanySetting.get_solo()
    verify_url = request.build_absolute_uri(
        reverse("documents:verify_qr", kwargs={"doc_kind": "facture", "token": str(invoice.verification_token)})
    )
    qr_code = generate_qr_base64(verify_url)
    context = {
        "company": company,
        "invoice": invoice,
        "lines": invoice.lines.select_related("parcel").all(),
        "payments": invoice.payments.all(),
        "qr_code": qr_code,
        "verify_url": verify_url,
        "generated_at": timezone.localtime(),
    }
    as_dl = request.GET.get("download") == "1"
    log_audit("DOCUMENT", "Génération PDF", invoice.number, str(invoice.pk), f"Édition PDF {invoice.get_invoice_type_display()}.")
    return build_pdf_response(
        "pdf/invoice_pdf.html",
        context,
        filename=f"{invoice.number}.pdf",
        as_attachment=as_dl,
        base_url=request.build_absolute_uri("/"),
    )


@login_required
def receipt_pdf_view(request, pk):
    payment = get_object_or_404(
        Payment.objects.select_related("invoice", "invoice__folder", "client", "received_by"),
        pk=pk,
    )
    company = CompanySetting.get_solo()
    verify_url = request.build_absolute_uri(
        reverse("documents:verify_qr", kwargs={"doc_kind": "recu", "token": str(payment.verification_token)})
    )
    qr_code = generate_qr_base64(verify_url)
    context = {
        "company": company,
        "payment": payment,
        "invoice": payment.invoice,
        "qr_code": qr_code,
        "verify_url": verify_url,
        "generated_at": timezone.localtime(),
    }
    as_dl = request.GET.get("download") == "1"
    log_audit("DOCUMENT", "Génération PDF", payment.receipt_number, str(payment.pk), "Édition PDF Reçu de paiement.")
    return build_pdf_response(
        "pdf/receipt_pdf.html",
        context,
        filename=f"{payment.receipt_number}.pdf",
        as_attachment=as_dl,
        base_url=request.build_absolute_uri("/"),
    )


@login_required
def manifest_pdf_view(request, folder_id):
    folder = get_object_or_404(
        ShipmentFolder.objects.select_related("origin", "destination", "created_by"),
        pk=folder_id,
    )
    parcels = folder.parcels.select_related("client", "category").order_by("parcel_code")
    company = CompanySetting.get_solo()
    verify_url = request.build_absolute_uri(
        reverse("documents:verify_qr", kwargs={"doc_kind": "manifeste", "token": folder.reference})
    )
    qr_code = generate_qr_base64(verify_url)
    context = {
        "company": company,
        "folder": folder,
        "parcels": parcels,
        "qr_code": qr_code,
        "verify_url": verify_url,
        "generated_at": timezone.localtime(),
    }
    as_dl = request.GET.get("download") == "1"
    log_audit("DOCUMENT", "Génération PDF", f"Manifeste {folder.reference}", str(folder.pk), "Édition PDF du manifeste d'expédition.")
    return build_pdf_response(
        "pdf/manifest_pdf.html",
        context,
        filename=f"MANIFESTE_{folder.reference}.pdf",
        as_attachment=as_dl,
        base_url=request.build_absolute_uri("/"),
    )


@login_required
def delivery_note_pdf_view(request, delivery_id):
    delivery = get_object_or_404(
        Delivery.objects.select_related("client", "folder", "invoice", "credit_authorization", "delivered_by").prefetch_related("parcels"),
        pk=delivery_id,
    )
    company = CompanySetting.get_solo()
    verify_url = request.build_absolute_uri(
        reverse("documents:verify_qr", kwargs={"doc_kind": "livraison", "token": str(delivery.verification_token)})
    )
    qr_code = generate_qr_base64(verify_url)
    context = {
        "company": company,
        "delivery": delivery,
        "parcels": delivery.parcels.all(),
        "qr_code": qr_code,
        "verify_url": verify_url,
        "generated_at": timezone.localtime(),
    }
    as_dl = request.GET.get("download") == "1"
    log_audit("DOCUMENT", "Génération PDF", delivery.delivery_number, str(delivery.pk), "Édition PDF Bon de Livraison.")
    return build_pdf_response(
        "pdf/delivery_note_pdf.html",
        context,
        filename=f"{delivery.delivery_number}.pdf",
        as_attachment=as_dl,
        base_url=request.build_absolute_uri("/"),
    )


@login_required
def parcel_label_pdf_view(request, parcel_id):
    parcel = get_object_or_404(
        Parcel.objects.select_related("folder", "folder__origin", "folder__destination", "client", "category"),
        pk=parcel_id,
    )
    company = CompanySetting.get_solo()
    verify_url = request.build_absolute_uri(
        reverse("documents:verify_qr", kwargs={"doc_kind": "colis", "token": str(parcel.verification_token)})
    )
    qr_code = generate_qr_base64(verify_url)
    context = {
        "company": company,
        "parcel": parcel,
        "qr_code": qr_code,
        "verify_url": verify_url,
        "generated_at": timezone.localtime(),
    }
    as_dl = request.GET.get("download") == "1"
    return build_pdf_response(
        "pdf/parcel_label_pdf.html",
        context,
        filename=f"ETIQUETTE_{parcel.parcel_code}.pdf",
        as_attachment=as_dl,
        base_url=request.build_absolute_uri("/"),
    )


def verify_document_qr_view(request, doc_kind: str, token: str):
    """Contrôle d'authenticité des documents et étiquettes via QR Code."""
    company = CompanySetting.get_solo()
    record_info = None

    if doc_kind == "facture":
        inv = Invoice.objects.select_related("client", "folder").filter(verification_token=token).first()
        if inv:
            record_info = {
                "type_label": inv.get_invoice_type_display(),
                "reference": inv.number,
                "status": inv.get_status_display(),
                "beneficiary": inv.client.name,
                "date": inv.issue_date,
                "amount": f"{inv.total_amount_fcfa} FCFA (Payé : {inv.paid_amount_fcfa} FCFA)",
                "extra": f"Dossier : {inv.folder.reference}" if inv.folder else "",
            }
    elif doc_kind == "recu":
        pay = Payment.objects.select_related("client", "invoice").filter(verification_token=token).first()
        if pay:
            record_info = {
                "type_label": "Reçu Officiel de Paiement",
                "reference": pay.receipt_number,
                "status": "Authentique & Enregistré",
                "beneficiary": pay.client.name,
                "date": pay.payment_date,
                "amount": f"{pay.amount_fcfa} FCFA ({pay.get_payment_method_display()})",
                "extra": f"Facture réglée : {pay.invoice.number}",
            }
    elif doc_kind == "livraison":
        bl = Delivery.objects.select_related("client", "folder").filter(verification_token=token).first()
        if bl:
            record_info = {
                "type_label": "Bon de Livraison",
                "reference": bl.delivery_number,
                "status": "Remis au réceptionnaire",
                "beneficiary": f"{bl.client.name} (Réceptionnaire : {bl.recipient_name})",
                "date": bl.delivered_at,
                "amount": f"{bl.parcels.count()} colis livré(s)",
                "extra": f"Dossier : {bl.folder.reference}",
            }
    elif doc_kind == "colis":
        parcel = Parcel.objects.select_related("client", "folder").filter(verification_token=token).first()
        if parcel:
            record_info = {
                "type_label": "Étiquette & Fiche Colis",
                "reference": parcel.parcel_code,
                "status": parcel.get_status_display(),
                "beneficiary": parcel.client.name,
                "date": parcel.created_at,
                "amount": f"{parcel.volume_cbm} m³ / {parcel.weight_kg} kg ({parcel.quantity} unités)",
                "extra": f"Dossier : {parcel.folder.reference} ({parcel.folder.get_transport_mode_display()})",
            }
    elif doc_kind == "manifeste":
        folder = ShipmentFolder.objects.select_related("origin", "destination").filter(reference=token).first()
        if folder:
            record_info = {
                "type_label": f"Manifeste {folder.get_transport_mode_display()}",
                "reference": folder.reference,
                "status": folder.get_status_display(),
                "beneficiary": f"{folder.origin.city} -> {folder.destination.city}",
                "date": folder.created_at,
                "amount": f"{folder.total_parcels_count} colis | {folder.total_volume_cbm} m³ | {folder.total_weight_kg} kg",
                "extra": folder.transport_doc_ref,
            }

    return render(
        request,
        "documents/verify_qr.html",
        {
            "company": company,
            "doc_kind": doc_kind,
            "record_info": record_info,
        },
    )
