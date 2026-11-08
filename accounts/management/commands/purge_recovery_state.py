from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import RecoveryChallenge, RecoveryRateBucket


class Command(BaseCommand):
    help = 'Delete expired password recovery challenges and rate buckets.'

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=1)
        challenges, _ = RecoveryChallenge.objects.filter(expires_at__lt=cutoff).delete()
        buckets, _ = RecoveryRateBucket.objects.filter(window_started_at__lt=cutoff).delete()
        self.stdout.write(f'Deleted {challenges} recovery challenges and {buckets} rate buckets.')
