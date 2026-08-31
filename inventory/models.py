import uuid
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models

from bakery.models import Bakery


SUPPORTED_UNIT_ABBREVIATIONS = ('kg', 'g', 'u', 'L')


class UnitOfMeasure(models.Model):
    """Reference catalog of measurement units supported by Crumb (FR02, DR01).

    Seeded once via a data migration with the four units FR02 supports
    (kilograms, grams, units, liters). Managing this catalog (adding,
    editing, deactivating units) is the scope of FR02, not FR01 - this app
    only depends on the units existing so Ingredient can reference one.
    """

    class UnitType(models.TextChoices):
        MASS = 'mass', 'Mass'
        VOLUME = 'volume', 'Volume'
        COUNT = 'count', 'Count'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=30, unique=True)
    abbreviation = models.CharField(max_length=10, unique=True)
    unit_type = models.CharField(max_length=10, choices=UnitType.choices)

    class Meta:
        verbose_name = 'unit of measure'
        verbose_name_plural = 'units of measure'
        ordering = ['name']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(abbreviation__in=SUPPORTED_UNIT_ABBREVIATIONS),
                name='unit_abbreviation_is_supported',
            ),
        ]

    def __str__(self):
        return f'{self.name} ({self.abbreviation})'


class Ingredient(models.Model):
    """Raw-material catalog item tracked in inventory (FR01, DR01, DR03).

    Deliberately excludes cost_per_unit and category at this stage: cost
    belongs to the purchase/stock-in flow (FR07) and categorization is a
    separate, unbuilt Could-have (FR35). Adding either later is a single
    nullable-field migration - it is not worth speculatively building a
    field FR01 never asks for.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bakery = models.ForeignKey(Bakery, on_delete=models.PROTECT, related_name='ingredients')
    unit = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT, related_name='ingredients')
    name = models.CharField(max_length=120)
    current_quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    expiration_date = models.DateField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['bakery', 'name'],
                name='unique_ingredient_name_per_bakery',
            ),
            models.CheckConstraint(
                condition=models.Q(current_quantity__gte=0),
                name='ingredient_quantity_non_negative',
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def active_barcode(self):
        """FR17 - the barcode currently linked to this ingredient, if any.

        Walks the related rows in Python instead of hitting the database so a
        prefetched list of ingredients stays at a constant number of queries.
        """
        for barcode in self.barcodes.all():
            if barcode.is_active:
                return barcode.barcode_value
        return ''


class AlertConfiguration(models.Model):
    """Per-ingredient alert settings shared by FR06, FR10, and FR11.

    A missing row means that alerts have not been configured for the
    ingredient. Each threshold is optional so expiration and low-stock
    configuration can be introduced independently.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ingredient = models.OneToOneField(
        Ingredient,
        on_delete=models.CASCADE,
        related_name='alert_configuration',
    )
    minimum_stock_threshold = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    expiration_warning_days = models.PositiveIntegerField(
        null=True,
        blank=True,
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(minimum_stock_threshold__isnull=True)
                    | models.Q(minimum_stock_threshold__gt=0)
                ),
                name='alert_minimum_stock_threshold_positive',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(expiration_warning_days__isnull=True)
                    | models.Q(expiration_warning_days__gte=0)
                ),
                name='alert_expiration_warning_days_non_negative',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(minimum_stock_threshold__isnull=False)
                    | models.Q(expiration_warning_days__isnull=False)
                ),
                name='alert_at_least_one_threshold_configured',
            ),
        ]

    def __str__(self):
        return f'Alerts for {self.ingredient.name}'


class StockMovement(models.Model):
    # Declaración de la lista de opciones
    MOVEMENT_TYPES = [
        ('StockIn', 'Stock-In (Purchase)'),
        ('Consumption', 'Consumption'),
        ('Correction', 'Correction'),
        ('Loss', 'Loss'),
    ]

    movement_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bakery = models.ForeignKey(Bakery, on_delete=models.CASCADE)
    ingredient = models.ForeignKey('Ingredient', on_delete=models.PROTECT)


    movement_type = models.CharField(max_length=20, choices=MOVEMENT_TYPES, default='StockIn')

    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    movement_date = models.DateTimeField(auto_now_add=True)
    note = models.TextField(blank=True, null=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name='stock_movement_quantity_positive',
            ),
        ]

    def __str__(self):
        return f"{self.movement_type} - {self.quantity} of {self.ingredient.name}"


class BarcodeIdentifier(models.Model):
    """Maps a scanned barcode to an ingredient (FR17, DR09).

    Scoped to ingredient registration only, matching FR17's text. Product
    linkage isn't added because the Product entity doesn't exist in the
    codebase yet - it belongs to whoever builds that part of the domain.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ingredient = models.ForeignKey(
        'Ingredient', on_delete=models.CASCADE, related_name='barcodes'
    )
    barcode_value = models.CharField(max_length=64, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'barcode identifier'
        verbose_name_plural = 'barcode identifiers'

    def __str__(self):
        return self.barcode_value

