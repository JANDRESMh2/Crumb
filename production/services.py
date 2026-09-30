from django.core.exceptions import ValidationError
from django.db import transaction
from decimal import Decimal, ROUND_HALF_UP

from .models import Product, ProductionRecord, SalesRecord


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