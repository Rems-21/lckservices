"""Vues de facturation Proforma/Définitive, encaissements, reçus, créances et autorisations de crédit (Section 2.7)."""
from decimal import Decimal
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import F, Q, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from accounts.services import log_audit
from cargo.models import Parcel
from core.models import CompanySetting
from core.utils import generate_qr_base64
from documents.pdf_service import build_pdf_response
from shipments.models import ShipmentFolder
from .forms import CreditAuthorizationForm, InvoiceForm, InvoiceLineForm, PaymentForm
from .models import CreditDeliveryAuthorization, Invoice, InvoiceLine, Payment
from .services import convert_proforma_to_definitive, generate_folder_invoices, sync_or_create_parcel_invoice


@login_required
def invoice_list_view(request):
    q = request.GET.get("q", "").strip()
    inv_type = request.GET.get("type", "").strip()
    status = request.GET.get("status", "").strip()

    qs = Invoice.objects.select_related("client", "folder", "created_by").all()
    if q:
        qs = qs.filter(
            Q(number__icontains=q)
            | Q(client__name__icontains=q)
            | Q(client__code__icontains=q)
            | Q(folder__reference__icontains=q)
        )
    if inv_type:
        qs = qs.filter(invoice_type=inv_type)
    if status:
        qs = qs.filter(status=status)

    definitive_qs = Invoice.objects.filter(invoice_type="DEFINITIVE").exclude(status="ANNULEE")
    agg = definitive_qs.aggregate(
        billed=Sum("total_amount_fcfa"),
        paid=Sum("paid_amount_fcfa"),
    )
    total_billed = agg["billed"] or Decimal("0.00")
    total_paid = agg["paid"] or Decimal("0.00")

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "billing/invoice_list.html",
        {
            "page_obj": page_obj,
            "q": q,
            "inv_type": inv_type,
            "status": status,
            "status_choices": Invoice.STATUS_CHOICES,
            "total_billed": total_billed,
            "total_paid": total_paid,
            "total_receivables": max(total_billed - total_paid, Decimal("0.00")),
        },
    )


@login_required
def invoice_create_view(request):
    initial = {}
    if request.GET.get("client", "").isdigit():
        initial["client"] = int(request.GET["client"])
    if request.GET.get("folder", "").isdigit():
        initial["folder"] = int(request.GET["folder"])
    if request.GET.get("type") in ("PROFORMA", "DEFINITIVE"):
        initial["invoice_type"] = request.GET["type"]

    form = InvoiceForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        inv = form.save(commit=False)
        inv.created_by = request.user
        inv.save()
        log_audit("CREATE", "Facturation", inv.number, str(inv.pk), f"Création manuelle {inv.get_invoice_type_display()} pour {inv.client.name}.")
        messages.success(request, f"Facture « {inv.number} » créée. Ajoutez maintenant les lignes de facturation.")
        return redirect("billing:invoice_detail", pk=inv.pk)
    return render(request, "billing/invoice_form.html", {"form": form, "is_edit": False})


@login_required
def invoice_edit_view(request, pk):
    inv = get_object_or_404(Invoice, pk=pk)
    form = InvoiceForm(request.POST or None, instance=inv)
    if request.method == "POST" and form.is_valid():
        inv = form.save()
        inv.recalculate_totals(save=True)
        log_audit("UPDATE", "Facturation", inv.number, str(inv.pk), "Mise à jour en-tête / remise / TVA de facture.")
        messages.success(request, f"Facture « {inv.number} » mise à jour.")
        return redirect("billing:invoice_detail", pk=inv.pk)
    return render(request, "billing/invoice_form.html", {"form": form, "is_edit": True, "invoice": inv})


@login_required
def generate_folder_invoices_view(request, folder_id):
    folder = get_object_or_404(ShipmentFolder, pk=folder_id)
    if request.method == "POST":
        inv_type = request.POST.get("invoice_type", "DEFINITIVE")
        if inv_type not in ("PROFORMA", "DEFINITIVE"):
            inv_type = "DEFINITIVE"
        client_id = request.POST.get("client_id")
        cid = int(client_id) if (client_id and client_id.isdigit()) else None

        generated = generate_folder_invoices(folder=folder, invoice_type=inv_type, client_id=cid, user=request.user)
        if generated:
            nums = ", ".join(i.number for i in generated)
            log_audit(
                "CREATE",
                "Facturation automatique",
                folder.reference,
                str(folder.pk),
                f"{len(generated)} facture(s) {inv_type} générée(s) automatiquement : {nums}.",
            )
            messages.success(request, f"{len(generated)} facture(s) générée(s) automatiquement : {nums}.")
            if len(generated) == 1:
                return redirect("billing:invoice_detail", pk=generated[0].pk)
        else:
            messages.info(
                request,
                "Aucune nouvelle facture à générer (tous les colis du dossier ont déjà été facturés en Définitive, ou le dossier ne contient aucun colis).",
            )
    return redirect("shipments:detail", pk=folder.pk)


@login_required
def invoice_detail_view(request, pk):
    inv = get_object_or_404(
        Invoice.objects.select_related("client", "folder", "source_proforma", "created_by"),
        pk=pk,
    )
    lines = inv.lines.select_related("parcel").all()
    payments = inv.payments.select_related("received_by").all()
    credit_auths = inv.credit_authorizations.select_related("approved_by").all()

    line_form = InvoiceLineForm(folder=inv.folder, client=inv.client)
    payment_form = PaymentForm(initial={"invoice": inv.pk, "amount_fcfa": inv.balance_due_fcfa})

    return render(
        request,
        "billing/invoice_detail.html",
        {
            "invoice": inv,
            "lines": lines,
            "payments": payments,
            "credit_auths": credit_auths,
            "line_form": line_form,
            "payment_form": payment_form,
        },
    )


@login_required
def invoice_line_add_view(request, pk):
    inv = get_object_or_404(Invoice, pk=pk)
    if request.method == "POST":
        form = InvoiceLineForm(request.POST, folder=inv.folder, client=inv.client)
        if form.is_valid():
            line = form.save(commit=False)
            line.invoice = inv
            line.save()
            inv.recalculate_totals(save=True)
            log_audit("UPDATE", "Facturation", inv.number, str(inv.pk), f"Ajout ligne : {line.description} ({line.line_total_fcfa} FCFA).")
            messages.success(request, "Ligne ajoutée à la facture.")
        else:
            messages.error(request, "Erreur lors de l'ajout de la ligne.")
    return redirect("billing:invoice_detail", pk=inv.pk)


@login_required
def invoice_line_delete_view(request, pk, line_id):
    inv = get_object_or_404(Invoice, pk=pk)
    line = get_object_or_404(InvoiceLine, pk=line_id, invoice=inv)
    if request.method == "POST":
        desc = line.description
        line.delete()
        inv.recalculate_totals(save=True)
        log_audit("DELETE", "Facturation", inv.number, str(inv.pk), f"Suppression ligne : {desc}.")
        messages.success(request, "Ligne supprimée et totaux recalculés.")
    return redirect("billing:invoice_detail", pk=inv.pk)


@login_required
def convert_proforma_view(request, pk):
    proforma = get_object_or_404(Invoice, pk=pk, invoice_type="PROFORMA")
    if request.method == "POST":
        definitive = convert_proforma_to_definitive(proforma, user=request.user)
        log_audit(
            "CREATE",
            "Facturation",
            definitive.number,
            str(definitive.pk),
            f"Conversion de la Proforma {proforma.number} en facture Définitive {definitive.number}.",
        )
        messages.success(request, f"Proforma {proforma.number} convertie en Facture Définitive « {definitive.number} ».")
        return redirect("billing:invoice_detail", pk=definitive.pk)
    return redirect("billing:invoice_detail", pk=proforma.pk)


@login_required
def invoice_cancel_view(request, pk):
    inv = get_object_or_404(Invoice, pk=pk)
    if request.method == "POST":
        if inv.paid_amount_fcfa > 0:
            messages.error(request, "Impossible d'annuler une facture ayant déjà fait l'objet d'encaissements.")
        else:
            inv.status = "ANNULEE"
            inv.save(update_fields=["status", "updated_at"])
            log_audit("STATUS", "Facturation", inv.number, str(inv.pk), "Annulation de la facture.")
            messages.warning(request, f"Facture « {inv.number} » annulée.")
    return redirect("billing:invoice_detail", pk=inv.pk)


@login_required
def payment_list_create_view(request):
    initial = {}
    if request.GET.get("invoice", "").isdigit():
        inv = Invoice.objects.filter(pk=int(request.GET["invoice"])).first()
        if inv:
            initial["invoice"] = inv.pk
            initial["amount_fcfa"] = inv.balance_due_fcfa

    form = PaymentForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            payment = form.save(commit=False)
            payment.client = payment.invoice.client
            payment.received_by = request.user
            payment.save()

            # Si la facture est désormais intégralement soldée, régulariser les autorisations de crédit actives
            if payment.invoice.status == "PAYEE":
                payment.invoice.credit_authorizations.filter(status="ACTIVE").update(status="REGULARISEE")

            log_audit(
                "PAYMENT",
                "Paiements & Reçus",
                payment.receipt_number,
                str(payment.pk),
                f"Encaissement de {payment.amount_fcfa} FCFA ({payment.get_payment_method_display()}) sur facture {payment.invoice.number}.",
            )
            messages.success(
                request,
                f"Paiement enregistré ! Reçu « {payment.receipt_number} » généré (Solde restant : {payment.invoice.balance_due_fcfa} FCFA).",
            )
            next_to_inv = request.POST.get("from_invoice")
            if next_to_inv:
                return redirect("billing:invoice_detail", pk=payment.invoice_id)
            return redirect("billing:payment_list")

    payments = Payment.objects.select_related("invoice", "client", "received_by").all()
    total_collected = payments.aggregate(s=Sum("amount_fcfa"))["s"] or Decimal("0.00")
    paginator = Paginator(payments, 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "billing/payment_list.html",
        {
            "page_obj": page_obj,
            "form": form,
            "total_collected": total_collected,
        },
    )


@login_required
def receivables_and_credit_view(request):
    """Suivi des créances clients (balance âgée) et gestion des autorisations de livraison à crédit."""
    initial = {}
    if request.GET.get("invoice", "").isdigit():
        inv = Invoice.objects.filter(pk=int(request.GET["invoice"])).first()
        if inv:
            initial["invoice"] = inv.pk
            initial["client"] = inv.client_id

    form = CreditAuthorizationForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        auth_obj = form.save(commit=False)
        auth_obj.authorized_balance_fcfa = auth_obj.invoice.balance_due_fcfa
        auth_obj.folder = auth_obj.invoice.folder
        auth_obj.approved_by = request.user
        auth_obj.save()
        log_audit(
            "CREDIT_AUTH",
            "Autorisations de crédit",
            auth_obj.reference,
            str(auth_obj.pk),
            f"Autorisation livraison à crédit accordée à {auth_obj.client.name} sur {auth_obj.invoice.number} ({auth_obj.authorized_balance_fcfa} FCFA).",
        )
        messages.success(
            request,
            f"Autorisation de livraison à crédit « {auth_obj.reference} » accordée pour {auth_obj.invoice.number}.",
        )
        return redirect("billing:receivables")

    unpaid_invoices = (
        Invoice.objects.filter(invoice_type="DEFINITIVE")
        .exclude(status__in=["PAYEE", "ANNULEE"])
        .annotate(remaining=F("total_amount_fcfa") - F("paid_amount_fcfa"))
        .filter(remaining__gt=0)
        .select_related("client", "folder")
        .order_by("due_date", "-issue_date")
    )

    today = timezone.localdate()
    total_receivables = Decimal("0.00")
    overdue_total = Decimal("0.00")
    for u_inv in unpaid_invoices:
        bal = u_inv.balance_due_fcfa
        total_receivables += bal
        if u_inv.due_date and u_inv.due_date < today:
            overdue_total += bal

    credit_auths = CreditDeliveryAuthorization.objects.select_related("client", "invoice", "folder", "approved_by").all()

    return render(
        request,
        "billing/receivables_credit.html",
        {
            "unpaid_invoices": unpaid_invoices,
            "total_receivables": total_receivables,
            "overdue_total": overdue_total,
            "credit_auths": credit_auths,
            "form": form,
            "today": today,
        },
    )


@login_required
def credit_status_toggle_view(request, pk):
    auth_obj = get_object_or_404(CreditDeliveryAuthorization, pk=pk)
    if request.method == "POST":
        new_status = request.POST.get("status", "REVOQUEE")
        if new_status in dict(CreditDeliveryAuthorization.STATUS_CHOICES):
            auth_obj.status = new_status
            auth_obj.save(update_fields=["status", "updated_at"])
            log_audit("CREDIT_AUTH", "Autorisations de crédit", auth_obj.reference, str(auth_obj.pk), f"Statut changé -> {auth_obj.get_status_display()}.")
            messages.info(request, f"Autorisation {auth_obj.reference} mise au statut « {auth_obj.get_status_display()} ».")
    return redirect("billing:receivables")


def shared_invoice_view(request):
    """Vue publique sécurisée par jeton HMAC de la facture client partagée sur WhatsApp (façon MTsarl shared_invoice)."""
    item_id = request.GET.get("item", "").strip()
    token = request.GET.get("token", "").strip()
    if not item_id.isdigit() or not token:
        raise Http404("Lien de facture invalide ou incomplet.")

    parcel = get_object_or_404(
        Parcel.objects.select_related("folder", "folder__origin", "folder__destination", "client", "category", "declared_currency"),
        pk=int(item_id),
    )
    if not parcel.verify_share_token(token):
        raise Http404("Jeton de sécurité invalide pour cette facture.")

    invoice = (
        Invoice.objects.filter(lines__parcel=parcel)
        .exclude(status="ANNULEE")
        .order_by("invoice_type", "-id")
        .first()
    )
    if not invoice and parcel.suggested_price_fcfa > 0:
        invoice = sync_or_create_parcel_invoice(parcel, user=None, create_if_missing=True)

    payments = list(
        Payment.objects.filter(Q(parcel=parcel) | (Q(invoice=invoice) if invoice else Q(pk__in=[])))
        .distinct()
        .order_by("payment_date", "id")
    )
    company = CompanySetting.get_solo()

    if invoice:
        verify_url = request.build_absolute_uri(
            reverse("documents:verify_qr", kwargs={"doc_kind": "facture", "token": str(invoice.verification_token)})
        )
    else:
        verify_url = request.build_absolute_uri(
            reverse("documents:verify_qr", kwargs={"doc_kind": "colis", "token": str(parcel.verification_token)})
        )
    qr_code = generate_qr_base64(verify_url)

    if request.GET.get("download") == "pdf" and invoice:
        return build_pdf_response(
            "pdf/invoice_pdf.html",
            {
                "company": company,
                "invoice": invoice,
                "lines": invoice.lines.select_related("parcel").all(),
                "payments": payments,
                "qr_code": qr_code,
                "verify_url": verify_url,
                "generated_at": timezone.localtime(),
            },
            filename=f"{invoice.number}.pdf",
            as_attachment=True,
            base_url=request.build_absolute_uri("/"),
        )

    return render(
        request,
        "billing/shared_invoice.html",
        {
            "company": company,
            "parcel": parcel,
            "folder": parcel.folder,
            "client": parcel.client,
            "invoice": invoice,
            "payments": payments,
            "qr_code": qr_code,
            "verify_url": verify_url,
            "token": token,
            "generated_at": timezone.localtime(),
        },
    )
