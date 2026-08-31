from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from bakery.services import get_current_bakery

from .forms import IngredientForm, StockInForm
from .models import Ingredient
from .services import (
    deactivate_ingredient,
    is_ingredient_expired,
    is_ingredient_expiring_soon,
    is_ingredient_low_stock,
    register_ingredient,
    update_ingredient,
)


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


def ingredient_edit(request, ingredient_id):
    """FR03 - edit an existing ingredient."""
    bakery = get_current_bakery()

    if bakery is None:
        messages.info(
            request,
            'Set up the bakery profile before editing ingredients.'
        )
        return redirect('bakery:setup')

    ingredient = get_object_or_404(
        Ingredient,
        pk=ingredient_id,
        bakery=bakery,
        is_active=True,
    )

    if request.method == 'POST':
        form = IngredientForm(
            request.POST,
            instance=ingredient,
            bakery=bakery,
        )

        if form.is_valid():
            update_ingredient(
                ingredient=ingredient,
                **form.cleaned_data,
            )

            messages.success(
                request,
                'Ingredient updated successfully.'
            )
            return redirect('inventory:list')

    else:
        form = IngredientForm(
            instance=ingredient,
            bakery=bakery,
        )

    return render(
        request,
        'inventory/ingredient_edit.html',
        {
            'form': form,
            'ingredient': ingredient,
            'bakery': bakery,
        },
    )


def ingredient_delete(request, ingredient_id):
    """FR04 - remove an existing ingredient from the active inventory."""
    bakery = get_current_bakery()

    if bakery is None:
        messages.info(
            request,
            'Set up the bakery profile before deleting ingredients.'
        )
        return redirect('bakery:setup')

    ingredient = get_object_or_404(
        Ingredient,
        pk=ingredient_id,
        bakery=bakery,
        is_active=True,
    )

    if request.method == 'POST':
        deactivate_ingredient(ingredient=ingredient)

        messages.success(
            request,
            'Ingredient deleted successfully.'
        )
        return redirect('inventory:list')

    return render(
        request,
        'inventory/ingredient_confirm_delete.html',
        {
            'ingredient': ingredient,
            'bakery': bakery,
        },
    )


def ingredient_list(request):
    """Display active inventory with alerts and name search (FR05/06/11/22)."""
    bakery = get_current_bakery()
    query = request.GET.get('q', '').strip()
    ingredients = (
        Ingredient.objects.filter(bakery=bakery, is_active=True).select_related(
            'unit',
            'alert_configuration',
        )
        if bakery is not None
        else Ingredient.objects.none()
    )
    if query:
        ingredients = ingredients.filter(name__icontains=query)

    ingredients = list(ingredients)
    for ingredient in ingredients:
        ingredient.is_low_stock = is_ingredient_low_stock(
            ingredient=ingredient,
        )
        ingredient.is_expiring_soon = is_ingredient_expiring_soon(
            ingredient=ingredient,
        )
        ingredient.is_expired = is_ingredient_expired(
            ingredient=ingredient,
        )

    return render(
        request,
        'inventory/ingredient_list.html',
        {'ingredients': ingredients, 'bakery': bakery, 'query': query},
    )


@transaction.atomic
def stock_in_create(request):
    bakery = get_current_bakery()
    if bakery is None:
        messages.info(request, 'Set up the bakery profile before registering stock.')
        return redirect('bakery:setup')

    if request.method == 'POST':
        form = StockInForm(request.POST, bakery=bakery)
        if form.is_valid():
            movement = form.save(commit=False)
            movement.movement_type = 'StockIn'
            movement.bakery = bakery

            ingredient = movement.ingredient
            ingredient.current_quantity += movement.quantity
            ingredient.save()

            movement.save()
            messages.success(
                request,
                f'Stock-in successfully registered for {ingredient.name}.',
            )
            return redirect('inventory:list')
    else:
        form = StockInForm(bakery=bakery)

    return render(
        request,
        'inventory/stock_in_form.html',
        {'form': form, 'bakery': bakery},
    )
