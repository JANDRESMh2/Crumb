"""Shared view decorators for the bakery context.

Every screen that works with bakery data needs the same guard: if the bakery
profile has not been created yet there is nothing to show, so the user is sent
to the setup page. That check used to be copied into sixteen views; it lives
here now, and the bakery it resolves is attached to the request so the view can
use it without asking for it again.
"""
from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect

from .services import get_current_bakery


def bakery_required(message=None):
    """Require a configured bakery, and attach it to the request.

    Usage:

        @bakery_required('Set up the bakery profile before registering stock.')
        def stock_in_create(request):
            bakery = request.bakery

    When no bakery exists the optional message is shown and the user is
    redirected to the setup page.
    """

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            bakery = get_current_bakery()

            if bakery is None:
                if message:
                    messages.info(request, message)
                return redirect('bakery:setup')

            request.bakery = bakery
            return view(request, *args, **kwargs)

        return wrapper

    return decorator
