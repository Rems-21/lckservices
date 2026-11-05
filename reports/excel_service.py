"""
Service d'exportation Excel (.xlsx) via OpenPyXL pour les rapports LCK Services SARL (Section 4.4 & 2.10).
"""
import io
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from django.http import HttpResponse


def generate_reports_workbook(report_data: dict) -> bytes:
    wb = Workbook()
    header_fill = PatternFill("solid", fgColor="0F2942")
    sub_fill = PatternFill("solid", fgColor="E2E8F0")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    title_font = Font(name="Calibri", size=14, bold=True, color="0F2942")
    bold_font = Font(name="Calibri", size=11, bold=True, color="0F2942")
    thin_border = Border(
        left=Side(style="thin", color="CBD5E1"),
        right=Side(style="thin", color="CBD5E1"),
        top=Side(style="thin", color="CBD5E1"),
        bottom=Side(style="thin", color="CBD5E1"),
    )

    def _style_table(ws, headers, start_row=4):
        for col_idx, h_text in enumerate(headers, start=1):
            cell = ws.cell(row=start_row, column=col_idx, value=h_text)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = thin_border

    def _autosize(ws):
        for col in ws.columns:
            max_len = 12
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                val = str(cell.value or "")
                if len(val) > max_len:
                    max_len = min(len(val) + 4, 48)
            ws.column_dimensions[col_letter].width = max_len

    # 1. Feuille Synthèse
    ws_kpi = wb.active
    ws_kpi.title = "Synthese Globale"
    ws_kpi["A1"] = f"LCK SERVICES SARL — RAPPORT DE SYNTHÈSE ({report_data['period_label']})"
    ws_kpi["A1"].font = title_font
    _style_table(ws_kpi, ["Indicateur", "Valeur"], start_row=3)
    kpis = [
        ("Nombre de dossiers sur la période", report_data["summary"]["folders_count"]),
        ("Dossiers Maritimes", report_data["summary"]["maritime_count"]),
        ("Dossiers Aériens", report_data["summary"]["aerien_count"]),
        ("Nombre total de colis", report_data["summary"]["parcels_count"]),
        ("Volume total traité (m³)", float(report_data["summary"]["volume_cbm"])),
        ("Poids total traité (kg)", float(report_data["summary"]["weight_kg"])),
        ("Total Recettes Facturées (FCFA)", float(report_data["summary"]["invoiced_fcfa"])),
        ("Total Paiements Encaissés (FCFA)", float(report_data["summary"]["collected_fcfa"])),
        ("Total Dépenses Engagées (FCFA)", float(report_data["summary"]["expenses_fcfa"])),
        ("Résultat / Marge Nette (FCFA)", float(report_data["summary"]["net_profit_fcfa"])),
        ("Total Créances Impayées (FCFA)", float(report_data["summary"]["receivables_fcfa"])),
    ]
    for idx, (label, val) in enumerate(kpis, start=4):
        c1 = ws_kpi.cell(row=idx, column=1, value=label)
        c2 = ws_kpi.cell(row=idx, column=2, value=val)
        c1.border = thin_border
        c2.border = thin_border
        if "FCFA" in label:
            c2.number_format = '#,##0 "FCFA"'
            c2.font = bold_font
    _autosize(ws_kpi)

    # 2. Feuille Rentabilité des Dossiers
    ws_prof = wb.create_sheet("Rentabilite Dossiers")
    ws_prof["A1"] = "ANALYSE DES EXPÉDITIONS ET DE LA RENTABILITÉ PAR DOSSIER"
    ws_prof["A1"].font = title_font
    headers_prof = [
        "Référence",
        "Mode",
        "Trajet",
        "Statut",
        "Colis",
        "Volume (m³)",
        "Poids (kg)",
        "Dépenses (FCFA)",
        "Facturé (FCFA)",
        "Encaissé (FCFA)",
        "Marge Nette (FCFA)",
        "Rentabilité (%)",
    ]
    _style_table(ws_prof, headers_prof, start_row=3)
    for r_idx, row in enumerate(report_data["profitability_rows"], start=4):
        vals = [
            row["reference"],
            row["mode"],
            row["route"],
            row["status"],
            row["parcels_count"],
            float(row["volume_cbm"]),
            float(row["weight_kg"]),
            float(row["expenses_fcfa"]),
            float(row["invoiced_fcfa"]),
            float(row["paid_fcfa"]),
            float(row["profit_fcfa"]),
            float(row["margin_pct"]),
        ]
        for c_idx, v in enumerate(vals, start=1):
            cell = ws_prof.cell(row=r_idx, column=c_idx, value=v)
            cell.border = thin_border
            if c_idx in (8, 9, 10, 11):
                cell.number_format = '#,##0'
            elif c_idx == 12:
                cell.number_format = '0.00"%"'
    _autosize(ws_prof)

    # 3. Feuille Dépenses
    ws_exp = wb.create_sheet("Depenses")
    ws_exp["A1"] = "DÉTAIL DES DÉPENSES ENGAGÉES"
    ws_exp["A1"].font = title_font
    _style_table(
        ws_exp,
        ["Référence", "Date", "Dossier", "Catégorie", "Libellé", "Prestataire", "Montant Devise", "Devise", "Montant (FCFA)"],
        start_row=3,
    )
    for r_idx, exp in enumerate(report_data["expenses"], start=4):
        vals = [
            exp.reference,
            exp.expense_date.strftime("%d/%m/%Y"),
            exp.folder.reference,
            exp.category.name,
            exp.label,
            exp.vendor_name,
            float(exp.amount_original),
            exp.currency.code,
            float(exp.amount_fcfa),
        ]
        for c_idx, v in enumerate(vals, start=1):
            cell = ws_exp.cell(row=r_idx, column=c_idx, value=v)
            cell.border = thin_border
            if c_idx == 9:
                cell.number_format = '#,##0'
    _autosize(ws_exp)

    # 4. Feuille Factures & Créances
    ws_inv = wb.create_sheet("Factures et Creances")
    ws_inv["A1"] = "ÉTAT DES FACTURES DÉFINITIVES ET CRÉANCES CLIENTS"
    ws_inv["A1"].font = title_font
    _style_table(
        ws_inv,
        ["N° Facture", "Date", "Client", "Dossier", "Statut", "Total TTC (FCFA)", "Encaissé (FCFA)", "Solde Restant (FCFA)"],
        start_row=3,
    )
    for r_idx, inv in enumerate(report_data["invoices"], start=4):
        vals = [
            inv.number,
            inv.issue_date.strftime("%d/%m/%Y"),
            inv.client.name,
            inv.folder.reference if inv.folder else "-",
            inv.get_status_display(),
            float(inv.total_amount_fcfa),
            float(inv.paid_amount_fcfa),
            float(inv.balance_due_fcfa),
        ]
        for c_idx, v in enumerate(vals, start=1):
            cell = ws_inv.cell(row=r_idx, column=c_idx, value=v)
            cell.border = thin_border
            if c_idx in (6, 7, 8):
                cell.number_format = '#,##0'
    _autosize(ws_inv)

    # 5. Feuille Paiements
    ws_pay = wb.create_sheet("Paiements")
    ws_pay["A1"] = "JOURNAL DES ENCAISSEMENTS"
    ws_pay["A1"].font = title_font
    _style_table(ws_pay, ["N° Reçu", "Date", "Client", "Facture", "Mode de paiement", "Référence", "Montant (FCFA)"], start_row=3)
    for r_idx, pay in enumerate(report_data["payments"], start=4):
        vals = [
            pay.receipt_number,
            pay.payment_date.strftime("%d/%m/%Y"),
            pay.client.name,
            pay.invoice.number,
            pay.get_payment_method_display(),
            pay.transaction_reference,
            float(pay.amount_fcfa),
        ]
        for c_idx, v in enumerate(vals, start=1):
            cell = ws_pay.cell(row=r_idx, column=c_idx, value=v)
            cell.border = thin_border
            if c_idx == 7:
                cell.number_format = '#,##0'
    _autosize(ws_pay)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_excel_response(report_data: dict, filename: str) -> HttpResponse:
    xlsx_bytes = generate_reports_workbook(report_data)
    resp = HttpResponse(
        xlsx_bytes,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp
