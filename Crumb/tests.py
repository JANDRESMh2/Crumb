"""Tests for the language switcher that sits in the header.

The interface ships in English and in Spanish. What matters here is that the
visitor gets the right one, that their choice sticks, and that switching to
Spanish does not break the numbers the templates write into CSS.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from Crumb.testutils import AuthenticatedTestCase
from bakery.models import Bakery
from production.models import Product, SalesRecord
from production.services import register_daily_sale, register_product


class LanguageSwitcherTests(AuthenticatedTestCase):
    def setUp(self):
        super().setUp()
        self.bakery = Bakery.objects.create(
            name='El Buen Pan',
            address='Calle 10 #20-30',
        )
        self.product = register_product(
            bakery=self.bakery,
            name='Croissant',
            sku='CRO-001',
            unit_price=Decimal('5000.00'),
        )
        register_daily_sale(
            bakery=self.bakery,
            product=self.product,
            quantity_sold=Decimal('12.00'),
            sale_timestamp=timezone.now(),
        )
        self.url = reverse('production:sales_analytics')

    def elegir(self, idioma):
        return self.client.post(
            reverse('set_language'),
            {'language': idioma, 'next': self.url},
        )

    def test_the_interface_is_in_english_by_default(self):
        response = self.client.get(self.url)

        self.assertContains(response, 'Sales analytics')
        self.assertNotContains(response, 'Análisis de ventas')

    def test_the_interface_follows_the_language_of_the_browser(self):
        response = self.client.get(self.url, headers={'accept-language': 'es'})

        self.assertContains(response, 'Análisis de ventas')

    def test_the_header_offers_both_languages(self):
        response = self.client.get(self.url)

        self.assertContains(response, reverse('set_language'))
        self.assertContains(response, 'name="language"')
        self.assertContains(response, 'value="en"')
        self.assertContains(response, 'value="es"')

    def test_choosing_spanish_translates_the_page(self):
        self.elegir('es')

        response = self.client.get(self.url)

        self.assertContains(response, 'Análisis de ventas')
        self.assertContains(response, 'Lo más vendido')

    def test_the_choice_wins_over_the_language_of_the_browser(self):
        self.elegir('en')

        response = self.client.get(self.url, headers={'accept-language': 'es'})

        self.assertContains(response, 'Sales analytics')

    def test_the_choice_survives_the_next_request(self):
        self.elegir('es')

        self.client.get(self.url)
        response = self.client.get(reverse('production:loss_report'))

        self.assertContains(response, 'Reporte de pérdidas')

    def test_the_page_declares_the_language_it_is_written_in(self):
        self.elegir('es')

        response = self.client.get(self.url)

        self.assertContains(response, '<html lang="es">')

    def test_switching_back_to_english_works(self):
        self.elegir('es')
        self.elegir('en')

        response = self.client.get(self.url)

        self.assertContains(response, 'Sales analytics')

    def test_spanish_does_not_break_the_width_of_the_bars(self):
        """Spanish writes decimals with a comma, which CSS does not accept.

        The width of each bar has to stay a plain number, or every bar
        collapses to nothing.
        """
        self.elegir('es')

        response = self.client.get(self.url)

        self.assertContains(response, 'width: 100.0%')
        self.assertNotContains(response, 'width: 100,0%')

    def test_spanish_still_writes_amounts_the_way_the_reader_expects(self):
        self.elegir('es')

        response = self.client.get(self.url)

        # el mismo separador decimal que acepta el formulario de entrada
        self.assertContains(response, '100,0%')


class ActivityDescriptionLanguageTests(TestCase):
    """What gets stored in the activity log follows the active language."""

    def setUp(self):
        self.bakery = Bakery.objects.create(
            name='El Buen Pan',
            address='Calle 10 #20-30',
        )
        self.product = register_product(
            bakery=self.bakery,
            name='Croissant',
            sku='CRO-001',
            unit_price=Decimal('5000.00'),
        )

    def test_a_sale_registered_in_spanish_is_described_in_spanish(self):
        from django.utils import translation

        from bakery.models import ActivityLog

        with translation.override('es'):
            register_daily_sale(
                bakery=self.bakery,
                product=self.product,
                quantity_sold=Decimal('3.00'),
                sale_timestamp=timezone.now(),
            )

        entry = ActivityLog.objects.get()
        self.assertIn('Se registró la venta', entry.description)


class DashboardHomeTests(AuthenticatedTestCase):
    """FR33 - The home page shows the bakery dashboard."""

    def setUp(self):
        super().setUp()
        self.bakery = Bakery.objects.create(
            name='El Buen Pan',
            address='Calle 10 #20-30',
        )
        self.product = register_product(
            bakery=self.bakery,
            name='Croissant',
            sku='CRO-001',
            unit_price=Decimal('5000.00'),
        )
        register_daily_sale(
            bakery=self.bakery,
            product=self.product,
            quantity_sold=Decimal('7.00'),
            sale_timestamp=timezone.now(),
        )
        self.url = reverse('home')

    def test_the_home_page_shows_the_indicators(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Active ingredients')
        self.assertContains(response, 'Revenue today')
        self.assertContains(response, '35000.00')
        self.assertContains(response, 'Best sellers, last 7 days')
        self.assertContains(response, 'Croissant')
        self.assertContains(response, 'Today is not closed yet')
        self.assertContains(response, 'Quick actions')

    def test_the_indicators_link_to_the_detailed_screens(self):
        response = self.client.get(self.url)

        for name in (
            'inventory:list',
            'production:sales_analytics',
            'production:loss_report',
            'production:scheduled_orders',
            'production:daily_closing',
        ):
            self.assertContains(response, f'href="{reverse(name)}"')

    def test_the_change_against_the_previous_week_is_shown(self):
        register_daily_sale(
            bakery=self.bakery,
            product=self.product,
            quantity_sold=Decimal('14.00'),
            sale_timestamp=timezone.now() - timedelta(days=10),
        )

        response = self.client.get(self.url)

        self.assertContains(response, '-50.0%')

    def test_without_a_previous_week_there_is_nothing_to_compare(self):
        response = self.client.get(self.url)

        self.assertContains(response, 'No sales in the previous period to compare')

    def test_without_a_bakery_the_home_page_invites_to_set_it_up(self):
        SalesRecord.objects.all().delete()
        Product.objects.all().delete()
        Bakery.objects.all().delete()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['dashboard'])
        self.assertNotContains(response, 'Revenue today')
        self.assertContains(response, "Start by setting up your bakery")

    def test_the_dashboard_is_translated_to_spanish(self):
        self.client.post(reverse('set_language'), {'language': 'es', 'next': self.url})

        response = self.client.get(self.url)

        self.assertContains(response, 'Ingresos de hoy')
        self.assertContains(response, 'Más vendidos, últimos 7 días')
        self.assertContains(response, '35000,00')
