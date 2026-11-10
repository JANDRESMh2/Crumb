"""Shared helpers for the downloadable reports (FR16, FR27).

The inventory report and the daily closing summary are both written as XLSX
and PDF files. Whatever makes those files safe to open has to be applied the
same way in both, so it lives here instead of being copied into each app.
"""
import re
from pathlib import Path

import reportlab
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

EXCEL_INVALID_CONTROL_CHARACTERS = re.compile(r'[\x00-\x08\x0b-\x0c\x0e-\x1f]')


def spreadsheet_text(value):
    """Remove Excel-invalid controls and keep text from becoming a formula."""
    value = EXCEL_INVALID_CONTROL_CHARACTERS.sub('', str(value or ''))
    if value.lstrip().startswith(('=', '+', '-', '@')):
        return "'" + value
    return value


def register_report_fonts():
    """Register the fonts the PDF reports use, once per process.

    The Vera fonts ship with reportlab and cover the accented letters the
    Spanish interface needs, which the built-in PDF fonts do not.
    """
    fonts = Path(reportlab.__file__).parent / 'fonts'
    registered_fonts = pdfmetrics.getRegisteredFontNames()
    if 'CrumbVera' not in registered_fonts:
        pdfmetrics.registerFont(TTFont('CrumbVera', str(fonts / 'Vera.ttf')))
    if 'CrumbVeraBold' not in registered_fonts:
        pdfmetrics.registerFont(TTFont('CrumbVeraBold', str(fonts / 'VeraBd.ttf')))
