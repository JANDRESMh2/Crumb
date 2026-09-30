from django import forms

from .models import Product, ProductionRecord


class ProductForm(forms.Form):
    """Form for registering or reactivating baked products."""

    name = forms.CharField(
        max_length=120,
        widget=forms.TextInput(
            attrs={
                'class': 'form-control',
                'autofocus': True,
            }
        ),
    )

    def __init__(self, *args, bakery=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.bakery = bakery

    def clean_name(self):
        name = self.cleaned_data['name'].strip()

        if self.bakery is not None:
            duplicate = Product.objects.filter(
                bakery=self.bakery,
                name__iexact=name,
                is_active=True,
            ).exists()

            if duplicate:
                raise forms.ValidationError(
                    'This product is already registered.'
                )

        return name


class DailyProductionRegistrationForm(forms.ModelForm):
    """FR12 - Daily production registration form."""

    class Meta:
        model = ProductionRecord

        fields = [
            'product',
            'quantity',
            'production_date',
        ]

        labels = {
            'product': 'Product',
            'quantity': 'Quantity produced',
            'production_date': 'Production date',
        }

        widgets = {
            'product': forms.Select(
                attrs={
                    'class': 'form-select',
                }
            ),
            'quantity': forms.NumberInput(
                attrs={
                    'class': 'form-control',
                    'min': '1',
                    'step': '1',
                }
            ),
            'production_date': forms.DateInput(
                attrs={
                    'class': 'form-control',
                    'type': 'date',
                },
                format='%Y-%m-%d',
            ),
        }

    def __init__(self, *args, bakery=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['product'].queryset = (
            Product.objects.filter(
                bakery=bakery,
                is_active=True,
            )
            if bakery is not None
            else Product.objects.none()
        )