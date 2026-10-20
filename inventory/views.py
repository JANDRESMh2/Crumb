from django.contrib import messages
import json
from decimal import Decimal
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.utils.dateparse import parse_date

from bakery.decorators import bakery_required
from bakery.services import get_current_bakery

from .forms import (
    BarcodeScanningForIngredientRegistrationForm,
    IngredientForm,
    IngredientImportForm,
    LowStockThresholdConfigurationForm,
    ManualInventoryCorrectionForm,
    StockConsumptionRegistrationForm,
    StockInForm,
)

from .models import AlertConfiguration, Ingredient, BarcodeIdentifier, StockMovement

from .services import (
    InsufficientStockError,
    InventoryCorrectionError,
    configure_low_stock_threshold,
    deactivate_ingredient,
    import_ingredients_from_excel,
    is_ingredient_expired,
    expiration_alerts,
    low_stock_alerts,
    register_ingredient,
    build_import_template,
    find_ingredient_by_barcode,
    register_inventory_correction,
    register_stock_in,
    register_stock_consumption,
    update_ingredient,
)


@bakery_required('Set up the bakery profile before registering ingredients.')
def ingredient_create(request):
    """FR01 - register a new ingredient (name, quantity, unit, expiration date).

    Also handles FR17 (optional barcode capture) via
    BarcodeScanningForIngredientRegistrationForm.
    """
    bakery = request.bakery

    if request.method == 'POST':
        form = BarcodeScanningForIngredientRegistrationForm(request.POST, bakery=bakery)
        if form.is_valid():
            register_ingredient(bakery=bakery, **form.cleaned_data)
            messages.success(request, 'Ingredient registered successfully.')
            return redirect('inventory:list')
    else:
        form = BarcodeScanningForIngredientRegistrationForm(bakery=bakery)

    return render(request, 'inventory/ingredient_form.html', {'form': form, 'bakery': bakery})
@bakery_required('Set up the bakery profile before editing ingredients.')
def ingredient_edit(request, ingredient_id):
    """FR03 - edit an existing ingredient."""
    bakery = request.bakery

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
@bakery_required('Set up the bakery profile before deleting ingredients.')
def ingredient_delete(request, ingredient_id):
    """FR04 - remove an existing ingredient from the active inventory."""
    bakery = request.bakery

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
def expiration_date_range_filter(
    *,
    ingredients,
    start_date,
    end_date,
):
    """FR24 - filter ingredients by expiration date range."""

    start_date_value = parse_date(start_date) if start_date else None
    end_date_value = parse_date(end_date) if end_date else None

    if (
        start_date_value
        and end_date_value
        and start_date_value > end_date_value
    ):
        return Ingredient.objects.none(), False

    if start_date_value:
        ingredients = ingredients.filter(
            expiration_date__gte=start_date_value
        )

    if end_date_value:
        ingredients = ingredients.filter(
            expiration_date__lte=end_date_value
        )

    return ingredients, True


def ingredient_list(request):
    """Display active inventory with alerts and name search (FR05/06/11/22)."""
    bakery = get_current_bakery()
    query = request.GET.get('q', '').strip()
    start_date = request.GET.get('start_date', '').strip()
    end_date = request.GET.get('end_date', '').strip()

    ingredients = (
        Ingredient.objects.filter(bakery=bakery, is_active=True)
        .select_related('unit', 'alert_configuration')
        .prefetch_related('barcodes')
        if bakery is not None
        else Ingredient.objects.none()
    )
    if query:
        ingredients = ingredients.filter(name__icontains=query)

    ingredients, valid_date_range = expiration_date_range_filter(
        ingredients=ingredients,
        start_date=start_date,
        end_date=end_date,
    )

    if not valid_date_range:
        messages.error(
            request,
            'The start date cannot be later than the end date.'
        )

    ingredients = list(ingredients)
    for ingredient in ingredients:
        ingredient.is_low_stock = low_stock_alerts(
            ingredient=ingredient,
        )
        ingredient.is_expiring_soon = expiration_alerts(
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


@bakery_required('Set up the bakery profile before registering stock.')
def stock_in_create(request):
    bakery = request.bakery

    if request.method == 'POST':
        form = StockInForm(request.POST, bakery=bakery)
        if form.is_valid():
            movement = form.save(commit=False)
            ingredient = movement.ingredient

            register_stock_in(
                bakery=bakery,
                ingredient=ingredient,
                quantity=movement.quantity,
                note=movement.note or '',
                user=request.user if request.user.is_authenticated else None,
            )
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
@bakery_required('Set up the bakery profile before registering consumption.')
def stock_consumption_registration(request):
    """FR08 - register the consumption of an ingredient."""

    bakery = request.bakery

    if request.method == 'POST':
        form = StockConsumptionRegistrationForm(
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
        form = StockConsumptionRegistrationForm(
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
@bakery_required('Set up the bakery profile before configuring stock thresholds.')
def low_stock_threshold_configuration(request, ingredient_id):
    """FR10 - configure the low-stock threshold for an ingredient."""

    bakery = request.bakery

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
@bakery_required('Set up the bakery profile before importing ingredients.')
def ingredient_import_view(request):
    """FR15 - bulk import ingredients from Excel or CSV file."""
    bakery = request.bakery

    if request.method == 'POST':
        form = IngredientImportForm(request.POST, request.FILES)
        if form.is_valid():
            file = form.cleaned_data['file']
            try:
                created, updated = import_ingredients_from_excel(file=file, bakery=bakery)
                messages.success(request, f'Successfully imported ingredients: {created} created, {updated} updated.')
                return redirect('inventory:list')
            except Exception as e:
                messages.error(request, f'Error importing file: {str(e)}')
    else:
        form = IngredientImportForm()

    return render(request, 'inventory/ingredient_import.html', {'form': form, 'bakery': bakery})
def download_import_template_view(request):
    """Provides an Excel template for FR15."""
    response = HttpResponse(
        build_import_template(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = 'attachment; filename="ingredients_template.xlsx"'
    return response


@require_POST
def stock_in_barcode_scan(request):
    """FR18 - Continuous barcode scanning for stock-in."""
    bakery = get_current_bakery()
    if bakery is None:
        return JsonResponse({'error': 'Set up the bakery profile before registering stock.'}, status=400)

    try:
        data = json.loads(request.body)
        barcode_value = data.get('barcode', '').strip()
        quantity_str = data.get('quantity', '1')
        quantity = Decimal(quantity_str)
        if quantity <= 0:
            return JsonResponse({'error': 'Quantity must be positive.'}, status=400)
    except (json.JSONDecodeError, TypeError, ValueError):
        return JsonResponse({'error': 'Invalid request format.'}, status=400)

    if not barcode_value:
        return JsonResponse({'error': 'No barcode provided.'}, status=400)

    ingredient = find_ingredient_by_barcode(bakery=bakery, barcode_value=barcode_value)

    if ingredient is None:
        return JsonResponse({
            'error': 'The scanned barcode is not registered. You must register the product as an ingredient first.'
        }, status=404)

    register_stock_in(
        bakery=bakery,
        ingredient=ingredient,
        quantity=quantity,
        note='Continuous scan',
        user=request.user if request.user.is_authenticated else None,
    )

    return JsonResponse({
        'success': True,
        'ingredient_name': ingredient.name,
        'unit': ingredient.unit.abbreviation,
        'added': str(quantity),
        'new_total': str(ingredient.current_quantity)
    })


# [FR23: Manual inventory correction]
@bakery_required('Set up the bakery profile before correcting the inventory.')
def manual_inventory_correction(request, ingredient_id):
    """FR23 - manually correct an ingredient's quantity with date, user and reason."""
    bakery = request.bakery

    ingredient = get_object_or_404(
        Ingredient.objects.select_related('unit'),
        pk=ingredient_id,
        bakery=bakery,
        is_active=True,
    )

    if request.method == 'POST':
        form = ManualInventoryCorrectionForm(request.POST, ingredient=ingredient)
        if form.is_valid():
            try:
                register_inventory_correction(
                    bakery=bakery,
                    ingredient=ingredient,
                    new_quantity=form.cleaned_data['new_quantity'],
                    reason=form.cleaned_data['reason'],
                    user=request.user if request.user.is_authenticated else None,
                )
            except InventoryCorrectionError as error:
                # The form already validates the input; this covers the stock
                # changing between rendering the form and saving it.
                form.add_error('new_quantity', str(error))
            else:
                messages.success(request, f'Inventory corrected for {ingredient.name}.')
                return redirect('inventory:list')
    else:
        form = ManualInventoryCorrectionForm(ingredient=ingredient)

    corrections = (
        StockMovement.objects.filter(ingredient=ingredient, movement_type='Correction')
        .select_related('user')
        .order_by('-movement_date')[:10]
    )

    return render(
        request,
        'inventory/manual_inventory_correction.html',
        {'form': form, 'ingredient': ingredient, 'bakery': bakery, 'corrections': corrections},
    )
