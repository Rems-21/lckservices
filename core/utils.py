"""Fonctions utilitaires de numérotation, formatage monétaire et QR Code."""
import base64
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import BytesIO
from django.utils import timezone


def to_decimal(value, default="0.00") -> Decimal:
    if value is None or value == "":
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    try:
        cleaned = str(value).replace(" ", "").replace("\u00a0", "").replace(",", ".")
        return Decimal(cleaned)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def round_money(value) -> Decimal:
    return to_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def format_fcfa(value, suffix="FCFA") -> str:
    amount = round_money(value)
    if amount == amount.to_integral_value():
        formatted = f"{int(amount):,}".replace(",", " ")
    else:
        formatted = f"{amount:,.2f}".replace(",", " ").replace(".", ",")
    return f"{formatted} {suffix}".strip()


def generate_sequence_code(model_cls, field_name: str, prefix: str, pad: int = 4) -> str:
    """Génère une référence séquentielle unique de type PREFIX-YYYY-0001."""
    year = timezone.now().year
    full_prefix = f"{prefix}-{year}-"
    last_obj = (
        model_cls.objects.filter(**{f"{field_name}__startswith": full_prefix})
        .order_by(f"-{field_name}")
        .values_list(field_name, flat=True)
        .first()
    )
    next_num = 1
    if last_obj:
        tail = last_obj.replace(full_prefix, "")
        if tail.isdigit():
            next_num = int(tail) + 1
    code = f"{full_prefix}{next_num:0{pad}d}"
    while model_cls.objects.filter(**{field_name: code}).exists():
        next_num += 1
        code = f"{full_prefix}{next_num:0{pad}d}"
    return code


def generate_qr_base64(data: str) -> str:
    """Génère un QR Code PNG encodé en data URI Base64 pour intégration directe HTML/WeasyPrint."""
    import qrcode

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=6,
        border=2,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0f2942", back_color="white")
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"
