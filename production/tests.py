from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from bakery.models import Bakery
from inventory.models import Ingredient, UnitOfMeasure

from .forms import (
    DailyProductionRegistrationForm,
    DailySalesRegistrationForm,
    ProductEditForm,
)
from .models import Product, ProductionRecord, SalesRecord
from .services import (
    build_daily_unsold_products,
    build_history_tracking,
    build_loss_report,
    build_sales_analytics,
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

class ProductionSalesHistoryTests(TestCase):
    """FR25 - view the history of production and sales records."""

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


class SalesAnalyticsViewTests(TestCase):
    """FR36 - the screen that shows the ranking."""

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


class LossReportViewTests(TestCase):
    """FR26 - the screen that shows the losses."""

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
