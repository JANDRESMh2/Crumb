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
