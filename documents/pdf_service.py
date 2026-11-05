"""
Service de génération PDF pour LCK Services SARL (Section 4.4 & 2.8).
Utilise WeasyPrint en moteur principal et bascule automatiquement sur xhtml2pdf
sous Windows si les bibliothèques système GTK3/Pango ne sont pas installées.
"""
import contextlib
import io
from django.http import HttpResponse
from django.template.loader import render_to_string

_WEASYPRINT_AVAILABLE = None


def _get_weasyprint():
    global _WEASYPRINT_AVAILABLE
    if _WEASYPRINT_AVAILABLE is False:
        return None
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            import weasyprint
        _WEASYPRINT_AVAILABLE = True
        return weasyprint
    except (ImportError, OSError):
        _WEASYPRINT_AVAILABLE = False
        return None


def render_html_to_pdf_bytes(template_name: str, context: dict, base_url: str = None) -> tuple[bytes, str]:
    """Retourne (pdf_bytes, engine_used)."""
    html_string = render_to_string(template_name, context)

    # 1. Moteur principal : WeasyPrint (Cahier des charges 4.4)
    weasyprint = _get_weasyprint()
    if weasyprint is not None:
        try:
            pdf_bytes = weasyprint.HTML(string=html_string, base_url=base_url).write_pdf()
            return pdf_bytes, "WeasyPrint"
        except OSError:
            pass

    # 2. Moteur de secours Windows sans GTK3 : xhtml2pdf / ReportLab
    from xhtml2pdf import pisa

    result = io.BytesIO()
    src_bytes = io.BytesIO(html_string.encode("utf-8"))
    pisa_status = pisa.CreatePDF(src_bytes, dest=result, encoding="utf-8")
    if pisa_status.err:
        raise RuntimeError("Erreur lors de la génération du document PDF.")
    return result.getvalue(), "xhtml2pdf"


def build_pdf_response(
    template_name: str,
    context: dict,
    filename: str,
    as_attachment: bool = False,
    base_url: str = None,
) -> HttpResponse:
    pdf_bytes, engine = render_html_to_pdf_bytes(template_name, context, base_url=base_url)
    disposition = "attachment" if as_attachment else "inline"
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'{disposition}; filename="{filename}"'
    response["X-PDF-Engine"] = engine
    return response
