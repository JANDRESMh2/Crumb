import pandas as pd
from decimal import Decimal
from django.db import transaction
from django.utils import timezone

from .models import AlertConfiguration, BarcodeIdentifier, Ingredient, StockMovement, UnitOfMeasure, SUPPORTED_UNIT_ABBREVIATIONS


class InsufficientStockError(Exception):
    """Raised when a consumption would leave an ingredient with negative stock."""


def low_stock_alerts(*, ingredient):
    """FR11 - return whether an ingredient needs a low-stock alert."""
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


def expiration_alerts(*, ingredient, today=None):
    """FR06 - return whether an ingredient needs an expiration alert."""
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


def import_ingredients_from_excel(*, file, bakery):
    """FR15 - import ingredients from Excel or CSV file."""
    column_mapping = {
        'Nombre': 'name', 'Unidad': 'unit', 'Cantidad': 'quantity',
        'Fecha de caducidad': 'expiration_date', 
        'Dias de aviso de caducidad': 'expiration_warning_days',
        'Codigo de barras': 'barcode'
    }

    # Cargar y normalizar encabezados
    df = pd.read_csv(file) if file.name.endswith('.csv') else pd.read_excel(file)
    df.columns = [str(c).strip().capitalize() for c in df.columns] # Normaliza mayúsculas
    df.rename(columns=column_mapping, inplace=True)
    df.columns = [c.lower() for c in df.columns] # Fuerza minúsculas para validación interna

    required_cols = {'name', 'unit', 'quantity', 'expiration_date'}
    if missing := required_cols - set(df.columns):
        raise ValueError(f"Missing required columns: {', '.join(missing)}")

    # Limpiar nulos de forma nativa para evitar strings 'nan' o 'none'
    df = df.where(pd.notnull(df), None)

    # Precargar datos de la BD
    units = UnitOfMeasure.objects.filter(abbreviation__in=SUPPORTED_UNIT_ABBREVIATIONS)
    unit_map = {**{u.name.lower(): u for u in units}, **{u.abbreviation.lower(): u for u in units}}
    existing_map = {ing.name.lower(): ing for ing in Ingredient.objects.filter(bakery=bakery, is_active=True)}

    new_ingredients, update_ingredients = [], []
    alerts_to_process, barcodes_to_link = [], []

    # itertuples es más rápido y limpio que iterrows
    for row in df.itertuples(index=False):
        if not row.name: continue
        name = str(row.name).strip()
        
        unit = unit_map.get(str(row.unit).strip().lower())
        if not unit: 
            raise ValueError(f"Unknown unit: {row.unit} for ingredient {name}")

        try:
            quantity = Decimal(str(row.quantity))
            expiration_date = pd.to_datetime(row.expiration_date).date()
        except Exception as e:
            raise ValueError(f"Invalid quantity or date for {name}: {e}")

        # Lógica de creación / actualización
        ing = existing_map.get(name.lower())
        if ing:
            ing.current_quantity += quantity
            ing.expiration_date = expiration_date
            ing.unit = unit
            update_ingredients.append(ing)
        else:
            ing = Ingredient(bakery=bakery, name=name, unit=unit, current_quantity=quantity, expiration_date=expiration_date)
            new_ingredients.append(ing)

        # Alertas y códigos de barras (sin distinguir si son nuevos o actualizados)
        if getattr(row, 'expiration_warning_days', None) is not None:
            alerts_to_process.append((ing, int(row.expiration_warning_days)))
        
        barcode = getattr(row, 'barcode', None)
        if barcode:
            barcodes_to_link.append((ing, str(barcode).strip()))

    # Ejecución en base de datos
    with transaction.atomic():
        if new_ingredients:
            Ingredient.objects.bulk_create(new_ingredients)
        if update_ingredients:
            # Nota: Si updated_at usa auto_now=True, bulk_update no lo actualizará automáticamente,
            # tendrías que inyectar timezone.now() manualmente en el objeto antes de este paso.
            Ingredient.objects.bulk_update(update_ingredients, ['current_quantity', 'expiration_date', 'unit'])

        for ing, wd in alerts_to_process:
            configure_expiration_alert(ingredient=ing, expiration_warning_days=wd)
            
        for ing, code in barcodes_to_link:
            _link_barcode(ingredient=ing, barcode_value=code)

    return len(new_ingredients), len(update_ingredients)
