from decimal import Decimal
from time import perf_counter

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from bakery.models import Bakery

from .forms import IngredientForm
from .models import AlertConfiguration, Ingredient, UnitOfMeasure
from .services import is_ingredient_low_stock, register_ingredient


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


class UnitOfMeasureModelTests(TestCase):
    def test_rejects_units_outside_the_four_supported_by_fr02(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                UnitOfMeasure.objects.create(
                    name='Ounce', abbreviation='oz', unit_type='mass'
                )


class IngredientFormUnitTests(TestCase):
    def test_offers_exactly_the_four_supported_units(self):
        form = IngredientForm(bakery=make_bakery())

        abbreviations = set(
            form.fields['unit'].queryset.values_list('abbreviation', flat=True)
        )

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


class AlertConfigurationModelTests(TestCase):
    def setUp(self):
        self.ingredient = Ingredient.objects.create(
            bakery=make_bakery(),
            unit=UnitOfMeasure.objects.get(abbreviation='kg'),
            name='Flour',
            current_quantity=Decimal('5.00'),
            expiration_date='2026-12-31',
        )

    def test_associates_at_most_one_alert_configuration_with_an_ingredient(self):
        AlertConfiguration.objects.create(
            ingredient=self.ingredient,
            minimum_stock_threshold=Decimal('2.00'),
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AlertConfiguration.objects.create(
                    ingredient=self.ingredient,
                    minimum_stock_threshold=Decimal('3.00'),
                )

    def test_rejects_a_non_positive_minimum_stock_threshold(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AlertConfiguration.objects.create(
                    ingredient=self.ingredient,
                    minimum_stock_threshold=Decimal('0.00'),
                )


class LowStockServiceTests(TestCase):
    def setUp(self):
        self.ingredient = Ingredient.objects.create(
            bakery=make_bakery(),
            unit=UnitOfMeasure.objects.get(abbreviation='kg'),
            name='Flour',
            current_quantity=Decimal('5.00'),
            expiration_date='2026-12-31',
        )

    def configure_threshold(self, threshold, *, is_active=True):
        return AlertConfiguration.objects.create(
            ingredient=self.ingredient,
            minimum_stock_threshold=threshold,
            is_active=is_active,
        )

    def test_quantity_below_threshold_is_low_stock(self):
        self.configure_threshold(Decimal('6.00'))

        self.assertTrue(is_ingredient_low_stock(ingredient=self.ingredient))

    def test_quantity_equal_to_threshold_is_not_low_stock(self):
        self.configure_threshold(Decimal('5.00'))

        self.assertFalse(is_ingredient_low_stock(ingredient=self.ingredient))

    def test_quantity_above_threshold_is_not_low_stock(self):
        self.configure_threshold(Decimal('4.00'))

        self.assertFalse(is_ingredient_low_stock(ingredient=self.ingredient))

    def test_missing_configuration_is_not_low_stock(self):
        self.assertFalse(is_ingredient_low_stock(ingredient=self.ingredient))

    def test_inactive_configuration_is_not_low_stock(self):
        self.configure_threshold(Decimal('6.00'), is_active=False)

        self.assertFalse(is_ingredient_low_stock(ingredient=self.ingredient))


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
    def test_post_reactivates_previously_deleted_ingredient(self):
        bakery = make_bakery()
        unit = UnitOfMeasure.objects.get(abbreviation='kg')

        ingredient = Ingredient.objects.create(
            bakery=bakery,
            unit=unit,
            name='Flour',
            current_quantity=Decimal('5.00'),
            expiration_date='2026-12-31',
            is_active=False,
        )

        response = self.client.post(self.url, {
            'name': 'Flour',
            'unit': str(unit.pk),
            'current_quantity': '12.00',
            'expiration_date': '2027-02-01',
        })

        self.assertRedirects(
            response,
            reverse('inventory:list'),
        )

        ingredient.refresh_from_db()

        self.assertTrue(ingredient.is_active)
        self.assertEqual(
            ingredient.current_quantity,
            Decimal('12.00'),
        )
        self.assertEqual(
            Ingredient.objects.filter(
                bakery=bakery,
                name='Flour',
            ).count(),
            1,
        )


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

    def test_searches_ingredients_by_partial_case_insensitive_name(self):
        bakery = make_bakery()
        unit = UnitOfMeasure.objects.get(abbreviation='kg')
        Ingredient.objects.create(
            bakery=bakery, unit=unit, name='Whole Wheat Flour',
            current_quantity=Decimal('5.00'), expiration_date='2026-12-31',
        )
        Ingredient.objects.create(
            bakery=bakery, unit=unit, name='Sugar',
            current_quantity=Decimal('3.00'), expiration_date='2026-12-31',
        )

        response = self.client.get(reverse('inventory:list'), {'q': 'FLOUR'})

        self.assertContains(response, 'Whole Wheat Flour')
        self.assertNotContains(response, 'Sugar')
        self.assertEqual(response.context['query'], 'FLOUR')

    def test_search_does_not_expose_ingredients_from_another_bakery(self):
        current_bakery = make_bakery()
        other_bakery = Bakery.objects.create(name='Other Bakery', address='Calle 20')
        unit = UnitOfMeasure.objects.get(abbreviation='kg')
        Ingredient.objects.create(
            bakery=current_bakery, unit=unit, name='Local Flour',
            current_quantity=Decimal('5.00'), expiration_date='2026-12-31',
        )
        Ingredient.objects.create(
            bakery=other_bakery, unit=unit, name='Private Flour',
            current_quantity=Decimal('5.00'), expiration_date='2026-12-31',
        )

        response = self.client.get(reverse('inventory:list'), {'q': 'flour'})

        self.assertContains(response, 'Local Flour')
        self.assertNotContains(response, 'Private Flour')

    def test_empty_search_keeps_the_complete_active_inventory(self):
        bakery = make_bakery()
        unit = UnitOfMeasure.objects.get(abbreviation='kg')
        Ingredient.objects.create(
            bakery=bakery, unit=unit, name='Flour',
            current_quantity=Decimal('5.00'), expiration_date='2026-12-31',
        )

        response = self.client.get(reverse('inventory:list'), {'q': '   '})

        self.assertContains(response, 'Flour')
        self.assertEqual(response.context['query'], '')

    def test_shows_a_specific_empty_state_when_search_has_no_matches(self):
        make_bakery()

        response = self.client.get(reverse('inventory:list'), {'q': 'yeast'})

        self.assertContains(response, 'No ingredients match “yeast”.')


class LowStockAlertViewTests(TestCase):
    def setUp(self):
        self.bakery = make_bakery()
        self.unit = UnitOfMeasure.objects.get(abbreviation='kg')
        self.url = reverse('inventory:list')

    def create_ingredient(
        self,
        *,
        name='Flour',
        quantity,
        threshold=None,
        configuration_is_active=True,
    ):
        ingredient = Ingredient.objects.create(
            bakery=self.bakery,
            unit=self.unit,
            name=name,
            current_quantity=quantity,
            expiration_date='2026-12-31',
        )
        if threshold is not None:
            AlertConfiguration.objects.create(
                ingredient=ingredient,
                minimum_stock_threshold=threshold,
                is_active=configuration_is_active,
            )
        return ingredient

    def test_displays_low_stock_alert_when_quantity_is_below_threshold(self):
        self.create_ingredient(
            quantity=Decimal('4.00'),
            threshold=Decimal('5.00'),
        )

        response = self.client.get(self.url)

        self.assertContains(response, 'Low stock', count=1)
        self.assertContains(response, 'status-badge-warning')
        self.assertContains(response, 'aria-hidden="true"')

    def test_does_not_display_alert_when_quantity_equals_threshold(self):
        self.create_ingredient(
            quantity=Decimal('5.00'),
            threshold=Decimal('5.00'),
        )

        response = self.client.get(self.url)

        self.assertNotContains(response, 'Low stock')

    def test_does_not_display_alert_when_quantity_is_above_threshold(self):
        self.create_ingredient(
            quantity=Decimal('6.00'),
            threshold=Decimal('5.00'),
        )

        response = self.client.get(self.url)

        self.assertNotContains(response, 'Low stock')

    def test_does_not_display_alert_without_configuration(self):
        self.create_ingredient(quantity=Decimal('0.00'))

        response = self.client.get(self.url)

        self.assertNotContains(response, 'Low stock')

    def test_does_not_display_alert_for_inactive_configuration(self):
        self.create_ingredient(
            quantity=Decimal('4.00'),
            threshold=Decimal('5.00'),
            configuration_is_active=False,
        )

        response = self.client.get(self.url)

        self.assertNotContains(response, 'Low stock')

    def test_displays_alert_within_two_seconds_without_per_item_queries(self):
        for index in range(50):
            self.create_ingredient(
                name=f'Ingredient {index:02}',
                quantity=Decimal('1.00'),
                threshold=Decimal('2.00'),
            )

        started_at = perf_counter()
        with self.assertNumQueries(2):
            response = self.client.get(self.url)
        elapsed_seconds = perf_counter() - started_at

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Low stock', count=50)
        self.assertLess(elapsed_seconds, 2)


class IngredientEditViewTests(TestCase):
    def setUp(self):
        self.bakery = make_bakery()
        self.unit = UnitOfMeasure.objects.get(abbreviation='kg')

        self.ingredient = Ingredient.objects.create(
            bakery=self.bakery,
            unit=self.unit,
            name='Flour',
            current_quantity=Decimal('5.00'),
            expiration_date='2026-12-31',
        )

        self.url = reverse(
            'inventory:edit',
            args=[self.ingredient.pk],
        )

    def test_get_renders_existing_ingredient_data(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Flour')
        self.assertEqual(
            response.context['form'].instance,
            self.ingredient,
        )

    def test_post_updates_existing_ingredient(self):
        gram = UnitOfMeasure.objects.get(abbreviation='g')

        response = self.client.post(
            self.url,
            {
                'name': 'Whole Wheat Flour',
                'unit': str(gram.pk),
                'current_quantity': '8.50',
                'expiration_date': '2027-01-15',
            },
        )

        self.assertRedirects(
            response,
            reverse('inventory:list'),
        )

        self.ingredient.refresh_from_db()

        self.assertEqual(
            self.ingredient.name,
            'Whole Wheat Flour',
        )
        self.assertEqual(
            self.ingredient.current_quantity,
            Decimal('8.50'),
        )
        self.assertEqual(
            self.ingredient.unit,
            gram,
        )

    def test_edit_rejects_duplicate_ingredient_name(self):
        Ingredient.objects.create(
            bakery=self.bakery,
            unit=self.unit,
            name='Sugar',
            current_quantity=Decimal('3.00'),
            expiration_date='2026-12-31',
        )

        response = self.client.post(
            self.url,
            {
                'name': 'Sugar',
                'unit': str(self.unit.pk),
                'current_quantity': '5.00',
                'expiration_date': '2026-12-31',
            },
        )

        self.assertEqual(response.status_code, 200)

        self.ingredient.refresh_from_db()

        self.assertEqual(
            self.ingredient.name,
            'Flour',
        )

class IngredientDeleteViewTests(TestCase):
    def setUp(self):
        self.bakery = make_bakery()
        self.unit = UnitOfMeasure.objects.get(abbreviation='kg')

        self.ingredient = Ingredient.objects.create(
            bakery=self.bakery,
            unit=self.unit,
            name='Flour',
            current_quantity=Decimal('5.00'),
            expiration_date='2026-12-31',
        )

        self.url = reverse(
            'inventory:delete',
            args=[self.ingredient.pk],
        )

    def test_get_displays_delete_confirmation(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Flour')
        self.assertTrue(
            Ingredient.objects.get(
                pk=self.ingredient.pk
            ).is_active
        )

    def test_post_deactivates_ingredient(self):
        response = self.client.post(self.url)

        self.assertRedirects(
            response,
            reverse('inventory:list'),
        )

        self.ingredient.refresh_from_db()

        self.assertFalse(
            self.ingredient.is_active
        )

    def test_deleted_ingredient_no_longer_appears_in_inventory(self):
        self.client.post(self.url)

        response = self.client.get(
            reverse('inventory:list')
        )

        self.assertNotContains(
            response,
            'Flour',
        )

    def test_reactivates_an_inactive_ingredient_instead_of_creating_duplicate(self):
        bakery = make_bakery()
        unit = UnitOfMeasure.objects.get(abbreviation='kg')

        ingredient = Ingredient.objects.create(
            bakery=bakery,
            unit=unit,
            name='Flour',
            current_quantity=Decimal('5.00'),
            expiration_date='2026-12-31',
            is_active=False,
        )

        registered = register_ingredient(
            bakery=bakery,
            name='Flour',
            unit=unit,
            current_quantity=Decimal('10.00'),
            expiration_date='2027-01-31',
        )

        ingredient.refresh_from_db()

        self.assertEqual(registered.pk, ingredient.pk)
        self.assertTrue(ingredient.is_active)
        self.assertEqual(
            ingredient.current_quantity,
            Decimal('10.00'),
        )
        self.assertEqual(
            Ingredient.objects.filter(
                bakery=bakery,
                name='Flour',
            ).count(),
            1,
        )
