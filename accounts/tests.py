import re
import smtplib
import threading
from io import StringIO
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.db import close_old_connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from bakery.models import Bakery

from .models import RecoveryChallenge, RecoveryRateBucket
from .services import request_recovery, verify_recovery_code


class RecoveryFlowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='baker_admin', email='baker@example.com',
            password='OldPassword-9876',
        )
        self.request_url = reverse('accounts:recovery_request')
        self.verify_url = reverse('accounts:recovery_verify')
        self.resend_url = reverse('accounts:recovery_resend')
        self.password_url = reverse('accounts:recovery_password')
        self.complete_url = reverse('accounts:recovery_complete')

    def request_code(self, username='baker_admin', email='baker@example.com', client=None):
        response = (client or self.client).post(self.request_url, {
            'username': username, 'email': email,
        })
        self.assertRedirects(response, self.verify_url)
        return response

    def code(self, message=None):
        match = re.search(r'\b[0-9]{6}\b', (message or mail.outbox[-1]).body)
        self.assertIsNotNone(match)
        return match.group()

    def verify_code(self, code=None, client=None):
        return (client or self.client).post(self.verify_url, {
            'code': code or self.code(),
        })

    def test_login_links_to_recovery_and_pages_need_no_bakery(self):
        bakery = Bakery.objects.create(name='Test Bakery', address='Test Address')
        self.assertContains(self.client.get(reverse('accounts:login')),
                            self.request_url)
        bakery.delete()
        self.assertEqual(self.client.get(self.request_url).status_code, 200)
        self.request_code()
        self.assertEqual(self.client.get(self.verify_url).status_code, 200)

    def test_code_is_six_digits_and_only_a_hmac_digest_is_stored(self):
        with patch('accounts.services.secrets.randbelow', return_value=7):
            self.request_code()
        self.assertEqual(self.code(), '000007')
        challenge = RecoveryChallenge.objects.get(user=self.user)
        self.assertEqual(len(challenge.code_digest), 64)
        self.assertNotIn('000007', challenge.code_digest)
        self.assertNotEqual(challenge.code_digest, self.user.password)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user.email])
        self.assertEqual(mail.outbox[0].from_email, settings.DEFAULT_FROM_EMAIL)
        self.assertIn('baker_admin', mail.outbox[0].body)

    def test_successful_recovery_requires_manual_login_and_rejects_old_password(self):
        Bakery.objects.create(name='Test Bakery', address='Test Address')
        self.request_code()
        self.assertRedirects(self.verify_code(), self.password_url)
        self.assertNotIn('_auth_user_id', self.client.session)
        response = self.client.post(self.password_url, {
            'new_password1': 'NewStrongPassword-9876',
            'new_password2': 'NewStrongPassword-9876',
        })
        self.assertRedirects(response, self.complete_url)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NewStrongPassword-9876'))
        self.assertFalse(self.user.check_password('OldPassword-9876'))
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(self.client.post(reverse('accounts:login'), {
            'username': self.user.username, 'password': 'OldPassword-9876',
        }).status_code, 200)
        self.assertRedirects(self.client.post(reverse('accounts:login'), {
            'username': self.user.username, 'password': 'NewStrongPassword-9876',
        }), reverse('home'))

    def test_unknown_and_ineligible_accounts_receive_generic_responses(self):
        for username, email in (
            ('missing', 'missing@example.com'),
            ('baker_admin', 'wrong@example.com'),
        ):
            self.request_code(username, email)
            self.assertContains(self.client.get(self.verify_url),
                                'If we can process the request')
            self.assertEqual(len(mail.outbox), 0)
            self.assertEqual(self.verify_code('123456').status_code, 200)
        self.user.is_active = False
        self.user.save(update_fields=['is_active'])
        self.request_code()
        self.assertEqual(len(mail.outbox), 0)
        self.user.is_active = True
        self.user.set_unusable_password()
        self.user.save(update_fields=['is_active', 'password'])
        self.request_code()
        self.assertEqual(len(mail.outbox), 0)

    def test_duplicate_email_targets_only_the_requested_username(self):
        get_user_model().objects.create_user(
            username='second_baker', email=self.user.email,
            password='AnotherPassword-9876',
        )
        self.request_code('second_baker')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('second_baker', mail.outbox[0].body)
        self.assertNotIn('baker_admin', mail.outbox[0].body)
        self.assertEqual(RecoveryChallenge.objects.count(), 1)
        self.assertEqual(RecoveryChallenge.objects.get().user.username, 'second_baker')

    def test_wrong_codes_are_limited_to_five_attempts(self):
        self.request_code()
        correct_code = self.code()
        for attempt in range(5):
            with self.subTest(attempt=attempt):
                self.assertEqual(self.verify_code('999999').status_code, 200)
        challenge = RecoveryChallenge.objects.get(user=self.user)
        self.assertEqual(challenge.failed_attempts, 5)
        self.assertEqual(self.verify_code(correct_code).status_code, 200)
        self.assertIsNone(RecoveryChallenge.objects.get(user=self.user).verified_at)

    def test_malformed_code_also_consumes_an_attempt(self):
        self.request_code()
        self.client.post(self.verify_url, {'code': 'abc'})
        self.assertEqual(RecoveryChallenge.objects.get(user=self.user).failed_attempts, 1)

    def test_expired_code_cannot_be_verified(self):
        self.request_code()
        now = timezone.now()
        with patch('accounts.services.timezone.now', return_value=now + timedelta(minutes=11)):
            self.assertEqual(self.verify_code().status_code, 200)
        self.assertIsNone(RecoveryChallenge.objects.get(user=self.user).verified_at)

    def test_account_change_invalidates_the_code(self):
        self.request_code()
        self.user.set_password('ChangedElsewhere-9876')
        self.user.save(update_fields=['password'])
        self.assertEqual(self.verify_code().status_code, 200)
        self.assertIsNone(RecoveryChallenge.objects.get(user=self.user).verified_at)

    def test_code_is_single_use_after_verification(self):
        self.request_code()
        challenge_id = self.client.session['recovery_challenge_id']
        code = self.code()
        self.assertRedirects(self.verify_code(code), self.password_url)
        self.assertFalse(verify_recovery_code(challenge_id, code))
        self.assertEqual(len(RecoveryChallenge.objects.get(user=self.user).code_digest), 64)

    def test_successful_password_change_consumes_the_reset_authorization(self):
        self.request_code()
        self.verify_code()
        challenge_id = self.client.session['recovery_challenge_id']
        self.client.post(self.password_url, {
            'new_password1': 'NewStrongPassword-9876',
            'new_password2': 'NewStrongPassword-9876',
        })
        from .services import set_recovered_password
        self.assertFalse(set_recovered_password(challenge_id, 'AnotherStrongPassword-9876'))
        self.assertIsNotNone(RecoveryChallenge.objects.get(user=self.user).consumed_at)

    def test_resend_cooldown_and_old_code_invalidation(self):
        self.request_code()
        first_code = self.code()
        self.assertRedirects(self.client.post(self.resend_url), self.verify_url)
        self.assertEqual(len(mail.outbox), 1)
        now = timezone.now()
        self.assertLessEqual(
            RecoveryRateBucket.objects.get(scope='identity').next_allowed_at,
            now + timedelta(seconds=61),
        )
        with patch('accounts.services.timezone.now', return_value=now + timedelta(seconds=61)):
            self.assertRedirects(self.client.post(self.resend_url), self.verify_url)
        self.assertEqual(len(mail.outbox), 2, list(RecoveryRateBucket.objects.values('scope', 'request_count', 'next_allowed_at')))
        self.assertEqual(RecoveryChallenge.objects.filter(revoked_at__isnull=True).count(), 1)
        self.assertFalse(verify_recovery_code(
            RecoveryChallenge.objects.get(revoked_at__isnull=False).pk, first_code,
        ))
        self.assertRedirects(self.verify_code(), self.password_url)

    def test_failed_resend_keeps_the_previous_code_usable(self):
        self.request_code()
        old_id = self.client.session['recovery_challenge_id']
        old_code = self.code()
        later = timezone.now() + timedelta(seconds=61)
        with patch('accounts.services.timezone.now', return_value=later):
            with patch('accounts.services.send_mail', side_effect=smtplib.SMTPException('private SMTP error')):
                with self.assertLogs('accounts.services', level='ERROR'):
                    self.assertRedirects(self.client.post(self.resend_url), self.verify_url)

        self.assertEqual(self.client.session['recovery_challenge_id'], old_id)
        old_challenge = RecoveryChallenge.objects.get(pk=old_id)
        replacement = RecoveryChallenge.objects.exclude(pk=old_id).get()
        self.assertIsNotNone(old_challenge.activated_at)
        self.assertIsNone(old_challenge.revoked_at)
        self.assertIsNone(replacement.activated_at)
        self.assertIsNotNone(replacement.delivery_failed_at)
        self.assertIsNotNone(replacement.revoked_at)
        self.assertRedirects(self.client.post(self.resend_url), self.verify_url)
        self.assertEqual(RecoveryChallenge.objects.count(), 2)
        self.assertEqual(len(mail.outbox), 1)
        self.assertRedirects(self.verify_code(old_code), self.password_url)

    def test_unaccepted_resend_keeps_the_previous_code_usable(self):
        self.request_code()
        old_id = self.client.session['recovery_challenge_id']
        old_code = self.code()
        later = timezone.now() + timedelta(seconds=61)
        with patch('accounts.services.timezone.now', return_value=later):
            with patch('accounts.services.send_mail', return_value=0):
                with self.assertLogs('accounts.services', level='ERROR'):
                    self.assertRedirects(self.client.post(self.resend_url), self.verify_url)

        self.assertEqual(self.client.session['recovery_challenge_id'], old_id)
        self.assertIsNone(RecoveryChallenge.objects.get(pk=old_id).revoked_at)
        self.assertIsNotNone(RecoveryChallenge.objects.exclude(pk=old_id).get().delivery_failed_at)
        self.assertRedirects(self.verify_code(old_code), self.password_url)

    def test_pending_code_cannot_be_verified_before_smtp_acceptance(self):
        self.request_code()
        old_id = self.client.session['recovery_challenge_id']

        def inspect_pending(subject, message, from_email, recipients, **kwargs):
            replacement = RecoveryChallenge.objects.exclude(pk=old_id).get()
            new_code = re.search(r'\b[0-9]{6}\b', message).group()
            self.assertIsNone(replacement.activated_at)
            self.assertIsNone(RecoveryChallenge.objects.get(pk=old_id).revoked_at)
            self.assertFalse(verify_recovery_code(replacement.pk, new_code))
            self.assertEqual(RecoveryChallenge.objects.get(pk=replacement.pk).failed_attempts, 0)
            return 1

        later = timezone.now() + timedelta(seconds=61)
        with patch('accounts.services.timezone.now', return_value=later):
            with patch('accounts.services.send_mail', side_effect=inspect_pending):
                self.assertRedirects(self.client.post(self.resend_url), self.verify_url)
        self.assertIsNotNone(RecoveryChallenge.objects.exclude(pk=old_id).get().activated_at)
        self.assertIsNotNone(RecoveryChallenge.objects.get(pk=old_id).revoked_at)

    def test_resend_retries_when_the_generated_code_matches_the_previous_code(self):
        with patch('accounts.services.secrets.randbelow', side_effect=[7, 7, 8]):
            self.request_code()
            old_id = self.client.session['recovery_challenge_id']
            self.assertEqual(self.code(), '000007')
            later = timezone.now() + timedelta(seconds=61)
            with patch('accounts.services.timezone.now', return_value=later):
                self.assertRedirects(self.client.post(self.resend_url), self.verify_url)
        self.assertEqual(self.code(), '000008')
        self.assertFalse(verify_recovery_code(old_id, '000007'))
        self.assertRedirects(self.verify_code('000008'), self.password_url)

    def test_new_request_retries_when_the_verified_code_is_generated_again(self):
        with patch('accounts.services.secrets.randbelow', side_effect=[7, 7, 8]):
            self.request_code()
            old_id = self.client.session['recovery_challenge_id']
            self.assertRedirects(self.verify_code('000007'), self.password_url)
            later = timezone.now() + timedelta(seconds=61)
            with patch('accounts.services.timezone.now', return_value=later):
                self.request_code()
        self.assertEqual(self.code(), '000008')
        self.assertIsNotNone(RecoveryChallenge.objects.get(pk=old_id).revoked_at)
        self.assertFalse(verify_recovery_code(old_id, '000007'))
        self.assertRedirects(self.verify_code('000008'), self.password_url)

    def test_repeating_the_request_during_cooldown_keeps_the_existing_code(self):
        self.request_code()
        first_challenge_id = self.client.session['recovery_challenge_id']
        code = self.code()
        self.request_code()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(self.client.session['recovery_challenge_id'], first_challenge_id)
        self.assertRedirects(self.verify_code(code), self.password_url)

    @override_settings(RECOVERY_IDENTITY_HOURLY_LIMIT=2, RECOVERY_RESEND_COOLDOWN_SECONDS=0)
    def test_identity_rate_limit_persists_across_browser_sessions(self):
        for _ in range(2):
            self.request_code(client=Client())
        self.request_code(client=Client())
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(RecoveryRateBucket.objects.get(scope='identity').request_count, 2)
        self.assertEqual(RecoveryRateBucket.objects.get(scope='ip').request_count, 3)

    @override_settings(RECOVERY_IP_HOURLY_LIMIT=2)
    def test_ip_rate_limit_applies_across_different_accounts(self):
        for index in range(3):
            get_user_model().objects.create(
                username=f'other_{index}', email=f'other_{index}@example.com',
                password='usable-but-not-hashed-for-this-test',
            )
            self.request_code(f'other_{index}', f'other_{index}@example.com')
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(RecoveryRateBucket.objects.get(scope='ip').request_count, 2)

    @override_settings(RECOVERY_IP_HOURLY_LIMIT=1)
    def test_forwarded_for_header_does_not_bypass_the_ip_limit(self):
        self.client.post(self.request_url, {
            'username': self.user.username, 'email': self.user.email,
        }, HTTP_X_FORWARDED_FOR='1.1.1.1')
        get_user_model().objects.create(
            username='other', email='other@example.com', password='usable-hash',
        )
        self.client.post(self.request_url, {
            'username': 'other', 'email': 'other@example.com',
        }, HTTP_X_FORWARDED_FOR='2.2.2.2')
        self.assertEqual(len(mail.outbox), 1)

    def test_reset_authorization_expires_after_five_minutes(self):
        self.request_code()
        self.assertRedirects(self.verify_code(), self.password_url)
        now = timezone.now()
        with patch('accounts.services.timezone.now', return_value=now + timedelta(minutes=6)):
            self.assertRedirects(self.client.get(self.password_url), self.request_url)

    def test_account_change_invalidates_a_verified_authorization(self):
        self.request_code()
        self.verify_code()
        self.user.email = 'changed@example.com'
        self.user.save(update_fields=['email'])
        self.assertRedirects(self.client.get(self.password_url), self.request_url)

    def test_password_must_differ_and_pass_django_validation(self):
        self.request_code()
        self.verify_code()
        for password1, password2 in (
            ('OldPassword-9876', 'OldPassword-9876'),
            ('short', 'short'),
            ('NewStrongPassword-9876', 'DifferentPassword-9876'),
        ):
            with self.subTest(password1=password1):
                response = self.client.post(self.password_url, {
                    'new_password1': password1, 'new_password2': password2,
                })
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['form'].errors)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('OldPassword-9876'))

    def test_password_page_cannot_be_opened_without_verified_code(self):
        self.assertRedirects(self.client.get(self.password_url), self.request_url)
        self.request_code()
        self.assertRedirects(self.client.get(self.password_url), self.request_url)

    def test_invalid_request_fields_do_not_send_email(self):
        for username, email in (('', self.user.email), (self.user.username, 'invalid')):
            response = self.client.post(self.request_url, {
                'username': username, 'email': email,
            })
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context['form'].errors)
        self.assertEqual(len(mail.outbox), 0)

    def test_smtp_failure_invalidates_challenge_without_exposing_details(self):
        with patch('accounts.services.send_mail', side_effect=smtplib.SMTPException('private SMTP error')):
            with self.assertLogs('accounts.services', level='ERROR') as logs:
                self.request_code()
        challenge = RecoveryChallenge.objects.get(user=self.user)
        self.assertIsNotNone(challenge.delivery_failed_at)
        self.assertIsNotNone(challenge.revoked_at)
        self.assertNotIn('private SMTP error', '\n'.join(logs.output))
        self.assertContains(self.client.get(self.verify_url), 'If we can process the request')

    def test_csrf_is_required_on_each_recovery_post(self):
        strict_client = Client(enforce_csrf_checks=True)
        strict_client.get(self.request_url)
        self.assertEqual(strict_client.post(self.request_url, {
            'username': self.user.username, 'email': self.user.email,
        }).status_code, 403)
        self.request_code()
        strict_client.get(self.verify_url)
        self.assertEqual(strict_client.post(self.verify_url, {'code': self.code()}).status_code, 403)
        self.assertEqual(strict_client.post(self.resend_url).status_code, 403)

        RecoveryRateBucket.objects.all().delete()
        csrf_token = strict_client.cookies['csrftoken'].value
        self.assertRedirects(strict_client.post(self.request_url, {
            'username': self.user.username, 'email': self.user.email,
            'csrfmiddlewaretoken': csrf_token,
        }), self.verify_url)
        self.assertRedirects(strict_client.post(self.verify_url, {
            'code': self.code(), 'csrfmiddlewaretoken': csrf_token,
        }), self.password_url)
        self.assertEqual(strict_client.post(self.password_url, {
            'new_password1': 'NewStrongPassword-9876',
            'new_password2': 'NewStrongPassword-9876',
        }).status_code, 403)

    def test_purge_command_removes_old_recovery_state(self):
        self.request_code()
        old_time = timezone.now() - timedelta(days=2)
        RecoveryChallenge.objects.update(expires_at=old_time)
        RecoveryRateBucket.objects.update(window_started_at=old_time)
        call_command('purge_recovery_state', stdout=StringIO())
        self.assertEqual(RecoveryChallenge.objects.count(), 0)
        self.assertEqual(RecoveryRateBucket.objects.count(), 0)

    def test_english_and_spanish_pages_and_email(self):
        for language, heading, subject, verify_heading, password_heading, complete_heading, email_phrase in (
            ('en', 'Recover your password', 'Your Crumb recovery code',
             'Verify your code', 'Set a new password', 'Password updated', 'Your verification code is'),
            ('es', 'Recupera tu contraseña', 'Tu código de recuperación de Crumb',
             'Verifica tu código', 'Establecer una contraseña nueva',
             'Contraseña actualizada', 'Tu código de verificación es'),
        ):
            with self.subTest(language=language):
                self.client.post(reverse('set_language'), {
                    'language': language, 'next': self.request_url,
                })
                self.assertContains(self.client.get(self.request_url), heading)
                RecoveryRateBucket.objects.all().delete()
                self.request_code()
                self.assertEqual(mail.outbox[-1].subject, subject)
                self.assertIn(email_phrase, mail.outbox[-1].body)
                self.assertContains(self.client.get(self.verify_url), verify_heading)
                self.assertContains(self.client.get(self.verify_url), '<html lang="%s">' % language)
                self.assertRedirects(self.verify_code(), self.password_url)
                self.assertContains(self.client.get(self.password_url), password_heading)
                self.assertRedirects(self.client.post(self.password_url, {
                    'new_password1': f'NewStrongPassword-{language}-9876',
                    'new_password2': f'NewStrongPassword-{language}-9876',
                }), self.complete_url)
                self.assertContains(self.client.get(self.complete_url), complete_heading)


class ExistingAccountFlowTests(TestCase):
    def setUp(self):
        Bakery.objects.create(name='Test Bakery', address='Test Address')

    def test_registration_still_creates_user_with_email_and_hashed_password(self):
        response = self.client.post(reverse('accounts:register'), {
            'username': 'new_baker', 'email': 'new_baker@example.com',
            'password1': 'NewStrongPassword-9876',
            'password2': 'NewStrongPassword-9876',
        })
        self.assertRedirects(response, reverse('home'))
        user = get_user_model().objects.get(username='new_baker')
        self.assertTrue(user.check_password('NewStrongPassword-9876'))

    def test_login_still_creates_a_session(self):
        user = get_user_model().objects.create_user(
            username='baker', email='baker@example.com',
            password='OldPassword-9876',
        )
        response = self.client.post(reverse('accounts:login'), {
            'username': 'baker', 'password': 'OldPassword-9876',
        })
        self.assertRedirects(response, reverse('home'))
        self.assertEqual(self.client.session['_auth_user_id'], str(user.pk))


class ConcurrentRecoveryTests(TransactionTestCase):
    def test_old_code_remains_usable_while_replacement_email_is_pending(self):
        user = get_user_model().objects.create_user(
            username='concurrent_baker', email='concurrent@example.com',
            password='OldPassword-9876',
        )
        old_id = request_recovery(user.username, user.email, '127.0.0.1')
        old_code = re.search(r'\b[0-9]{6}\b', mail.outbox[-1].body).group()
        RecoveryRateBucket.objects.filter(scope='identity').update(
            next_allowed_at=timezone.now() - timedelta(seconds=1),
        )
        sending = threading.Event()
        release = threading.Event()
        replacement_code = []

        def hold_delivery(subject, message, from_email, recipients, **kwargs):
            replacement_code.append(re.search(r'\b[0-9]{6}\b', message).group())
            sending.set()
            if not release.wait(timeout=10):
                raise TimeoutError('The concurrent delivery test timed out.')
            return 1

        def resend():
            close_old_connections()
            try:
                return request_recovery(
                    user.username, user.email, '127.0.0.1',
                    fallback_challenge_id=old_id,
                )
            finally:
                close_old_connections()

        with patch('accounts.services.send_mail', side_effect=hold_delivery):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(resend)
                try:
                    self.assertTrue(sending.wait(timeout=10))
                    pending = RecoveryChallenge.objects.exclude(pk=old_id).get()
                    self.assertIsNone(pending.activated_at)
                    self.assertFalse(verify_recovery_code(pending.pk, replacement_code[0]))
                    self.assertTrue(verify_recovery_code(old_id, old_code))
                    self.assertIsNone(RecoveryChallenge.objects.get(pk=old_id).revoked_at)
                finally:
                    release.set()
                self.assertEqual(future.result(timeout=10), pending.pk)

        self.assertIsNotNone(RecoveryChallenge.objects.get(pk=old_id).revoked_at)
        self.assertIsNotNone(RecoveryChallenge.objects.get(pk=pending.pk).activated_at)
        self.assertTrue(verify_recovery_code(pending.pk, replacement_code[0]))

    def test_code_can_be_verified_only_once_under_concurrent_requests(self):
        user = get_user_model().objects.create_user(
            username='concurrent_baker', email='concurrent@example.com',
            password='OldPassword-9876',
        )
        challenge_id = request_recovery(user.username, user.email, '127.0.0.1')
        code = re.search(r'\b[0-9]{6}\b', mail.outbox[-1].body).group()
        barrier = threading.Barrier(2)
        import hmac
        original_compare = hmac.compare_digest

        def compare_together(left, right):
            barrier.wait(timeout=5)
            return original_compare(left, right)

        def attempt():
            close_old_connections()
            try:
                return verify_recovery_code(challenge_id, code)
            finally:
                close_old_connections()

        with patch('accounts.services.hmac.compare_digest', side_effect=compare_together):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: attempt(), range(2)))

        self.assertEqual(results.count(True), 1)
        challenge = RecoveryChallenge.objects.get(pk=challenge_id)
        self.assertEqual(len(challenge.code_digest), 64)
        self.assertIsNotNone(challenge.verified_at)
