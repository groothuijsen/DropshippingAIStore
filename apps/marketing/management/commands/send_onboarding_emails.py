from django.core.management.base import BaseCommand

from apps.marketing.emails import send_onboarding


class Command(BaseCommand):
    help = "Send the day-based onboarding email series (T-159). Cron-ready: daily."

    def handle(self, *args, **options):
        sent = send_onboarding()
        self.stdout.write(self.style.SUCCESS(f'onboarding emails processed: {sent}'))
