from django import forms
from django.utils.translation import gettext_lazy as _

from bakery.fields import DecimalInputField, decimal_field_classes
from decimal import Decimal
from django.utils import timezone

from .models import Product, ProductionRecord, SalesRecord, ScheduledOrder


class ScheduledOrderForm(forms.ModelForm):
    class Meta:
        model = ScheduledOrder
        fields = ['customer_name', 'product', 'quantity', 'scheduled_for', 'notes']
        widgets = {
            'customer_name': forms.TextInput(attrs={'class': 'form-control'}),
            'product': forms.Select(attrs={'class': 'form-select'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'scheduled_for': forms.DateTimeInput(
                attrs={'class': 'form-control', 'type': 'datetime-local'},
                format='%Y-%m-%dT%H:%M',
            ),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, bakery, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['product'].queryset = Product.objects.filter(
            bakery=bakery, status=Product.Status.ACTIVE,
        )

    def clean_scheduled_for(self):
        scheduled_for = self.cleaned_data['scheduled_for']
        if scheduled_for <= timezone.now():
            raise forms.ValidationError('Choose a date and time in the future.')
        return scheduled_for


class ProductForm(forms.Form):
    """Form for registering or reactivating baked products."""

    name = forms.CharField(
        max_length=120,
        label=_('Name'),
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
        label=_('SKU'),
        widget=forms.TextInput(
            attrs={
                'class': 'form-control',
            }
        ),
    )

    unit_price = DecimalInputField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal('0.00'),
        label=_('Unit price'),
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
                    _('This product is already registered.')
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
        field_classes = decimal_field_classes('unit_price')

        labels = {
            'name': _('Name'),
            'sku': _('SKU'),
            'unit_price': _('Unit price'),
            'status': _('Status'),
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
                    _('This product is already registered.')
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
        field_classes = decimal_field_classes('produced_quantity')

        labels = {
            'product': _('Product'),
            'produced_quantity': _('Quantity produced'),
            'production_date': _('Production date and time'),
        }

        widgets = {
            'product': forms.Select(
                attrs={
                    'class': 'form-select',
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
        self.fields['product'].empty_label = _('Select a product')


class DailySalesRegistrationForm(forms.ModelForm):
    """FR13 - Daily sales registration form."""

    class Meta:
        model = SalesRecord

        fields = [
            'product',
            'quantity_sold',
            'sale_timestamp',
        ]
        field_classes = decimal_field_classes('quantity_sold')

        labels = {
            'product': _('Product'),
            'quantity_sold': _('Quantity sold'),
            'sale_timestamp': _('Sale date and time'),
        }

        widgets = {
            'product': forms.Select(
                attrs={
                    'class': 'form-select',
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
        self.fields['product'].empty_label = _('Select a product')


# [FR27: Automatic daily closing summary]
class DailyClosingForm(forms.Form):
    """FR27 - choose the business day to close, today unless told otherwise."""

    business_date = forms.DateField(
        label=_('Business day'),
        input_formats=['%Y-%m-%d'],
        help_text=_('Days are counted in UTC, the time zone the server keeps.'),
        widget=forms.DateInput(
            format='%Y-%m-%d',
            attrs={'class': 'form-control', 'type': 'date'},
        ),
    )
    confirm_regenerate = forms.BooleanField(
        required=False,
        label=_('Replace the summary if this day is already closed'),
        help_text=_('Only needed when the day was closed before.'),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['business_date'].widget.attrs['max'] = timezone.localdate().isoformat()

    def clean_business_date(self):
        business_date = self.cleaned_data['business_date']
        if business_date > timezone.localdate():
            raise forms.ValidationError(
                _('A day that has not started yet cannot be closed.')
            )
        return business_date


class DailyClosingExportForm(forms.Form):
    """FR27 - the format a closing summary is downloaded in."""

    format = forms.ChoiceField(choices=[('xlsx', 'Excel'), ('pdf', 'PDF')])
