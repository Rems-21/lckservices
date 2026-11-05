"""Vues CRUD Clients, modales rapides façon MTsarl, contacts, historique des expéditions et suivi des soldes (Section 2.2)."""
from decimal import Decimal
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, DecimalField, F, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from accounts.services import log_audit
from core.utils import to_decimal
from .forms import ClientContactForm, ClientForm
from .models import Client, ClientContact


@login_required
def client_list_view(request):
    q = request.GET.get("q", "").strip()
    ctype = request.GET.get("type", "").strip()
    balance_filter = request.GET.get("balance", "").strip()

    definitive_filter = Q(invoices__invoice_type="DEFINITIVE") & ~Q(invoices__status="ANNULEE")
    qs = Client.objects.annotate(
        parcels_count=Count("parcels", distinct=True),
        folders_count=Count("parcels__folder", distinct=True),
        invoiced_sum=Coalesce(
            Sum("invoices__total_amount_fcfa", filter=definitive_filter),
            Value(Decimal("0.00")),
            output_field=DecimalField(max_digits=15, decimal_places=2),
        ),
        paid_sum=Coalesce(
            Sum("invoices__paid_amount_fcfa", filter=definitive_filter),
            Value(Decimal("0.00")),
            output_field=DecimalField(max_digits=15, decimal_places=2),
        ),
    ).annotate(balance_sum=F("invoiced_sum") - F("paid_sum"))

    if q:
        qs = qs.filter(
            Q(code__icontains=q)
            | Q(name__icontains=q)
            | Q(phone__icontains=q)
            | Q(whatsapp__icontains=q)
            | Q(email__icontains=q)
            | Q(city__icontains=q)
        )
    if ctype:
        qs = qs.filter(client_type=ctype)
    if balance_filter == "owes":
        qs = qs.filter(balance_sum__gt=0)
    elif balance_filter == "settled":
        qs = qs.filter(balance_sum__lte=0)

    qs = qs.order_by("-created_at")
    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    totals = Client.objects.aggregate(total_clients=Count("id"))
    return render(
        request,
        "clients/client_list.html",
        {
            "page_obj": page_obj,
            "q": q,
            "ctype": ctype,
            "balance_filter": balance_filter,
            "total_clients": totals["total_clients"] or 0,
            "client_types": Client.CLIENT_TYPES,
        },
    )


@login_required
def client_quick_create_view(request):
    """Ajout rapide d'un client depuis la modale #addClientModal façon MTsarl."""
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        phone = request.POST.get("phone", "").strip()
        if not name or not phone:
            messages.error(request, "Le nom et le téléphone du client sont obligatoires.")
            return redirect("clients:list")

        client = Client.objects.create(
            client_type=request.POST.get("client_type", "ENTREPRISE").strip() or "ENTREPRISE",
            name=name,
            tax_id=request.POST.get("tax_id", "").strip(),
            phone=phone,
            whatsapp=request.POST.get("whatsapp", "").strip() or phone,
            email=request.POST.get("email", "").strip(),
            address=request.POST.get("address", "").strip(),
            city=request.POST.get("city", "Douala").strip() or "Douala",
            country=request.POST.get("country", "Cameroun").strip() or "Cameroun",
            credit_allowed=bool(request.POST.get("credit_allowed")),
            credit_limit_fcfa=to_decimal(request.POST.get("credit_limit_fcfa", "0"), "0"),
            notes=request.POST.get("notes", "").strip(),
        )
        log_audit("CREATE", "Clients", f"{client.code} - {client.name}", str(client.pk), "Enregistrement client via modale.")
        messages.success(request, f"Client « {client.name} » ({client.code}) enregistré avec succès.")
        if request.POST.get("redirect_detail") == "1":
            return redirect("clients:detail", pk=client.pk)
    return redirect("clients:list")


@login_required
def client_quick_update_view(request, pk):
    client = get_object_or_404(Client, pk=pk)
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        phone = request.POST.get("phone", "").strip()
        if name:
            client.name = name
        if phone:
            client.phone = phone
        ctype = request.POST.get("client_type", "").strip()
        if ctype in dict(Client.CLIENT_TYPES):
            client.client_type = ctype
        client.tax_id = request.POST.get("tax_id", "").strip()
        client.whatsapp = request.POST.get("whatsapp", "").strip() or client.phone
        client.email = request.POST.get("email", "").strip()
        client.address = request.POST.get("address", "").strip()
        client.city = request.POST.get("city", client.city).strip() or "Douala"
        client.country = request.POST.get("country", client.country).strip() or "Cameroun"
        client.credit_allowed = bool(request.POST.get("credit_allowed"))
        client.credit_limit_fcfa = to_decimal(request.POST.get("credit_limit_fcfa", str(client.credit_limit_fcfa)), "0")
        client.notes = request.POST.get("notes", "").strip()
        client.save()
        log_audit("UPDATE", "Clients", f"{client.code} - {client.name}", str(client.pk), "Mise à jour rapide fiche client.")
        messages.success(request, f"Fiche du client « {client.name} » mise à jour.")
        if request.POST.get("from_list") == "1":
            return redirect("clients:list")
    return redirect("clients:detail", pk=client.pk)


@login_required
def client_delete_view(request, pk):
    client = get_object_or_404(Client, pk=pk)
    if request.method == "POST":
        if client.parcels.exists() or client.invoices.exists():
            messages.error(
                request,
                f"Impossible de supprimer « {client.name} » car des expéditions ou factures lui sont associées.",
            )
            return redirect("clients:detail", pk=client.pk)
        cname = client.name
        ccode = client.code
        client.delete()
        log_audit("DELETE", "Clients", f"{ccode} - {cname}", str(pk), "Suppression de la fiche client.")
        messages.success(request, f"Le client « {cname} » a été supprimé.")
    return redirect("clients:list")


@login_required
def client_create_view(request):
    form = ClientForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        client = form.save()
        log_audit("CREATE", "Clients", f"{client.code} - {client.name}", str(client.pk), "Enregistrement d'un nouveau client.")
        messages.success(request, f"Le client « {client.name} » ({client.code}) a été enregistré.")
        return redirect("clients:detail", pk=client.pk)
    return render(request, "clients/client_form.html", {"form": form, "is_edit": False})


@login_required
def client_edit_view(request, pk):
    client = get_object_or_404(Client, pk=pk)
    form = ClientForm(request.POST or None, instance=client)
    if request.method == "POST" and form.is_valid():
        client = form.save()
        log_audit("UPDATE", "Clients", f"{client.code} - {client.name}", str(client.pk), "Modification de la fiche client.")
        messages.success(request, f"Les informations du client « {client.name} » ont été mises à jour.")
        return redirect("clients:detail", pk=client.pk)
    return render(request, "clients/client_form.html", {"form": form, "is_edit": True, "client": client})


@login_required
def client_detail_query_view(request):
    pk = request.GET.get("id", "")
    if pk.isdigit():
        return redirect("clients:detail", pk=int(pk))
    return redirect("clients:list")


@login_required
def client_detail_view(request, pk):
    client = get_object_or_404(Client, pk=pk)
    parcels = client.parcels.select_related("folder", "folder__origin", "folder__destination", "category", "declared_currency").order_by("-created_at")
    invoices = client.invoices.select_related("folder").order_by("-issue_date", "-id")
    payments = client.payments.select_related("invoice", "parcel", "received_by").order_by("-payment_date", "-id")
    contacts = client.contacts.all()
    credit_auths = client.credit_authorizations.select_related("invoice", "approved_by").all()
    contact_form = ClientContactForm()

    return render(
        request,
        "clients/client_detail.html",
        {
            "client": client,
            "parcels": parcels,
            "invoices": invoices,
            "payments": payments,
            "contacts": contacts,
            "credit_auths": credit_auths,
            "contact_form": contact_form,
            "client_types": Client.CLIENT_TYPES,
        },
    )


@login_required
def client_contact_add_view(request, pk):
    client = get_object_or_404(Client, pk=pk)
    if request.method == "POST":
        form = ClientContactForm(request.POST)
        if form.is_valid():
            contact = form.save(commit=False)
            contact.client = client
            if contact.is_primary:
                client.contacts.update(is_primary=False)
            contact.save()
            log_audit("CREATE", "Clients", contact.full_name, str(contact.pk), f"Ajout d'un contact pour {client.name}.")
            messages.success(request, f"Contact « {contact.full_name} » ajouté.")
        else:
            messages.error(request, "Veuillez vérifier les informations du contact.")
    return redirect("clients:detail", pk=client.pk)


@login_required
def client_contact_delete_view(request, pk, contact_id):
    client = get_object_or_404(Client, pk=pk)
    contact = get_object_or_404(ClientContact, pk=contact_id, client=client)
    if request.method == "POST":
        cname = contact.full_name
        contact.delete()
        log_audit("DELETE", "Clients", cname, str(contact_id), f"Suppression contact de {client.name}.")
        messages.success(request, f"Contact « {cname} » supprimé.")
    return redirect("clients:detail", pk=client.pk)
