from django.contrib import messages
from django.contrib.auth.decorators import login_not_required, login_required
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from bakery.services import get_current_bakery

from .forms import (
    RecoveryCodeForm,
    RecoveryRequestForm,
    RecoverySetPasswordForm,
    UserLoginForm,
    UserRegistrationForm,
)
from .services import (
    get_recovery_user,
    log_in_user,
    log_out_user,
    recovery_identity_digest,
    register_new_user,
    request_recovery,
    resend_recovery,
    set_recovered_password,
    verify_recovery_code,
)


def _next_url(request):
    """Conserva el next tanto en GET como en el POST del formulario."""
    return request.POST.get('next') or request.GET.get('next') or ''


def _safe_next(request, next_url):
    """Devuelve un redirect solo si next es interno y seguro."""
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return None


def _after_login(request, next_url=''):
    """Decide a donde ir despues de autenticar."""
    safe_redirect = _safe_next(request, next_url)
    if safe_redirect is not None:
        return safe_redirect

    if get_current_bakery() is None:
        return redirect('bakery:setup')
    return redirect('home')


@login_not_required
def user_login_view(request):
    if request.user.is_authenticated:
        return _after_login(request)

    next_url = _next_url(request)

    if request.method == 'POST':
        form = UserLoginForm(request, data=request.POST)
        if form.is_valid():
            user = log_in_user(request, form.get_user())
            messages.success(
                request,
                _('Welcome back, %(username)s!') % {
                    'username': user.get_username(),
                },
            )
            return _after_login(request, next_url)
    else:
        form = UserLoginForm(request)

    return render(
        request,
        'accounts/login.html',
        {'form': form, 'next': next_url},
    )


@login_not_required
def user_registration_view(request):
    if request.user.is_authenticated:
        return _after_login(request)

    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = register_new_user(form)
            log_in_user(request, user)
            messages.success(
                request,
                _('Your account was created successfully.'),
            )
            return _after_login(request)
    else:
        form = UserRegistrationForm()

    return render(request, 'accounts/register.html', {'form': form})


@require_POST
@login_required
def user_logout_view(request):
    log_out_user(request)
    messages.success(request, _('You signed out.'))
    return redirect('accounts:login')


@login_not_required
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


@login_not_required
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


@login_not_required
@require_POST
def recovery_resend_view(request):
    challenge_id = request.session.get('recovery_challenge_id')
    if challenge_id:
        request.session['recovery_challenge_id'] = str(resend_recovery(
            challenge_id, request.META.get('REMOTE_ADDR', ''),
        ))
    return redirect('accounts:recovery_verify')


@login_not_required
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


@login_not_required
def recovery_complete_view(request):
    return render(request, 'accounts/recovery_complete.html')
