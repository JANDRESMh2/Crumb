"""Shared form fields.

Quantities and prices used to be captured with ``<input type="number">``. That
looks convenient, but the browser renders and parses those fields with its own
locale: in a browser set to English, typing ``12,5`` silently drops the comma
and submits ``125``, ten times the intended amount, with no error at all. The
same happens the other way round in a Spanish browser with ``12.5``.

``DecimalInputField`` captures the value as text instead, so whatever the user
typed reaches the server untouched, and normalises it here, the same way for
everybody, no matter which browser or language they use.
"""
import re
from decimal import Decimal, InvalidOperation

from django import forms
from django.core.exceptions import ValidationError

# Un separador seguido de exactamente tres digitos y nada mas es ambiguo:
# "1,000" puede ser mil o uno con cero decimales segun el pais.
AMBIGUO = re.compile(r'^\d{1,3}[.,]\d{3}$')


def normalize_decimal_input(value):
    """Turn a human written amount into a value Decimal understands.

    Accepts the separators used on either side of the Atlantic::

        '12.5'      -> '12.5'
        '12,5'      -> '12.5'
        '1.234,56'  -> '1234.56'
        '1,234.56'  -> '1234.56'
        '18000'     -> '18000'

    The last separator in the string is the decimal one, and any other
    separator groups thousands. A value such as ``1,000`` is refused instead of
    guessed, because it means one thousand in English and one in Spanish.
    """
    if value is None:
        return value

    texto = str(value).strip().replace(' ', '')
    if not texto:
        return texto

    signo = ''
    if texto[0] in '+-':
        signo, texto = texto[0], texto[1:]

    if AMBIGUO.match(texto):
        raise ValidationError(
            'Write the amount without a thousands separator, for example '
            '1000 or 1000.50.',
            code='ambiguous_separator',
        )

    ultimo_punto = texto.rfind('.')
    ultima_coma = texto.rfind(',')

    if ultimo_punto == -1 and ultima_coma == -1:
        return signo + texto

    if ultima_coma > ultimo_punto:
        entero, _, decimales = texto.rpartition(',')
    else:
        entero, _, decimales = texto.rpartition('.')

    entero = entero.replace('.', '').replace(',', '')
    return '%s%s.%s' % (signo, entero or '0', decimales)


class DecimalInputField(forms.DecimalField):
    """A decimal field that reads the same in every browser and language."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('widget', forms.TextInput())
        super().__init__(*args, **kwargs)
        self.widget.attrs.setdefault('inputmode', 'decimal')
        self.widget.attrs.setdefault('autocomplete', 'off')
        self.widget.attrs.setdefault('class', 'form-control')

    def to_python(self, value):
        if value in self.empty_values:
            return super().to_python(value)
        try:
            return super().to_python(normalize_decimal_input(value))
        except InvalidOperation:
            raise ValidationError(self.error_messages['invalid'], code='invalid')

    def widget_attrs(self, widget):
        # El atributo step solo tiene sentido en un input numerico; aqui estorba.
        attrs = super().widget_attrs(widget)
        attrs.pop('step', None)
        return attrs


def decimal_field_classes(*nombres):
    """Helper for ``ModelForm.Meta.field_classes``."""
    return {nombre: DecimalInputField for nombre in nombres}
