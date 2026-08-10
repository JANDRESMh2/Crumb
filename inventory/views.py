from django.contrib import messages
from django.shortcuts import redirect, render

from bakery.services import get_current_bakery

from .forms import IngredientForm
from .models import Ingredient
from .services import register_ingredient


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
    """List active ingredients and search them by name (FR22)."""
    bakery = get_current_bakery()
    query = request.GET.get('q', '').strip()
    ingredients = (
        Ingredient.objects.filter(bakery=bakery, is_active=True).select_related('unit')
        if bakery is not None
        else Ingredient.objects.none()
    )
    if query:
        ingredients = ingredients.filter(name__icontains=query)

    return render(
        request,
        'inventory/ingredient_list.html',
        {'ingredients': ingredients, 'bakery': bakery, 'query': query},
    )
