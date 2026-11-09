from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from bakery.models import Bakery


class LoginViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='ana',
            password='ClaveSegura-2026',
        )

    def test_login_page_is_public_and_links_to_register(self):
        response = self.client.get(reverse('accounts:login'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('accounts:register'))

    def test_invalid_credentials_keep_the_user_anonymous(self):
        response = self.client.post(reverse('accounts:login'), {
            'username': 'ana',
            'password': 'incorrecta',
        })

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].non_field_errors())
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_valid_credentials_open_a_session(self):
        response = self.client.post(reverse('accounts:login'), {
            'username': 'ana',
            'password': 'ClaveSegura-2026',
        })

        self.assertRedirects(
            response,
            reverse('bakery:setup'),
            fetch_redirect_response=False,
        )
        self.assertIn('_auth_user_id', self.client.session)

    def test_login_goes_home_when_the_bakery_exists(self):
        Bakery.objects.create(name='El Buen Pan', address='Calle 10')

        response = self.client.post(reverse('accounts:login'), {
            'username': 'ana',
            'password': 'ClaveSegura-2026',
        })

        self.assertRedirects(
            response,
            reverse('home'),
            fetch_redirect_response=False,
        )

    def test_next_is_honoured_for_internal_urls(self):
        response = self.client.post(
            reverse('accounts:login') + '?next=/inventory/',
            {
                'username': 'ana',
                'password': 'ClaveSegura-2026',
                'next': '/inventory/',
            },
        )

        self.assertRedirects(
            response,
            '/inventory/',
            fetch_redirect_response=False,
        )

    def test_external_next_is_ignored(self):
        response = self.client.post(
            reverse('accounts:login') + '?next=https://evil.example/',
            {
                'username': 'ana',
                'password': 'ClaveSegura-2026',
                'next': 'https://evil.example/',
            },
        )

        self.assertRedirects(
            response,
            reverse('bakery:setup'),
            fetch_redirect_response=False,
        )


class RegistrationViewTests(TestCase):
    payload = {
        'username': 'nueva',
        'email': 'nueva@example.com',
        'password1': 'OtraClaveSegura-2026',
        'password2': 'OtraClaveSegura-2026',
    }

    def test_registration_is_public_even_without_a_bakery(self):
        response = self.client.get(reverse('accounts:register'))

        self.assertEqual(response.status_code, 200)

    def test_registering_creates_the_user_and_opens_a_session(self):
        response = self.client.post(
            reverse('accounts:register'),
            self.payload,
        )

        self.assertTrue(
            get_user_model().objects.filter(username='nueva').exists()
        )
        self.assertRedirects(
            response,
            reverse('bakery:setup'),
            fetch_redirect_response=False,
        )
        self.assertIn('_auth_user_id', self.client.session)


class LogoutViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='ana',
            password='ClaveSegura-2026',
        )
        self.client.force_login(self.user)

    def test_logout_requires_post(self):
        response = self.client.get(reverse('accounts:logout'))

        self.assertEqual(response.status_code, 405)

    def test_logout_closes_the_session(self):
        response = self.client.post(reverse('accounts:logout'))

        self.assertRedirects(
            response,
            reverse('accounts:login'),
            fetch_redirect_response=False,
        )
        self.assertNotIn('_auth_user_id', self.client.session)


class EntryPointTests(TestCase):
    def test_home_sends_anonymous_visitors_to_login(self):
        response = self.client.get(reverse('home'))

        self.assertRedirects(
            response,
            f"{reverse('accounts:login')}?next={reverse('home')}",
            fetch_redirect_response=False,
        )

    def test_home_is_reachable_after_login(self):
        Bakery.objects.create(name='El Buen Pan', address='Calle 10')
        user = get_user_model().objects.create_user(
            username='ana',
            password='ClaveSegura-2026',
        )
        self.client.force_login(user)

        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)


class ProtectedAreaTests(TestCase):
    def test_inventory_requires_login(self):
        url = reverse('inventory:list')
        response = self.client.get(url)
        self.assertRedirects(
            response,
            f"{reverse('accounts:login')}?next={url}",
            fetch_redirect_response=False,
        )

    def test_bakery_and_production_require_login(self):
        for route in ('bakery:detail', 'production:list'):
            url = reverse(route)
            response = self.client.get(url)
            self.assertRedirects(
                response,
                f"{reverse('accounts:login')}?next={url}",
                fetch_redirect_response=False,
            )

    def test_language_switch_is_public(self):
        response = self.client.post(
            reverse('set_language'),
            {'language': 'es', 'next': reverse('accounts:login')},
        )
        self.assertEqual(response.status_code, 302)


