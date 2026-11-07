from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from bakery.services import get_current_bakery

from .forms import (
    RecoveryCodeForm, RecoveryRequestForm, RecoverySetPasswordForm,
    UserLoginForm, UserRegistrationForm,
)
from .services import (
    authenticate_user,
    get_recovery_user,
    recovery_identity_digest,
    register_new_user,
    request_recovery,
    resend_recovery,
    set_recovered_password,
    verify_recovery_code,
)


def user_registration_view(request):
    bakery = get_current_bakery()
    if not bakery:
        return redirect('bakery:setup')

    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            register_new_user(form)
            messages.success(request, _('User account registered successfully.'))
            return redirect('home')
    else:
        form = UserRegistrationForm()

    return render(request, 'accounts/register.html', {'form': form})


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


@never_cache
def recovery_request_view(request):
    form = RecoveryRequestForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        identity_digest = recovery_identity_digest(
            form.cleaned_data['username'], form.cleaned_data['email'],
        )
        fallback = (
            request.session.get('recovery_challenge_id')
            if request.session.get('recovery_identity_digest') == identity_digest
            else None
        )
        challenge_id = request_recovery(
            form.cleaned_data['username'], form.cleaned_data['email'],
            request.META.get('REMOTE_ADDR', ''),
            fallback_challenge_id=fallback,
        )
        request.session['recovery_challenge_id'] = str(challenge_id)
        request.session['recovery_identity_digest'] = identity_digest
        return redirect('accounts:recovery_verify')
    return render(request, 'accounts/recovery_request.html', {'form': form})


@never_cache
def recovery_verify_view(request):
    if 'recovery_challenge_id' not in request.session:
        return redirect('accounts:recovery_request')
    form = RecoveryCodeForm(request.POST or None)
    if request.method == 'POST':
        code = form.cleaned_data['code'] if form.is_valid() else request.POST.get('code', '')[:20]
        if verify_recovery_code(request.session['recovery_challenge_id'], code):
            request.session.cycle_key()
            return redirect('accounts:recovery_password')
        form.add_error(None, _('The code is invalid, expired, or has no attempts remaining.'))
    return render(request, 'accounts/recovery_verify.html', {'form': form})


@require_POST
def recovery_resend_view(request):
    challenge_id = request.session.get('recovery_challenge_id')
    if challenge_id:
        request.session['recovery_challenge_id'] = str(resend_recovery(
            challenge_id, request.META.get('REMOTE_ADDR', ''),
        ))
    return redirect('accounts:recovery_verify')


@never_cache
def recovery_password_view(request):
    user = get_recovery_user(request.session.get('recovery_challenge_id'))
    if user is None:
        return redirect('accounts:recovery_request')
    form = RecoverySetPasswordForm(user, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        if set_recovered_password(
            request.session['recovery_challenge_id'], form.cleaned_data['new_password1'],
        ):
            del request.session['recovery_challenge_id']
            request.session.pop('recovery_identity_digest', None)
            return redirect('accounts:recovery_complete')
        form.add_error(None, _('This recovery authorization has expired. Request a new code.'))
    return render(request, 'accounts/recovery_password.html', {'form': form})


def recovery_complete_view(request):
    return render(request, 'accounts/recovery_complete.html')
