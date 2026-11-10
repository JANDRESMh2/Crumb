from django import forms
from django.contrib.auth.forms import (
    AuthenticationForm,
    SetPasswordForm,
    UserCreationForm,
)
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _


class UserRegistrationForm(UserCreationForm):
    email = forms.EmailField(
        required=True,
        label=_('Email'),
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'autocomplete': 'email',
        }),
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ['username', 'email']
        labels = {
            'username': _('Username'),
            'email': _('Email'),
        }
        widgets = {
            'username': forms.TextInput(attrs={
                'class': 'form-control',
                'autocomplete': 'username',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['password1'].widget.attrs.update({
            'class': 'form-control',
            'autocomplete': 'new-password',
        })
        self.fields['password2'].widget.attrs.update({
            'class': 'form-control',
            'autocomplete': 'new-password',
        })


class UserLoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].widget.attrs.update({
            'class': 'form-control',
            'autocomplete': 'username',
        })
        self.fields['password'].widget.attrs.update({
            'class': 'form-control',
        })


class RecoveryRequestForm(forms.Form):
    username = forms.CharField(max_length=150, label=_('Username'))
    email = forms.EmailField(label=_('Email'))


class RecoveryCodeForm(forms.Form):
    code = forms.RegexField(
        regex=r'^[0-9]{6}$',
        max_length=6,
        label=_('Verification code'),
        error_messages={'invalid': _('Enter a six-digit code.')},
        widget=forms.TextInput(attrs={
            'inputmode': 'numeric', 'autocomplete': 'one-time-code',
            'maxlength': '6', 'pattern': '[0-9]{6}',
        }),
    )


class RecoverySetPasswordForm(SetPasswordForm):
    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get('new_password1')
        if new_password and self.user.check_password(new_password):
            self.add_error('new_password1', _('The new password must differ from the current password.'))
        return cleaned_data
