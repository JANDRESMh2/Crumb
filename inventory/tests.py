from decimal import Decimal
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from bakery.models import Bakery

from .forms import IngredientForm, IngredientRegistrationForm, StockConsumptionForm
from .models import BarcodeIdentifier, Ingredient, StockMovement, UnitOfMeasure
from .services import (
    InsufficientStockError,
    deactivate_ingredient,
    register_ingredient,
    register_stock_consumption,
)


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


class BarcodeRegistrationServiceTests(TestCase):
    def test_register_ingredient_with_barcode_creates_the_link(self):
        bakery = make_bakery()
        unit = UnitOfMeasure.objects.get(abbreviation='kg')
        ingredient = register_ingredient(
            bakery=bakery, name='Flour', unit=unit,
            current_quantity=Decimal('10.00'), expiration_date='2027-01-31',
            barcode_value='7501234567890',
        )
        barcode = BarcodeIdentifier.objects.get(barcode_value='7501234567890')
        self.assertEqual(barcode.ingredient, ingredient)

    def test_register_ingredient_without_barcode_creates_no_link(self):
        bakery = make_bakery()
        unit = UnitOfMeasure.objects.get(abbreviation='kg')
        register_ingredient(
            bakery=bakery, name='Flour', unit=unit,
            current_quantity=Decimal('10.00'), expiration_date='2027-01-31',
        )
        self.assertEqual(BarcodeIdentifier.objects.count(), 0)


class IngredientRegistrationFormBarcodeTests(TestCase):
    def test_rejects_a_barcode_already_linked_to_another_ingredient(self):
        bakery = make_bakery()
        unit = UnitOfMeasure.objects.get(abbreviation='kg')
        existing = Ingredient.objects.create(
            bakery=bakery, unit=unit, name='Sugar',
            current_quantity=Decimal('5.00'), expiration_date='2027-01-31',
        )
        BarcodeIdentifier.objects.create(ingredient=existing, barcode_value='7501234567890')

        form = IngredientRegistrationForm(data={
            'name': 'Flour',
            'unit': unit.pk,
            'current_quantity': '10.00',
            'expiration_date': '2027-01-31',
            'barcode_value': '7501234567890',
        }, bakery=bakery)

        self.assertFalse(form.is_valid())
        self.assertIn('barcode_value', form.errors)

    def test_barcode_field_is_optional(self):
        bakery = make_bakery()
        unit = UnitOfMeasure.objects.get(abbreviation='kg')
        form = IngredientRegistrationForm(data={
            'name': 'Flour',
            'unit': unit.pk,
            'current_quantity': '10.00',
            'expiration_date': '2027-01-31',
            'barcode_value': '',
        }, bakery=bakery)
        self.assertTrue(form.is_valid())


class IngredientCreateViewBarcodeTests(TestCase):
    def test_post_with_barcode_links_it_to_the_new_ingredient(self):
        bakery = make_bakery()
        unit = UnitOfMeasure.objects.get(abbreviation='kg')
        response = self.client.post(reverse('inventory:create'), {
            'name': 'Flour',
            'unit': str(unit.pk),
            'current_quantity': '10.00',
            'expiration_date': '2027-01-31',
            'barcode_value': '7501234567890',
        })
        self.assertRedirects(response, reverse('inventory:list'))
        ingredient = Ingredient.objects.get(name='Flour')
        self.assertEqual(
            BarcodeIdentifier.objects.get(barcode_value='7501234567890').ingredient,
            ingredient,
        )


class StockMovementModelTests(TestCase):
    def test_rejects_zero_or_negative_quantity_at_the_database_level(self):
        bakery = make_bakery()
        unit = UnitOfMeasure.objects.get(abbreviation='kg')
        ingredient = Ingredient.objects.create(
            bakery=bakery, unit=unit, name='Flour',
            current_quantity=Decimal('10.00'), expiration_date='2027-01-31',
        )
        movement = StockMovement(
            bakery=bakery, ingredient=ingredient, movement_type='Consumption',
            quantity=Decimal('0.00'),
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                movement.save()


class RegisterStockConsumptionServiceTests(TestCase):
    def test_consuming_available_stock_decreases_the_ingredient_and_logs_the_movement(self):
        bakery = make_bakery()
        unit = UnitOfMeasure.objects.get(abbreviation='kg')
        ingredient = Ingredient.objects.create(
            bakery=bakery, unit=unit, name='Flour',
            current_quantity=Decimal('10.00'), expiration_date='2027-01-31',
        )
        movement = register_stock_consumption(
            bakery=bakery, ingredient=ingredient, quantity=Decimal('4.00'), note='For today\'s batch',
        )
        ingredient.refresh_from_db()
        self.assertEqual(ingredient.current_quantity, Decimal('6.00'))
        self.assertEqual(movement.movement_type, 'Consumption')
        self.assertEqual(movement.quantity, Decimal('4.00'))

    def test_consuming_more_than_available_is_rejected(self):
        bakery = make_bakery()
        unit = UnitOfMeasure.objects.get(abbreviation='kg')
        ingredient = Ingredient.objects.create(
            bakery=bakery, unit=unit, name='Flour',
            current_quantity=Decimal('3.00'), expiration_date='2027-01-31',
        )
        with self.assertRaises(InsufficientStockError):
            register_stock_consumption(bakery=bakery, ingredient=ingredient, quantity=Decimal('5.00'))
        ingredient.refresh_from_db()
        self.assertEqual(ingredient.current_quantity, Decimal('3.00'))
        self.assertEqual(StockMovement.objects.count(), 0)


class StockConsumptionFormTests(TestCase):
    def test_rejects_a_quantity_greater_than_the_available_stock(self):
        bakery = make_bakery()
        unit = UnitOfMeasure.objects.get(abbreviation='kg')
        ingredient = Ingredient.objects.create(
            bakery=bakery, unit=unit, name='Flour',
            current_quantity=Decimal('3.00'), expiration_date='2027-01-31',
        )
        form = StockConsumptionForm(data={
            'ingredient': ingredient.pk,
            'quantity': '5.00',
            'note': '',
        }, bakery=bakery)
        self.assertFalse(form.is_valid())
        self.assertIn('quantity', form.errors)


class StockConsumptionCreateViewTests(TestCase):
    def setUp(self):
        self.url = reverse('inventory:stock_consumption')

    def test_redirects_to_bakery_setup_when_no_bakery_is_configured(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse('bakery:setup'))

    def test_get_renders_the_consumption_form(self):
        make_bakery()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Register consumption')

    def test_post_with_valid_data_registers_the_consumption_and_redirects(self):
        bakery = make_bakery()
        unit = UnitOfMeasure.objects.get(abbreviation='kg')
        ingredient = Ingredient.objects.create(
            bakery=bakery, unit=unit, name='Flour',
            current_quantity=Decimal('10.00'), expiration_date='2027-01-31',
        )
        response = self.client.post(self.url, {
            'ingredient': str(ingredient.pk),
            'quantity': '4.00',
            'note': 'For today\'s batch',
        })
        self.assertRedirects(response, reverse('inventory:list'))
        ingredient.refresh_from_db()
        self.assertEqual(ingredient.current_quantity, Decimal('6.00'))

    def test_post_exceeding_available_stock_reshows_form_with_error(self):
        bakery = make_bakery()
        unit = UnitOfMeasure.objects.get(abbreviation='kg')
        ingredient = Ingredient.objects.create(
            bakery=bakery, unit=unit, name='Flour',
            current_quantity=Decimal('3.00'), expiration_date='2027-01-31',
        )
        response = self.client.post(self.url, {
            'ingredient': str(ingredient.pk),
            'quantity': '5.00',
            'note': '',
        })
        self.assertEqual(response.status_code, 200)
        ingredient.refresh_from_db()
        self.assertEqual(ingredient.current_quantity, Decimal('3.00'))


class BarcodeAfterIngredientDeletionTests(TestCase):
    """FR17 + FR04 - a deleted ingredient must not keep holding its barcode."""

    def setUp(self):
        self.bakery = make_bakery()
        self.unit = UnitOfMeasure.objects.get(abbreviation='kg')
        self.ingredient = register_ingredient(
            bakery=self.bakery, name='Flour', unit=self.unit,
            current_quantity=Decimal('10.00'), expiration_date='2027-01-31',
            barcode_value='7501234567890',
        )

    def test_deleting_an_ingredient_deactivates_its_barcodes(self):
        deactivate_ingredient(ingredient=self.ingredient)

        barcode = BarcodeIdentifier.objects.get(barcode_value='7501234567890')
        self.assertFalse(barcode.is_active)

    def test_form_accepts_a_barcode_left_behind_by_a_deleted_ingredient(self):
        deactivate_ingredient(ingredient=self.ingredient)

        form = IngredientRegistrationForm(data={
            'name': 'Flour',
            'unit': self.unit.pk,
            'current_quantity': '5.00',
            'expiration_date': '2027-02-28',
            'barcode_value': '7501234567890',
        }, bakery=self.bakery)

        self.assertTrue(form.is_valid(), form.errors)

    def test_re_registering_a_deleted_ingredient_reuses_its_barcode_row(self):
        deactivate_ingredient(ingredient=self.ingredient)

        reactivated = register_ingredient(
            bakery=self.bakery, name='Flour', unit=self.unit,
            current_quantity=Decimal('5.00'), expiration_date='2027-02-28',
            barcode_value='7501234567890',
        )

        self.assertEqual(reactivated.pk, self.ingredient.pk)
        self.assertEqual(BarcodeIdentifier.objects.count(), 1)
        barcode = BarcodeIdentifier.objects.get(barcode_value='7501234567890')
        self.assertEqual(barcode.ingredient, reactivated)
        self.assertTrue(barcode.is_active)

    def test_a_barcode_freed_by_deletion_can_be_linked_to_another_ingredient(self):
        deactivate_ingredient(ingredient=self.ingredient)

        sugar = register_ingredient(
            bakery=self.bakery, name='Sugar', unit=self.unit,
            current_quantity=Decimal('2.00'), expiration_date='2027-02-28',
            barcode_value='7501234567890',
        )

        self.assertEqual(BarcodeIdentifier.objects.count(), 1)
        self.assertEqual(
            BarcodeIdentifier.objects.get(barcode_value='7501234567890').ingredient,
            sugar,
        )

    def test_a_barcode_linked_to_an_active_ingredient_is_still_rejected(self):
        form = IngredientRegistrationForm(data={
            'name': 'Sugar',
            'unit': self.unit.pk,
            'current_quantity': '5.00',
            'expiration_date': '2027-02-28',
            'barcode_value': '7501234567890',
        }, bakery=self.bakery)

        self.assertFalse(form.is_valid())
        self.assertIn('barcode_value', form.errors)


class IngredientListViewBarcodeTests(TestCase):
    """FR17 - the linked barcode has to be visible in the catalog, not only in the admin."""

    def setUp(self):
        self.bakery = make_bakery()
        self.unit = UnitOfMeasure.objects.get(abbreviation='kg')

    def test_shows_the_barcode_linked_to_each_ingredient(self):
        register_ingredient(
            bakery=self.bakery, name='Flour', unit=self.unit,
            current_quantity=Decimal('10.00'), expiration_date='2027-01-31',
            barcode_value='7501234567890',
        )

        response = self.client.get(reverse('inventory:list'))

        self.assertContains(response, '7501234567890')

    def test_shows_a_placeholder_when_the_ingredient_has_no_barcode(self):
        register_ingredient(
            bakery=self.bakery, name='Sugar', unit=self.unit,
            current_quantity=Decimal('4.00'), expiration_date='2027-01-31',
        )

        response = self.client.get(reverse('inventory:list'))

        self.assertContains(response, '<td>—</td>')

    def test_does_not_show_the_barcode_of_a_deleted_ingredient(self):
        ingredient = register_ingredient(
            bakery=self.bakery, name='Flour', unit=self.unit,
            current_quantity=Decimal('10.00'), expiration_date='2027-01-31',
            barcode_value='7501234567890',
        )
        deactivate_ingredient(ingredient=ingredient)

        response = self.client.get(reverse('inventory:list'))

        self.assertNotContains(response, '7501234567890')


class StockConsumptionViewErrorHandlingTests(TestCase):
    """FR08 - a stock change between validating and saving must not raise a 500."""

    def test_reshows_the_form_when_the_service_reports_insufficient_stock(self):
        bakery = make_bakery()
        unit = UnitOfMeasure.objects.get(abbreviation='kg')
        ingredient = Ingredient.objects.create(
            bakery=bakery, unit=unit, name='Flour',
            current_quantity=Decimal('10.00'), expiration_date='2027-01-31',
        )

        with patch(
            'inventory.views.register_stock_consumption',
            side_effect=InsufficientStockError('Cannot consume 4.00 of Flour; only 1.00 available.'),
        ):
            response = self.client.post(reverse('inventory:stock_consumption'), {
                'ingredient': str(ingredient.pk),
                'quantity': '4.00',
                'note': '',
            })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'only 1.00 available.')
        self.assertEqual(StockMovement.objects.count(), 0)
