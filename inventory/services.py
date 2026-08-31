from django.db import transaction

from .models import AlertConfiguration, Ingredient


def is_ingredient_low_stock(*, ingredient):
    """FR11 - return whether an ingredient is below its active threshold."""
    try:
        configuration = ingredient.alert_configuration
    except AlertConfiguration.DoesNotExist:
        return False

    return (
        configuration.is_active
        and ingredient.current_quantity
        < configuration.minimum_stock_threshold
    )


@transaction.atomic
def register_ingredient(*, bakery, name, unit, current_quantity, expiration_date):
    """FR01 - register a new ingredient under the given bakery."""

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

        return existing

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
