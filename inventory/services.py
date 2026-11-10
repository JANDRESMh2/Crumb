import io
from decimal import Decimal
from xml.sax.saxutils import escape

import pandas as pd
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.translation import gettext, gettext_lazy as _
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Alignment, Font, PatternFill
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle

from bakery.exports import register_report_fonts, spreadsheet_text
from bakery.models import ActivityLog
from bakery.services import record_activity

from .models import (
    AlertConfiguration, BarcodeIdentifier, Ingredient, IngredientCategory,
    StockMovement, SUPPORTED_UNIT_ABBREVIATIONS, UnitOfMeasure,
)


class InsufficientStockError(Exception):
    """Raised when a consumption would leave an ingredient with negative stock."""


class InventoryCorrectionError(Exception):
    """Raised when a manual correction is invalid (no change, negative or without a reason)."""


def low_stock_alerts(*, ingredient):
    """FR11 - return whether an ingredient needs a low-stock alert."""
    try:
        configuration = ingredient.alert_configuration
    except AlertConfiguration.DoesNotExist:
        return False

    return (
        configuration.is_active
        and configuration.minimum_stock_threshold is not None
        and ingredient.current_quantity
        < configuration.minimum_stock_threshold
    )


def expiration_alerts(*, ingredient, today=None):
    """FR06 - return whether an ingredient needs an expiration alert."""
    if ingredient.expiration_date is None:
        return False

    try:
        configuration = ingredient.alert_configuration
    except AlertConfiguration.DoesNotExist:
        return False

    if (
        not configuration.is_active
        or configuration.expiration_warning_days is None
    ):
        return False

    today = today or timezone.localdate()
    days_until_expiration = (ingredient.expiration_date - today).days
    return 0 <= days_until_expiration <= configuration.expiration_warning_days


def is_ingredient_expired(*, ingredient, today=None):
    """FR06 - return whether an ingredient's expiration date has passed."""
    if ingredient.expiration_date is None:
        return False

    today = today or timezone.localdate()
    return ingredient.expiration_date < today


def configure_expiration_alert(*, ingredient, expiration_warning_days):
    """FR06 - persist or clear an ingredient's expiration warning period."""
    try:
        configuration = ingredient.alert_configuration
    except AlertConfiguration.DoesNotExist:
        if expiration_warning_days is None:
            return None
        return AlertConfiguration.objects.create(
            ingredient=ingredient,
            expiration_warning_days=expiration_warning_days,
        )

    configuration.expiration_warning_days = expiration_warning_days
    if (
        configuration.minimum_stock_threshold is None
        and configuration.expiration_warning_days is None
    ):
        configuration.delete()
        return None

    configuration.save(update_fields=['expiration_warning_days'])
    return configuration


@transaction.atomic
def configure_low_stock_threshold(*, ingredient, minimum_stock_threshold):
    """FR10 - configure or clear an ingredient's low-stock threshold."""

    try:
        configuration = ingredient.alert_configuration
    except AlertConfiguration.DoesNotExist:
        if minimum_stock_threshold is None:
            return None

        return AlertConfiguration.objects.create(
            ingredient=ingredient,
            minimum_stock_threshold=minimum_stock_threshold,
        )

    configuration.minimum_stock_threshold = minimum_stock_threshold

    if (
        configuration.minimum_stock_threshold is None
        and configuration.expiration_warning_days is None
    ):
        configuration.delete()
        return None

    configuration.save(
        update_fields=['minimum_stock_threshold']
    )

    return configuration


def _validate_ingredient_category(category):
    if category not in IngredientCategory.values:
        raise ValueError('Select a valid ingredient category.')


@transaction.atomic
def register_ingredient(
    *,
    bakery,
    name,
    category,
    unit,
    current_quantity,
    expiration_date,
    expiration_warning_days=None,
    barcode_value='',
):
    """FR01 - register a new ingredient under the given bakery.

    barcode_value is optional (FR17) - when provided, links a scanned barcode
    to the ingredient being registered.
    """
    _validate_ingredient_category(category)

    existing = Ingredient.objects.filter(
        bakery=bakery,
        name__iexact=name,
        is_active=False,
    ).first()

    if existing is not None:
        existing.name = name
        existing.category = category
        existing.unit = unit
        existing.current_quantity = current_quantity
        existing.expiration_date = expiration_date
        existing.is_active = True

        existing.save(
            update_fields=[
                'name',
                'category',
                'unit',
                'current_quantity',
                'expiration_date',
                'is_active',
                'updated_at',
            ]
        )

        configure_expiration_alert(
            ingredient=existing,
            expiration_warning_days=expiration_warning_days,
        )
        if barcode_value:
            _link_barcode(ingredient=existing, barcode_value=barcode_value)
        return existing

    ingredient = Ingredient.objects.create(
        bakery=bakery,
        name=name,
        category=category,
        unit=unit,
        current_quantity=current_quantity,
        expiration_date=expiration_date,
    )
    configure_expiration_alert(
        ingredient=ingredient,
        expiration_warning_days=expiration_warning_days,
    )
    if barcode_value:
        _link_barcode(ingredient=ingredient, barcode_value=barcode_value)
    return ingredient


def _link_barcode(*, ingredient, barcode_value):
    """FR17 - point a barcode at an ingredient.

    barcode_value is unique, so an ingredient that was deleted and registered
    again would collide with its own old row. Reusing the row (instead of
    creating a second one) keeps the re-registration flow working and
    reactivates the link.
    """
    BarcodeIdentifier.objects.update_or_create(
        barcode_value=barcode_value,
        defaults={'ingredient': ingredient, 'is_active': True},
    )


@transaction.atomic
def register_stock_consumption(*, bakery, ingredient, quantity, note=''):
    """FR08 - register the consumption of an ingredient, decreasing its stock.

    Refuses to leave the ingredient with negative stock (DR03). The form
    already checks this for a friendly error message; this check is the
    authoritative guard in case the service is called directly.
    """
    if quantity > ingredient.current_quantity:
        raise InsufficientStockError(
            f'Cannot consume {quantity} of {ingredient.name}; '
            f'only {ingredient.current_quantity} available.'
        )

    ingredient.current_quantity -= quantity
    ingredient.save(update_fields=['current_quantity', 'updated_at'])

    return StockMovement.objects.create(
        bakery=bakery,
        ingredient=ingredient,
        movement_type='Consumption',
        quantity=quantity,
        note=note,
    )


@transaction.atomic
def update_ingredient(
    *,
    ingredient,
    name,
    category,
    unit,
    current_quantity,
    expiration_date,
    expiration_warning_days=None,
):
    """FR03 - edit an existing ingredient."""
    _validate_ingredient_category(category)
    ingredient.name = name
    ingredient.category = category
    ingredient.unit = unit
    ingredient.current_quantity = current_quantity
    ingredient.expiration_date = expiration_date
    ingredient.save(
        update_fields=[
            'name',
            'category',
            'unit',
            'current_quantity',
            'expiration_date',
            'updated_at',
        ]
    )
    configure_expiration_alert(
        ingredient=ingredient,
        expiration_warning_days=expiration_warning_days,
    )
    return ingredient


@transaction.atomic
def deactivate_ingredient(*, ingredient):
    """FR04 - remove an ingredient from the active inventory.

    Its barcodes are deactivated too (FR17), so the value stops showing in the
    catalog and can be linked to another ingredient later.
    """
    ingredient.is_active = False
    ingredient.save(update_fields=['is_active', 'updated_at'])
    ingredient.barcodes.update(is_active=False)
    return ingredient


def import_ingredients_from_excel(*, file, bakery):
    """FR15 - import ingredients from Excel or CSV file."""
    column_mapping = {
        'Nombre': 'name', 'Unidad': 'unit', 'Cantidad': 'quantity',
        'Fecha de caducidad': 'expiration_date', 
        'Dias de aviso de caducidad': 'expiration_warning_days',
        'Codigo de barras': 'barcode'
    }

    # Cargar y normalizar encabezados
    df = pd.read_csv(file) if file.name.endswith('.csv') else pd.read_excel(file)
    df.columns = [str(c).strip().capitalize() for c in df.columns] # Normaliza mayúsculas
    df.rename(columns=column_mapping, inplace=True)
    df.columns = [c.lower() for c in df.columns] # Fuerza minúsculas para validación interna

    required_cols = {'name', 'unit', 'quantity', 'expiration_date'}
    if missing := required_cols - set(df.columns):
        raise ValueError(f"Missing required columns: {', '.join(missing)}")

    # Limpiar nulos de forma nativa para evitar strings 'nan' o 'none'
    df = df.where(pd.notnull(df), None)

    # Precargar datos de la BD
    units = UnitOfMeasure.objects.filter(abbreviation__in=SUPPORTED_UNIT_ABBREVIATIONS)
    unit_map = {**{u.name.lower(): u for u in units}, **{u.abbreviation.lower(): u for u in units}}
    existing_map = {ing.name.lower(): ing for ing in Ingredient.objects.filter(bakery=bakery, is_active=True)}

    new_ingredients, update_ingredients = [], []
    alerts_to_process, barcodes_to_link = [], []

    # itertuples es más rápido y limpio que iterrows
    for row in df.itertuples(index=False):
        if not row.name: continue
        name = str(row.name).strip()
        
        unit = unit_map.get(str(row.unit).strip().lower())
        if not unit: 
            raise ValueError(f"Unknown unit: {row.unit} for ingredient {name}")

        try:
            quantity = Decimal(str(row.quantity))
            expiration_date = pd.to_datetime(row.expiration_date).date()
        except Exception as e:
            raise ValueError(f"Invalid quantity or date for {name}: {e}")

        # Lógica de creación / actualización
        ing = existing_map.get(name.lower())
        if ing:
            ing.current_quantity += quantity
            ing.expiration_date = expiration_date
            ing.unit = unit
            update_ingredients.append(ing)
        else:
            ing = Ingredient(bakery=bakery, name=name, unit=unit, current_quantity=quantity, expiration_date=expiration_date)
            new_ingredients.append(ing)

        # Alertas y códigos de barras (sin distinguir si son nuevos o actualizados)
        if getattr(row, 'expiration_warning_days', None) is not None:
            alerts_to_process.append((ing, int(row.expiration_warning_days)))
        
        barcode = getattr(row, 'barcode', None)
        if barcode:
            barcodes_to_link.append((ing, str(barcode).strip()))

    # Ejecución en base de datos
    with transaction.atomic():
        if new_ingredients:
            Ingredient.objects.bulk_create(new_ingredients)
        if update_ingredients:
            # Nota: Si updated_at usa auto_now=True, bulk_update no lo actualizará automáticamente,
            # tendrías que inyectar timezone.now() manualmente en el objeto antes de este paso.
            Ingredient.objects.bulk_update(update_ingredients, ['current_quantity', 'expiration_date', 'unit'])

        for ing, wd in alerts_to_process:
            configure_expiration_alert(ingredient=ing, expiration_warning_days=wd)
            
        for ing, code in barcodes_to_link:
            _link_barcode(ingredient=ing, barcode_value=code)

    return len(new_ingredients), len(update_ingredients)


@transaction.atomic
def register_inventory_correction(*, bakery, ingredient, new_quantity, reason, user=None):
    """FR23 - manually correct an ingredient's quantity, logging the change.

    The correction is stored as a StockMovement of type Correction with the
    quantity before and after, the reason and the user, so every manual change
    to the stock leaves an audit trail. The form already validates the input;
    these checks are the authoritative guard if the service is called directly.
    """
    ingredient.refresh_from_db(fields=['current_quantity'])
    previous_quantity = ingredient.current_quantity
    reason = (reason or '').strip()

    if new_quantity is None or new_quantity < 0:
        raise InventoryCorrectionError(_('The corrected quantity cannot be negative.'))
    if new_quantity == previous_quantity:
        raise InventoryCorrectionError(
            _('The corrected quantity must be different from the current quantity.')
        )
    if not reason:
        raise InventoryCorrectionError(_('A reason is required to correct the inventory.'))

    ingredient.current_quantity = new_quantity
    ingredient.save(update_fields=['current_quantity', 'updated_at'])

    movement = StockMovement.objects.create(
        bakery=bakery,
        ingredient=ingredient,
        movement_type='Correction',
        quantity=abs(new_quantity - previous_quantity),
        previous_quantity=previous_quantity,
        new_quantity=new_quantity,
        note=reason,
        user=user,
    )

    record_activity(
        user=user,
        action_type=ActivityLog.ActionType.CORRECTION,
        description=gettext(
            'Corrected the stock of %(name)s from %(before)s to %(after)s.'
        ) % {
            'name': ingredient.name,
            'before': previous_quantity,
            'after': new_quantity,
        },
    )

    return movement


@transaction.atomic
def register_stock_in(*, bakery, ingredient, quantity, note='', user=None):
    """FR07 - register a stock-in movement, increasing the ingredient's stock.

    Shared by the stock-in form (FR07) and the continuous barcode scan (FR18),
    so both paths update the stock and log the movement in exactly the same way.
    """
    if quantity is None or quantity <= 0:
        raise ValueError(_('A stock-in quantity must be greater than zero.'))

    ingredient.current_quantity += quantity
    ingredient.save(update_fields=['current_quantity', 'updated_at'])

    movement = StockMovement.objects.create(
        bakery=bakery,
        ingredient=ingredient,
        movement_type='StockIn',
        quantity=quantity,
        note=note,
        user=user,
    )

    record_activity(
        user=user,
        action_type=ActivityLog.ActionType.STOCK_IN,
        description=gettext(
            'Registered %(quantity)s of %(name)s into the stock.'
        ) % {'quantity': quantity, 'name': ingredient.name},
    )

    return movement


def find_ingredient_by_barcode(*, bakery, barcode_value):
    """FR18 - find the active ingredient a scanned barcode belongs to."""
    barcode = (
        BarcodeIdentifier.objects
        .filter(
            barcode_value=barcode_value,
            is_active=True,
            ingredient__bakery=bakery,
            ingredient__is_active=True,
        )
        .select_related('ingredient', 'ingredient__unit')
        .first()
    )
    return barcode.ingredient if barcode is not None else None


IMPORT_TEMPLATE_COLUMNS = [
    'Name',
    'Unit',
    'Quantity',
    'Expiration date',
    'Expiration warning days',
    'Barcode',
]


def build_import_template():
    """FR15 - build the empty Excel template used to import ingredients."""
    buffer = io.BytesIO()
    pd.DataFrame(columns=IMPORT_TEMPLATE_COLUMNS).to_excel(buffer, index=False)
    return buffer.getvalue()


def filter_inventory_ingredients(*, bakery, query='', start_date=None, end_date=None):
    """Return active ingredients using the inventory page's search and dates."""
    ingredients = (
        Ingredient.objects.filter(bakery=bakery, is_active=True)
        .select_related('unit', 'alert_configuration')
        .prefetch_related('barcodes')
        if bakery is not None else Ingredient.objects.none()
    )
    if query:
        ingredients = ingredients.filter(name__icontains=query)

    start = parse_date(start_date) if isinstance(start_date, str) else start_date
    end = parse_date(end_date) if isinstance(end_date, str) else end_date
    if start and end and start > end:
        return Ingredient.objects.none(), False
    if start:
        ingredients = ingredients.filter(expiration_date__gte=start)
    if end:
        ingredients = ingredients.filter(expiration_date__lte=end)
    return ingredients.order_by('name', 'pk'), True


def build_inventory_report(*, bakery, query='', start_date=None, end_date=None):
    """Build the same inventory rows for both downloadable formats."""
    ingredients, valid_range = filter_inventory_ingredients(
        bakery=bakery, query=query, start_date=start_date, end_date=end_date,
    )
    if not valid_range:
        raise ValueError(gettext('The start date cannot be later than the end date.'))

    today = timezone.localdate()
    rows = []
    for ingredient in ingredients:
        statuses = []
        if low_stock_alerts(ingredient=ingredient):
            statuses.append(gettext('Low stock'))
        if is_ingredient_expired(ingredient=ingredient, today=today):
            statuses.append(gettext('Expired'))
        elif expiration_alerts(ingredient=ingredient, today=today):
            statuses.append(gettext('Expiring soon'))
        rows.append({
            'name': ingredient.name,
            'category': ingredient.get_category_display() if ingredient.category else gettext('Uncategorized'),
            'quantity': ingredient.current_quantity,
            'unit': ingredient.unit.abbreviation,
            'expiration_date': ingredient.expiration_date,
            'barcode': ingredient.active_barcode,
            'status': ', '.join(statuses) if statuses else gettext('No inventory alert'),
        })
    return rows


def _report_headers():
    return [
        gettext('Name'), gettext('Category'), gettext('Quantity'), gettext('Unit'),
        gettext('Expires'), gettext('Barcode'), gettext('Status'),
    ]


def build_inventory_excel(*, rows, bakery):
    """Render inventory rows as a formatted XLSX document."""
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet(gettext('Inventory')[:31])
    sheet.freeze_panes = 'A4'
    for column, width in {
        'A': 35, 'B': 30, 'C': 16, 'D': 12, 'E': 18, 'F': 24, 'G': 28,
    }.items():
        sheet.column_dimensions[column].width = width

    sheet.append([gettext('Inventory report'), spreadsheet_text(bakery.name)])
    sheet.append([])
    header_cells = []
    for heading in _report_headers():
        cell = WriteOnlyCell(sheet, value=heading)
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = PatternFill('solid', fgColor='344760')
        cell.alignment = Alignment(vertical='center')
        header_cells.append(cell)
    sheet.append(header_cells)

    for row in rows:
        date_cell = WriteOnlyCell(sheet, value=row['expiration_date'])
        date_cell.number_format = 'yyyy-mm-dd'
        quantity_cell = WriteOnlyCell(sheet, value=float(row['quantity']))
        quantity_cell.number_format = '0.00'
        sheet.append([
            spreadsheet_text(row['name']), spreadsheet_text(row['category']),
            quantity_cell, row['unit'], date_cell,
            spreadsheet_text(row['barcode']), spreadsheet_text(row['status']),
        ])
    if not rows:
        sheet.append([gettext('No ingredients match the selected filters.')])

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def build_inventory_pdf(*, rows, bakery):
    """Render inventory rows as a paginated PDF document."""
    register_report_fonts()
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=landscape(A4), leftMargin=28, rightMargin=28,
        topMargin=32, bottomMargin=32,
    )
    title_style = ParagraphStyle(
        'ReportTitle', fontName='CrumbVeraBold', fontSize=16, leading=21,
        textColor=colors.HexColor('#25364A'), spaceAfter=8,
    )
    body_style = ParagraphStyle(
        'ReportBody', fontName='CrumbVera', fontSize=8, leading=11,
        splitLongWords=1,
    )
    heading_style = ParagraphStyle(
        'ReportHeading', parent=body_style, fontName='CrumbVeraBold',
        textColor=colors.white,
    )
    title = Paragraph(escape(gettext('Inventory report')), title_style)
    bakery_label = Paragraph(escape(bakery.name), body_style)
    table_rows = [[Paragraph(escape(label), heading_style) for label in _report_headers()]]
    for row in rows:
        values = [
            row['name'], row['category'], f"{row['quantity']:.2f}", row['unit'],
            row['expiration_date'].isoformat() if row['expiration_date'] else '—',
            row['barcode'] or '—', row['status'],
        ]
        table_rows.append([
            Paragraph(escape(str(value)), body_style) for value in values
        ])
    if not rows:
        table_rows.append([
            Paragraph(escape(gettext('No ingredients match the selected filters.')), body_style),
            '', '', '', '', '', '',
        ])

    table = LongTable(
        table_rows, colWidths=[138, 128, 64, 50, 85, 105, 195],
        repeatRows=1, hAlign='LEFT',
    )
    table_styles = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#344760')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F2F5F8')]),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 7),
        ('RIGHTPADDING', (0, 0), (-1, -1), 7),
    ]
    if not rows:
        table_styles.append(('SPAN', (0, 1), (-1, 1)))
    table.setStyle(TableStyle(table_styles))

    def draw_page_number(canvas, pdf_document):
        canvas.setFont('CrumbVera', 8)
        canvas.setFillColor(colors.HexColor('#5B6573'))
        canvas.drawCentredString(
            landscape(A4)[0] / 2, 18,
            f"{gettext('Page')} {pdf_document.page}",
        )

    document.build(
        [title, bakery_label, Spacer(1, 14), table],
        onFirstPage=draw_page_number, onLaterPages=draw_page_number,
    )
    return buffer.getvalue()


def build_expired_ingredient_losses(
    *,
    bakery,
    start_date=None,
    end_date=None,
    today=None,
):
    """
    FR26 - List the ingredients that expired while still holding stock.

    An ingredient counts as a loss when its expiration date has already
    passed, which is the same rule FR06 applies in `is_ingredient_expired`,
    and some quantity is still on hand. The optional dates narrow the report
    to the ingredients that expired inside that range.

    Only active ingredients are reported. Deactivating an ingredient (FR04)
    takes it out of the inventory without touching its quantity, so the
    stored amount is no longer a reliable measure of what was lost.
    """

    today = today or timezone.localdate()

    ingredients = (
        Ingredient.objects
        .filter(
            bakery=bakery,
            is_active=True,
            expiration_date__lt=today,
            current_quantity__gt=0,
        )
        .select_related('unit')
        .order_by('expiration_date', 'name')
    )

    if start_date:
        ingredients = ingredients.filter(expiration_date__gte=start_date)
    if end_date:
        ingredients = ingredients.filter(expiration_date__lte=end_date)

    return [
        {
            'ingredient_id': ingredient.pk,
            'ingredient_name': ingredient.name,
            'unit_abbreviation': ingredient.unit.abbreviation,
            'quantity': ingredient.current_quantity,
            'expiration_date': ingredient.expiration_date,
            'days_expired': (today - ingredient.expiration_date).days,
        }
        for ingredient in ingredients
    ]
