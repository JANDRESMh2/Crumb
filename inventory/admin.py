from django.contrib import admin

from .models import BarcodeIdentifier, Ingredient, UnitOfMeasure


@admin.register(UnitOfMeasure)
class UnitOfMeasureAdmin(admin.ModelAdmin):
    list_display = ('name', 'abbreviation', 'unit_type')


@admin.register(Ingredient)
class IngredientAdmin(admin.ModelAdmin):
    list_display = ('name', 'bakery', 'unit', 'current_quantity', 'expiration_date', 'is_active')
    list_filter = ('bakery', 'unit', 'is_active')
    search_fields = ('name',)


@admin.register(BarcodeIdentifier)
class BarcodeIdentifierAdmin(admin.ModelAdmin):
    list_display = ('barcode_value', 'ingredient', 'is_active', 'created_at')
    search_fields = ('barcode_value', 'ingredient__name')
