from django.contrib import admin

from .models import Ingredient, UnitOfMeasure


@admin.register(UnitOfMeasure)
class UnitOfMeasureAdmin(admin.ModelAdmin):
    list_display = ('name', 'abbreviation', 'unit_type')


@admin.register(Ingredient)
class IngredientAdmin(admin.ModelAdmin):
    list_display = ('name', 'bakery', 'unit', 'current_quantity', 'expiration_date', 'is_active')
    list_filter = ('bakery', 'unit', 'is_active')
    search_fields = ('name',)
