from django.contrib.auth import login, logout
from django.db import transaction


@transaction.atomic
def register_new_user(form):
    """Crea el usuario a partir de un formulario ya validado."""
    return form.save()


def log_in_user(request, user):
    """Abre la sesion. authentication ya la hizo el form."""
    login(request, user)
    return user


def log_out_user(request):
    """Cierra la sesion y deja que la signal registre la salida."""
    logout(request)
