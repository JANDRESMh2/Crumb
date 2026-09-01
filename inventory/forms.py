from django import forms

from decimal import Decimal

from .models import (
    AlertConfiguration,
    BarcodeIdentifier,
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


# [FR17: Barcode scanning for ingredient registration]
class Barcode_scanning_for_ingredient_registration(IngredientForm):
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
        taken = value and BarcodeIdentifier.objects.filter(
            barcode_value=value,
            is_active=True,
            ingredient__is_active=True,
        ).exists()
        if taken:
            raise forms.ValidationError('This barcode is already linked to another ingredient.')
        return value


# [FR08: Stock consumption registration]
class Stock_consumption_registration_form(forms.ModelForm):
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


class LowStockThresholdConfigurationForm(forms.Form):
    minimum_stock_threshold = forms.DecimalField(
        required=False,
        min_value=Decimal('0.01'),
        max_digits=10,
        decimal_places=2,
        label='Low-stock threshold',
        help_text=(
            'Enter the minimum quantity before the ingredient is considered '
            'low stock. Leave blank to remove the threshold.'
        ),
        widget=forms.NumberInput(
            attrs={
                'class': 'form-control',
                'min': '0.01',
                'step': '0.01',
            }
        ),
    )
