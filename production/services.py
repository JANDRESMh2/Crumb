from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.db.models.functions import TruncDate
from decimal import Decimal, ROUND_HALF_UP

from .models import Product, ProductionRecord, SalesRecord


def build_daily_unsold_products(*, bakery):
    """Calculate unsold quantity per product and local calendar day (FR14)."""
    production_totals = (
        ProductionRecord.objects
        .filter(bakery=bakery, status=ProductionRecord.Status.COMPLETED)
        .annotate(day=TruncDate('production_date'))
        .values('product_id', 'product__name', 'day')
        .annotate(quantity=Sum('produced_quantity'))
    )
    sales_totals = (
        SalesRecord.objects
        .filter(bakery=bakery)
        .annotate(day=TruncDate('sale_timestamp'))
        .values('product_id', 'product__name', 'day')
        .annotate(quantity=Sum('quantity_sold'))
    )

    totals = {}
    for row in production_totals:
        key = (row['product_id'], row['day'])
        totals[key] = {
            'product_name': row['product__name'],
            'date': row['day'],
            'produced_quantity': row['quantity'],
            'sold_quantity': Decimal('0'),
        }
    for row in sales_totals:
        key = (row['product_id'], row['day'])
        daily = totals.setdefault(key, {
            'product_name': row['product__name'],
            'date': row['day'],
            'produced_quantity': Decimal('0'),
            'sold_quantity': Decimal('0'),
        })
        daily['sold_quantity'] = row['quantity']

    results = []
    for daily in totals.values():
        daily['unsold_quantity'] = max(
            daily['produced_quantity'] - daily['sold_quantity'],
            Decimal('0'),
        )
        results.append(daily)
    return sorted(results, key=lambda daily: (-daily['date'].toordinal(), daily['product_name']))


@transaction.atomic
def register_product(
    *,
    bakery,
    name,
    unit_price,
    sku=None,
):
    """
    Register or reactivate a baked product.
    """

    name = name.strip()
    sku = sku.strip() if sku else None

    if not name:
        raise ValidationError(
            'The product name is required.'
        )

    existing_product = Product.objects.filter(
        bakery=bakery,
        name__iexact=name,
    ).first()

    if existing_product is not None:

        if existing_product.status == Product.Status.ACTIVE:
            raise ValidationError(
                'This product is already registered.'
            )

        existing_product.name = name
        existing_product.sku = sku
        existing_product.unit_price = unit_price
        existing_product.status = Product.Status.ACTIVE

        existing_product.full_clean()

        existing_product.save(
            update_fields=[
                'name',
                'sku',
                'unit_price',
                'status',
                'updated_at',
            ]
        )

        return existing_product

    product = Product(
        bakery=bakery,
        name=name,
        sku=sku,
        unit_price=unit_price,
    )

    product.full_clean()
    product.save()

    return product


@transaction.atomic
def register_daily_production(
    *,
    bakery,
    product,
    produced_quantity,
    production_date,
):
    """
    FR12 - Register daily production.
    """

    if product.bakery_id != bakery.pk:
        raise ValidationError(
            'The selected product does not belong '
            'to this bakery.'
        )

    if product.status != Product.Status.ACTIVE:
        raise ValidationError(
            'Inactive products cannot be used '
            'for production registration.'
        )

    record = ProductionRecord(
        bakery=bakery,
        product=product,
        produced_quantity=produced_quantity,
        production_date=production_date,
        status=ProductionRecord.Status.COMPLETED,
    )

    record.full_clean()
    record.save()

    return record


@transaction.atomic
def register_daily_sale(
    *,
    bakery,
    product,
    quantity_sold,
    sale_timestamp,
    user=None,
):
    """
    FR13 - Register the daily sale of a baked product.

    The product price is stored as a historical snapshot so later
    price changes do not modify previous sales.
    """

    if product.bakery_id != bakery.pk:
        raise ValidationError(
            'The selected product does not belong '
            'to this bakery.'
        )

    if product.status != Product.Status.ACTIVE:
        raise ValidationError(
            'Inactive products cannot be used '
            'for sales registration.'
        )

    if product.unit_price is None:
        raise ValidationError(
            'The selected product does not have '
            'a unit price configured.'
        )

    unit_price_at_sale = product.unit_price.quantize(
        Decimal('0.01'),
        rounding=ROUND_HALF_UP,
    )

    total_amount = (
        quantity_sold * unit_price_at_sale
    ).quantize(
        Decimal('0.01'),
        rounding=ROUND_HALF_UP,
    )

    record = SalesRecord(
        bakery=bakery,
        product=product,
        user=user,
        quantity_sold=quantity_sold,
        unit_price_at_sale=unit_price_at_sale,
        total_amount=total_amount,
        sale_timestamp=sale_timestamp,
    )

    record.full_clean()
    record.save()

    return record

HISTORY_RECORD_TYPES = ('all', 'production', 'sales')


def build_history_tracking(
    *,
    bakery,
    record_type='all',
    product=None,
    start_date=None,
    end_date=None,
):
    """
    FR25 - Build the combined history of production and sales records.

    Returns the entries newest first, each one tagged with its kind, plus
    the totals of the filtered entries.
    """

    if record_type not in HISTORY_RECORD_TYPES:
        raise ValidationError('Unknown record type.')

    if start_date and end_date and start_date > end_date:
        raise ValidationError(
            'The start date cannot be later than the end date.'
        )

    entries = []

    if record_type in ('all', 'production'):
        production = (
            ProductionRecord.objects
            .filter(bakery=bakery)
            .select_related('product', 'user')
        )
        if product is not None:
            production = production.filter(product=product)
        if start_date:
            production = production.filter(
                production_date__date__gte=start_date
            )
        if end_date:
            production = production.filter(
                production_date__date__lte=end_date
            )

        entries.extend(
            {
                'kind': 'production',
                'date': record.production_date,
                'product': record.product,
                'quantity': record.produced_quantity,
                'total_amount': None,
                'status': record.get_status_display(),
                'user': record.user,
                'record': record,
            }
            for record in production
        )

    if record_type in ('all', 'sales'):
        sales = (
            SalesRecord.objects
            .filter(bakery=bakery)
            .select_related('product', 'user')
        )
        if product is not None:
            sales = sales.filter(product=product)
        if start_date:
            sales = sales.filter(sale_timestamp__date__gte=start_date)
        if end_date:
            sales = sales.filter(sale_timestamp__date__lte=end_date)

        entries.extend(
            {
                'kind': 'sale',
                'date': record.sale_timestamp,
                'product': record.product,
                'quantity': record.quantity_sold,
                'total_amount': record.total_amount,
                'status': None,
                'user': record.user,
                'record': record,
            }
            for record in sales
        )

    entries.sort(key=lambda entry: entry['date'], reverse=True)

    totals = {
        'produced_quantity': sum(
            (
                entry['quantity']
                for entry in entries
                if entry['kind'] == 'production'
                and entry['record'].status
                == ProductionRecord.Status.COMPLETED
            ),
            Decimal('0'),
        ),
        'sold_quantity': sum(
            (
                entry['quantity']
                for entry in entries
                if entry['kind'] == 'sale'
            ),
            Decimal('0'),
        ),
        'sales_amount': sum(
            (
                entry['total_amount']
                for entry in entries
                if entry['kind'] == 'sale'
            ),
            Decimal('0'),
        ),
    }

    return entries, totals
