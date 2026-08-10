from django.contrib import messages
from django.shortcuts import redirect, render

from .forms import BakeryProfileForm
from .services import BakeryAlreadyConfigured, get_current_bakery, setup_bakery_profile


def bakery_setup(request):
    """FR09 - register the bakery's business profile during initial setup."""
    if get_current_bakery() is not None:
        return redirect('bakery:detail')

    if request.method == 'POST':
        form = BakeryProfileForm(request.POST)
        if form.is_valid():
            try:
                setup_bakery_profile(**form.cleaned_data)
            except BakeryAlreadyConfigured:
                messages.warning(request, 'The bakery profile was already set up.')
                return redirect('bakery:detail')
            messages.success(request, 'Business profile created successfully.')
            return redirect('bakery:detail')
    else:
        form = BakeryProfileForm()

    return render(request, 'bakery/setup.html', {'form': form})


def bakery_detail(request):
    bakery = get_current_bakery()
    if bakery is None:
        return redirect('bakery:setup')
    return render(request, 'bakery/detail.html', {'bakery': bakery})
