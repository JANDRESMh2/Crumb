"""Business logic for the bakery profile, kept out of views and models.

Sprint 1 has no authentication yet (FR31 is a separate, unbuilt ticket), so
Crumb supports exactly one Bakery profile per deployment for now. Once FR31
lands, get_current_bakery() should resolve the tenant from the authenticated
user instead of assuming a single row.
"""

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import ActivityLog, Bakery


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


@transaction.atomic
def update_bakery_profile(bakery, *, name, address, phone='', email='', tax_id=''):
    bakery.name = name
    bakery.address = address
    bakery.phone = phone
    bakery.email = email
    bakery.tax_id = tax_id
    bakery.save(update_fields=['name', 'address', 'phone', 'email', 'tax_id', 'updated_at'])
    return bakery


def record_activity(*, user, action_type, description):
    """FR28 - Record one action in the user activity log.

    Callers pass whatever they have in hand: a signed-in user, ``None``, or
    the anonymous user Django uses before anyone signs in. Only a real
    account is stored, so the entry is kept either way.
    """

    if user is not None and not getattr(user, 'is_authenticated', False):
        user = None

    return ActivityLog.objects.create(
        user=user,
        action_type=action_type,
        description=description,
    )


def build_activity_log(
    *,
    user=None,
    action_type=None,
    start_date=None,
    end_date=None,
):
    """FR28 - Read the activity log, newest first, with optional filters."""

    if start_date and end_date and start_date > end_date:
        raise ValidationError(
            'The start date cannot be later than the end date.'
        )

    entries = ActivityLog.objects.select_related('user')

    if user is not None:
        entries = entries.filter(user=user)
    if action_type:
        entries = entries.filter(action_type=action_type)
    if start_date:
        entries = entries.filter(created_at__date__gte=start_date)
    if end_date:
        entries = entries.filter(created_at__date__lte=end_date)

    return entries
