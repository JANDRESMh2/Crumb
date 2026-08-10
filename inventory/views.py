from os import name
from django.contrib import messages
from django.shortcuts import redirect, render

from bakery.services import get_current_bakery

from .forms import IngredientForm
from .models import Ingredient
from .services import register_ingredient

from .models import Ingredient, StockMovement
from .forms import StockInForm
from django.db import transaction


def ingredient_create(request):
    """FR01 - register a new ingredient (name, quantity, unit, expiration date)."""
    bakery = get_current_bakery()
    if bakery is None:
        messages.info(request, 'Set up the bakery profile before registering ingredients.')
        return redirect('bakery:setup')

    if request.method == 'POST':
        form = IngredientForm(request.POST, bakery=bakery)
        if form.is_valid():
            register_ingredient(bakery=bakery, **form.cleaned_data)
            messages.success(request, 'Ingredient registered successfully.')
            return redirect('inventory:list')
    else:
        form = IngredientForm(bakery=bakery)

    return render(request, 'inventory/ingredient_form.html', {'form': form, 'bakery': bakery})


def ingredient_list(request):
    """Minimal listing to close the loop on FR01 registration.

    Full inventory viewing with filtering/search belongs to FR05 and FR22
    (separate, unbuilt tickets) - this view only proves ingredients were
    registered correctly, it is not that feature.
    """
    bakery = get_current_bakery()
    ingredients = (
        Ingredient.objects.filter(bakery=bakery, is_active=True)
        if bakery is not None
        else Ingredient.objects.none()
    )
    return render(
        request,
        'inventory/ingredient_list.html',
        {'ingredients': ingredients, 'bakery': bakery},
    )


@transaction.atomic
def stock_in_create(request):
    if request.method == 'POST':
        form = StockInForm(request.POST)
        if form.is_valid():
            movement = form.save(commit=False)
            movement.movement_type = 'StockIn'
            # Asignar la panadería activa del contexto o sesión
            movement.bakery = request.user.bakery if hasattr(request.user, 'bakery') else Ingredient.objects.first().bakery
            
            # Actualizar el stock actual del ingrediente
            ingredient = movement.ingredient
            ingredient.current_quantity += movement.quantity
            ingredient.save()
            
            movement.save()
            messages.success(request, f"Stock-in successfully registered for {ingredient.name}.")
            return redirect('inventory:ingredient_list')
    else:
        form = StockInForm()
    
    return render(request, 'inventory/stock_in_form.html', {'form': form})


    def ingredient_list(request):
        ingredients = Ingredient.objects.select_reletad('unit', 'category').all().order_by('name')
        
        return render(request, 'inventory/inventory_catalog.html', {'ingredients': ingredients})
