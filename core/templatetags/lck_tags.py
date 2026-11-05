"""Filtres et balises de gabarits personnalisés — LCK Services SARL."""
from decimal import Decimal
from django import template
from core.utils import format_fcfa, round_money, to_decimal

register = template.Library()


@register.filter
def fcfa(value):
    return format_fcfa(value, "FCFA")


@register.filter
def fcfa_num(value):
    """Formate un montant entier avec séparateurs d'espaces sans suffixe FCFA (ex: 1 250 000)."""
    val = round_money(to_decimal(value))
    formatted = f"{int(val):,}".replace(",", " ")
    return formatted


@register.filter
def money(value, currency_code="FCFA"):
    return format_fcfa(value, currency_code or "FCFA")


@register.filter
def num(value, decimals=2):
    val = to_decimal(value)
    fmt = f"{{:,.{int(decimals)}f}}"
    return fmt.format(val).replace(",", " ").replace(".", ",")


@register.filter
def status_color(status):
    """Retourne le jeton de couleur Bootstrap (primary, info, warning, success, danger, secondary) façon MTsarl."""
    mapping = {
        "BROUILLON": "secondary",
        "OUVERT": "info",
        "RECU_ORIGINE": "info",
        "CHARGE": "primary",
        "EN_TRANSIT": "primary",
        "ARRIVE": "warning",
        "DEDOUANEMENT": "warning",
        "DISPONIBLE_ENTREPOT": "success",
        "LIVRE": "success",
        "CLOTURE": "dark",
        "ANNULE": "danger",
        "PROFORMA": "info",
        "EMISE": "warning",
        "PARTIELLEMENT_PAYEE": "primary",
        "PAYEE": "success",
        "ANNULEE": "danger",
        "EN_COURS": "warning",
        "RESOLU": "success",
        "CLOS": "secondary",
        "CRITIQUE": "danger",
        "MOYENNE": "warning",
        "FAIBLE": "info",
        "ACTIVE": "warning",
        "REGULARISEE": "success",
        "REVOQUEE": "danger",
    }
    return mapping.get(str(status), "secondary")


@register.filter
def badge_class(status):
    color = status_color(status)
    if color == "dark":
        return "bg-dark text-white"
    return f"bg-{color}-subtle text-{color} border border-{color}-subtle"


@register.filter
def abs_val(value):
    return abs(to_decimal(value))


@register.filter
def get_item(dictionary, key):
    if not isinstance(dictionary, dict):
        return None
    return dictionary.get(key)
