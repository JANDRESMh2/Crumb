from django.db import transaction

from .models import Ingredient


@transaction.atomic
def register_ingredient(*, bakery, name, unit, current_quantity, expiration_date):
    """FR01 - register a new ingredient under the given bakery."""
    return Ingredient.objects.create(
        bakery=bakery,
        name=name,
        unit=unit,
        current_quantity=current_quantity,
        expiration_date=expiration_date,
    )
