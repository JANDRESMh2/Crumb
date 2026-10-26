"""Tests for the language switcher that sits in the header.

The interface ships in English and in Spanish. What matters here is that the
visitor gets the right one, that their choice sticks, and that switching to
Spanish does not break the numbers the templates write into CSS.
"""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from bakery.models import Bakery
from production.services import register_daily_sale, register_product


class LanguageSwitcherTests(TestCase):
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
