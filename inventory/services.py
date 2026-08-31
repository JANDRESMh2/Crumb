from django.db import transaction
from django.utils import timezone

from .models import AlertConfiguration, Ingredient


def is_ingredient_low_stock(*, ingredient):
    """FR11 - return whether an ingredient is below its active threshold."""
    try:
        configuration = ingredient.alert_configuration
    except AlertConfiguration.DoesNotExist:
        return False

    return (
        configuration.is_active
        and configuration.minimum_stock_threshold is not None
        and ingredient.current_quantity
        < configuration.minimum_stock_threshold
    )


def is_ingredient_expiring_soon(*, ingredient, today=None):
    """FR06 - return whether an ingredient is inside its warning period."""
    if ingredient.expiration_date is None:
        return False

    try:
        configuration = ingredient.alert_configuration
    except AlertConfiguration.DoesNotExist:
        return False

    if (
        not configuration.is_active
        or configuration.expiration_warning_days is None
    ):
        return False

    today = today or timezone.localdate()
    days_until_expiration = (ingredient.expiration_date - today).days
    return 0 <= days_until_expiration <= configuration.expiration_warning_days


def is_ingredient_expired(*, ingredient, today=None):
    """FR06 - return whether an ingredient's expiration date has passed."""
    if ingredient.expiration_date is None:
        return False

    today = today or timezone.localdate()
    return ingredient.expiration_date < today


def configure_expiration_alert(*, ingredient, expiration_warning_days):
    """FR06 - persist or clear an ingredient's expiration warning period."""
    try:
        configuration = ingredient.alert_configuration
    except AlertConfiguration.DoesNotExist:
        if expiration_warning_days is None:
            return None
        return AlertConfiguration.objects.create(
            ingredient=ingredient,
            expiration_warning_days=expiration_warning_days,
        )

    configuration.expiration_warning_days = expiration_warning_days
    if (
        configuration.minimum_stock_threshold is None
        and configuration.expiration_warning_days is None
    ):
        configuration.delete()
        return None

    configuration.save(update_fields=['expiration_warning_days'])
    return configuration


@transaction.atomic
def register_ingredient(
    *,
    bakery,
    name,
    unit,
    current_quantity,
    expiration_date,
    expiration_warning_days=None,
):
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

        configure_expiration_alert(
            ingredient=existing,
            expiration_warning_days=expiration_warning_days,
        )
        return existing

    ingredient = Ingredient.objects.create(
        bakery=bakery,
        name=name,
        unit=unit,
        current_quantity=current_quantity,
        expiration_date=expiration_date,
    )
    configure_expiration_alert(
        ingredient=ingredient,
        expiration_warning_days=expiration_warning_days,
    )
    return ingredient


@transaction.atomic
def update_ingredient(
    *,
    ingredient,
    name,
    unit,
    current_quantity,
    expiration_date,
    expiration_warning_days=None,
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
    configure_expiration_alert(
        ingredient=ingredient,
        expiration_warning_days=expiration_warning_days,
    )
    return ingredient


@transaction.atomic
def deactivate_ingredient(*, ingredient):
    """FR04 - remove an ingredient from the active inventory."""
    ingredient.is_active = False
    ingredient.save(update_fields=['is_active', 'updated_at'])
    return ingredient
