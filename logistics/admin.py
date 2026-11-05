from django.contrib import admin
from .models import Delivery, Incident, TrackingEvent, WarehouseOperation

admin.site.register(TrackingEvent)
admin.site.register(WarehouseOperation)
admin.site.register(Delivery)
admin.site.register(Incident)
