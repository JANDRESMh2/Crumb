from django.db import transaction
from django.contrib.auth.models import User

@transaction.atomic
def register_new_user(form):
    # El formulario ya trae los datos validados y encripta la contraseña de forma segura
    user = form.save()
    return user