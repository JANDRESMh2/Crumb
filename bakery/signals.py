"""Activity log entries that nothing has to remember to write (FR28).

Signing in and out happens inside Django's own authentication views, so the
only way to trace it without touching that code is to listen for the signals
it sends.
"""
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver

from .models import ActivityLog
from .services import record_activity


@receiver(user_logged_in)
def log_sign_in(sender, request, user, **kwargs):
    record_activity(
        user=user,
        action_type=ActivityLog.ActionType.LOGIN,
        description=f'{user.get_username()} signed in.',
    )


@receiver(user_logged_out)
def log_sign_out(sender, request, user, **kwargs):
    if user is None:
        return

    record_activity(
        user=user,
        action_type=ActivityLog.ActionType.LOGOUT,
        description=f'{user.get_username()} signed out.',
    )
