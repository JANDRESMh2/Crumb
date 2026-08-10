import uuid

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
    
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    movement_date = models.DateTimeField(auto_now_add=True)
    note = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.movement_type} - {self.quantity} of {self.ingredient.name}"

