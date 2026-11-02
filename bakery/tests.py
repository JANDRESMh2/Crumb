from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import ActivityLog, Bakery
from .services import (
    BakeryAlreadyConfigured,
    build_activity_log,
    get_current_bakery,
    record_activity,
    setup_bakery_profile,
)


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


class RecordActivityTests(TestCase):
    """FR28 - writing entries into the user activity log."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username='panadera')

    def test_records_who_did_what(self):
        entry = record_activity(
            user=self.user,
            action_type=ActivityLog.ActionType.STOCK_IN,
            description='Registered 10 of Flour into the stock.',
        )

        self.assertEqual(entry.user, self.user)
        self.assertEqual(entry.action_type, 'StockIn')
        self.assertEqual(
            entry.description,
            'Registered 10 of Flour into the stock.',
        )
        self.assertIsNotNone(entry.created_at)

    def test_keeps_the_entry_when_nobody_is_signed_in(self):
        entry = record_activity(
            user=AnonymousUser(),
            action_type=ActivityLog.ActionType.STOCK_IN,
            description='Registered 10 of Flour into the stock.',
        )

        self.assertIsNone(entry.user)
        self.assertEqual(ActivityLog.objects.count(), 1)

    def test_accepts_no_user_at_all(self):
        entry = record_activity(
            user=None,
            action_type=ActivityLog.ActionType.CORRECTION,
            description='Corrected the stock of Flour from 5 to 3.',
        )

        self.assertIsNone(entry.user)

    def test_keeps_the_trace_when_the_account_is_deleted(self):
        record_activity(
            user=self.user,
            action_type=ActivityLog.ActionType.LOGIN,
            description='panadera signed in.',
        )

        self.user.delete()

        entry = ActivityLog.objects.get()
        self.assertIsNone(entry.user)
        self.assertEqual(entry.description, 'panadera signed in.')


class ActivityLogSignalTests(TestCase):
    """FR28 - signing in and out is traced without touching the auth views."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username='panadera')

    def test_signing_in_is_recorded(self):
        self.client.force_login(self.user)

        entry = ActivityLog.objects.get(action_type='Login')
        self.assertEqual(entry.user, self.user)
        self.assertIn('panadera', entry.description)

    def test_signing_out_is_recorded(self):
        self.client.force_login(self.user)
        self.client.logout()

        entry = ActivityLog.objects.get(action_type='Logout')
        self.assertEqual(entry.user, self.user)

    def test_signing_out_without_a_session_records_nothing(self):
        self.client.logout()

        self.assertFalse(ActivityLog.objects.filter(action_type='Logout').exists())


class BuildActivityLogTests(TestCase):
    """FR28 - reading the log back, with filters."""

    def setUp(self):
        self.panadera = get_user_model().objects.create_user(username='panadera')
        self.cajero = get_user_model().objects.create_user(username='cajero')

    def log(self, user, action_type, description='Something happened.'):
        return record_activity(
            user=user,
            action_type=action_type,
            description=description,
        )

    def test_returns_the_newest_entry_first(self):
        self.log(self.panadera, ActivityLog.ActionType.STOCK_IN, 'First.')
        self.log(self.panadera, ActivityLog.ActionType.SALE, 'Second.')

        entries = list(build_activity_log())

        self.assertEqual(entries[0].description, 'Second.')
        self.assertEqual(entries[1].description, 'First.')

    def test_filters_by_user(self):
        self.log(self.panadera, ActivityLog.ActionType.STOCK_IN)
        self.log(self.cajero, ActivityLog.ActionType.SALE)

        entries = build_activity_log(user=self.cajero)

        self.assertEqual(entries.count(), 1)
        self.assertEqual(entries.first().user, self.cajero)

    def test_filters_by_action(self):
        self.log(self.panadera, ActivityLog.ActionType.STOCK_IN)
        self.log(self.panadera, ActivityLog.ActionType.SALE)

        entries = build_activity_log(
            action_type=ActivityLog.ActionType.SALE,
        )

        self.assertEqual(entries.count(), 1)
        self.assertEqual(entries.first().action_type, 'Sale')

    def test_filters_by_date_range(self):
        old = self.log(self.panadera, ActivityLog.ActionType.STOCK_IN, 'Old.')
        ActivityLog.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=10),
        )
        self.log(self.panadera, ActivityLog.ActionType.SALE, 'Today.')

        entries = build_activity_log(start_date=timezone.localdate())

        self.assertEqual(
            [entry.description for entry in entries],
            ['Today.'],
        )

    def test_rejects_a_range_that_ends_before_it_starts(self):
        today = timezone.localdate()

        with self.assertRaises(ValidationError):
            build_activity_log(
                start_date=today,
                end_date=today - timedelta(days=1),
            )


class ActivityLogViewTests(TestCase):
    """FR28 - the screen that shows the log."""

    def setUp(self):
        self.bakery = Bakery.objects.create(
            name='El Buen Pan',
            address='Calle 10 #20-30',
        )
        self.user = get_user_model().objects.create_user(username='panadera')

    def test_shows_the_recorded_activity(self):
        record_activity(
            user=self.user,
            action_type=ActivityLog.ActionType.STOCK_IN,
            description='Registered 10 of Flour into the stock.',
        )

        response = self.client.get(reverse('bakery:activity_log'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'panadera')
        self.assertContains(response, 'Registered 10 of Flour into the stock.')

    def test_says_so_when_nothing_was_recorded(self):
        response = self.client.get(reverse('bakery:activity_log'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No activity has been recorded yet.')

    def test_filters_by_action_from_the_query_string(self):
        record_activity(
            user=self.user,
            action_type=ActivityLog.ActionType.STOCK_IN,
            description='A stock-in.',
        )
        record_activity(
            user=self.user,
            action_type=ActivityLog.ActionType.SALE,
            description='A sale.',
        )

        response = self.client.get(
            reverse('bakery:activity_log'),
            {'action_type': 'Sale'},
        )

        self.assertContains(response, 'A sale.')
        self.assertNotContains(response, 'A stock-in.')

    def test_ignores_an_action_that_does_not_exist(self):
        record_activity(
            user=self.user,
            action_type=ActivityLog.ActionType.SALE,
            description='A sale.',
        )

        response = self.client.get(
            reverse('bakery:activity_log'),
            {'action_type': 'NotAnAction'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'A sale.')

    def test_reports_an_invalid_date_range_instead_of_failing(self):
        today = timezone.localdate()

        response = self.client.get(
            reverse('bakery:activity_log'),
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
        Bakery.objects.all().delete()

        response = self.client.get(reverse('bakery:activity_log'))

        self.assertRedirects(response, reverse('bakery:setup'))
