from django.contrib import admin

from .models import Bakery


@admin.register(Bakery)
class BakeryAdmin(admin.ModelAdmin):
    list_display = ('name', 'address', 'phone', 'email', 'updated_at')
    search_fields = ('name', 'address', 'email')
