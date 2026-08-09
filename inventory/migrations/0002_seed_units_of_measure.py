from django.db import migrations

UNITS = [
    {'name': 'Kilogram', 'abbreviation': 'kg', 'unit_type': 'mass'},
    {'name': 'Gram', 'abbreviation': 'g', 'unit_type': 'mass'},
    {'name': 'Unit', 'abbreviation': 'u', 'unit_type': 'count'},
    {'name': 'Liter', 'abbreviation': 'L', 'unit_type': 'volume'},
]


def seed_units(apps, schema_editor):
    UnitOfMeasure = apps.get_model('inventory', 'UnitOfMeasure')
    for unit in UNITS:
        UnitOfMeasure.objects.get_or_create(abbreviation=unit['abbreviation'], defaults=unit)


def remove_seeded_units(apps, schema_editor):
    UnitOfMeasure = apps.get_model('inventory', 'UnitOfMeasure')
    UnitOfMeasure.objects.filter(
        abbreviation__in=[unit['abbreviation'] for unit in UNITS]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_units, remove_seeded_units),
    ]
