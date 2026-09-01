from django.db import transaction
from django.utils import timezone

from .models import AlertConfiguration, BarcodeIdentifier, Ingredient, StockMovement


class InsufficientStockError(Exception):
    """Raised when a consumption would leave an ingredient with negative stock."""


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
def configure_low_stock_threshold(*, ingredient, minimum_stock_threshold):
    """FR10 - configure or clear an ingredient's low-stock threshold."""

    try:
        configuration = ingredient.alert_configuration
    except AlertConfiguration.DoesNotExist:
        if minimum_stock_threshold is None:
            return None

        return AlertConfiguration.objects.create(
            ingredient=ingredient,
            minimum_stock_threshold=minimum_stock_threshold,
        )

    configuration.minimum_stock_threshold = minimum_stock_threshold

    if (
        configuration.minimum_stock_threshold is None
        and configuration.expiration_warning_days is None
    ):
        configuration.delete()
        return None

    configuration.save(
        update_fields=['minimum_stock_threshold']
    )

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
    barcode_value='',
):
    """FR01 - register a new ingredient under the given bakery.

    barcode_value is optional (FR17) - when provided, links a scanned barcode
    to the ingredient being registered.
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

        configure_expiration_alert(
            ingredient=existing,
            expiration_warning_days=expiration_warning_days,
        )
        if barcode_value:
            _link_barcode(ingredient=existing, barcode_value=barcode_value)
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
    if barcode_value:
        _link_barcode(ingredient=ingredient, barcode_value=barcode_value)
    return ingredient


def _link_barcode(*, ingredient, barcode_value):
    """FR17 - point a barcode at an ingredient.

    barcode_value is unique, so an ingredient that was deleted and registered
    again would collide with its own old row. Reusing the row (instead of
    creating a second one) keeps the re-registration flow working and
    reactivates the link.
    """
    BarcodeIdentifier.objects.update_or_create(
        barcode_value=barcode_value,
        defaults={'ingredient': ingredient, 'is_active': True},
    )


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
    """FR04 - remove an ingredient from the active inventory.

    Its barcodes are deactivated too (FR17), so the value stops showing in the
    catalog and can be linked to another ingredient later.
    """
    ingredient.is_active = False
    ingredient.save(update_fields=['is_active', 'updated_at'])
    ingredient.barcodes.update(is_active=False)
    return ingredient
