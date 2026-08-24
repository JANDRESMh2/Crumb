from django import forms

from .models import (
    BarcodeIdentifier,
    Ingredient,
    StockMovement,
    SUPPORTED_UNIT_ABBREVIATIONS,
    UnitOfMeasure,
)


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
        self.fields['unit'].queryset = UnitOfMeasure.objects.filter(
            abbreviation__in=SUPPORTED_UNIT_ABBREVIATIONS
        )
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


class IngredientRegistrationForm(IngredientForm):
    """Adds an optional barcode field to IngredientForm, scoped to initial
    registration (FR17). Editing an ingredient (FR03) keeps using the base
    IngredientForm unchanged.
    """

    barcode_value = forms.CharField(
        required=False,
        label='Barcode',
        help_text='Optional. Scan or type a barcode to link it to this ingredient.',
        widget=forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'off'}),
    )

    def clean_barcode_value(self):
        value = self.cleaned_data['barcode_value'].strip()
        if value and BarcodeIdentifier.objects.filter(barcode_value=value).exists():
            raise forms.ValidationError('This barcode is already linked to another ingredient.')
        return value


class StockConsumptionForm(forms.ModelForm):
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

    def clean(self):
        cleaned = super().clean()
        ingredient = cleaned.get('ingredient')
        quantity = cleaned.get('quantity')

        if ingredient is not None and quantity is not None and quantity > ingredient.current_quantity:
            self.add_error(
                'quantity',
                f'Only {ingredient.current_quantity} {ingredient.unit.abbreviation} '
                f'of {ingredient.name} available.',
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
