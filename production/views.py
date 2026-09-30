from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)
from django.utils import timezone

from bakery.services import get_current_bakery

from .forms import (
    DailyProductionRegistrationForm,
    DailySalesRegistrationForm,
    ProductEditForm,
    ProductForm,
)
from .models import Product, ProductionRecord, SalesRecord
from .services import (
    register_daily_production,
    register_daily_sale,
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
                    **form.cleaned_data,
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
                status=Product.Status.ACTIVE,
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


def daily_sales_registration(request):
    """FR13 - register daily sales."""

    bakery = get_current_bakery()

    if bakery is None:
        messages.info(
            request,
            'Set up the bakery profile before registering sales.'
        )
        return redirect('bakery:setup')

    if request.method == 'POST':
        form = DailySalesRegistrationForm(
            request.POST,
            bakery=bakery,
        )

        if form.is_valid():
            try:
                register_daily_sale(
                    bakery=bakery,
                    **form.cleaned_data,
                )
            except ValidationError as error:
                form.add_error(
                    None,
                    ValidationError(error.messages),
                )
            else:
                messages.success(
                    request,
                    'Daily sale registered successfully.',
                )

                return redirect(
                    'production:sales_list'
                )

    else:
        form = DailySalesRegistrationForm(
            bakery=bakery,
            initial={
                'sale_timestamp': timezone.localtime(),
            },
        )

    return render(
        request,
        'production/sales_form.html',
        {
            'form': form,
            'bakery': bakery,
            'has_products': Product.objects.filter(
                bakery=bakery,
                status=Product.Status.ACTIVE,
            ).exists(),
        },
    )


def sales_list(request):
    """Display sales registered by the bakery."""

    bakery = get_current_bakery()

    if bakery is None:
        return redirect('bakery:setup')

    records = (
        SalesRecord.objects
        .filter(bakery=bakery)
        .select_related('product')
    )

    return render(
        request,
        'production/sales_list.html',
        {
            'records': records,
            'bakery': bakery,
        },
    )


def product_list(request):
    """Display the bakery product catalog."""

    bakery = get_current_bakery()

    if bakery is None:
        return redirect('bakery:setup')

    products = Product.objects.filter(
        bakery=bakery,
    ).order_by('name')

    return render(
        request,
        'production/product_list.html',
        {
            'products': products,
            'bakery': bakery,
        },
    )


def product_edit(request, product_id):
    """Edit an existing baked product."""

    bakery = get_current_bakery()

    if bakery is None:
        return redirect('bakery:setup')

    product = get_object_or_404(
        Product,
        pk=product_id,
        bakery=bakery,
    )

    if request.method == 'POST':
        form = ProductEditForm(
            request.POST,
            instance=product,
            bakery=bakery,
        )

        if form.is_valid():
            form.save()

            messages.success(
                request,
                'Product updated successfully.',
            )

            return redirect(
                'production:product_list'
            )

    else:
        form = ProductEditForm(
            instance=product,
            bakery=bakery,
        )

    return render(
        request,
        'production/product_edit.html',
        {
            'form': form,
            'product': product,
            'bakery': bakery,
        },
    )