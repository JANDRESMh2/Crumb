from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.utils.translation import gettext_lazy as _

class UserRegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True, label=_('Email'))

    class Meta:
        model = User
        fields = ['username', 'email']
        labels = {
            'username': _('Username'),
            'email': _('Email'),
        }
        
class UserLoginForm(AuthenticationForm):
    pass