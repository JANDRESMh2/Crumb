import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from bakery.models import Bakery


class Product(models.Model):
    """Finished bakery product used for production and sales tracking."""

    class Status(models.TextChoices):
        ACTIVE = 'Active', 'Active'
        INACTIVE = 'Inactive', 'Inactive'

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    bakery = models.ForeignKey(
        Bakery,
        on_delete=models.PROTECT,
        related_name='products',
    )

    name = models.CharField(
        max_length=120,
    )

    sku = models.CharField(
        max_length=50,
        blank=True,
        null=True,
    )

    unit_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[
            MinValueValidator(Decimal('0.00')),
        ],
    )

    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.ACTIVE,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['bakery', 'name'],
                name='unique_product_name_per_bakery',
            ),
        ]

    @property
    def is_active(self):
        """Compatibility helper for code created before the status field."""
        return self.status == self.Status.ACTIVE

    @is_active.setter
    def is_active(self, value):
        self.status = (
            self.Status.ACTIVE
            if value
            else self.Status.INACTIVE
        )

    def __str__(self):
        return self.name


class ProductionRecord(models.Model):
    """Historical record of a product production event."""

    class Status(models.TextChoices):
        COMPLETED = 'Completed', 'Completed'
        CANCELLED = 'Cancelled', 'Cancelled'

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    bakery = models.ForeignKey(
        Bakery,
        on_delete=models.PROTECT,
        related_name='production_records',
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name='production_records',
    )

    # Deliverable 1 requires the responsible user.
    # Nullable until FR31 provides application user management.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='production_records',
    )

    produced_quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[
            MinValueValidator(Decimal('0.01')),
        ],
    )

    production_date = models.DateTimeField(
        default=timezone.now,
    )

    expiration_date = models.DateField(
        null=True,
        blank=True,
    )

    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.COMPLETED,
    )

    notes = models.TextField(
        blank=True,
        null=True,
    )

    # We keep this field because FR12 already had it.
    # It does not conflict with Deliverable 1.
    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = [
            '-production_date',
            '-created_at',
        ]

        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    produced_quantity__gt=0,
                ),
                name='production_quantity_positive',
            ),
        ]

    def __str__(self):
        return (
            f'{self.product.name}: '
            f'{self.produced_quantity} '
            f'on {self.production_date:%Y-%m-%d %H:%M}'
        )

class SalesRecord(models.Model):
    """FR13 - Daily sales registration."""

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    bakery = models.ForeignKey(
        Bakery,
        on_delete=models.PROTECT,
        related_name='sales_records',
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name='sales_records',
    )

    # Deliverable 1 requires the responsible seller.
    # Nullable until FR31 provides application user management.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sales_records',
    )

    quantity_sold = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[
            MinValueValidator(Decimal('0.01')),
        ],
    )

    unit_price_at_sale = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[
            MinValueValidator(Decimal('0.00')),
        ],
    )

    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[
            MinValueValidator(Decimal('0.00')),
        ],
    )

    sale_timestamp = models.DateTimeField(
        default=timezone.now,
    )

    class Meta:
        ordering = [
            '-sale_timestamp',
        ]

        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    quantity_sold__gt=0,
                ),
                name='sales_quantity_positive',
            ),
            models.CheckConstraint(
                condition=models.Q(
                    unit_price_at_sale__gte=0,
                ),
                name='sales_unit_price_non_negative',
            ),
            models.CheckConstraint(
                condition=models.Q(
                    total_amount__gte=0,
                ),
                name='sales_total_non_negative',
            ),
        ]

    def __str__(self):
        return (
            f'{self.product.name}: '
            f'{self.quantity_sold} sold '
            f'on {self.sale_timestamp:%Y-%m-%d %H:%M}'
        )