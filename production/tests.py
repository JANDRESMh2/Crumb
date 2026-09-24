from datetime import date

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from bakery.models import Bakery

from .forms import DailyProductionRegistrationForm
from .models import Product, ProductionRecord
from .services import (
    register_daily_production,
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
        )

    def test_register_daily_production(self):
        """FR12 - A valid production record is created."""

        record = register_daily_production(
            bakery=self.bakery,
            product=self.product,
            quantity=50,
            production_date=date(2026, 9, 23),
        )

        self.assertEqual(record.quantity, 50)

        self.assertEqual(
            record.product,
            self.product,
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
                quantity=0,
                production_date=date(2026, 9, 23),
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
                quantity=10,
                production_date=date(2026, 9, 23),
            )

    def test_inactive_product_is_rejected(self):
        """FR12 - Inactive products cannot be produced."""

        self.product.is_active = False
        self.product.save()

        with self.assertRaises(ValidationError):
            register_daily_production(
                bakery=self.bakery,
                product=self.product,
                quantity=10,
                production_date=date(2026, 9, 23),
            )

    def test_form_only_displays_active_products(self):
        """FR12 - The form excludes inactive products."""

        inactive_product = register_product(
            bakery=self.bakery,
            name='Baguette',
        )

        inactive_product.is_active = False
        inactive_product.save()

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


class ProductionViewTests(TestCase):

    def setUp(self):
        self.bakery = Bakery.objects.create(
            name='Test Bakery',
            address='Test Address',
        )

        self.product = register_product(
            bakery=self.bakery,
            name='Croissant',
        )

    def test_production_page_loads(self):
        """The production registration page is accessible."""

        response = self.client.get(
            reverse('production:register')
        )

        self.assertEqual(response.status_code, 200)

        self.assertContains(
            response,
            'Register daily production',
        )

    def test_register_product_from_web(self):
        """Products can be registered through the web interface."""

        response = self.client.post(
            reverse('production:product_create'),
            {'name': 'Pandebono'},
        )

        self.assertRedirects(
            response,
            reverse('production:register'),
        )

        self.assertTrue(
            Product.objects.filter(
                bakery=self.bakery,
                name='Pandebono',
            ).exists()
        )

    def test_register_production_from_web(self):
        """FR12 - Production can be registered through the interface."""

        response = self.client.post(
            reverse('production:register'),
            {
                'product': self.product.pk,
                'quantity': 50,
                'production_date': timezone.localdate().isoformat(),
            },
        )

        self.assertRedirects(
            response,
            reverse('production:list'),
        )

        self.assertTrue(
            ProductionRecord.objects.filter(
                bakery=self.bakery,
                product=self.product,
                quantity=50,
            ).exists()
        )

    def test_zero_quantity_is_rejected(self):
        """FR12 - The web form rejects zero production."""

        response = self.client.post(
            reverse('production:register'),
            {
                'product': self.product.pk,
                'quantity': 0,
                'production_date': timezone.localdate().isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)

        self.assertFormError(
            response.context['form'],
            'quantity',
            'Ensure this value is greater than or equal to 1.',
        )

        self.assertEqual(
            ProductionRecord.objects.count(),
            0,
        )

    def test_product_from_another_bakery_is_rejected(self):
        """FR12 - The form rejects products belonging to another bakery."""

        another_bakery = Bakery.objects.create(
            name='Another Bakery',
            address='Another Address',
        )

        another_product = register_product(
            bakery=another_bakery,
            name='Brownie',
        )

        response = self.client.post(
            reverse('production:register'),
            {
                'product': another_product.pk,
                'quantity': 10,
                'production_date': timezone.localdate().isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)

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
            quantity=50,
            production_date=timezone.localdate(),
        )

        response = self.client.get(
            reverse('production:list')
        )

        self.assertEqual(response.status_code, 200)

        self.assertContains(response, 'Croissant')

        self.assertContains(response, '50')