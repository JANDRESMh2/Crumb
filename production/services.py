from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from decimal import Decimal, ROUND_HALF_UP

from bakery.models import ActivityLog
from bakery.services import record_activity

from inventory.services import build_expired_ingredient_losses

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
            'product_id': row['product_id'],
            'product_name': row['product__name'],
            'date': row['day'],
            'produced_quantity': row['quantity'],
            'sold_quantity': Decimal('0'),
        }
    for row in sales_totals:
        key = (row['product_id'], row['day'])
        daily = totals.setdefault(key, {
            'product_id': row['product_id'],
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

    record_activity(
        user=user,
        action_type=ActivityLog.ActionType.SALE,
        description=(
            f'Registered the sale of {quantity_sold} {product.name} '
            f'for {total_amount}.'
        ),
    )

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


def build_sales_analytics(*, bakery, start_date=None, end_date=None):
    """
    FR36 - Rank the products of a bakery by how much they sell.

    Every product that was sold at least once inside the date range gets a
    row, ordered from the best seller down. Alongside the units sold each row
    carries the revenue it brought in and the share of the total revenue that
    represents, so the baker can tell apart what sells often from what sells
    for the most money.
    """

    if start_date and end_date and start_date > end_date:
        raise ValidationError(
            'The start date cannot be later than the end date.'
        )

    sales = SalesRecord.objects.filter(bakery=bakery)

    if start_date:
        sales = sales.filter(sale_timestamp__date__gte=start_date)
    if end_date:
        sales = sales.filter(sale_timestamp__date__lte=end_date)

    rows = list(
        sales
        .values('product_id', 'product__name')
        .annotate(
            units_sold=Sum('quantity_sold'),
            revenue=Sum('total_amount'),
            sale_count=Count('id'),
        )
        .order_by('-units_sold', 'product__name')
    )

    total_units = sum(
        (row['units_sold'] for row in rows),
        Decimal('0'),
    )
    total_revenue = sum(
        (row['revenue'] for row in rows),
        Decimal('0'),
    )

    best_units = rows[0]['units_sold'] if rows else Decimal('0')

    rankings = []

    for position, row in enumerate(rows, start=1):
        revenue = row['revenue']

        revenue_share = (
            (revenue / total_revenue * 100).quantize(
                Decimal('0.1'),
                rounding=ROUND_HALF_UP,
            )
            if total_revenue
            else Decimal('0.0')
        )

        units_share = (
            (row['units_sold'] / best_units * 100).quantize(
                Decimal('0.1'),
                rounding=ROUND_HALF_UP,
            )
            if best_units
            else Decimal('0.0')
        )

        rankings.append({
            'position': position,
            'product_id': row['product_id'],
            'product_name': row['product__name'],
            'units_sold': row['units_sold'],
            'revenue': revenue,
            'sale_count': row['sale_count'],
            'revenue_share': revenue_share,
            'units_share': units_share,
        })

    totals = {
        'units_sold': total_units,
        'revenue': total_revenue,
        'product_count': len(rankings),
        'sale_count': sum(row['sale_count'] for row in rows),
    }

    return rankings, totals


def build_loss_report(*, bakery, start_date=None, end_date=None):
    """
    FR26 - Report what the bakery lost, from its two sources.

    The first source is the inventory: ingredients that expired with stock
    still on hand (FR06 decides what counts as expired). The second is
    production: the products that were baked and never sold, which FR14
    already works out per product and day. Overproduction is also valued in
    money, using the current price of the product, because that is what the
    bakery stopped earning.

    Expired ingredients are not valued, since the inventory does not record
    what each ingredient costs.
    """

    if start_date and end_date and start_date > end_date:
        raise ValidationError(
            'The start date cannot be later than the end date.'
        )

    expired_ingredients = build_expired_ingredient_losses(
        bakery=bakery,
        start_date=start_date,
        end_date=end_date,
    )

    unit_prices = dict(
        Product.objects
        .filter(bakery=bakery)
        .values_list('pk', 'unit_price')
    )

    overproduction = []

    for daily in build_daily_unsold_products(bakery=bakery):
        if daily['unsold_quantity'] <= 0:
            continue
        if start_date and daily['date'] < start_date:
            continue
        if end_date and daily['date'] > end_date:
            continue

        unit_price = unit_prices.get(daily['product_id']) or Decimal('0')

        overproduction.append({
            'product_id': daily['product_id'],
            'product_name': daily['product_name'],
            'date': daily['date'],
            'produced_quantity': daily['produced_quantity'],
            'sold_quantity': daily['sold_quantity'],
            'unsold_quantity': daily['unsold_quantity'],
            'unit_price': unit_price,
            'lost_value': (
                daily['unsold_quantity'] * unit_price
            ).quantize(
                Decimal('0.01'),
                rounding=ROUND_HALF_UP,
            ),
        })

    totals = {
        'expired_ingredient_count': len(expired_ingredients),
        'expired_quantity': sum(
            (row['quantity'] for row in expired_ingredients),
            Decimal('0'),
        ),
        'overproduction_days': len(overproduction),
        'unsold_quantity': sum(
            (row['unsold_quantity'] for row in overproduction),
            Decimal('0'),
        ),
        'lost_value': sum(
            (row['lost_value'] for row in overproduction),
            Decimal('0'),
        ),
    }

    return {
        'expired_ingredients': expired_ingredients,
        'overproduction': overproduction,
        'totals': totals,
    }
