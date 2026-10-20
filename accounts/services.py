from django.db import transaction
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login

@transaction.atomic
def register_new_user(form):
    # El formulario ya trae los datos validados y encripta la contraseña de forma segura
    user = form.save()
    return user

def authenticate_user(request, username, password):
    # 'authenticate' verifica encriptación y que las credenciales sean correctas
    user = authenticate(request, username=username, password=password)
    if user is not None:
        # 'login' crea la cookie y guarda la sesión del usuario en el navegador
        login(request, user)
        return user
    return None