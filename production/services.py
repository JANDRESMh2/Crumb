import datetime
import io
import uuid
from datetime import timedelta
from xml.sax.saxutils import escape

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone
from django.utils.translation import gettext, gettext_lazy as _
from decimal import Decimal, ROUND_HALF_UP
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Alignment, Font, PatternFill
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle

from bakery.exports import register_report_fonts, spreadsheet_text
from bakery.models import ActivityLog
from bakery.services import record_activity

from inventory.models import NotificationPreference, StockMovement
from inventory.services import (
    build_expired_ingredient_losses,
    expiration_alerts,
    filter_inventory_ingredients,
    is_ingredient_expired,
    low_stock_alerts,
)

from .models import DailyClosingSummary, Product, ProductionRecord, SalesRecord
from .models import ScheduledOrder


@transaction.atomic
def register_scheduled_order(*, bakery, customer_name, product, quantity, scheduled_for, notes=''):
    """FR34 - save a future order for an active product in this bakery."""
    if product.bakery_id != bakery.pk or product.status != Product.Status.ACTIVE:
        raise ValidationError('Choose an active product from this bakery.')
    if quantity <= 0:
        raise ValidationError('Order quantity must be greater than zero.')
    return ScheduledOrder.objects.create(
        bakery=bakery,
        customer_name=customer_name,
        product=product,
        quantity=quantity,
        scheduled_for=scheduled_for,
        notes=notes,
    )


def build_daily_unsold_products(*, bakery, day=None):
    """Calculate unsold quantity per product and local calendar day (FR14).

    ``day`` narrows the calculation to a single date, which is what the daily
    closing (FR27) needs; without it every day on record is returned.
    """
    production = ProductionRecord.objects.filter(
        bakery=bakery, status=ProductionRecord.Status.COMPLETED,
    )
    sales = SalesRecord.objects.filter(bakery=bakery)
    if day is not None:
        production = production.filter(production_date__date=day)
        sales = sales.filter(sale_timestamp__date=day)

    production_totals = (
        production
        .annotate(day=TruncDate('production_date'))
        .values('product_id', 'product__name', 'day')
        .annotate(quantity=Sum('produced_quantity'))
    )
    sales_totals = (
        sales
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
            _('The product name is required.')
        )

    existing_product = Product.objects.filter(
        bakery=bakery,
        name__iexact=name,
    ).first()

    if existing_product is not None:

        if existing_product.status == Product.Status.ACTIVE:
            raise ValidationError(
                _('This product is already registered.')
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
            _('The selected product does not belong '
              'to this bakery.')
        )

    if product.status != Product.Status.ACTIVE:
        raise ValidationError(
            _('Inactive products cannot be used '
              'for production registration.')
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
            _('The selected product does not belong '
              'to this bakery.')
        )

    if product.status != Product.Status.ACTIVE:
        raise ValidationError(
            _('Inactive products cannot be used '
              'for sales registration.')
        )

    if product.unit_price is None:
        raise ValidationError(
            _('The selected product does not have '
              'a unit price configured.')
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
        description=gettext(
            'Registered the sale of %(quantity)s %(name)s for %(amount)s.'
        ) % {
            'quantity': quantity_sold,
            'name': product.name,
            'amount': total_amount,
        },
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
        raise ValidationError(_('Unknown record type.'))

    if start_date and end_date and start_date > end_date:
        raise ValidationError(
            _('The start date cannot be later than the end date.')
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
            _('The start date cannot be later than the end date.')
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
        # la suma de las participaciones, para el pie de la tabla
        'revenue_share': sum(
            (row['revenue_share'] for row in rankings),
            Decimal('0.0'),
        ),
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
            _('The start date cannot be later than the end date.')
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


# [FR27: Automatic daily closing summary]

MONEY = Decimal('0.01')


def _json_ready(value):
    """Turn a summary built from model values into plain JSON data.

    Decimals become strings with two places, so no cent is lost on the way
    to the database and SQLite sums such as ``20`` still read ``20.00``.
    Dates become ISO strings, which read the same in both languages.
    """
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, Decimal):
        return str(value.quantize(MONEY, rounding=ROUND_HALF_UP))
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def _closing_sales(*, bakery, business_date):
    """Production, sales and unsold quantity of each product on the day."""
    daily = build_daily_unsold_products(bakery=bakery, day=business_date)
    revenue_by_product = {
        row['product_id']: row
        for row in (
            SalesRecord.objects
            .filter(bakery=bakery, sale_timestamp__date=business_date)
            .values('product_id')
            .annotate(revenue=Sum('total_amount'), sale_count=Count('id'))
        )
    }

    products = []
    for daily_product in sorted(daily, key=lambda row: row['product_name']):
        sales = revenue_by_product.get(daily_product['product_id'], {})
        products.append({
            'product_id': daily_product['product_id'],
            'product_name': daily_product['product_name'],
            'produced_quantity': daily_product['produced_quantity'],
            'sold_quantity': daily_product['sold_quantity'],
            'unsold_quantity': daily_product['unsold_quantity'],
            'sale_count': sales.get('sale_count', 0),
            'revenue': sales.get('revenue') or Decimal('0.00'),
        })
    return products


def _closing_stock(*, bakery, business_date):
    """Stock movements of the day, per ingredient, plus every correction."""
    movements = StockMovement.objects.filter(
        bakery=bakery, movement_date__date=business_date,
    )
    per_ingredient = (
        movements
        .values('ingredient_id', 'ingredient__name', 'ingredient__unit__abbreviation')
        .annotate(
            stock_in=Sum('quantity', filter=Q(movement_type='StockIn'), default=Decimal('0')),
            consumption=Sum('quantity', filter=Q(movement_type='Consumption'), default=Decimal('0')),
            correction_count=Count('movement_id', filter=Q(movement_type='Correction')),
            movement_count=Count('movement_id'),
        )
        .order_by('ingredient__name')
    )
    corrections = (
        movements
        .filter(movement_type='Correction')
        .select_related('ingredient__unit', 'user')
        .order_by('movement_date')
    )
    return {
        'ingredients': [
            {
                'ingredient_name': row['ingredient__name'],
                'unit': row['ingredient__unit__abbreviation'],
                'stock_in': row['stock_in'],
                'consumption': row['consumption'],
                'correction_count': row['correction_count'],
                'movement_count': row['movement_count'],
            }
            for row in per_ingredient
        ],
        'corrections': [
            {
                'time': timezone.localtime(movement.movement_date).strftime('%H:%M'),
                'ingredient_name': movement.ingredient.name,
                'unit': movement.ingredient.unit.abbreviation,
                'previous_quantity': movement.previous_quantity,
                'new_quantity': movement.new_quantity,
                'reason': movement.note or '',
                'user': movement.user.get_username() if movement.user else '',
            }
            for movement in corrections
        ],
    }


def _closing_alerts(*, bakery, today):
    """Inventory alerts as they stand when the day is closed (FR06, FR11, FR29).

    The inventory keeps no history of its alerts, so they are evaluated at the
    moment of closing, honouring the alerts the bakery has turned off.
    """
    try:
        preferences = bakery.notification_preferences
    except NotificationPreference.DoesNotExist:
        preferences = None
    low_stock_enabled = preferences.low_stock_enabled if preferences else True
    expiration_enabled = preferences.expiration_enabled if preferences else True

    # Without a date range the filter cannot be invalid, so only the rows matter.
    ingredients = filter_inventory_ingredients(bakery=bakery)[0]

    low_stock, expiring_soon, expired = [], [], []
    for ingredient in ingredients:
        row = {
            'ingredient_name': ingredient.name,
            'quantity': ingredient.current_quantity,
            'unit': ingredient.unit.abbreviation,
            'expiration_date': ingredient.expiration_date,
        }
        if low_stock_enabled and low_stock_alerts(ingredient=ingredient):
            low_stock.append({
                **row,
                'threshold': ingredient.alert_configuration.minimum_stock_threshold,
            })
        if expiration_enabled and is_ingredient_expired(ingredient=ingredient, today=today):
            expired.append(row)
        elif expiration_enabled and expiration_alerts(ingredient=ingredient, today=today):
            expiring_soon.append(row)

    return {
        'evaluated_on': today,
        'low_stock_enabled': low_stock_enabled,
        'expiration_enabled': expiration_enabled,
        'low_stock': low_stock,
        'expiring_soon': expiring_soon,
        'expired': expired,
    }


def _closing_losses(*, bakery, business_date, products):
    """What the day lost: unsold products and ingredients whose life ended.

    Overproduction is valued at the current product price, as FR26 does. An
    ingredient counts when its expiration date is the closed day and it still
    holds stock, because from the next morning it can no longer be used.
    """
    unsold = [row for row in products if row['unsold_quantity'] > 0]
    unit_prices = dict(
        Product.objects
        .filter(pk__in=[row['product_id'] for row in unsold])
        .values_list('pk', 'unit_price')
    )

    overproduction = []
    for row in unsold:
        unit_price = unit_prices.get(row['product_id']) or Decimal('0')
        overproduction.append({
            'product_name': row['product_name'],
            'unsold_quantity': row['unsold_quantity'],
            'unit_price': unit_price,
            'lost_value': (row['unsold_quantity'] * unit_price).quantize(
                MONEY, rounding=ROUND_HALF_UP,
            ),
        })

    expired_ingredients = [
        {
            'ingredient_name': row['ingredient_name'],
            'quantity': row['quantity'],
            'unit': row['unit_abbreviation'],
            'expiration_date': row['expiration_date'],
        }
        for row in build_expired_ingredient_losses(
            bakery=bakery,
            start_date=business_date,
            end_date=business_date,
            today=business_date + timedelta(days=1),
        )
    ]

    return {
        'overproduction': overproduction,
        'expired_ingredients': expired_ingredients,
    }


def _closing_next_day_orders(*, bakery, business_date):
    """Scheduled orders the bakery has to prepare the following day (FR34)."""
    orders = (
        ScheduledOrder.objects
        .filter(bakery=bakery, scheduled_for__date=business_date + timedelta(days=1))
        .select_related('product')
        .order_by('scheduled_for', 'created_at')
    )
    return [
        {
            'time': timezone.localtime(order.scheduled_for).strftime('%H:%M'),
            'customer_name': order.customer_name,
            'product_name': order.product.name,
            'quantity': order.quantity,
            'notes': order.notes,
        }
        for order in orders
    ]


def build_daily_closing_summary(*, bakery, business_date, now=None):
    """FR27 - build the closing summary of one business day.

    Gathers four blocks: production and sales, stock movements, the inventory
    alerts at closing time, and the day's losses together with the orders
    scheduled for the next day. The result is plain JSON data, ready to be
    stored as the day's snapshot.
    """
    now = now or timezone.now()
    today = timezone.localdate(now)

    products = _closing_sales(bakery=bakery, business_date=business_date)
    stock = _closing_stock(bakery=bakery, business_date=business_date)
    alerts = _closing_alerts(bakery=bakery, today=today)
    losses = _closing_losses(
        bakery=bakery, business_date=business_date, products=products,
    )
    next_day_orders = _closing_next_day_orders(
        bakery=bakery, business_date=business_date,
    )

    totals = {
        'units_produced': sum((row['produced_quantity'] for row in products), Decimal('0')),
        'units_sold': sum((row['sold_quantity'] for row in products), Decimal('0')),
        'unsold_quantity': sum((row['unsold_quantity'] for row in products), Decimal('0')),
        'revenue': sum((row['revenue'] for row in products), Decimal('0.00')),
        'sale_count': sum(row['sale_count'] for row in products),
        'movement_count': sum(row['movement_count'] for row in stock['ingredients']),
        'alert_count': (
            len(alerts['low_stock']) + len(alerts['expiring_soon']) + len(alerts['expired'])
        ),
        'lost_value': sum(
            (row['lost_value'] for row in losses['overproduction']), Decimal('0.00'),
        ),
        'expired_ingredient_count': len(losses['expired_ingredients']),
        'next_day_order_count': len(next_day_orders),
    }

    for row in products:
        del row['product_id']

    return _json_ready({
        'business_date': business_date,
        'generated_at': timezone.localtime(now).strftime('%Y-%m-%d %H:%M'),
        'products': products,
        'stock': stock,
        'alerts': alerts,
        'losses': losses,
        'next_day_orders': next_day_orders,
        'totals': totals,
    })


@transaction.atomic
def close_business_day(*, bakery, business_date, user=None):
    """FR27 - close a business day and store its summary.

    A day can be closed once it has started; closing it again replaces the
    stored snapshot with the current data. Returns the summary and whether it
    was created (``True``) or regenerated (``False``).
    """
    now = timezone.now()

    if business_date is None:
        raise ValidationError(_('Choose the day to close.'))
    if business_date > timezone.localdate(now):
        raise ValidationError(_('A day that has not started yet cannot be closed.'))

    if user is not None and not getattr(user, 'is_authenticated', False):
        user = None

    content = build_daily_closing_summary(
        bakery=bakery, business_date=business_date, now=now,
    )
    totals = content['totals']

    closing, created = DailyClosingSummary.objects.update_or_create(
        bakery=bakery,
        business_date=business_date,
        defaults={
            'closed_by': user,
            'closed_at': now,
            'content': content,
            'units_produced': Decimal(totals['units_produced']),
            'units_sold': Decimal(totals['units_sold']),
            'revenue': Decimal(totals['revenue']),
            'lost_value': Decimal(totals['lost_value']),
        },
    )

    description = (
        gettext('Closed the business day %(date)s.')
        if created
        else gettext('Regenerated the closing summary of %(date)s.')
    )
    record_activity(
        user=user,
        action_type=ActivityLog.ActionType.DAILY_CLOSING,
        description=description % {'date': business_date.isoformat()},
    )

    return closing, created


def _closing_report_sections(content):
    """The tables shared by the XLSX and PDF versions of a closing summary.

    Each section is ``(title, headers, rows, numeric_columns, empty_message)``.
    Rows hold the stored snapshot values; numeric columns are the positions
    the spreadsheet writes as numbers instead of text.
    """
    totals = content['totals']
    alerts = content['alerts']
    stock = content['stock']
    losses = content['losses']

    product_rows = [
        [
            row['product_name'], row['produced_quantity'], row['sold_quantity'],
            row['unsold_quantity'], row['sale_count'], row['revenue'],
        ]
        for row in content['products']
    ]
    if product_rows:
        product_rows.append([
            gettext('Total'), totals['units_produced'], totals['units_sold'],
            totals['unsold_quantity'], totals['sale_count'], totals['revenue'],
        ])

    overproduction_rows = [
        [row['product_name'], row['unsold_quantity'], row['unit_price'], row['lost_value']]
        for row in losses['overproduction']
    ]
    if overproduction_rows:
        overproduction_rows.append([
            gettext('Total'), totals['unsold_quantity'], '', totals['lost_value'],
        ])

    def ingredient_rows(rows, extra):
        return [
            [row['ingredient_name'], row['quantity'], row['unit'], row[extra] or '']
            for row in rows
        ]

    low_stock_off = gettext('Low-stock alerts are turned off in the notification preferences.')
    expiration_off = gettext('Expiration alerts are turned off in the notification preferences.')

    return [
        (
            gettext('Production and sales'),
            [gettext('Product'), gettext('Produced'), gettext('Sold'), gettext('Unsold'),
             gettext('Sales'), gettext('Revenue')],
            product_rows, {1, 2, 3, 4, 5},
            gettext('Nothing was produced or sold on this day.'),
        ),
        (
            gettext('Stock movements'),
            [gettext('Ingredient'), gettext('Unit'), gettext('Stock-in'),
             gettext('Consumption'), gettext('Corrections')],
            [
                [row['ingredient_name'], row['unit'], row['stock_in'],
                 row['consumption'], row['correction_count']]
                for row in stock['ingredients']
            ],
            {2, 3, 4},
            gettext('No stock movement was registered on this day.'),
        ),
        (
            gettext('Inventory corrections'),
            [gettext('Time'), gettext('Ingredient'), gettext('Before'), gettext('After'),
             gettext('Unit'), gettext('Reason'), gettext('User')],
            [
                [row['time'], row['ingredient_name'], row['previous_quantity'],
                 row['new_quantity'], row['unit'], row['reason'], row['user']]
                for row in stock['corrections']
            ],
            {2, 3},
            gettext('No inventory correction was made on this day.'),
        ),
        (
            gettext('Low stock'),
            [gettext('Ingredient'), gettext('Quantity'), gettext('Unit'), gettext('Threshold')],
            ingredient_rows(alerts['low_stock'], 'threshold'),
            {1, 3},
            gettext('No ingredient is below its low-stock threshold.')
            if alerts['low_stock_enabled'] else low_stock_off,
        ),
        (
            gettext('Expiring soon'),
            [gettext('Ingredient'), gettext('Quantity'), gettext('Unit'), gettext('Expires')],
            ingredient_rows(alerts['expiring_soon'], 'expiration_date'),
            {1},
            gettext('No ingredient is about to expire.')
            if alerts['expiration_enabled'] else expiration_off,
        ),
        (
            gettext('Expired'),
            [gettext('Ingredient'), gettext('Quantity'), gettext('Unit'), gettext('Expired on')],
            ingredient_rows(alerts['expired'], 'expiration_date'),
            {1},
            gettext('No ingredient in the inventory has expired.')
            if alerts['expiration_enabled'] else expiration_off,
        ),
        (
            gettext('Overproduction'),
            [gettext('Product'), gettext('Unsold'), gettext('Unit price'),
             gettext('Value not earned')],
            overproduction_rows, {1, 2, 3},
            gettext('Every product produced on this day was sold.'),
        ),
        (
            gettext('Ingredients that expired at closing'),
            [gettext('Ingredient'), gettext('Quantity'), gettext('Unit'), gettext('Expired on')],
            ingredient_rows(losses['expired_ingredients'], 'expiration_date'),
            {1},
            gettext('No ingredient with stock left expired on this day.'),
        ),
        (
            gettext('Orders for the next day'),
            [gettext('Time'), gettext('Customer'), gettext('Product'), gettext('Quantity'),
             gettext('Notes')],
            [
                [row['time'], row['customer_name'], row['product_name'],
                 row['quantity'], row['notes']]
                for row in content['next_day_orders']
            ],
            {3},
            gettext('No order is scheduled for the next day.'),
        ),
    ]


def _closing_report_header(closing):
    closed_by = closing.closed_by.get_username() if closing.closed_by else '—'
    return [
        (gettext('Bakery'), closing.bakery.name),
        (gettext('Business day'), closing.business_date.isoformat()),
        (gettext('Generated at'), closing.content['generated_at']),
        (gettext('Closed by'), closed_by),
    ]


def build_daily_closing_excel(*, closing):
    """FR27 - render a stored closing summary as an XLSX document."""
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet(gettext('Daily closing')[:31])
    for column, width in {
        'A': 34, 'B': 26, 'C': 16, 'D': 16, 'E': 16, 'F': 30, 'G': 20,
    }.items():
        sheet.column_dimensions[column].width = width

    title = WriteOnlyCell(sheet, value=gettext('Daily closing summary'))
    title.font = Font(bold=True, size=14)
    sheet.append([title])
    for label, value in _closing_report_header(closing):
        sheet.append([label, spreadsheet_text(value)])

    for section_title, headers, rows, numeric_columns, empty_message in (
        _closing_report_sections(closing.content)
    ):
        sheet.append([])
        heading = WriteOnlyCell(sheet, value=section_title)
        heading.font = Font(bold=True, size=12)
        sheet.append([heading])

        header_cells = []
        for label in headers:
            cell = WriteOnlyCell(sheet, value=label)
            cell.font = Font(bold=True, color='FFFFFF')
            cell.fill = PatternFill('solid', fgColor='344760')
            cell.alignment = Alignment(vertical='center')
            header_cells.append(cell)
        sheet.append(header_cells)

        if not rows:
            sheet.append([empty_message])
            continue
        for row in rows:
            cells = []
            for position, value in enumerate(row):
                if position in numeric_columns and value not in ('', None):
                    cell = WriteOnlyCell(sheet, value=float(Decimal(str(value))))
                    cell.number_format = '0' if isinstance(value, int) else '0.00'
                    cells.append(cell)
                else:
                    cells.append(spreadsheet_text(value))
            sheet.append(cells)

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def build_daily_closing_pdf(*, closing):
    """FR27 - render a stored closing summary as a paginated PDF document."""
    register_report_fonts()
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=32, rightMargin=32,
        topMargin=36, bottomMargin=36,
    )
    available_width = A4[0] - 64

    title_style = ParagraphStyle(
        'ClosingTitle', fontName='CrumbVeraBold', fontSize=16, leading=21,
        textColor=colors.HexColor('#25364A'), spaceAfter=8,
    )
    section_style = ParagraphStyle(
        'ClosingSection', fontName='CrumbVeraBold', fontSize=11, leading=15,
        textColor=colors.HexColor('#25364A'), spaceBefore=12, spaceAfter=6,
    )
    body_style = ParagraphStyle(
        'ClosingBody', fontName='CrumbVera', fontSize=8, leading=11,
        splitLongWords=1,
    )
    heading_style = ParagraphStyle(
        'ClosingHeading', parent=body_style, fontName='CrumbVeraBold',
        textColor=colors.white,
    )

    def paragraph(value, style=body_style):
        text = '—' if value in (None, '') else str(value)
        return Paragraph(escape(text), style)

    story = [paragraph(gettext('Daily closing summary'), title_style)]
    for label, value in _closing_report_header(closing):
        story.append(paragraph(f'{label}: {value}'))

    for section_title, headers, rows, numeric_columns, empty_message in (
        _closing_report_sections(closing.content)
    ):
        story.append(paragraph(section_title, section_style))
        if not rows:
            story.append(paragraph(empty_message))
            continue

        table = LongTable(
            [[paragraph(label, heading_style) for label in headers]]
            + [[paragraph(value) for value in row] for row in rows],
            colWidths=[available_width / len(headers)] * len(headers),
            repeatRows=1, hAlign='LEFT',
        )
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#344760')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F2F5F8')]),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(table)

    def draw_page_number(canvas, pdf_document):
        canvas.setFont('CrumbVera', 8)
        canvas.setFillColor(colors.HexColor('#5B6573'))
        canvas.drawCentredString(A4[0] / 2, 18, f"{gettext('Page')} {pdf_document.page}")

    document.build(
        [*story, Spacer(1, 1)],
        onFirstPage=draw_page_number, onLaterPages=draw_page_number,
    )
    return buffer.getvalue()
