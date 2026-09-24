from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render

from bakery.services import get_current_bakery

from .forms import (
    DailyProductionRegistrationForm,
    ProductForm,
)
from .models import Product, ProductionRecord
from .services import (
    register_daily_production,
    register_product,
)


def product_create(request):
    """Register a baked product in the bakery catalog."""

    bakery = get_current_bakery()

    if bakery is None:
        messages.info(
            request,
            'Set up the bakery profile before registering products.'
        )
        return redirect('bakery:setup')

    if request.method == 'POST':
        form = ProductForm(request.POST, bakery=bakery)

        if form.is_valid():
            try:
                register_product(
                    bakery=bakery,
                    name=form.cleaned_data['name'],
                )
            except ValidationError as error:
                form.add_error('name', error)
            else:
                messages.success(
                    request,
                    'Product registered successfully.',
                )
                return redirect('production:register')

    else:
        form = ProductForm(bakery=bakery)

    return render(
        request,
        'production/product_form.html',
        {
            'form': form,
            'bakery': bakery,
        },
    )


def daily_production_registration(request):
    """FR12 - register daily production."""

    bakery = get_current_bakery()

    if bakery is None:
        messages.info(
            request,
            'Set up the bakery profile before registering production.'
        )
        return redirect('bakery:setup')

    if request.method == 'POST':
        form = DailyProductionRegistrationForm(
            request.POST,
            bakery=bakery,
        )

        if form.is_valid():
            try:
                register_daily_production(
                    bakery=bakery,
                    **form.cleaned_data,
                )
            except ValidationError as error:
                form.add_error(None, error)
            else:
                messages.success(
                    request,
                    'Daily production registered successfully.',
                )
                return redirect('production:list')

    else:
        form = DailyProductionRegistrationForm(
            bakery=bakery,
        )

    return render(
        request,
        'production/production_form.html',
        {
            'form': form,
            'bakery': bakery,
            'has_products': Product.objects.filter(
                bakery=bakery,
                is_active=True,
            ).exists(),
        },
    )


def production_list(request):
    """Display the production records registered by the bakery."""

    bakery = get_current_bakery()

    if bakery is None:
        return redirect('bakery:setup')

    records = (
        ProductionRecord.objects
        .filter(bakery=bakery)
        .select_related('product')
    )

    return render(
        request,
        'production/production_list.html',
        {
            'records': records,
            'bakery': bakery,
        },
    )