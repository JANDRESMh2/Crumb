from django.conf.urls.i18n import set_language as set_language_view
from django.contrib.auth.decorators import login_not_required, login_required
from django.shortcuts import render

from bakery.services import get_current_bakery


@login_required
def home(request):
    return render(request, 'home.html', {'bakery': get_current_bakery()})


@login_not_required
def set_language_public(request):
    return set_language_view(request)
