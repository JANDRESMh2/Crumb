from django import forms
from decimal import Decimal

from .models import Product, ProductionRecord, SalesRecord


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

    sku = forms.CharField(
        max_length=50,
        required=False,
        widget=forms.TextInput(
            attrs={
                'class': 'form-control',
            }
        ),
    )

    unit_price = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal('0.00'),
        widget=forms.NumberInput(
            attrs={
                'class': 'form-control',
                'min': '0',
                'step': '0.01',
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
                status=Product.Status.ACTIVE,
            ).exists()

            if duplicate:
                raise forms.ValidationError(
                    'This product is already registered.'
                )

        return name


class ProductEditForm(forms.ModelForm):
    """Edit an existing baked product."""

    class Meta:
        model = Product

        fields = [
            'name',
            'sku',
            'unit_price',
            'status',
        ]

        labels = {
            'name': 'Name',
            'sku': 'SKU',
            'unit_price': 'Unit price',
            'status': 'Status',
        }

        widgets = {
            'name': forms.TextInput(
                attrs={
                    'class': 'form-control',
                }
            ),
            'sku': forms.TextInput(
                attrs={
                    'class': 'form-control',
                }
            ),
            'unit_price': forms.NumberInput(
                attrs={
                    'class': 'form-control',
                    'min': '0',
                    'step': '0.01',
                }
            ),
            'status': forms.Select(
                attrs={
                    'class': 'form-select',
                }
            ),
        }

    def __init__(self, *args, bakery=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.bakery = bakery

    def clean_name(self):
        name = self.cleaned_data['name'].strip()

        if self.bakery is not None:
            duplicate = (
                Product.objects
                .filter(
                    bakery=self.bakery,
                    name__iexact=name,
                )
                .exclude(pk=self.instance.pk)
                .exists()
            )

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
            'produced_quantity',
            'production_date',
        ]

        labels = {
            'product': 'Product',
            'produced_quantity': 'Quantity produced',
            'production_date': 'Production date and time',
        }

        widgets = {
            'product': forms.Select(
                attrs={
                    'class': 'form-select',
                }
            ),
            'produced_quantity': forms.NumberInput(
                attrs={
                    'class': 'form-control',
                    'min': '0.01',
                    'step': '0.01',
                }
            ),
            'production_date': forms.DateTimeInput(
                attrs={
                    'class': 'form-control',
                    'type': 'datetime-local',
                },
                format='%Y-%m-%dT%H:%M',
            ),
        }

    def __init__(self, *args, bakery=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['product'].queryset = (
            Product.objects.filter(
                bakery=bakery,
                status=Product.Status.ACTIVE,
            )
            if bakery is not None
            else Product.objects.none()
        )


class DailySalesRegistrationForm(forms.ModelForm):
    """FR13 - Daily sales registration form."""

    class Meta:
        model = SalesRecord

        fields = [
            'product',
            'quantity_sold',
            'sale_timestamp',
        ]

        labels = {
            'product': 'Product',
            'quantity_sold': 'Quantity sold',
            'sale_timestamp': 'Sale date and time',
        }

        widgets = {
            'product': forms.Select(
                attrs={
                    'class': 'form-select',
                }
            ),
            'quantity_sold': forms.NumberInput(
                attrs={
                    'class': 'form-control',
                    'min': '0.01',
                    'step': '0.01',
                }
            ),
            'sale_timestamp': forms.DateTimeInput(
                attrs={
                    'class': 'form-control',
                    'type': 'datetime-local',
                },
                format='%Y-%m-%dT%H:%M',
            ),
        }

    def __init__(self, *args, bakery=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['product'].queryset = (
            Product.objects.filter(
                bakery=bakery,
                status=Product.Status.ACTIVE,
            )
            if bakery is not None
            else Product.objects.none()
        )