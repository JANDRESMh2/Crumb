"""Business logic for the bakery profile, kept out of views and models.

Sprint 1 has no authentication yet (FR31 is a separate, unbuilt ticket), so
Crumb supports exactly one Bakery profile per deployment for now. Once FR31
lands, get_current_bakery() should resolve the tenant from the authenticated
user instead of assuming a single row.
"""

from django.db import transaction

from .models import Bakery


class BakeryAlreadyConfigured(Exception):
    """Raised when initial setup is attempted after a profile already exists."""


def get_current_bakery():
    return Bakery.objects.order_by('created_at').first()


@transaction.atomic
def setup_bakery_profile(*, name, address, phone='', email='', tax_id=''):
    if Bakery.objects.exists():
        raise BakeryAlreadyConfigured('The bakery profile has already been set up.')
    return Bakery.objects.create(
        name=name,
        address=address,
        phone=phone,
        email=email,
        tax_id=tax_id,
    )
