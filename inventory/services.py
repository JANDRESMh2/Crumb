from django.db import transaction

from .models import BarcodeIdentifier, Ingredient, StockMovement


class InsufficientStockError(Exception):
    """Raised when a consumption would leave an ingredient with negative stock."""


@transaction.atomic
def register_ingredient(
    *, bakery, name, unit, current_quantity, expiration_date, barcode_value=''
):
    """FR01 - register a new ingredient under the given bakery.

    barcode_value is optional (FR17) - when provided, links a scanned
    barcode to the ingredient being registered.
    """

    existing = Ingredient.objects.filter(
        bakery=bakery,
        name__iexact=name,
        is_active=False,
    ).first()

    if existing is not None:
        existing.name = name
        existing.unit = unit
        existing.current_quantity = current_quantity
        existing.expiration_date = expiration_date
        existing.is_active = True

        existing.save(
            update_fields=[
                'name',
                'unit',
                'current_quantity',
                'expiration_date',
                'is_active',
                'updated_at',
            ]
        )
        ingredient = existing
    else:
        ingredient = Ingredient.objects.create(
            bakery=bakery,
            name=name,
            unit=unit,
            current_quantity=current_quantity,
            expiration_date=expiration_date,
        )

    if barcode_value:
        BarcodeIdentifier.objects.create(ingredient=ingredient, barcode_value=barcode_value)

    return ingredient


@transaction.atomic
def register_stock_consumption(*, bakery, ingredient, quantity, note=''):
    """FR08 - register the consumption of an ingredient, decreasing its stock.

    Refuses to leave the ingredient with negative stock (DR03). The form
    already checks this for a friendly error message; this check is the
    authoritative guard in case the service is called directly.
    """
    if quantity > ingredient.current_quantity:
        raise InsufficientStockError(
            f'Cannot consume {quantity} of {ingredient.name}; '
            f'only {ingredient.current_quantity} available.'
        )

    ingredient.current_quantity -= quantity
    ingredient.save(update_fields=['current_quantity', 'updated_at'])

    return StockMovement.objects.create(
        bakery=bakery,
        ingredient=ingredient,
        movement_type='Consumption',
        quantity=quantity,
        note=note,
    )


@transaction.atomic
def update_ingredient(
    *,
    ingredient,
    name,
    unit,
    current_quantity,
    expiration_date,
):
    """FR03 - edit an existing ingredient."""
    ingredient.name = name
    ingredient.unit = unit
    ingredient.current_quantity = current_quantity
    ingredient.expiration_date = expiration_date
    ingredient.save(
        update_fields=[
            'name',
            'unit',
            'current_quantity',
            'expiration_date',
            'updated_at',
        ]
    )
    return ingredient


@transaction.atomic
def deactivate_ingredient(*, ingredient):
    """FR04 - remove an ingredient from the active inventory."""
    ingredient.is_active = False
    ingredient.save(update_fields=['is_active', 'updated_at'])
    return ingredient