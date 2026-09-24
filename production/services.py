from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Product, ProductionRecord


@transaction.atomic
def register_product(*, bakery, name):
    """
    Register a baked product in the bakery catalog.

    Existing active products cannot be duplicated.
    Inactive products can be reactivated.
    """
    name = name.strip()

    if not name:
        raise ValidationError(
            'The product name is required.'
        )

    existing_product = Product.objects.filter(
        bakery=bakery,
        name__iexact=name,
    ).first()

    if existing_product is not None:

        if existing_product.is_active:
            raise ValidationError(
                'This product is already registered.'
            )

        existing_product.name = name
        existing_product.is_active = True

        existing_product.save(
            update_fields=[
                'name',
                'is_active',
                'updated_at',
            ]
        )

        return existing_product

    product = Product(
        bakery=bakery,
        name=name,
    )

    product.full_clean()
    product.save()

    return product


@transaction.atomic
def register_daily_production(
    *,
    bakery,
    product,
    quantity,
    production_date,
):
    """
    FR12 - Register the daily production of a baked product.
    """

    if product.bakery_id != bakery.pk:
        raise ValidationError(
            'The selected product does not belong '
            'to this bakery.'
        )

    if not product.is_active:
        raise ValidationError(
            'Inactive products cannot be used '
            'for production registration.'
        )

    record = ProductionRecord(
        bakery=bakery,
        product=product,
        quantity=quantity,
        production_date=production_date,
    )

    record.full_clean()
    record.save()

    return record