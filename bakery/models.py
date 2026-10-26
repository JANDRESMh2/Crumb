import uuid

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

phone_validator = RegexValidator(
    regex=r'^\+?[0-9 ()-]{7,20}$',
    message=_('Enter a valid phone number (digits, spaces, +, -, ( and ) only).'),
)


class Bakery(models.Model):
    """Root tenant entity holding a bakery's business profile (FR09, DR04)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=150)
    address = models.CharField(max_length=255)
    phone = models.CharField(max_length=20, blank=True, validators=[phone_validator])
    email = models.EmailField(blank=True)
    tax_id = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'bakery'
        verbose_name_plural = 'bakeries'

    def __str__(self):
        return self.name


class ActivityLog(models.Model):
    """Trace of what each user did in the system (FR28).

    One row per action worth remembering: who did it, what kind of action it
    was, a sentence describing it, and when it happened. The user is kept
    optional so the trace survives the account being deleted, and so actions
    performed before anyone signs in are still recorded.
    """

    class ActionType(models.TextChoices):
        LOGIN = 'Login', _('Signed in')
        LOGOUT = 'Logout', _('Signed out')
        STOCK_IN = 'StockIn', _('Stock-in registered')
        CORRECTION = 'Correction', _('Inventory corrected')
        SALE = 'Sale', _('Sale registered')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='activity_logs',
    )
    action_type = models.CharField(max_length=20, choices=ActionType.choices)
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'activity log entry'
        verbose_name_plural = 'activity log'
        indexes = [
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return f'{self.get_action_type_display()} - {self.created_at:%Y-%m-%d %H:%M}'
