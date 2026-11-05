"""Vues de génération de messages clients et partage rapide via WhatsApp (Section 2.9)."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from accounts.services import log_audit
from billing.models import Invoice
from cargo.models import Parcel
from clients.models import Client
from core.models import CompanySetting
from shipments.models import ShipmentFolder
from .forms import CommunicationComposeForm, MessageTemplateForm, render_message_body
from .models import CommunicationLog, MessageTemplate


@login_required
def communication_hub_view(request):
    company = CompanySetting.get_solo()
    client = Client.objects.filter(pk=request.GET.get("client")).first() if request.GET.get("client", "").isdigit() else None
    folder = ShipmentFolder.objects.filter(pk=request.GET.get("folder")).first() if request.GET.get("folder", "").isdigit() else None
    parcel = Parcel.objects.select_related("folder", "client").filter(pk=request.GET.get("parcel")).first() if request.GET.get("parcel", "").isdigit() else None
    invoice = Invoice.objects.select_related("folder", "client").filter(pk=request.GET.get("invoice")).first() if request.GET.get("invoice", "").isdigit() else None

    if parcel and not client:
        client = parcel.client
    if parcel and not folder:
        folder = parcel.folder
    if invoice and not client:
        client = invoice.client
    if invoice and not folder:
        folder = invoice.folder

    tpl_code = request.GET.get("template", "").strip()
    selected_tpl = None
    if tpl_code:
        selected_tpl = MessageTemplate.objects.filter(code=tpl_code, is_active=True).first()
    elif invoice:
        selected_tpl = MessageTemplate.objects.filter(category="FACTURATION", is_active=True).first()
    elif parcel:
        selected_tpl = MessageTemplate.objects.filter(category="RECEPTION", is_active=True).first()
    elif folder:
        selected_tpl = MessageTemplate.objects.filter(category="ARRIVEE", is_active=True).first()

    doc_url = ""
    if invoice:
        doc_url = request.build_absolute_uri(
            reverse("documents:verify_qr", kwargs={"doc_kind": "facture", "token": str(invoice.verification_token)})
        )
    elif parcel:
        doc_url = request.build_absolute_uri(
            reverse("documents:verify_qr", kwargs={"doc_kind": "colis", "token": str(parcel.verification_token)})
        )

    default_text = ""
    if selected_tpl:
        default_text = render_message_body(
            selected_tpl.body_template,
            company=company,
            client=client,
            folder=folder,
            parcel=parcel,
            invoice=invoice,
            doc_url=doc_url,
        )
    elif client:
        default_text = (
            f"Bonjour {client.name},\n"
            f"Ici le service opérations de {company.name}.\n"
            f"Nous vous contactons concernant le suivi de vos expéditions.\n"
            f"Cordialement,\n{company.name} ({company.phone})"
        )

    initial = {
        "client": client.pk if client else None,
        "folder": folder.pk if folder else None,
        "parcel": parcel.pk if parcel else None,
        "invoice": invoice.pk if invoice else None,
        "recipient_phone": (client.whatsapp or client.phone) if client else "",
        "subject": selected_tpl.name if selected_tpl else "Notification LCK Services",
        "message_body": default_text,
        "template_choice": selected_tpl.pk if selected_tpl else None,
    }

    created_log = None
    if request.method == "POST":
        form = CommunicationComposeForm(request.POST)
        if form.is_valid():
            comm = form.save(commit=False)
            comm.channel = "WHATSAPP"
            comm.sent_by = request.user
            comm.save()
            created_log = comm
            log_audit(
                "WHATSAPP",
                "Communication",
                f"WhatsApp -> {comm.client.name}",
                str(comm.pk),
                f"Message préparé et partagé au numéro {comm.recipient_phone}.",
            )
            if request.POST.get("open_whatsapp") == "1":
                return redirect(comm.whatsapp_link)
            messages.success(request, "Message enregistré ! Cliquez sur « Ouvrir dans WhatsApp » pour l'envoyer.")
    else:
        form = CommunicationComposeForm(initial=initial)

    templates_qs = MessageTemplate.objects.filter(is_active=True)
    templates_map = {t.id: {"name": t.name, "body": t.body_template} for t in templates_qs}
    recent_logs = CommunicationLog.objects.select_related("client", "folder", "invoice", "sent_by")[:20]

    return render(
        request,
        "communications/hub.html",
        {
            "form": form,
            "created_log": created_log,
            "templates_map": templates_map,
            "recent_logs": recent_logs,
            "context_invoice": invoice,
            "context_parcel": parcel,
            "context_folder": folder,
        },
    )


@login_required
def template_list_create_view(request):
    edit_id = request.GET.get("edit")
    instance = get_object_or_404(MessageTemplate, pk=int(edit_id)) if (edit_id and edit_id.isdigit()) else None

    form = MessageTemplateForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        tpl = form.save()
        log_audit("UPDATE" if instance else "CREATE", "Modèles WhatsApp", tpl.name, str(tpl.pk), "Enregistrement modèle de message.")
        messages.success(request, f"Modèle « {tpl.name} » enregistré.")
        return redirect("communications:templates")

    templates_list = MessageTemplate.objects.all()
    return render(
        request,
        "communications/template_list.html",
        {"templates_list": templates_list, "form": form, "editing_instance": instance},
    )
