from django.test import TestCase
from django.urls import reverse

from .models import Bakery
from .services import BakeryAlreadyConfigured, get_current_bakery, setup_bakery_profile


class GetCurrentBakeryTests(TestCase):
    def test_returns_none_when_not_configured(self):
        self.assertIsNone(get_current_bakery())

    def test_returns_the_configured_bakery(self):
        bakery = Bakery.objects.create(name='El Buen Pan', address='Calle 10 #20-30')
        self.assertEqual(get_current_bakery(), bakery)


class SetupBakeryProfileServiceTests(TestCase):
    def test_creates_bakery_with_required_fields(self):
        bakery = setup_bakery_profile(name='El Buen Pan', address='Calle 10 #20-30')
        self.assertEqual(bakery.name, 'El Buen Pan')
        self.assertEqual(bakery.address, 'Calle 10 #20-30')
        self.assertEqual(Bakery.objects.count(), 1)

    def test_rejects_a_second_setup(self):
        setup_bakery_profile(name='El Buen Pan', address='Calle 10 #20-30')
        with self.assertRaises(BakeryAlreadyConfigured):
            setup_bakery_profile(name='Otra Panaderia', address='Calle 99')
        self.assertEqual(Bakery.objects.count(), 1)


class BakerySetupViewTests(TestCase):
    def setUp(self):
        self.url = reverse('bakery:setup')

    def test_get_renders_the_setup_form(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Set up your bakery profile')

    def test_post_with_valid_data_creates_the_profile_and_redirects(self):
        response = self.client.post(self.url, {
            'name': 'El Buen Pan',
            'address': 'Calle 10 #20-30',
            'phone': '',
            'email': '',
            'tax_id': '',
        })
        self.assertRedirects(response, reverse('bakery:detail'))
        self.assertEqual(Bakery.objects.count(), 1)

    def test_post_missing_name_reshows_form_with_error(self):
        response = self.client.post(self.url, {
            'name': '',
            'address': 'Calle 10 #20-30',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Bakery.objects.count(), 0)
        self.assertFormError(response.context['form'], 'name', 'This field is required.')

    def test_post_missing_address_reshows_form_with_error(self):
        response = self.client.post(self.url, {
            'name': 'El Buen Pan',
            'address': '',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Bakery.objects.count(), 0)
        self.assertFormError(response.context['form'], 'address', 'This field is required.')

    def test_get_redirects_to_detail_when_already_configured(self):
        Bakery.objects.create(name='El Buen Pan', address='Calle 10 #20-30')
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse('bakery:detail'))


class BakeryDetailViewTests(TestCase):
    def test_redirects_to_setup_when_not_configured(self):
        response = self.client.get(reverse('bakery:detail'))
        self.assertRedirects(response, reverse('bakery:setup'))

    def test_shows_the_configured_profile(self):
        Bakery.objects.create(name='El Buen Pan', address='Calle 10 #20-30')
        response = self.client.get(reverse('bakery:detail'))
        self.assertContains(response, 'El Buen Pan')


class DecimalInputFieldTests(TestCase):
    """The same amount must be read identically in every browser and language."""

    def normalize(self, texto):
        from .fields import normalize_decimal_input
        return normalize_decimal_input(texto)

    def test_reads_a_dot_as_the_decimal_separator(self):
        self.assertEqual(self.normalize('12.5'), '12.5')

    def test_reads_a_comma_as_the_decimal_separator(self):
        self.assertEqual(self.normalize('12,5'), '12.5')

    def test_reads_the_spanish_thousands_format(self):
        self.assertEqual(self.normalize('1.234,56'), '1234.56')

    def test_reads_the_english_thousands_format(self):
        self.assertEqual(self.normalize('1,234.56'), '1234.56')

    def test_leaves_a_plain_number_untouched(self):
        self.assertEqual(self.normalize('18000'), '18000')

    def test_keeps_the_sign(self):
        self.assertEqual(self.normalize('-12,5'), '-12.5')

    def test_refuses_an_ambiguous_amount_instead_of_guessing(self):
        from django.core.exceptions import ValidationError
        for ambiguo in ('1,000', '18.000'):
            with self.assertRaises(ValidationError, msg=ambiguo):
                self.normalize(ambiguo)

    def test_the_field_accepts_both_separators(self):
        from decimal import Decimal
        from .fields import DecimalInputField
        campo = DecimalInputField(max_digits=10, decimal_places=2)
        self.assertEqual(campo.clean('12,5'), Decimal('12.5'))
        self.assertEqual(campo.clean('12.5'), Decimal('12.5'))

    def test_the_field_is_rendered_as_text_so_the_browser_does_not_reformat_it(self):
        from .fields import DecimalInputField
        html = DecimalInputField(max_digits=10, decimal_places=2).widget.render('quantity', '12.5')
        self.assertIn('type="text"', html)
        self.assertIn('inputmode="decimal"', html)
        self.assertNotIn('type="number"', html)
