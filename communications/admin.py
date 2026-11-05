from django.contrib import admin
from .models import CommunicationLog, MessageTemplate

admin.site.register(MessageTemplate)
admin.site.register(CommunicationLog)
