from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from bakery.models import Bakery

from .models import Ingredient, UnitOfMeasure
from .services import register_ingredient


def make_bakery():
    return Bakery.objects.create(name='El Buen Pan', address='Calle 10 #20-30')


def make_unit(abbreviation='kg'):
    names = {'kg': ('Kilogram', 'mass'), 'g': ('Gram', 'mass'), 'u': ('Unit', 'count'), 'L': ('Liter', 'volume')}
    name, unit_type = names[abbreviation]
    return UnitOfMeasure.objects.create(name=name, abbreviation=abbreviation, unit_type=unit_type)


class UnitSeedMigrationTests(TestCase):
    def test_the_four_fr02_units_are_seeded(self):
        abbreviations = set(UnitOfMeasure.objects.values_list('abbreviation', flat=True))
        self.assertEqual(abbreviations, {'kg', 'g', 'u', 'L'})


class IngredientModelTests(TestCase):
    def test_rejects_a_negative_quantity_at_the_database_level(self):
        bakery = make_bakery()
        unit = UnitOfMeasure.objects.get(abbreviation='kg')
        ingredient = Ingredient(
            bakery=bakery, unit=unit, name='Flour',
            current_quantity=Decimal('-1.00'), expiration_date='2026-12-31',
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ingredient.save()

    def test_rejects_duplicate_name_within_the_same_bakery(self):
        bakery = make_bakery()
        unit = UnitOfMeasure.objects.get(abbreviation='kg')
        Ingredient.objects.create(
            bakery=bakery, unit=unit, name='Flour',
            current_quantity=Decimal('5.00'), expiration_date='2026-12-31',
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Ingredient.objects.create(
                    bakery=bakery, unit=unit, name='Flour',
                    current_quantity=Decimal('2.00'), expiration_date='2026-12-31',
                )

    def test_allows_same_name_across_different_bakeries(self):
        bakery_a = Bakery.objects.create(name='Panaderia A', address='Calle 1')
        bakery_b = Bakery.objects.create(name='Panaderia B', address='Calle 2')
        unit = UnitOfMeasure.objects.get(abbreviation='kg')
        Ingredient.objects.create(
            bakery=bakery_a, unit=unit, name='Flour',
            current_quantity=Decimal('5.00'), expiration_date='2026-12-31',
        )
        Ingredient.objects.create(
            bakery=bakery_b, unit=unit, name='Flour',
            current_quantity=Decimal('5.00'), expiration_date='2026-12-31',
        )
        self.assertEqual(Ingredient.objects.count(), 2)


class RegisterIngredientServiceTests(TestCase):
    def test_creates_an_ingredient_for_the_given_bakery(self):
        bakery = make_bakery()
        unit = UnitOfMeasure.objects.get(abbreviation='g')
        ingredient = register_ingredient(
            bakery=bakery, name='Sugar', unit=unit,
            current_quantity=Decimal('750.00'), expiration_date='2026-10-01',
        )
        self.assertEqual(ingredient.bakery, bakery)
        self.assertEqual(ingredient.name, 'Sugar')
        self.assertTrue(ingredient.is_active)


class IngredientCreateViewTests(TestCase):
    def setUp(self):
        self.url = reverse('inventory:create')

    def test_redirects_to_bakery_setup_when_no_bakery_is_configured(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse('bakery:setup'))

    def test_get_renders_the_registration_form(self):
        make_bakery()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Register ingredient')

    def test_post_with_valid_data_registers_the_ingredient_and_redirects(self):
        bakery = make_bakery()
        unit = UnitOfMeasure.objects.get(abbreviation='kg')
        response = self.client.post(self.url, {
            'name': 'Flour',
            'unit': str(unit.pk),
            'current_quantity': '10.50',
            'expiration_date': '2026-12-31',
        })
        self.assertRedirects(response, reverse('inventory:list'))
        ingredient = Ingredient.objects.get(name='Flour')
        self.assertEqual(ingredient.bakery, bakery)
        self.assertEqual(ingredient.current_quantity, Decimal('10.50'))

    def test_post_missing_required_fields_reshows_form_with_errors(self):
        make_bakery()
        response = self.client.post(self.url, {
            'name': '',
            'unit': '',
            'current_quantity': '',
            'expiration_date': '',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Ingredient.objects.count(), 0)
        self.assertFormError(response.context['form'], 'name', 'This field is required.')

    def test_post_with_negative_quantity_is_rejected_by_the_form(self):
        make_bakery()
        unit = UnitOfMeasure.objects.get(abbreviation='kg')
        response = self.client.post(self.url, {
            'name': 'Flour',
            'unit': str(unit.pk),
            'current_quantity': '-5.00',
            'expiration_date': '2026-12-31',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Ingredient.objects.count(), 0)

    def test_post_duplicate_name_for_the_same_bakery_is_rejected(self):
        bakery = make_bakery()
        unit = UnitOfMeasure.objects.get(abbreviation='kg')
        Ingredient.objects.create(
            bakery=bakery, unit=unit, name='Flour',
            current_quantity=Decimal('5.00'), expiration_date='2026-12-31',
        )
        response = self.client.post(self.url, {
            'name': 'flour',
            'unit': str(unit.pk),
            'current_quantity': '2.00',
            'expiration_date': '2026-12-31',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Ingredient.objects.count(), 1)


class IngredientListViewTests(TestCase):
    def test_shows_ingredients_registered_for_the_configured_bakery(self):
        bakery = make_bakery()
        unit = UnitOfMeasure.objects.get(abbreviation='kg')
        Ingredient.objects.create(
            bakery=bakery, unit=unit, name='Flour',
            current_quantity=Decimal('5.00'), expiration_date='2026-12-31',
        )
        response = self.client.get(reverse('inventory:list'))
        self.assertContains(response, 'Flour')

    def test_shows_empty_state_when_no_bakery_is_configured(self):
        response = self.client.get(reverse('inventory:list'))
        self.assertContains(response, 'No ingredients registered yet.')
