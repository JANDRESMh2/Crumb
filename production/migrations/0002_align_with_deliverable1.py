from decimal import Decimal

from django.conf import settings
from django.db import migrations, models
import django.core.validators
import django.db.models.deletion
import django.utils.timezone


def copy_product_status(apps, schema_editor):
    Product = apps.get_model('production', 'Product')

    for product in Product.objects.all():
        product.status = (
            'Active'
            if product.is_active
            else 'Inactive'
        )
        product.save(
            update_fields=['status']
        )


def restore_product_is_active(apps, schema_editor):
    Product = apps.get_model('production', 'Product')

    for product in Product.objects.all():
        product.is_active = (
            product.status == 'Active'
        )
        product.save(
            update_fields=['is_active']
        )


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(
            settings.AUTH_USER_MODEL
        ),
        ('production', '0001_initial'),
    ]

    operations = [
        # The existing constraint references "quantity".
        migrations.RemoveConstraint(
            model_name='productionrecord',
            name='production_quantity_positive',
        ),

        # Preserve every existing FR12 quantity value.
        migrations.RenameField(
            model_name='productionrecord',
            old_name='quantity',
            new_name='produced_quantity',
        ),

        # Deliverable 1 Product fields.
        migrations.AddField(
            model_name='product',
            name='sku',
            field=models.CharField(
                blank=True,
                max_length=50,
                null=True,
            ),
        ),

        migrations.AddField(
            model_name='product',
            name='unit_price',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0.00'),
                max_digits=10,
                validators=[
                    django.core.validators.MinValueValidator(
                        Decimal('0.00')
                    )
                ],
            ),
            preserve_default=False,
        ),

        migrations.AddField(
            model_name='product',
            name='status',
            field=models.CharField(
                choices=[
                    ('Active', 'Active'),
                    ('Inactive', 'Inactive'),
                ],
                default='Active',
                max_length=10,
            ),
        ),

        # Convert existing is_active values into the new status.
        migrations.RunPython(
            copy_product_status,
            restore_product_is_active,
        ),

        migrations.RemoveField(
            model_name='product',
            name='is_active',
        ),

        # Deliverable 1 uses Decimal.
        migrations.AlterField(
            model_name='productionrecord',
            name='produced_quantity',
            field=models.DecimalField(
                decimal_places=2,
                max_digits=10,
                validators=[
                    django.core.validators.MinValueValidator(
                        Decimal('0.01')
                    )
                ],
            ),
        ),

        # Deliverable 1 uses a timestamp.
        migrations.AlterField(
            model_name='productionrecord',
            name='production_date',
            field=models.DateTimeField(
                default=django.utils.timezone.now,
            ),
        ),

        migrations.AddField(
            model_name='productionrecord',
            name='user',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='production_records',
                to=settings.AUTH_USER_MODEL,
            ),
        ),

        migrations.AddField(
            model_name='productionrecord',
            name='expiration_date',
            field=models.DateField(
                blank=True,
                null=True,
            ),
        ),

        migrations.AddField(
            model_name='productionrecord',
            name='status',
            field=models.CharField(
                choices=[
                    ('Completed', 'Completed'),
                    ('Cancelled', 'Cancelled'),
                ],
                default='Completed',
                max_length=10,
            ),
        ),

        migrations.AddField(
            model_name='productionrecord',
            name='notes',
            field=models.TextField(
                blank=True,
                null=True,
            ),
        ),

        migrations.AddConstraint(
            model_name='productionrecord',
            constraint=models.CheckConstraint(
                condition=models.Q(
                    produced_quantity__gt=0,
                ),
                name='production_quantity_positive',
            ),
        ),
    ]