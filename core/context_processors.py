"""Context processors globaux pour l'interface LCK Services SARL."""
from django.conf import settings
from django.db.utils import OperationalError, ProgrammingError
from .models import CompanySetting, Currency


def global_context(request):
    company = settings.COMPANY_DEFAULTS
    currencies = []
    try:
        if request.user.is_authenticated:
            company = CompanySetting.get_solo()
            currencies = list(Currency.objects.filter(is_active=True))
    except (OperationalError, ProgrammingError):
        pass

    return {
        "company_info": company,
        "active_currencies": currencies,
    }
