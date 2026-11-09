from django.contrib import messages
from django.contrib.auth.decorators import login_not_required, login_required
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from bakery.services import get_current_bakery

from .forms import UserLoginForm, UserRegistrationForm
from .services import log_in_user, log_out_user, register_new_user


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
