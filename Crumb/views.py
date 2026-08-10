from django.shortcuts import render

from bakery.services import get_current_bakery


def home(request):
    return render(request, 'home.html', {'bakery': get_current_bakery()})
