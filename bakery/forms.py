from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Bakery


class BakeryProfileForm(forms.ModelForm):
    class Meta:
        model = Bakery
        fields = ['name', 'address', 'phone', 'email', 'tax_id']
        labels = {
            'name': _('Name'),
            'address': _('Address'),
            'phone': _('Phone'),
            'email': _('Email'),
            'tax_id': _('Tax ID'),
        }
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'autofocus': True}),
            'address': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'tax_id': forms.TextInput(attrs={'class': 'form-control'}),
        }
        help_texts = {
            'phone': _('Optional.'),
            'email': _('Optional.'),
            'tax_id': _('Optional.'),
        }

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        if not name:
            raise forms.ValidationError(_('The bakery name is required.'))
        return name

    def clean_address(self):
        address = self.cleaned_data['address'].strip()
        if not address:
            raise forms.ValidationError(_('The bakery address is required.'))
        return address
