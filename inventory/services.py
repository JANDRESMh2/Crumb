from django.db import transaction

from .models import Ingredient


@transaction.atomic
def register_ingredient(*, bakery, name, unit, current_quantity, expiration_date):
    """FR01 - register a new ingredient under the given bakery."""
    return Ingredient.objects.create(
        bakery=bakery,
        name=name,
        unit=unit,
        current_quantity=current_quantity,
        expiration_date=expiration_date,
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