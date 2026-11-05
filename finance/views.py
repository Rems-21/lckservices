"""Vues de gestion des dépenses, répartition des coûts, marges et rentabilité (Section 2.6)."""
from decimal import Decimal
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from accounts.services import log_audit
from core.models import Currency
from core.utils import to_decimal
from documents.models import Document
from shipments.models import ShipmentFolder
from .forms import ExpenseCategoryForm, FolderExpenseForm
from .models import CostAllocationRun, ExpenseCategory, FolderExpense
from .services import compute_folder_allocation_rows, save_folder_allocation_run


@login_required
def expense_list_view(request):
    q = request.GET.get("q", "").strip()
    folder_id = request.GET.get("folder", "").strip()
    cat_id = request.GET.get("category", "").strip()

    qs = FolderExpense.objects.select_related("folder", "category", "currency", "recorded_by").all()
    if q:
        qs = qs.filter(
            Q(reference__icontains=q)
            | Q(label__icontains=q)
            | Q(vendor_name__icontains=q)
            | Q(folder__reference__icontains=q)
        )
    if folder_id.isdigit():
        qs = qs.filter(folder_id=int(folder_id))
    if cat_id.isdigit():
        qs = qs.filter(category_id=int(cat_id))

    total_fcfa = qs.aggregate(s=Sum("amount_fcfa"))["s"] or Decimal("0.00")
    by_category = (
        qs.values("category__name")
        .annotate(total=Sum("amount_fcfa"), count=Count("id"))
        .order_by("-total")
    )

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "finance/expense_list.html",
        {
            "page_obj": page_obj,
            "q": q,
            "folder_id": folder_id,
            "cat_id": cat_id,
            "total_fcfa": total_fcfa,
            "by_category": by_category,
            "categories": ExpenseCategory.objects.all(),
            "folders": ShipmentFolder.objects.order_by("-created_at")[:50],
        },
    )


@login_required
def expense_create_view(request):
    initial = {}
    if request.GET.get("folder", "").isdigit():
        initial["folder"] = int(request.GET["folder"])

    form = FolderExpenseForm(request.POST or None, request.FILES or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        exp = form.save(commit=False)
        exp.recorded_by = request.user
        exp.save()

        if exp.receipt_file:
            Document.objects.create(
                doc_type="JUSTIFICATIF_DEPENSE",
                title=f"Justificatif {exp.reference} — {exp.label}",
                external_number=exp.reference,
                file=exp.receipt_file,
                folder=exp.folder,
                uploaded_by=request.user,
            )

        log_audit(
            "CREATE",
            "Dépenses",
            exp.reference,
            str(exp.pk),
            f"Dépense enregistrée sur {exp.folder.reference} : {exp.amount_fcfa} FCFA ({exp.label}).",
        )
        messages.success(request, f"Dépense « {exp.reference} » enregistrée ({exp.amount_fcfa} FCFA).")
        return redirect("shipments:detail", pk=exp.folder_id)

    currencies = Currency.objects.filter(is_active=True)
    return render(
        request,
        "finance/expense_form.html",
        {
            "form": form,
            "is_edit": False,
            "currencies_rates": {c.id: str(c.rate_to_fcfa) for c in currencies},
        },
    )


@login_required
def expense_edit_view(request, pk):
    exp = get_object_or_404(FolderExpense, pk=pk)
    form = FolderExpenseForm(request.POST or None, request.FILES or None, instance=exp)
    if request.method == "POST" and form.is_valid():
        exp = form.save()
        log_audit("UPDATE", "Dépenses", exp.reference, str(exp.pk), f"Dépense modifiée : {exp.amount_fcfa} FCFA.")
        messages.success(request, f"Dépense « {exp.reference} » mise à jour.")
        return redirect("finance:expense_list")

    currencies = Currency.objects.filter(is_active=True)
    return render(
        request,
        "finance/expense_form.html",
        {
            "form": form,
            "is_edit": True,
            "expense": exp,
            "currencies_rates": {c.id: str(c.rate_to_fcfa) for c in currencies},
        },
    )


@login_required
def expense_delete_view(request, pk):
    exp = get_object_or_404(FolderExpense, pk=pk)
    if request.method == "POST":
        ref = exp.reference
        folder_id = exp.folder_id
        exp.delete()
        log_audit("DELETE", "Dépenses", ref, str(pk), "Suppression d'une dépense de dossier.")
        messages.success(request, f"Dépense « {ref} » supprimée.")
        return redirect("shipments:detail", pk=folder_id)
    return redirect("finance:expense_list")


@login_required
def folder_allocation_view(request, folder_id):
    """Interface interactive de simulation, ajustement manuel et validation de la répartition des coûts."""
    folder = get_object_or_404(ShipmentFolder.objects.select_related("origin", "destination"), pk=folder_id)
    default_method = "VOLUME" if folder.transport_mode == "MARITIME" else "WEIGHT"

    allocation_method = request.GET.get("method", default_method)
    margin_type = request.GET.get("margin_type", "PERCENT")
    margin_value = to_decimal(request.GET.get("margin_value", "25.00"), "25.00")

    if request.method == "POST":
        allocation_method = request.POST.get("allocation_method", default_method)
        margin_type = request.POST.get("margin_type", "PERCENT")
        margin_value = to_decimal(request.POST.get("margin_value", "25.00"), "25.00")
        notes = request.POST.get("notes", "").strip()
        submit_action = request.POST.get("submit_action", "preview")

        manual_adj = {}
        manual_prices = {}
        for p in folder.parcels.all():
            adj_raw = request.POST.get(f"adj_{p.id}", "0")
            price_raw = request.POST.get(f"price_{p.id}", "")
            manual_adj[p.id] = to_decimal(adj_raw, "0.00")
            if price_raw.strip() != "":
                manual_prices[p.id] = to_decimal(price_raw, "0.00")

        if submit_action == "save":
            run = save_folder_allocation_run(
                folder=folder,
                allocation_method=allocation_method,
                margin_type=margin_type,
                margin_value=margin_value,
                manual_cost_adjustments=manual_adj,
                manual_prices=manual_prices,
                notes=notes,
                user=request.user,
            )
            log_audit(
                "ALLOCATION",
                "Répartition financière",
                run.reference,
                str(run.pk),
                f"Répartition validée sur {folder.reference} ({run.get_allocation_method_display()}, Coût={run.total_allocated_cost_fcfa} FCFA, CA prévu={run.total_commercial_fcfa} FCFA).",
            )
            messages.success(
                request,
                f"Répartition « {run.reference} » appliquée aux colis du dossier {folder.reference} ! Vous pouvez maintenant générer les factures clients.",
            )
            return redirect("finance:allocation_detail", pk=run.pk)

        preview = compute_folder_allocation_rows(
            folder=folder,
            allocation_method=allocation_method,
            margin_type=margin_type,
            margin_value=margin_value,
            manual_cost_adjustments=manual_adj,
            manual_prices=manual_prices,
        )
    else:
        preview = compute_folder_allocation_rows(
            folder=folder,
            allocation_method=allocation_method,
            margin_type=margin_type,
            margin_value=margin_value,
        )

    history = folder.allocation_runs.select_related("created_by")[:10]
    return render(
        request,
        "finance/folder_allocation.html",
        {
            "folder": folder,
            "preview": preview,
            "allocation_method": allocation_method,
            "margin_type": margin_type,
            "margin_value": margin_value,
            "method_choices": CostAllocationRun.ALLOCATION_METHODS,
            "margin_choices": CostAllocationRun.MARGIN_TYPES,
            "history": history,
        },
    )


@login_required
def allocation_history_view(request):
    runs = CostAllocationRun.objects.select_related("folder", "created_by").all()
    return render(request, "finance/allocation_history.html", {"runs": runs})


@login_required
def allocation_detail_view(request, pk):
    run = get_object_or_404(CostAllocationRun.objects.select_related("folder", "created_by"), pk=pk)
    items = run.items.select_related("parcel", "parcel__client").order_by("parcel__parcel_code")
    return render(request, "finance/allocation_detail.html", {"run": run, "items": items})


@login_required
def expense_category_list_view(request):
    form = ExpenseCategoryForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        cat = form.save()
        log_audit("CREATE", "Catégories dépenses", cat.name, str(cat.pk), "Création catégorie de frais.")
        messages.success(request, f"Catégorie « {cat.name} » enregistrée.")
        return redirect("finance:categories")
    categories = ExpenseCategory.objects.annotate(expenses_count=Count("expenses"), total_fcfa=Sum("expenses__amount_fcfa"))
    return render(request, "finance/category_list.html", {"categories": categories, "form": form})
