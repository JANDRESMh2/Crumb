from django import forms

from .models import (
    AlertConfiguration,
    Ingredient,
    StockMovement,
    SUPPORTED_UNIT_ABBREVIATIONS,
    UnitOfMeasure,
)


class IngredientForm(forms.ModelForm):
    expiration_warning_days = forms.IntegerField(
        required=False,
        min_value=0,
        label='Expiration warning days',
        help_text='Show an alert this many days before the expiration date.',
        widget=forms.NumberInput(
            attrs={'class': 'form-control', 'min': '0', 'step': '1'}
        ),
    )

    class Meta:
        model = Ingredient
        fields = [
            'name',
            'unit',
            'current_quantity',
            'expiration_date',
            'expiration_warning_days',
        ]
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
        self.fields['unit'].queryset = UnitOfMeasure.objects.filter(
            abbreviation__in=SUPPORTED_UNIT_ABBREVIATIONS
        )
        self.fields['unit'].empty_label = 'Select a unit'

        if not self.instance._state.adding:
            try:
                configuration = self.instance.alert_configuration
            except AlertConfiguration.DoesNotExist:
                pass
            else:
                self.initial['expiration_warning_days'] = (
                    configuration.expiration_warning_days
                )

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
                bakery=self._bakery,
                name__iexact=name,
                is_active=True,
            )

            if not self.instance._state.adding:
                duplicate = duplicate.exclude(pk=self.instance.pk)

            if duplicate.exists():
                self.add_error(
                    'name',
                    'An ingredient with this name is already registered.'
                )

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

    def __init__(self, *args, bakery=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['ingredient'].queryset = (
            Ingredient.objects.filter(bakery=bakery, is_active=True)
            if bakery is not None
            else Ingredient.objects.none()
        )
