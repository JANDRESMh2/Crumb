"""Business logic for user accounts.

Signing in, signing out and registering (FR31) live next to the password
recovery flow (FR32): both work on the same account, so they share this
module and the rate limits that protect it.
"""
import hashlib
import hmac
import logging
import secrets
import smtplib
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model, login, logout
from django.core.mail import send_mail
from django.db import DatabaseError, transaction
from django.db.models import F, Q
from django.template.loader import render_to_string
from django.utils import timezone

from .models import RecoveryChallenge, RecoveryRateBucket

logger = logging.getLogger(__name__)


@transaction.atomic
def register_new_user(form):
    """FR31a - Crea el usuario a partir de un formulario ya validado."""
    return form.save()


def log_in_user(request, user):
    """FR31b - Abre la sesion. La autenticacion ya la hizo el formulario."""
    login(request, user)
    return user


def log_out_user(request):
    """FR31b - Cierra la sesion y deja que la signal registre la salida."""
    logout(request)


class RecoveryRateLimited(Exception):
    pass


def _digest(purpose, value):
    payload = f'{purpose}:{value}'.encode('utf-8')
    return hmac.new(settings.RECOVERY_HMAC_KEY.encode('utf-8'), payload, hashlib.sha256).hexdigest()


def _account_fingerprint(user):
    return _digest('account', f'{user.pk}:{user.password}:{user.email.casefold()}')


def recovery_identity_digest(username, email):
    return _digest('session-identity', f'{username.casefold()}\0{email.casefold()}')


def _reserve_bucket(scope, value, limit, now, cooldown=False):
    key_digest = _digest(f'rate-{scope}', value)
    bucket, _ = RecoveryRateBucket.objects.get_or_create(
        scope=scope, key_digest=key_digest,
        defaults={'window_started_at': now},
    )
    cutoff = now - timedelta(hours=1)
    RecoveryRateBucket.objects.filter(pk=bucket.pk, window_started_at__lte=cutoff).update(
        window_started_at=now, request_count=0, next_allowed_at=None,
    )
    eligible = RecoveryRateBucket.objects.filter(
        pk=bucket.pk, request_count__lt=limit, window_started_at__gt=cutoff,
    )
    if cooldown:
        eligible = eligible.filter(Q(next_allowed_at__isnull=True) | Q(next_allowed_at__lte=now))
    updates = {'request_count': F('request_count') + 1}
    if cooldown:
        updates['next_allowed_at'] = now + timedelta(seconds=settings.RECOVERY_RESEND_COOLDOWN_SECONDS)
    if not eligible.update(**updates):
        raise RecoveryRateLimited(scope)


def request_recovery(username, email, client_ip, fallback_challenge_id=None):
    now = timezone.now()
    identity = f'{username.casefold()}\0{email.casefold()}'
    try:
        with transaction.atomic():
            _reserve_bucket('ip', client_ip, settings.RECOVERY_IP_HOURLY_LIMIT, now)
        with transaction.atomic():
            _reserve_bucket('identity', identity, settings.RECOVERY_IDENTITY_HOURLY_LIMIT, now, cooldown=True)
            user = get_user_model().objects.filter(
                username=username, email__iexact=email, is_active=True,
            ).first()
            if user is None or not user.has_usable_password():
                return uuid.uuid4()

            previous_digests = set(RecoveryChallenge.objects.filter(
                user=user,
            ).exclude(code_digest='').values_list('code_digest', flat=True))
            for _ in range(10):
                code = f'{secrets.randbelow(1_000_000):06d}'
                code_digest = _digest('code', f'{user.pk}:{code}')
                if code_digest not in previous_digests:
                    break
            else:
                raise RecoveryRateLimited('code-generation')
            challenge = RecoveryChallenge.objects.create(
                user=user,
                code_digest=code_digest,
                account_fingerprint=_account_fingerprint(user),
                issued_at=now,
                expires_at=now + timedelta(seconds=settings.RECOVERY_CODE_LIFETIME_SECONDS),
            )
    except DatabaseError as error:
        logger.error('Recovery state could not be reserved: %s', type(error).__name__)
        return fallback_challenge_id or uuid.uuid4()
    except RecoveryRateLimited:
        return fallback_challenge_id or uuid.uuid4()

    subject = render_to_string('accounts/recovery_subject.txt').strip().replace('\n', ' ')
    message = render_to_string('accounts/recovery_email.txt', {
        'username': user.get_username(), 'code': code,
    })
    try:
        delivered = send_mail(subject, message, None, [user.email], fail_silently=False)
        if delivered != 1:
            raise smtplib.SMTPException('The email backend did not accept the message.')
    except (smtplib.SMTPException, OSError, ValueError) as error:
        failed_at = timezone.now()
        try:
            RecoveryChallenge.objects.filter(
                pk=challenge.pk, activated_at__isnull=True,
            ).update(delivery_failed_at=failed_at, revoked_at=failed_at)
        except DatabaseError:
            logger.error('Pending recovery challenge could not be marked as failed.')
        smtp_code = getattr(error, 'smtp_code', None)
        logger.error(
            'Recovery email delivery failed: %s (SMTP status %s)',
            type(error).__name__,
            smtp_code if isinstance(smtp_code, int) else 'unavailable',
        )
        return fallback_challenge_id or challenge.pk

    try:
        if _activate_sent_challenge(challenge):
            return challenge.pk
    except DatabaseError as error:
        logger.error('Recovery challenge could not be activated: %s', type(error).__name__)
    return fallback_challenge_id or challenge.pk


@transaction.atomic
def _activate_sent_challenge(challenge):
    accepted_at = timezone.now()
    activated = RecoveryChallenge.objects.filter(
        pk=challenge.pk, activated_at__isnull=True,
        revoked_at__isnull=True, delivery_failed_at__isnull=True,
        expires_at__gt=accepted_at,
    ).update(activated_at=accepted_at)
    if not activated:
        return False
    RecoveryChallenge.objects.filter(
        user_id=challenge.user_id, consumed_at__isnull=True, revoked_at__isnull=True,
    ).exclude(pk=challenge.pk).update(revoked_at=accepted_at)
    return True


def resend_recovery(challenge_id, client_ip):
    challenge = _get_challenge(challenge_id)
    if challenge is None or challenge.activated_at is None or challenge.verified_at or challenge.consumed_at:
        return challenge_id
    return request_recovery(
        challenge.user.get_username(), challenge.user.email, client_ip,
        fallback_challenge_id=challenge.pk,
    )


def _get_challenge(challenge_id):
    try:
        normalized = uuid.UUID(str(challenge_id))
    except (ValueError, TypeError, AttributeError):
        return None
    return RecoveryChallenge.objects.select_related('user').filter(pk=normalized).first()


def verify_recovery_code(challenge_id, code):
    try:
        return _verify_recovery_code(challenge_id, code)
    except DatabaseError as error:
        logger.error('Recovery code could not be verified: %s', type(error).__name__)
        return False


def _verify_recovery_code(challenge_id, code):
    challenge = _get_challenge(challenge_id)
    now = timezone.now()
    if (
        challenge is None or challenge.activated_at is None
        or challenge.verified_at or challenge.consumed_at
        or challenge.revoked_at or challenge.expires_at <= now
        or challenge.failed_attempts >= settings.RECOVERY_MAX_CODE_ATTEMPTS
        or not challenge.user.is_active
        or challenge.account_fingerprint != _account_fingerprint(challenge.user)
    ):
        return False

    candidate = _digest('code', f'{challenge.user_id}:{code}')
    if hmac.compare_digest(candidate, challenge.code_digest):
        # Retain the digest to prevent a later challenge from repeating this code.
        return bool(RecoveryChallenge.objects.filter(
            pk=challenge.pk, code_digest=challenge.code_digest,
            activated_at__isnull=False,
            verified_at__isnull=True, revoked_at__isnull=True,
            expires_at__gt=now,
            failed_attempts__lt=settings.RECOVERY_MAX_CODE_ATTEMPTS,
        ).update(
            verified_at=now,
            grant_expires_at=now + timedelta(seconds=settings.RECOVERY_GRANT_LIFETIME_SECONDS),
        ))

    RecoveryChallenge.objects.filter(
        pk=challenge.pk, verified_at__isnull=True, revoked_at__isnull=True,
        activated_at__isnull=False,
        expires_at__gt=now, failed_attempts__lt=settings.RECOVERY_MAX_CODE_ATTEMPTS,
    ).update(failed_attempts=F('failed_attempts') + 1)
    return False


def get_recovery_user(challenge_id):
    challenge = _get_challenge(challenge_id)
    if (
        challenge and challenge.activated_at and challenge.verified_at
        and challenge.grant_expires_at > timezone.now()
        and challenge.consumed_at is None and challenge.revoked_at is None
        and challenge.user.is_active
        and challenge.account_fingerprint == _account_fingerprint(challenge.user)
    ):
        return challenge.user
    return None


def set_recovered_password(challenge_id, new_password):
    try:
        return _set_recovered_password(challenge_id, new_password)
    except DatabaseError as error:
        logger.error('Recovered password could not be saved: %s', type(error).__name__)
        return False


@transaction.atomic
def _set_recovered_password(challenge_id, new_password):
    user = get_recovery_user(challenge_id)
    if user is None or user.check_password(new_password):
        return False
    now = timezone.now()
    updated = RecoveryChallenge.objects.filter(
        pk=challenge_id, consumed_at__isnull=True, revoked_at__isnull=True,
        activated_at__isnull=False,
        verified_at__isnull=False, grant_expires_at__gt=now,
    ).update(consumed_at=now)
    if not updated:
        return False
    user.set_password(new_password)
    user.save(update_fields=['password'])
    RecoveryChallenge.objects.filter(
        user=user, consumed_at__isnull=True, revoked_at__isnull=True,
    ).exclude(pk=challenge_id).update(revoked_at=now)
    return True
