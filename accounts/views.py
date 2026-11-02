from django.shortcuts import render, redirect
from django.contrib import messages
from django.utils.translation import gettext_lazy as _
from bakery.services import get_current_bakery
from .forms import UserRegistrationForm
from .services import register_new_user
from .forms import UserRegistrationForm, UserLoginForm
from .services import register_new_user, authenticate_user

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
            messages.success(request, _('User account registered successfully.'))
            return redirect('home') # Redirige al inicio o al panel de control
    else:
        form = UserRegistrationForm()

    return render(request, 'accounts/register.html', {'form': form})

    # ... (tus imports y user_registration_view) ...

def user_login_view(request):
    bakery = get_current_bakery()
    if not bakery:
        return redirect('bakery:setup')

    if request.method == 'POST':
        form = UserLoginForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            
            user = authenticate_user(request, username, password)
            
            if user is not None:
                messages.success(request, f'Welcome back, {username}!')
                return redirect('home')
            else:
                messages.error(request, _('Invalid username or password.'))
    else:
        form = UserLoginForm()

    return render(request, 'accounts/login.html', {'form': form})