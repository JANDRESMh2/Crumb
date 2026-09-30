from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from bakery.models import Bakery

from .forms import (
    DailyProductionRegistrationForm,
    DailySalesRegistrationForm,
    ProductEditForm,
)
from .models import Product, ProductionRecord, SalesRecord
from .services import (
    register_daily_production,
    register_daily_sale,
    register_product,
)


class DailyProductionRegistrationTests(TestCase):

    def setUp(self):
        self.bakery = Bakery.objects.create(
            name='Test Bakery',
            address='Test Address',
        )

        self.product = register_product(
            bakery=self.bakery,
            name='Croissant',
            sku='CRO-001',
            unit_price=Decimal('5000.00'),
        )

    def test_register_daily_production(self):
        """FR12 - A valid production record is created."""

        production_date = timezone.now()

        record = register_daily_production(
            bakery=self.bakery,
            product=self.product,
            produced_quantity=Decimal('50.00'),
            production_date=production_date,
        )

        self.assertEqual(
            record.produced_quantity,
            Decimal('50.00'),
        )

        self.assertEqual(
            record.product,
            self.product,
        )

        self.assertEqual(
            record.bakery,
            self.bakery,
        )

        self.assertEqual(
            record.status,
            ProductionRecord.Status.COMPLETED,
        )

        self.assertEqual(
            ProductionRecord.objects.count(),
            1,
        )

    def test_quantity_cannot_be_zero(self):
        """FR12 - Production quantity must be positive."""

        with self.assertRaises(ValidationError):
            register_daily_production(
                bakery=self.bakery,
                product=self.product,
                produced_quantity=Decimal('0.00'),
                production_date=timezone.now(),
            )

        self.assertEqual(
            ProductionRecord.objects.count(),
            0,
        )

    def test_product_must_belong_to_bakery(self):
        """FR12 - Products from other bakeries are rejected."""

        another_bakery = Bakery.objects.create(
            name='Another Bakery',
            address='Another Address',
        )

        with self.assertRaises(ValidationError):
            register_daily_production(
                bakery=another_bakery,
                product=self.product,
                produced_quantity=Decimal('10.00'),
                production_date=timezone.now(),
            )

        self.assertEqual(
            ProductionRecord.objects.count(),
            0,
        )

    def test_inactive_product_is_rejected(self):
        """FR12 - Inactive products cannot be produced."""

        self.product.status = Product.Status.INACTIVE

        self.product.save(
            update_fields=['status']
        )

        with self.assertRaises(ValidationError):
            register_daily_production(
                bakery=self.bakery,
                product=self.product,
                produced_quantity=Decimal('10.00'),
                production_date=timezone.now(),
            )

        self.assertEqual(
            ProductionRecord.objects.count(),
            0,
        )

    def test_form_only_displays_active_products(self):
        """FR12 - The form excludes inactive products."""

        inactive_product = register_product(
            bakery=self.bakery,
            name='Baguette',
            sku='BAG-001',
            unit_price=Decimal('4000.00'),
        )

        inactive_product.status = Product.Status.INACTIVE

        inactive_product.save(
            update_fields=['status']
        )

        form = DailyProductionRegistrationForm(
            bakery=self.bakery,
        )

        products = form.fields['product'].queryset

        self.assertIn(
            self.product,
            products,
        )

        self.assertNotIn(
            inactive_product,
            products,
        )

    def test_duplicate_product_is_rejected(self):
        """An active product cannot be registered twice."""

        with self.assertRaises(ValidationError):
            register_product(
                bakery=self.bakery,
                name='Croissant',
                sku='CRO-002',
                unit_price=Decimal('5500.00'),
            )

        self.assertEqual(
            Product.objects.count(),
            1,
        )

    def test_inactive_product_is_reactivated(self):
        """Registering an inactive product reactivates it."""

        self.product.status = Product.Status.INACTIVE

        self.product.save(
            update_fields=['status']
        )

        reactivated = register_product(
            bakery=self.bakery,
            name='Croissant',
            sku='CRO-NEW',
            unit_price=Decimal('5500.00'),
        )

        self.assertEqual(
            reactivated.pk,
            self.product.pk,
        )

        self.assertEqual(
            reactivated.status,
            Product.Status.ACTIVE,
        )

        self.assertEqual(
            reactivated.sku,
            'CRO-NEW',
        )

        self.assertEqual(
            reactivated.unit_price,
            Decimal('5500.00'),
        )

        self.assertEqual(
            Product.objects.count(),
            1,
        )

    def test_product_stores_deliverable_1_fields(self):
        """Product stores the additional Deliverable 1 data."""

        self.assertEqual(
            self.product.sku,
            'CRO-001',
        )

        self.assertEqual(
            self.product.unit_price,
            Decimal('5000.00'),
        )

        self.assertEqual(
            self.product.status,
            Product.Status.ACTIVE,
        )

    def test_production_record_defaults_to_completed(self):
        """A new production record starts as completed."""

        record = register_daily_production(
            bakery=self.bakery,
            product=self.product,
            produced_quantity=Decimal('25.00'),
            production_date=timezone.now(),
        )

        self.assertEqual(
            record.status,
            ProductionRecord.Status.COMPLETED,
        )

        self.assertIsNone(
            record.user,
        )

        self.assertIsNone(
            record.expiration_date,
        )

        self.assertIsNone(
            record.notes,
        )


class ProductionViewTests(TestCase):

    def setUp(self):
        self.bakery = Bakery.objects.create(
            name='Test Bakery',
            address='Test Address',
        )

        self.product = register_product(
            bakery=self.bakery,
            name='Croissant',
            sku='CRO-001',
            unit_price=Decimal('5000.00'),
        )

    def test_production_page_loads(self):
        """The production registration page is accessible."""

        response = self.client.get(
            reverse('production:register')
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertContains(
            response,
            'Register daily production',
        )

    def test_register_product_from_web(self):
        """Products can be registered through the web interface."""

        response = self.client.post(
            reverse('production:product_create'),
            {
                'name': 'Pandebono',
                'sku': 'PAN-001',
                'unit_price': '3500.00',
            },
        )

        self.assertRedirects(
            response,
            reverse('production:register'),
        )

        product = Product.objects.get(
            bakery=self.bakery,
            name='Pandebono',
        )

        self.assertEqual(
            product.sku,
            'PAN-001',
        )

        self.assertEqual(
            product.unit_price,
            Decimal('3500.00'),
        )

        self.assertEqual(
            product.status,
            Product.Status.ACTIVE,
        )

    def test_register_production_from_web(self):
        """FR12 - Production can be registered through the interface."""

        production_date = (
            timezone.localtime()
            .replace(
                second=0,
                microsecond=0,
            )
        )

        response = self.client.post(
            reverse('production:register'),
            {
                'product': self.product.pk,
                'produced_quantity': '50.00',
                'production_date': production_date.strftime(
                    '%Y-%m-%dT%H:%M'
                ),
            },
        )

        self.assertRedirects(
            response,
            reverse('production:list'),
        )

        record = ProductionRecord.objects.get(
            bakery=self.bakery,
            product=self.product,
        )

        self.assertEqual(
            record.produced_quantity,
            Decimal('50.00'),
        )

        self.assertEqual(
            record.status,
            ProductionRecord.Status.COMPLETED,
        )

    def test_zero_quantity_is_rejected(self):
        """FR12 - The web form rejects zero production."""

        production_date = (
            timezone.localtime()
            .replace(
                second=0,
                microsecond=0,
            )
        )

        response = self.client.post(
            reverse('production:register'),
            {
                'product': self.product.pk,
                'produced_quantity': '0.00',
                'production_date': production_date.strftime(
                    '%Y-%m-%dT%H:%M'
                ),
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertFormError(
            response.context['form'],
            'produced_quantity',
            (
                'Ensure this value is greater than '
                'or equal to 0.01.'
            ),
        )

        self.assertEqual(
            ProductionRecord.objects.count(),
            0,
        )

    def test_product_from_another_bakery_is_rejected(self):
        """FR12 - The form rejects products from another bakery."""

        another_bakery = Bakery.objects.create(
            name='Another Bakery',
            address='Another Address',
        )

        another_product = register_product(
            bakery=another_bakery,
            name='Brownie',
            sku='BRO-001',
            unit_price=Decimal('6000.00'),
        )

        production_date = (
            timezone.localtime()
            .replace(
                second=0,
                microsecond=0,
            )
        )

        response = self.client.post(
            reverse('production:register'),
            {
                'product': another_product.pk,
                'produced_quantity': '10.00',
                'production_date': production_date.strftime(
                    '%Y-%m-%dT%H:%M'
                ),
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertTrue(
            response.context['form'].errors['product']
        )

        self.assertEqual(
            ProductionRecord.objects.count(),
            0,
        )

    def test_production_history_displays_records(self):
        """The production history displays registered production."""

        register_daily_production(
            bakery=self.bakery,
            product=self.product,
            produced_quantity=Decimal('50.00'),
            production_date=timezone.now(),
        )

        response = self.client.get(
            reverse('production:list')
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertContains(
            response,
            'Croissant',
        )

        self.assertContains(
            response,
            '50',
        )
    def test_product_list_displays_products(self):
        """Registered products are displayed in the catalog."""

        response = self.client.get(
            reverse('production:product_list')
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertContains(
            response,
            'Croissant',
        )

        self.assertContains(
            response,
            '5000.00',
        )


    def test_product_can_be_edited(self):
        """Product data, including price, can be edited."""

        response = self.client.post(
            reverse(
                'production:product_edit',
                args=[self.product.pk],
            ),
            {
                'name': 'Croissant',
                'sku': 'CRO-001',
                'unit_price': '6500.00',
                'status': Product.Status.ACTIVE,
            },
        )

        self.assertRedirects(
            response,
            reverse('production:product_list'),
        )

        self.product.refresh_from_db()

        self.assertEqual(
            self.product.unit_price,
            Decimal('6500.00'),
        )


    def test_product_edit_preserves_previous_sale_price(self):
        """Editing a product price does not alter previous sales."""

        sale = register_daily_sale(
            bakery=self.bakery,
            product=self.product,
            quantity_sold=Decimal('2.00'),
            sale_timestamp=timezone.now(),
        )

        self.client.post(
            reverse(
                'production:product_edit',
                args=[self.product.pk],
            ),
            {
                'name': 'Croissant',
                'sku': 'CRO-001',
                'unit_price': '7000.00',
                'status': Product.Status.ACTIVE,
            },
        )

        sale.refresh_from_db()

        self.assertEqual(
            sale.unit_price_at_sale,
            Decimal('5000.00'),
        )

        self.assertEqual(
            sale.total_amount,
            Decimal('10000.00'),
        )


class DailySalesRegistrationTests(TestCase):

    def setUp(self):
        self.bakery = Bakery.objects.create(
            name='Test Bakery',
            address='Test Address',
        )

        self.product = register_product(
            bakery=self.bakery,
            name='Croissant',
            sku='CRO-001',
            unit_price=Decimal('5000.00'),
        )

    def test_register_daily_sale(self):
        """FR13 - A valid sale is registered."""

        record = register_daily_sale(
            bakery=self.bakery,
            product=self.product,
            quantity_sold=Decimal('2.00'),
            sale_timestamp=timezone.now(),
        )

        self.assertEqual(
            record.quantity_sold,
            Decimal('2.00'),
        )

        self.assertEqual(
            record.unit_price_at_sale,
            Decimal('5000.00'),
        )

        self.assertEqual(
            record.total_amount,
            Decimal('10000.00'),
        )

    def test_sale_preserves_price_snapshot(self):
        """Changing Product price does not modify previous sales."""

        record = register_daily_sale(
            bakery=self.bakery,
            product=self.product,
            quantity_sold=Decimal('2.00'),
            sale_timestamp=timezone.now(),
        )

        self.product.unit_price = Decimal('6000.00')
        self.product.save(
            update_fields=['unit_price']
        )

        record.refresh_from_db()

        self.assertEqual(
            record.unit_price_at_sale,
            Decimal('5000.00'),
        )

        self.assertEqual(
            record.total_amount,
            Decimal('10000.00'),
        )

    def test_zero_quantity_is_rejected(self):
        """FR13 - Sale quantity must be positive."""

        with self.assertRaises(ValidationError):
            register_daily_sale(
                bakery=self.bakery,
                product=self.product,
                quantity_sold=Decimal('0.00'),
                sale_timestamp=timezone.now(),
            )

    def test_inactive_product_is_rejected(self):
        """FR13 - Inactive products cannot be sold."""

        self.product.status = Product.Status.INACTIVE

        self.product.save(
            update_fields=['status']
        )

        with self.assertRaises(ValidationError):
            register_daily_sale(
                bakery=self.bakery,
                product=self.product,
                quantity_sold=Decimal('1.00'),
                sale_timestamp=timezone.now(),
            )

    def test_product_must_belong_to_bakery(self):
        """FR13 - Product must belong to the selected bakery."""

        another_bakery = Bakery.objects.create(
            name='Another Bakery',
            address='Another Address',
        )

        with self.assertRaises(ValidationError):
            register_daily_sale(
                bakery=another_bakery,
                product=self.product,
                quantity_sold=Decimal('1.00'),
                sale_timestamp=timezone.now(),
            )

    def test_sales_form_only_displays_active_products(self):
        """FR13 - Sales form excludes inactive products."""

        inactive_product = register_product(
            bakery=self.bakery,
            name='Baguette',
            sku='BAG-001',
            unit_price=Decimal('4000.00'),
        )

        inactive_product.status = Product.Status.INACTIVE
        inactive_product.save(
            update_fields=['status']
        )

        form = DailySalesRegistrationForm(
            bakery=self.bakery,
        )

        products = form.fields['product'].queryset

        self.assertIn(
            self.product,
            products,
        )

        self.assertNotIn(
            inactive_product,
            products,
        )

    def test_total_amount_is_rounded_to_two_decimal_places(self):
        """FR13 - Sale total is stored with two decimal places."""

        self.product.unit_price = Decimal('3333.33')
        self.product.save(
            update_fields=['unit_price']
        )

        record = register_daily_sale(
            bakery=self.bakery,
            product=self.product,
            quantity_sold=Decimal('1.25'),
            sale_timestamp=timezone.now(),
        )

        self.assertEqual(
            record.total_amount,
            Decimal('4166.66'),
        )


class SalesViewTests(TestCase):

    def setUp(self):
        self.bakery = Bakery.objects.create(
            name='Test Bakery',
            address='Test Address',
        )

        self.product = register_product(
            bakery=self.bakery,
            name='Croissant',
            sku='CRO-001',
            unit_price=Decimal('5000.00'),
        )

    def test_sales_page_loads(self):
        """FR13 - Sales registration page is accessible."""

        response = self.client.get(
            reverse('production:sales_register')
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertContains(
            response,
            'Register daily sales',
        )

    def test_register_sale_from_web(self):
        """FR13 - Sale can be registered through the interface."""

        sale_timestamp = (
            timezone.localtime()
            .replace(
                second=0,
                microsecond=0,
            )
        )

        response = self.client.post(
            reverse('production:sales_register'),
            {
                'product': self.product.pk,
                'quantity_sold': '2.00',
                'sale_timestamp': sale_timestamp.strftime(
                    '%Y-%m-%dT%H:%M'
                ),
            },
        )

        self.assertRedirects(
            response,
            reverse('production:sales_list'),
        )

        record = SalesRecord.objects.get(
            bakery=self.bakery,
            product=self.product,
        )

        self.assertEqual(
            record.quantity_sold,
            Decimal('2.00'),
        )

        self.assertEqual(
            record.unit_price_at_sale,
            Decimal('5000.00'),
        )

        self.assertEqual(
            record.total_amount,
            Decimal('10000.00'),
        )