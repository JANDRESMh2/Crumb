from django.shortcuts import render, redirect
from django.contrib import messages
from bakery.services import get_current_bakery
from .forms import UserRegistrationForm
from .services import register_new_user

def user_registration_view(request):
    # Patrón recurrente: verificar el perfil del negocio
    bakery = get_current_bakery()
    if not bakery:
        return redirect('bakery:setup')

    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            # Delegamos la creación a la capa de servicios
            register_new_user(form)
            messages.success(request, 'User account registered successfully.')
            return redirect('home') # Redirige al inicio o al panel de control
    else:
        form = UserRegistrationForm()

    return render(request, 'accounts/register.html', {'form': form})