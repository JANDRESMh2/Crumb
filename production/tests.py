import json
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from time import perf_counter

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook
from pypdf import PdfReader

from Crumb.testutils import AuthenticatedTestCase
from bakery.models import ActivityLog, Bakery
from inventory.models import (
    AlertConfiguration,
    Ingredient,
    NotificationPreference,
    StockMovement,
    UnitOfMeasure,
)
from inventory.services import (
    register_inventory_correction,
    register_stock_consumption,
    register_stock_in,
)

from .forms import (
    DailyProductionRegistrationForm,
    DailySalesRegistrationForm,
    ProductEditForm,
)
from .models import (
    DailyClosingSummary,
    Product,
    ProductionRecord,
    SalesRecord,
    ScheduledOrder,
)
from .services import (
    build_daily_closing_summary,
    build_daily_unsold_products,
    build_history_tracking,
    build_loss_report,
    build_sales_analytics,
    close_business_day,
    register_daily_production,
    register_daily_sale,
    register_product,
)


class DailyUnsoldCalculationTests(TestCase):
    def setUp(self):
        self.bakery = Bakery.objects.create(name='Test Bakery', address='Test Address')
        self.product = register_product(
            bakery=self.bakery,
            name='Croissant',
            sku='CRO-001',
            unit_price=Decimal('5000.00'),
        )

    def test_calculates_unsold_quantity_for_each_product_and_day(self):
        day = timezone.now().replace(hour=10, minute=0, second=0, microsecond=0)
        register_daily_production(
            bakery=self.bakery,
            product=self.product,
            produced_quantity=Decimal('20.00'),
            production_date=day,
        )
        register_daily_sale(
            bakery=self.bakery,
            product=self.product,
            quantity_sold=Decimal('7.00'),
            sale_timestamp=day.replace(hour=14),
        )

        daily = build_daily_unsold_products(bakery=self.bakery)

        self.assertEqual(len(daily), 1)
        self.assertEqual(daily[0]['produced_quantity'], Decimal('20.00'))
        self.assertEqual(daily[0]['sold_quantity'], Decimal('7.00'))
        self.assertEqual(daily[0]['unsold_quantity'], Decimal('13.00'))

    def test_unsold_calculation_is_limited_to_the_current_bakery(self):
        other_bakery = Bakery.objects.create(name='Other Bakery', address='Other Address')
        other_product = register_product(
            bakery=other_bakery,
            name='Croissant',
            sku='CRO-002',
            unit_price=Decimal('5000.00'),
        )
        register_daily_production(
            bakery=other_bakery,
            product=other_product,
            produced_quantity=Decimal('10.00'),
            production_date=timezone.now(),
        )

        self.assertEqual(build_daily_unsold_products(bakery=self.bakery), [])


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


class ProductionViewTests(AuthenticatedTestCase):

    def setUp(self):
        super().setUp()
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


class SalesViewTests(AuthenticatedTestCase):

    def setUp(self):
        super().setUp()
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

class ProductionSalesHistoryTests(AuthenticatedTestCase):
    """FR25 - view the history of production and sales records."""

    def setUp(self):
        super().setUp()
        self.bakery = Bakery.objects.create(
            name='Test Bakery',
            address='Test Address',
        )
        self.croissant = register_product(
            bakery=self.bakery,
            name='Croissant',
            sku='CRO-001',
            unit_price=Decimal('5000.00'),
        )
        self.bread = register_product(
            bakery=self.bakery,
            name='Bread',
            sku='BRE-001',
            unit_price=Decimal('2000.00'),
        )

        now = timezone.now()
        self.old_date = now - timezone.timedelta(days=10)
        self.recent_date = now - timezone.timedelta(days=1)

        self.old_production = register_daily_production(
            bakery=self.bakery,
            product=self.croissant,
            produced_quantity=Decimal('40.00'),
            production_date=self.old_date,
        )
        self.recent_production = register_daily_production(
            bakery=self.bakery,
            product=self.bread,
            produced_quantity=Decimal('20.00'),
            production_date=self.recent_date,
        )
        self.sale = register_daily_sale(
            bakery=self.bakery,
            product=self.croissant,
            quantity_sold=Decimal('3.00'),
            sale_timestamp=now,
        )

    def test_history_combines_records_newest_first(self):
        entries, totals = build_history_tracking(
            bakery=self.bakery,
        )

        self.assertEqual(
            [entry['record'] for entry in entries],
            [self.sale, self.recent_production, self.old_production],
        )
        self.assertEqual(totals['produced_quantity'], Decimal('60.00'))
        self.assertEqual(totals['sold_quantity'], Decimal('3.00'))
        self.assertEqual(totals['sales_amount'], Decimal('15000.00'))

    def test_history_filters_by_record_type(self):
        entries, _ = build_history_tracking(
            bakery=self.bakery,
            record_type='sales',
        )
        self.assertEqual([e['kind'] for e in entries], ['sale'])

        entries, _ = build_history_tracking(
            bakery=self.bakery,
            record_type='production',
        )
        self.assertEqual(
            [e['kind'] for e in entries],
            ['production', 'production'],
        )

    def test_history_filters_by_product(self):
        entries, _ = build_history_tracking(
            bakery=self.bakery,
            product=self.croissant,
        )
        self.assertEqual(
            [entry['record'] for entry in entries],
            [self.sale, self.old_production],
        )

    def test_history_filters_by_date_range(self):
        entries, _ = build_history_tracking(
            bakery=self.bakery,
            start_date=self.recent_date.date(),
            end_date=self.recent_date.date(),
        )
        self.assertEqual(
            [entry['record'] for entry in entries],
            [self.recent_production],
        )

    def test_history_rejects_inverted_date_range(self):
        with self.assertRaises(ValidationError):
            build_history_tracking(
                bakery=self.bakery,
                start_date=self.recent_date.date(),
                end_date=self.old_date.date(),
            )

    def test_cancelled_production_is_not_counted_in_totals(self):
        self.old_production.status = ProductionRecord.Status.CANCELLED
        self.old_production.save()

        entries, totals = build_history_tracking(
            bakery=self.bakery,
        )
        self.assertEqual(len(entries), 3)
        self.assertEqual(totals['produced_quantity'], Decimal('20.00'))

    def test_history_excludes_other_bakeries(self):
        other_bakery = Bakery.objects.create(
            name='Other Bakery',
            address='Other Address',
        )
        other_product = register_product(
            bakery=other_bakery,
            name='Muffin',
            sku='MUF-001',
            unit_price=Decimal('1000.00'),
        )
        register_daily_production(
            bakery=other_bakery,
            product=other_product,
            produced_quantity=Decimal('5.00'),
            production_date=timezone.now(),
        )

        entries, _ = build_history_tracking(bakery=self.bakery)
        self.assertNotIn(
            other_product,
            [entry['product'] for entry in entries],
        )

    def test_history_view_lists_records(self):
        response = self.client.get(reverse('production:history_tracking'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Croissant')
        self.assertContains(response, 'Bread')
        self.assertEqual(len(response.context['entries']), 3)

    def test_history_view_applies_filters(self):
        response = self.client.get(
            reverse('production:history_tracking'),
            {'type': 'sales', 'product': str(self.croissant.pk)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [entry['record'] for entry in response.context['entries']],
            [self.sale],
        )

    def test_history_view_reports_inverted_date_range(self):
        response = self.client.get(
            reverse('production:history_tracking'),
            {'start_date': '2026-02-10', 'end_date': '2026-02-01'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['entries'], [])
        self.assertContains(
            response,
            'The start date cannot be later than the end date.',
        )

    def test_history_view_ignores_unknown_product_and_type(self):
        response = self.client.get(
            reverse('production:history_tracking'),
            {'type': 'bogus', 'product': 'not-a-uuid'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['entries']), 3)

    def test_history_view_redirects_without_bakery(self):
        SalesRecord.objects.all().delete()
        ProductionRecord.objects.all().delete()
        Product.objects.all().delete()
        Bakery.objects.all().delete()
        response = self.client.get(reverse('production:history_tracking'))
        self.assertRedirects(response, reverse('bakery:setup'))


class SalesAnalyticsTests(TestCase):
    """FR36 - Sales analytics (best-selling products)."""

    def setUp(self):
        self.bakery = Bakery.objects.create(
            name='Test Bakery',
            address='Test Address',
        )

        self.croissant = register_product(
            bakery=self.bakery,
            name='Croissant',
            sku='CRO-001',
            unit_price=Decimal('5000.00'),
        )

        self.bread = register_product(
            bakery=self.bakery,
            name='Sourdough bread',
            sku='BRE-001',
            unit_price=Decimal('12000.00'),
        )

    def _sell(self, product, quantity, when=None):
        return register_daily_sale(
            bakery=self.bakery,
            product=product,
            quantity_sold=Decimal(quantity),
            sale_timestamp=when or timezone.now(),
        )

    def test_ranks_products_from_the_best_seller_down(self):
        self._sell(self.croissant, '30.00')
        self._sell(self.bread, '4.00')

        rankings, _ = build_sales_analytics(bakery=self.bakery)

        self.assertEqual(
            [row['product_name'] for row in rankings],
            ['Croissant', 'Sourdough bread'],
        )
        self.assertEqual(rankings[0]['position'], 1)
        self.assertEqual(rankings[0]['units_sold'], Decimal('30.00'))

    def test_adds_up_several_sales_of_the_same_product(self):
        self._sell(self.croissant, '10.00')
        self._sell(self.croissant, '5.00')

        rankings, totals = build_sales_analytics(bakery=self.bakery)

        self.assertEqual(len(rankings), 1)
        self.assertEqual(rankings[0]['units_sold'], Decimal('15.00'))
        self.assertEqual(rankings[0]['sale_count'], 2)
        self.assertEqual(totals['sale_count'], 2)

    def test_the_best_seller_fills_the_whole_bar(self):
        self._sell(self.croissant, '20.00')
        self._sell(self.bread, '5.00')

        rankings, _ = build_sales_analytics(bakery=self.bakery)

        self.assertEqual(rankings[0]['units_share'], Decimal('100.0'))
        self.assertEqual(rankings[1]['units_share'], Decimal('25.0'))

    def test_revenue_share_is_measured_against_the_total(self):
        # 10 croissants at 5000 = 50000; 5 breads at 12000 = 60000.
        self._sell(self.croissant, '10.00')
        self._sell(self.bread, '5.00')

        rankings, totals = build_sales_analytics(bakery=self.bakery)

        by_name = {row['product_name']: row for row in rankings}

        self.assertEqual(totals['revenue'], Decimal('110000.00'))
        self.assertEqual(
            by_name['Sourdough bread']['revenue_share'],
            Decimal('54.5'),
        )
        self.assertEqual(
            by_name['Croissant']['revenue_share'],
            Decimal('45.5'),
        )

    def test_the_product_that_sells_most_is_not_the_one_that_earns_most(self):
        self._sell(self.croissant, '10.00')
        self._sell(self.bread, '5.00')

        rankings, _ = build_sales_analytics(bakery=self.bakery)

        self.assertEqual(rankings[0]['product_name'], 'Croissant')
        self.assertLess(rankings[0]['revenue'], rankings[1]['revenue'])

    def test_keeps_only_the_sales_inside_the_date_range(self):
        today = timezone.localdate()
        old = timezone.now() - timedelta(days=10)

        self._sell(self.croissant, '7.00', when=old)
        self._sell(self.bread, '2.00')

        rankings, totals = build_sales_analytics(
            bakery=self.bakery,
            start_date=today,
        )

        self.assertEqual(len(rankings), 1)
        self.assertEqual(rankings[0]['product_name'], 'Sourdough bread')
        self.assertEqual(totals['units_sold'], Decimal('2.00'))

    def test_rejects_a_range_that_ends_before_it_starts(self):
        today = timezone.localdate()

        with self.assertRaises(ValidationError):
            build_sales_analytics(
                bakery=self.bakery,
                start_date=today,
                end_date=today - timedelta(days=1),
            )

    def test_a_bakery_without_sales_reports_nothing(self):
        rankings, totals = build_sales_analytics(bakery=self.bakery)

        self.assertEqual(rankings, [])
        self.assertEqual(totals['units_sold'], Decimal('0'))
        self.assertEqual(totals['revenue'], Decimal('0'))
        self.assertEqual(totals['product_count'], 0)

    def test_leaves_out_the_sales_of_another_bakery(self):
        other = Bakery.objects.create(
            name='Other Bakery',
            address='Other Address',
        )
        other_product = register_product(
            bakery=other,
            name='Baguette',
            sku='BAG-001',
            unit_price=Decimal('3000.00'),
        )
        register_daily_sale(
            bakery=other,
            product=other_product,
            quantity_sold=Decimal('50.00'),
            sale_timestamp=timezone.now(),
        )
        self._sell(self.croissant, '1.00')

        rankings, _ = build_sales_analytics(bakery=self.bakery)

        self.assertEqual(
            [row['product_name'] for row in rankings],
            ['Croissant'],
        )


class SalesAnalyticsViewTests(AuthenticatedTestCase):
    """FR36 - the screen that shows the ranking."""

    def setUp(self):
        super().setUp()
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

    def _sell(self, quantity='12.00'):
        return register_daily_sale(
            bakery=self.bakery,
            product=self.product,
            quantity_sold=Decimal(quantity),
            sale_timestamp=timezone.now(),
        )

    def test_shows_the_ranking(self):
        self._sell()

        response = self.client.get(reverse('production:sales_analytics'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Croissant')
        self.assertContains(response, 'Best seller')

    def test_tells_the_user_when_there_are_no_sales_yet(self):
        response = self.client.get(reverse('production:sales_analytics'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No sales have been registered yet.')

    def test_reports_an_invalid_date_range_instead_of_failing(self):
        today = timezone.localdate()

        response = self.client.get(
            reverse('production:sales_analytics'),
            {
                'start_date': today.isoformat(),
                'end_date': (today - timedelta(days=1)).isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'The start date cannot be later than the end date.',
        )

    def test_the_bar_width_always_uses_a_decimal_point(self):
        self._sell()

        response = self.client.get(reverse('production:sales_analytics'))

        self.assertContains(response, 'width: 100.0%')

    def test_redirects_when_the_bakery_is_not_set_up(self):
        SalesRecord.objects.all().delete()
        Product.objects.all().delete()
        Bakery.objects.all().delete()

        response = self.client.get(reverse('production:sales_analytics'))

        self.assertRedirects(response, reverse('bakery:setup'))


class LossReportTests(TestCase):
    """FR26 - Loss reporting (expired ingredients and overproduction)."""

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
        self.unit = UnitOfMeasure.objects.get(abbreviation='kg')

    def expire_ingredient(self, name, *, days_ago=3, quantity='4.00'):
        return Ingredient.objects.create(
            bakery=self.bakery,
            unit=self.unit,
            name=name,
            current_quantity=Decimal(quantity),
            expiration_date=timezone.localdate() - timedelta(days=days_ago),
        )

    def overproduce(self, produced, sold, *, days_ago=0):
        when = timezone.now() - timedelta(days=days_ago)
        register_daily_production(
            bakery=self.bakery,
            product=self.product,
            produced_quantity=Decimal(produced),
            production_date=when,
        )
        if Decimal(sold) > 0:
            register_daily_sale(
                bakery=self.bakery,
                product=self.product,
                quantity_sold=Decimal(sold),
                sale_timestamp=when,
            )
        return when

    def test_reports_both_sources_of_loss_together(self):
        self.expire_ingredient('Flour')
        self.overproduce('20.00', '12.00')

        report = build_loss_report(bakery=self.bakery)

        self.assertEqual(len(report['expired_ingredients']), 1)
        self.assertEqual(len(report['overproduction']), 1)

    def test_values_the_unsold_products_at_their_price(self):
        self.overproduce('20.00', '12.00')

        report = build_loss_report(bakery=self.bakery)
        row = report['overproduction'][0]

        self.assertEqual(row['unsold_quantity'], Decimal('8.00'))
        self.assertEqual(row['unit_price'], Decimal('5000.00'))
        self.assertEqual(row['lost_value'], Decimal('40000.00'))
        self.assertEqual(report['totals']['lost_value'], Decimal('40000.00'))

    def test_a_day_sold_out_is_not_overproduction(self):
        self.overproduce('10.00', '10.00')

        report = build_loss_report(bakery=self.bakery)

        self.assertEqual(report['overproduction'], [])
        self.assertEqual(report['totals']['lost_value'], Decimal('0'))

    def test_adds_up_the_totals_of_both_sources(self):
        self.expire_ingredient('Flour', quantity='4.00')
        self.expire_ingredient('Sugar', quantity='1.50')
        self.overproduce('20.00', '12.00')

        totals = build_loss_report(bakery=self.bakery)['totals']

        self.assertEqual(totals['expired_ingredient_count'], 2)
        self.assertEqual(totals['expired_quantity'], Decimal('5.50'))
        self.assertEqual(totals['unsold_quantity'], Decimal('8.00'))
        self.assertEqual(totals['overproduction_days'], 1)

    def test_keeps_only_the_overproduction_inside_the_range(self):
        self.overproduce('20.00', '12.00', days_ago=10)
        self.overproduce('5.00', '1.00', days_ago=0)

        report = build_loss_report(
            bakery=self.bakery,
            start_date=timezone.localdate(),
        )

        self.assertEqual(len(report['overproduction']), 1)
        self.assertEqual(
            report['overproduction'][0]['unsold_quantity'],
            Decimal('4.00'),
        )

    def test_rejects_a_range_that_ends_before_it_starts(self):
        today = timezone.localdate()

        with self.assertRaises(ValidationError):
            build_loss_report(
                bakery=self.bakery,
                start_date=today,
                end_date=today - timedelta(days=1),
            )

    def test_a_bakery_with_nothing_lost_reports_zeros(self):
        report = build_loss_report(bakery=self.bakery)

        self.assertEqual(report['expired_ingredients'], [])
        self.assertEqual(report['overproduction'], [])
        self.assertEqual(report['totals']['lost_value'], Decimal('0'))
        self.assertEqual(report['totals']['expired_quantity'], Decimal('0'))


class LossReportViewTests(AuthenticatedTestCase):
    """FR26 - the screen that shows the losses."""

    def setUp(self):
        super().setUp()
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

    def test_shows_the_overproduction(self):
        when = timezone.now()
        register_daily_production(
            bakery=self.bakery,
            product=self.product,
            produced_quantity=Decimal('20.00'),
            production_date=when,
        )
        register_daily_sale(
            bakery=self.bakery,
            product=self.product,
            quantity_sold=Decimal('12.00'),
            sale_timestamp=when,
        )

        response = self.client.get(reverse('production:loss_report'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Croissant')
        self.assertContains(response, 'Value not earned')

    def test_says_so_when_nothing_was_lost(self):
        response = self.client.get(reverse('production:loss_report'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No ingredient expired with stock left.')
        self.assertContains(
            response,
            'Every product produced so far has been sold.',
        )

    def test_reports_an_invalid_date_range_instead_of_failing(self):
        today = timezone.localdate()

        response = self.client.get(
            reverse('production:loss_report'),
            {
                'start_date': today.isoformat(),
                'end_date': (today - timedelta(days=1)).isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'The start date cannot be later than the end date.',
        )

    def test_redirects_when_the_bakery_is_not_set_up(self):
        SalesRecord.objects.all().delete()
        ProductionRecord.objects.all().delete()
        Product.objects.all().delete()
        Bakery.objects.all().delete()

        response = self.client.get(reverse('production:loss_report'))

        self.assertRedirects(response, reverse('bakery:setup'))


class DailyClosingTestMixin:
    """Shared data for the FR27 daily closing tests."""

    def make_closing_data(self):
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
        self.unit = UnitOfMeasure.objects.get(abbreviation='kg')
        self.now = timezone.now()
        self.today = timezone.localdate(self.now)

    def ingredient(self, name, *, quantity='10.00', expires_in=30, bakery=None):
        return Ingredient.objects.create(
            bakery=bakery or self.bakery,
            unit=self.unit,
            name=name,
            current_quantity=Decimal(quantity),
            expiration_date=self.today + timedelta(days=expires_in),
        )

    def produce_and_sell(self, produced, sold, *, when=None, product=None, bakery=None):
        when = when or self.now
        product = product or self.product
        bakery = bakery or self.bakery
        register_daily_production(
            bakery=bakery,
            product=product,
            produced_quantity=Decimal(produced),
            production_date=when,
        )
        if Decimal(sold) > 0:
            register_daily_sale(
                bakery=bakery,
                product=product,
                quantity_sold=Decimal(sold),
                sale_timestamp=when,
            )


class DailyClosingSummaryTests(DailyClosingTestMixin, TestCase):
    """FR27 - What the closing summary of a day contains."""

    def setUp(self):
        self.make_closing_data()

    def summary(self, business_date=None):
        # A fresh instance, as each request gets: Django caches a missing
        # notification preference on the object after the first look.
        return build_daily_closing_summary(
            bakery=Bakery.objects.get(pk=self.bakery.pk),
            business_date=business_date or self.today,
        )

    def test_summarises_the_production_and_sales_of_each_product(self):
        self.produce_and_sell('20.00', '7.00')

        summary = self.summary()

        self.assertEqual(summary['business_date'], self.today.isoformat())
        self.assertEqual(summary['products'], [{
            'product_name': 'Croissant',
            'produced_quantity': '20.00',
            'sold_quantity': '7.00',
            'unsold_quantity': '13.00',
            'sale_count': 1,
            'revenue': '35000.00',
        }])
        self.assertEqual(summary['totals']['units_produced'], '20.00')
        self.assertEqual(summary['totals']['units_sold'], '7.00')
        self.assertEqual(summary['totals']['revenue'], '35000.00')
        self.assertEqual(summary['totals']['sale_count'], 1)

    def test_leaves_out_other_days_and_other_bakeries(self):
        other = Bakery.objects.create(name='Other bakery', address='Other address')
        other_product = register_product(
            bakery=other, name='Baguette', unit_price=Decimal('3000.00'),
        )
        self.produce_and_sell('20.00', '7.00', when=self.now - timedelta(days=1))
        self.produce_and_sell('5.00', '5.00', product=other_product, bakery=other)

        summary = self.summary()

        self.assertEqual(summary['products'], [])
        self.assertEqual(summary['totals']['revenue'], '0.00')

    def test_summarises_the_stock_movements_of_each_ingredient(self):
        flour = self.ingredient('Flour')
        register_stock_in(bakery=self.bakery, ingredient=flour, quantity=Decimal('5.00'))
        register_stock_consumption(bakery=self.bakery, ingredient=flour, quantity=Decimal('3.00'))
        register_inventory_correction(
            bakery=self.bakery, ingredient=flour, new_quantity=Decimal('11.50'),
            reason='Physical count', user=None,
        )

        stock = self.summary()['stock']

        self.assertEqual(stock['ingredients'], [{
            'ingredient_name': 'Flour',
            'unit': 'kg',
            'stock_in': '5.00',
            'consumption': '3.00',
            'correction_count': 1,
            'movement_count': 3,
        }])
        self.assertEqual(len(stock['corrections']), 1)
        correction = stock['corrections'][0]
        self.assertEqual(correction['previous_quantity'], '12.00')
        self.assertEqual(correction['new_quantity'], '11.50')
        self.assertEqual(correction['reason'], 'Physical count')

    def test_leaves_out_the_stock_movements_of_another_day(self):
        flour = self.ingredient('Flour')
        movement = register_stock_in(
            bakery=self.bakery, ingredient=flour, quantity=Decimal('5.00'),
        )
        StockMovement.objects.filter(pk=movement.pk).update(
            movement_date=self.now - timedelta(days=2),
        )

        self.assertEqual(self.summary()['stock']['ingredients'], [])

    def test_lists_the_inventory_alerts_at_closing(self):
        low = self.ingredient('Butter', quantity='1.00')
        AlertConfiguration.objects.create(ingredient=low, minimum_stock_threshold=Decimal('2.00'))
        soon = self.ingredient('Milk', expires_in=2)
        AlertConfiguration.objects.create(ingredient=soon, expiration_warning_days=5)
        self.ingredient('Old yeast', expires_in=-3)
        self.ingredient('Sugar')

        alerts = self.summary()['alerts']

        self.assertEqual([row['ingredient_name'] for row in alerts['low_stock']], ['Butter'])
        self.assertEqual(alerts['low_stock'][0]['threshold'], '2.00')
        self.assertEqual([row['ingredient_name'] for row in alerts['expiring_soon']], ['Milk'])
        self.assertEqual([row['ingredient_name'] for row in alerts['expired']], ['Old yeast'])
        self.assertEqual(alerts['evaluated_on'], self.today.isoformat())

    def test_alerts_turned_off_in_the_preferences_are_left_out(self):
        low = self.ingredient('Butter', quantity='1.00')
        AlertConfiguration.objects.create(ingredient=low, minimum_stock_threshold=Decimal('2.00'))
        self.ingredient('Old yeast', expires_in=-3)
        NotificationPreference.objects.create(
            bakery=self.bakery, low_stock_enabled=False, expiration_enabled=False,
        )
        self.bakery.refresh_from_db()

        alerts = self.summary()['alerts']

        self.assertFalse(alerts['low_stock_enabled'])
        self.assertFalse(alerts['expiration_enabled'])
        self.assertEqual(alerts['low_stock'], [])
        self.assertEqual(alerts['expired'], [])

    def test_values_the_overproduction_of_the_day(self):
        self.produce_and_sell('20.00', '7.00')

        losses = self.summary()['losses']

        self.assertEqual(losses['overproduction'], [{
            'product_name': 'Croissant',
            'unsold_quantity': '13.00',
            'unit_price': '5000.00',
            'lost_value': '65000.00',
        }])

    def test_a_day_sold_out_has_no_overproduction(self):
        self.produce_and_sell('10.00', '10.00')

        summary = self.summary()

        self.assertEqual(summary['losses']['overproduction'], [])
        self.assertEqual(summary['totals']['lost_value'], '0.00')

    def test_reports_the_ingredients_whose_life_ends_with_the_day(self):
        self.ingredient('Cream', quantity='2.00', expires_in=0)
        self.ingredient('Old yeast', expires_in=-3)
        self.ingredient('Empty cream', quantity='0.00', expires_in=0)

        expired = self.summary()['losses']['expired_ingredients']

        self.assertEqual(expired, [{
            'ingredient_name': 'Cream',
            'quantity': '2.00',
            'unit': 'kg',
            'expiration_date': self.today.isoformat(),
        }])

    def test_lists_the_orders_scheduled_for_the_next_day(self):
        tomorrow = self.now + timedelta(days=1)
        ScheduledOrder.objects.create(
            bakery=self.bakery, product=self.product, customer_name='Ana',
            quantity=12, scheduled_for=tomorrow, notes='Birthday',
        )
        ScheduledOrder.objects.create(
            bakery=self.bakery, product=self.product, customer_name='Luis',
            quantity=3, scheduled_for=self.now + timedelta(days=3),
        )

        orders = self.summary()['next_day_orders']

        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]['customer_name'], 'Ana')
        self.assertEqual(orders[0]['product_name'], 'Croissant')
        self.assertEqual(orders[0]['quantity'], 12)
        self.assertEqual(orders[0]['notes'], 'Birthday')

    def test_a_quiet_day_reports_zeros(self):
        summary = self.summary()

        self.assertEqual(summary['products'], [])
        self.assertEqual(summary['stock'], {'ingredients': [], 'corrections': []})
        self.assertEqual(summary['next_day_orders'], [])
        self.assertEqual(summary['totals']['units_produced'], '0.00')
        self.assertEqual(summary['totals']['revenue'], '0.00')
        self.assertEqual(summary['totals']['alert_count'], 0)

    def test_the_summary_is_plain_json(self):
        self.produce_and_sell('20.00', '7.00')

        summary = self.summary()

        self.assertEqual(json.loads(json.dumps(summary)), summary)

    def test_the_query_count_does_not_grow_with_the_records(self):
        self.produce_and_sell('20.00', '7.00')
        self.ingredient('Flour')
        with CaptureQueriesContext(connection) as few:
            self.summary()

        for number in range(10):
            product = register_product(
                bakery=self.bakery, name=f'Bread {number}', unit_price=Decimal('100.00'),
            )
            self.produce_and_sell('5.00', '2.00', product=product)
            flour = self.ingredient(f'Flour {number}')
            register_stock_in(bakery=self.bakery, ingredient=flour, quantity=Decimal('1.00'))
        with CaptureQueriesContext(connection) as many:
            self.summary()

        self.assertEqual(len(few), len(many))


class CloseBusinessDayTests(DailyClosingTestMixin, TestCase):
    """FR27 - Closing a business day stores its summary."""

    def setUp(self):
        self.make_closing_data()
        self.user = get_user_model().objects.create_user(username='baker')

    def test_closing_stores_the_summary_and_its_totals(self):
        self.produce_and_sell('20.00', '7.00')

        closing, created = close_business_day(
            bakery=self.bakery, business_date=self.today, user=self.user,
        )

        self.assertTrue(created)
        self.assertEqual(closing.business_date, self.today)
        self.assertEqual(closing.closed_by, self.user)
        self.assertEqual(closing.units_produced, Decimal('20.00'))
        self.assertEqual(closing.units_sold, Decimal('7.00'))
        self.assertEqual(closing.revenue, Decimal('35000.00'))
        self.assertEqual(closing.lost_value, Decimal('65000.00'))
        self.assertEqual(closing.content['products'][0]['product_name'], 'Croissant')

    def test_closing_a_day_again_replaces_its_summary(self):
        close_business_day(bakery=self.bakery, business_date=self.today, user=self.user)
        self.produce_and_sell('20.00', '7.00')

        closing, created = close_business_day(
            bakery=self.bakery, business_date=self.today, user=self.user,
        )

        self.assertFalse(created)
        self.assertEqual(DailyClosingSummary.objects.filter(bakery=self.bakery).count(), 1)
        self.assertEqual(closing.revenue, Decimal('35000.00'))

    def test_the_stored_summary_does_not_change_with_later_records(self):
        closing, _created = close_business_day(bakery=self.bakery, business_date=self.today)
        self.produce_and_sell('20.00', '7.00')

        closing.refresh_from_db()

        self.assertEqual(closing.content['products'], [])
        self.assertEqual(closing.revenue, Decimal('0.00'))

    def test_a_past_day_can_be_closed(self):
        yesterday = self.today - timedelta(days=1)
        self.produce_and_sell('8.00', '8.00', when=self.now - timedelta(days=1))

        closing, created = close_business_day(bakery=self.bakery, business_date=yesterday)

        self.assertTrue(created)
        self.assertEqual(closing.units_sold, Decimal('8.00'))

    def test_a_day_that_has_not_started_cannot_be_closed(self):
        with self.assertRaises(ValidationError):
            close_business_day(
                bakery=self.bakery, business_date=self.today + timedelta(days=1),
            )
        self.assertFalse(DailyClosingSummary.objects.exists())

    def test_closing_is_recorded_in_the_activity_log(self):
        close_business_day(bakery=self.bakery, business_date=self.today, user=self.user)
        close_business_day(bakery=self.bakery, business_date=self.today, user=self.user)

        entries = list(
            ActivityLog.objects
            .filter(action_type=ActivityLog.ActionType.DAILY_CLOSING)
            .order_by('created_at')
        )

        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].user, self.user)
        self.assertIn('Closed the business day', entries[0].description)
        self.assertIn('Regenerated', entries[1].description)

    def test_each_bakery_closes_its_own_days(self):
        other = Bakery.objects.create(name='Other bakery', address='Other address')
        close_business_day(bakery=self.bakery, business_date=self.today)

        closing, created = close_business_day(bakery=other, business_date=self.today)

        self.assertTrue(created)
        self.assertEqual(DailyClosingSummary.objects.count(), 2)


class DailyClosingViewTests(DailyClosingTestMixin, AuthenticatedTestCase):
    """FR27 - Closing a day from the web interface."""

    def setUp(self):
        super().setUp()
        self.make_closing_data()
        self.url = reverse('production:daily_closing')

    def close(self, business_date=None, **extra):
        return self.client.post(self.url, {
            'business_date': (business_date or self.today).isoformat(),
            **extra,
        })

    def test_the_page_proposes_to_close_today(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Close the day')
        self.assertContains(response, f'value="{self.today.isoformat()}"')
        self.assertContains(response, 'No business day has been closed yet.')

    def test_the_menu_links_to_the_daily_closing(self):
        response = self.client.get(reverse('home'))

        self.assertContains(response, self.url)

    def test_closing_from_the_web_shows_the_summary(self):
        self.produce_and_sell('20.00', '7.00')

        response = self.close()

        closing = DailyClosingSummary.objects.get(bakery=self.bakery)
        self.assertRedirects(
            response,
            reverse('production:daily_closing_detail', kwargs={'closing_id': closing.pk}),
            fetch_redirect_response=False,
        )
        self.assertEqual(closing.closed_by, self.auth_user)

        detail = self.client.get(response.url)
        self.assertContains(detail, 'Croissant')
        self.assertContains(detail, '35000.00')
        self.assertContains(detail, 'Business day closed successfully.')

    def test_a_closed_day_needs_confirmation_to_be_regenerated(self):
        self.close()
        self.produce_and_sell('20.00', '7.00')

        response = self.close()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'This day is already closed.')
        closing = DailyClosingSummary.objects.get(bakery=self.bakery)
        self.assertEqual(closing.revenue, Decimal('0.00'))

        response = self.close(confirm_regenerate='on')

        closing.refresh_from_db()
        self.assertRedirects(
            response,
            reverse('production:daily_closing_detail', kwargs={'closing_id': closing.pk}),
        )
        self.assertEqual(closing.revenue, Decimal('35000.00'))

    def test_a_future_day_is_rejected(self):
        response = self.close(self.today + timedelta(days=1))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'A day that has not started yet cannot be closed.')
        self.assertFalse(DailyClosingSummary.objects.exists())

    def test_the_closed_days_are_listed(self):
        self.close(self.today - timedelta(days=1))
        self.close()

        response = self.client.get(self.url)

        self.assertContains(response, self.today.isoformat())
        self.assertContains(response, (self.today - timedelta(days=1)).isoformat())
        self.assertContains(response, 'View summary', count=2)

    def test_the_summary_of_another_bakery_is_not_found(self):
        other = Bakery.objects.create(name='Other bakery', address='Other address')
        closing, _created = close_business_day(bakery=other, business_date=self.today)

        detail = self.client.get(
            reverse('production:daily_closing_detail', kwargs={'closing_id': closing.pk})
        )
        export = self.client.get(
            reverse('production:daily_closing_export', kwargs={'closing_id': closing.pk}),
            {'format': 'pdf'},
        )

        self.assertEqual(detail.status_code, 404)
        self.assertEqual(export.status_code, 404)

    def test_redirects_when_the_bakery_is_not_set_up(self):
        Product.objects.all().delete()
        Bakery.objects.all().delete()

        response = self.client.get(self.url)

        self.assertRedirects(response, reverse('bakery:setup'))

    def test_closing_takes_less_than_five_seconds_on_a_busy_day(self):
        products = Product.objects.bulk_create([
            Product(bakery=self.bakery, name=f'Bread {number}', unit_price=Decimal('1500.00'))
            for number in range(200)
        ])
        ProductionRecord.objects.bulk_create([
            ProductionRecord(
                bakery=self.bakery, product=product,
                produced_quantity=Decimal('30.00'), production_date=self.now,
            )
            for product in products
        ])
        SalesRecord.objects.bulk_create([
            SalesRecord(
                bakery=self.bakery, product=product, quantity_sold=Decimal('25.00'),
                unit_price_at_sale=Decimal('1500.00'), total_amount=Decimal('37500.00'),
                sale_timestamp=self.now,
            )
            for product in products
        ])
        ingredients = Ingredient.objects.bulk_create([
            Ingredient(
                bakery=self.bakery, unit=self.unit, name=f'Ingredient {number}',
                current_quantity=Decimal('10.00'),
                expiration_date=self.today + timedelta(days=number % 10),
            )
            for number in range(200)
        ])
        StockMovement.objects.bulk_create([
            StockMovement(
                bakery=self.bakery, ingredient=ingredient,
                movement_type='StockIn', quantity=Decimal('2.00'),
            )
            for ingredient in ingredients
        ])

        started = perf_counter()
        response = self.close()
        elapsed = perf_counter() - started

        self.assertEqual(response.status_code, 302)
        self.assertLess(elapsed, 5)
        closing = DailyClosingSummary.objects.get(bakery=self.bakery)
        self.assertEqual(len(closing.content['products']), 200)

    def test_the_page_is_translated_to_spanish(self):
        self.client.post(reverse('set_language'), {'language': 'es', 'next': self.url})

        response = self.client.get(self.url)

        self.assertContains(response, 'Cierre del día')
        self.assertContains(response, 'Cerrar el día')


class DailyClosingExportTests(DailyClosingTestMixin, AuthenticatedTestCase):
    """FR27 - Downloading a closing summary as Excel or PDF."""

    def setUp(self):
        super().setUp()
        self.make_closing_data()
        self.produce_and_sell('20.00', '7.00')
        self.closing, _created = close_business_day(
            bakery=self.bakery, business_date=self.today, user=self.auth_user,
        )
        self.url = reverse(
            'production:daily_closing_export', kwargs={'closing_id': self.closing.pk},
        )

    def test_the_summary_page_offers_both_downloads(self):
        response = self.client.get(
            reverse('production:daily_closing_detail', kwargs={'closing_id': self.closing.pk})
        )

        self.assertContains(response, f'{self.url}?format=xlsx')
        self.assertContains(response, f'{self.url}?format=pdf')

    def test_the_excel_file_is_readable_and_holds_the_summary(self):
        response = self.client.get(self.url, {'format': 'xlsx'})

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            f'daily_closing_{self.today.isoformat()}.xlsx',
            response['Content-Disposition'],
        )
        workbook = load_workbook(BytesIO(response.content), read_only=True)
        rows = list(workbook.active.values)
        workbook.close()
        cells = [cell for row in rows for cell in row if cell is not None]
        self.assertIn('Daily closing summary', cells)
        self.assertIn('Production and sales', cells)
        self.assertIn('Croissant', cells)
        self.assertIn(35000.0, cells)
        self.assertIn('Orders for the next day', cells)

    def test_the_pdf_file_is_readable_and_holds_the_summary(self):
        response = self.client.get(self.url, {'format': 'pdf'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        text = '\n'.join(
            page.extract_text() for page in PdfReader(BytesIO(response.content)).pages
        )
        self.assertIn('Daily closing summary', text)
        self.assertIn('Croissant', text)
        self.assertIn('35000.00', text)

    def test_an_unknown_format_is_rejected(self):
        response = self.client.get(self.url, {'format': 'docx'})

        self.assertEqual(response.status_code, 400)

    def test_post_is_not_allowed(self):
        response = self.client.post(self.url, {'format': 'pdf'})

        self.assertEqual(response.status_code, 405)

    def test_excel_escapes_formula_prefixes_in_product_names(self):
        product = register_product(
            bakery=self.bakery, name='=HYPERLINK("http://x")', unit_price=Decimal('10.00'),
        )
        self.produce_and_sell('1.00', '1.00', product=product)
        close_business_day(bakery=self.bakery, business_date=self.today)

        response = self.client.get(self.url, {'format': 'xlsx'})

        workbook = load_workbook(BytesIO(response.content), read_only=True)
        cells = [cell for row in workbook.active.values for cell in row if cell is not None]
        workbook.close()
        self.assertIn('\'=HYPERLINK("http://x")', cells)
