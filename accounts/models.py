import uuid

from django.conf import settings
from django.db import models


class RecoveryChallenge(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    code_digest = models.CharField(max_length=64, blank=True)
    account_fingerprint = models.CharField(max_length=64)
    issued_at = models.DateTimeField()
    activated_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(db_index=True)
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    verified_at = models.DateTimeField(null=True, blank=True)
    grant_expires_at = models.DateTimeField(null=True, blank=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    delivery_failed_at = models.DateTimeField(null=True, blank=True)


class RecoveryRateBucket(models.Model):
    scope = models.CharField(max_length=16)
    key_digest = models.CharField(max_length=64)
    window_started_at = models.DateTimeField()
    request_count = models.PositiveSmallIntegerField(default=0)
    next_allowed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['scope', 'key_digest'], name='unique_recovery_rate_bucket'),
        ]
