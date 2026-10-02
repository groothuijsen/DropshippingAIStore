from datetime import UTC, datetime, timedelta

from django.core.management.base import BaseCommand

from apps.marketing.models import Lead


class Command(BaseCommand):
    help = "Delete unconfirmed leads older than 7 days (T-155)."

    def handle(self, *args, **options):
        cutoff = datetime.now(UTC) - timedelta(days=7)
        deleted, _ = Lead.objects.filter(confirmed_at__isnull=True, created_at__lt=cutoff).delete()
        self.stdout.write(self.style.SUCCESS(f"deleted {deleted} unconfirmed leads"))
