from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase


class AuthenticatedTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.auth_user = get_user_model().objects.create_user(
            username='test-auth-user',
            password='ClaveDePrueba-2026',
        )

    def setUp(self):
        super().setUp()
        session = self.client.session
        session['_auth_user_id'] = str(self.auth_user.pk)
        session['_auth_user_backend'] = settings.AUTHENTICATION_BACKENDS[0]
        session['_auth_user_hash'] = self.auth_user.get_session_auth_hash()
        session.save()

