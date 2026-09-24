import uuid

from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from bakery.models import Bakery


class Product(models.Model):
    """Catalog of baked products produced by a bakery."""

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

    name = models.CharField(max_length=120)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['bakery', 'name'],
                name='unique_product_name_per_bakery',
            ),
        ]

    def __str__(self):
        return self.name


class ProductionRecord(models.Model):
    """FR12 - daily production registration."""

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

    quantity = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
    )

    production_date = models.DateField(
        default=timezone.localdate,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ['-production_date', '-created_at']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name='production_quantity_positive',
            ),
        ]

    def __str__(self):
        return (
            f'{self.product.name}: {self.quantity} '
            f'on {self.production_date}'
        )