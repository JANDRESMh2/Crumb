from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from bakery.services import get_current_bakery

from .forms import Ingredient_registration, Barcode_scanning_for_ingredient_registration, Stock_consumption_registration_form, StockInForm
from .models import Ingredient
from .services import (
    InsufficientStockError,
    deactivate_ingredient,
    register_ingredient,
    register_stock_consumption,
    update_ingredient,
)


def ingredient_create(request):
    """FR01 - register a new ingredient (name, quantity, unit, expiration date).

    Also handles FR17 (optional barcode capture) via Barcode_scanning_for_ingredient_registration.
    """
    bakery = get_current_bakery()
    if bakery is None:
        messages.info(request, 'Set up the bakery profile before registering ingredients.')
        return redirect('bakery:setup')

    if request.method == 'POST':
        form = Barcode_scanning_for_ingredient_registration(request.POST, bakery=bakery)
        if form.is_valid():
            register_ingredient(bakery=bakery, **form.cleaned_data)
            messages.success(request, 'Ingredient registered successfully.')
            return redirect('inventory:list')
    else:
        form = Barcode_scanning_for_ingredient_registration(bakery=bakery)

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
        form = Ingredient_registration(
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
        form = Ingredient_registration(
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


def  Ingredient_deletion(request, ingredient_id):
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


def Search_ingredient(request):
    """List active ingredients and search them by name (FR22)."""
    bakery = get_current_bakery()
    query = request.GET.get('q', '').strip()
    ingredients = (
        Ingredient.objects.filter(bakery=bakery, is_active=True)
        .select_related('unit')
        .prefetch_related('barcodes')
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


# [FR08: Stock consumption registration]
def Stock_consumption_registration(request):
    """FR08 - register the consumption of an ingredient."""
    bakery = get_current_bakery()
    if bakery is None:
        messages.info(request, 'Set up the bakery profile before registering consumption.')
        return redirect('bakery:setup')

    if request.method == 'POST':
        form = Stock_consumption_registration_form(request.POST, bakery=bakery)
        if form.is_valid():
            ingredient = form.cleaned_data['ingredient']
            try:
                register_stock_consumption(
                    bakery=bakery,
                    ingredient=ingredient,
                    quantity=form.cleaned_data['quantity'],
                    note=form.cleaned_data.get('note', ''),
                )
            except InsufficientStockError as error:
                # The form already validates the available stock; this covers
                # the stock changing between validation and saving.
                form.add_error('quantity', str(error))
            else:
                messages.success(request, f'Consumption registered for {ingredient.name}.')
                return redirect('inventory:list')
    else:
        form = Stock_consumption_registration_form(bakery=bakery)

    return render(
        request,
        'inventory/stock_consumption_form.html',
        {'form': form, 'bakery': bakery},
    )
