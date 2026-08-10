from django import forms

from .models import Ingredient, UnitOfMeasure
from .models import StockMovement


class IngredientForm(forms.ModelForm):
    class Meta:
        model = Ingredient
        fields = ['name', 'unit', 'current_quantity', 'expiration_date']
        labels = {
            'current_quantity': 'Quantity',
            'unit': 'Unit of measure',
        }
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'autofocus': True}),
            'unit': forms.Select(attrs={'class': 'form-select'}),
            'current_quantity': forms.NumberInput(
                attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}
            ),
            'expiration_date': forms.DateInput(
                attrs={'class': 'form-control', 'type': 'date'}
            ),
        }

    def __init__(self, *args, bakery=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._bakery = bakery
        self.fields['unit'].queryset = UnitOfMeasure.objects.all()
        self.fields['unit'].empty_label = 'Select a unit'

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        if not name:
            raise forms.ValidationError('The ingredient name is required.')
        return name

    def clean(self):
        cleaned = super().clean()
        name = cleaned.get('name')
        if name and self._bakery is not None:
            duplicate = Ingredient.objects.filter(
                bakery=self._bakery, name__iexact=name
            ).exists()
            if duplicate:
                self.add_error('name', 'An ingredient with this name is already registered.')
        return cleaned


class StockInForm(forms.ModelForm):
    class Meta:
        model = StockMovement
        fields = ['ingredient', 'quantity', 'note'] 
        widgets = {
            'quantity': forms.NumberInput(attrs={'step': '0.01', 'min': '0.01', 'class': 'form-control'}),
            'ingredient': forms.Select(attrs={'class': 'form-select'}),
            'note': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
        }