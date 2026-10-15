import uuid

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)
from django.utils import timezone
from django.utils.dateparse import parse_date

from bakery.services import get_current_bakery

from .forms import (
    DailyProductionRegistrationForm,
    DailySalesRegistrationForm,
    ProductEditForm,
    ProductForm,
)
from .models import Product, ProductionRecord, SalesRecord
from .services import (
    HISTORY_RECORD_TYPES,
    build_daily_unsold_products,
    build_history_tracking,
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
            'daily_unsold_products': build_daily_unsold_products(bakery=bakery),
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

def history_tracking(request):
    """FR25 - view the history of production and sales records."""

    bakery = get_current_bakery()

    if bakery is None:
        return redirect('bakery:setup')

    record_type = request.GET.get('type', 'all').strip()
    product_id = request.GET.get('product', '').strip()
    start_date = request.GET.get('start_date', '').strip()
    end_date = request.GET.get('end_date', '').strip()

    if record_type not in HISTORY_RECORD_TYPES:
        record_type = 'all'

    products = Product.objects.filter(bakery=bakery).order_by('name')

    product = None
    if product_id and _is_uuid(product_id):
        product = products.filter(pk=product_id).first()
    if product is None:
        product_id = ''

    try:
        entries, totals = build_history_tracking(
            bakery=bakery,
            record_type=record_type,
            product=product,
            start_date=parse_date(start_date) if start_date else None,
            end_date=parse_date(end_date) if end_date else None,
        )
    except (ValidationError, ValueError) as error:
        messages.error(
            request,
            ' '.join(getattr(error, 'messages', ['Invalid date.'])),
        )
        entries, totals = [], None

    return render(
        request,
        'production/history_tracking.html',
        {
            'bakery': bakery,
            'entries': entries,
            'totals': totals,
            'products': products,
            'record_type': record_type,
            'product_id': product_id,
            'start_date': start_date,
            'end_date': end_date,
            'has_filters': bool(
                record_type != 'all'
                or product_id
                or start_date
                or end_date
            ),
        },
    )


def _is_uuid(value):
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True
