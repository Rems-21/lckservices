from django.contrib import admin
from .models import CreditDeliveryAuthorization, Invoice, InvoiceLine, Payment

admin.site.register(Invoice)
admin.site.register(InvoiceLine)
admin.site.register(Payment)
admin.site.register(CreditDeliveryAuthorization)
