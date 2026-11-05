from django.contrib import admin
from .models import CostAllocationRun, ExpenseCategory, FolderExpense, ParcelCostAllocation

admin.site.register(ExpenseCategory)
admin.site.register(FolderExpense)
admin.site.register(CostAllocationRun)
admin.site.register(ParcelCostAllocation)
