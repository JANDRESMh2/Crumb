from django.conf.urls.i18n import set_language as set_language_view
from django.contrib.auth.decorators import login_not_required, login_required
from django.shortcuts import render

from bakery.services import get_current_bakery
from production.services import build_dashboard


@login_required
def home(request):
    """Home page, with the bakery dashboard once a bakery is set up (FR33)."""
    bakery = get_current_bakery()
    return render(request, 'home.html', {
        'bakery': bakery,
        'dashboard': build_dashboard(bakery=bakery) if bakery is not None else None,
    })


@login_not_required
def set_language_public(request):
    return set_language_view(request)
