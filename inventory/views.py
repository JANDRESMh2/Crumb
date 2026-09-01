from urllib import request

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date

from bakery.services import get_current_bakery

from .forms import (
    Barcode_scanning_for_ingredient_registration,
    IngredientForm,
    LowStockThresholdConfigurationForm,
    Stock_consumption_registration_form,
    StockInForm,
)

from .models import AlertConfiguration, Ingredient

from .services import (
    InsufficientStockError,
    configure_low_stock_threshold,
    deactivate_ingredient,
    is_ingredient_expired,
    is_ingredient_expiring_soon,
    is_ingredient_low_stock,
    register_ingredient,
    register_stock_consumption,
    update_ingredient,
)


def ingredient_create(request):
    """FR01 - register a new ingredient (name, quantity, unit, expiration date).

    Also handles FR17 (optional barcode capture) via
    Barcode_scanning_for_ingredient_registration.
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
    start_date = request.GET.get('start_date', '').strip()
    end_date = request.GET.get('end_date', '').strip()

    start_date_value = parse_date(start_date) if start_date else None
    end_date_value = parse_date(end_date) if end_date else None

    ingredients = (
        Ingredient.objects.filter(bakery=bakery, is_active=True)
        .select_related('unit', 'alert_configuration')
        .prefetch_related('barcodes')
        if bakery is not None
        else Ingredient.objects.none()
    )
    if query:
        ingredients = ingredients.filter(name__icontains=query)

    if (
        start_date_value
        and end_date_value
        and start_date_value > end_date_value
    ):
        messages.error(
            request,
            'The start date cannot be later than the end date.'
        )
        ingredients = Ingredient.objects.none()
    else:
        if start_date_value:
            ingredients = ingredients.filter(
                expiration_date__gte=start_date_value
            )

        if end_date_value:
            ingredients = ingredients.filter(
                expiration_date__lte=end_date_value
            )

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
        {
            'ingredients': ingredients,
            'bakery': bakery,
            'query': query,
            'start_date': start_date,
            'end_date': end_date,
        },
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
        messages.info(
            request,
            'Set up the bakery profile before registering consumption.'
        )
        return redirect('bakery:setup')

    if request.method == 'POST':
        form = Stock_consumption_registration_form(
            request.POST,
            bakery=bakery,
        )

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
                form.add_error(
                    'quantity',
                    str(error),
                )

            else:
                messages.success(
                    request,
                    f'Consumption registered for {ingredient.name}.'
                )
                return redirect('inventory:list')

    else:
        form = Stock_consumption_registration_form(
            bakery=bakery
        )

    return render(
        request,
        'inventory/stock_consumption_form.html',
        {
            'form': form,
            'bakery': bakery,
        },
    )


def low_stock_threshold_configuration(request, ingredient_id):
    """FR10 - configure the low-stock threshold for an ingredient."""

    bakery = get_current_bakery()

    if bakery is None:
        messages.info(
            request,
            'Set up the bakery profile before configuring stock thresholds.'
        )
        return redirect('bakery:setup')

    ingredient = get_object_or_404(
        Ingredient,
        pk=ingredient_id,
        bakery=bakery,
        is_active=True,
    )

    try:
        configuration = ingredient.alert_configuration
        current_threshold = configuration.minimum_stock_threshold
    except AlertConfiguration.DoesNotExist:
        current_threshold = None

    if request.method == 'POST':
        form = LowStockThresholdConfigurationForm(request.POST)

        if form.is_valid():
            configure_low_stock_threshold(
                ingredient=ingredient,
                minimum_stock_threshold=form.cleaned_data[
                    'minimum_stock_threshold'
                ],
            )

            messages.success(
                request,
                'Low-stock threshold updated successfully.'
            )

            return redirect('inventory:list')

    else:
        form = LowStockThresholdConfigurationForm(
            initial={
                'minimum_stock_threshold': current_threshold,
            }
        )

    return render(
        request,
        'inventory/low_stock_threshold_configuration.html',
        {
            'form': form,
            'ingredient': ingredient,
            'bakery': bakery,
        },
    )
