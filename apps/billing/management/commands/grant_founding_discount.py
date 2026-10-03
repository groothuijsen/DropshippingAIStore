"""Grant a founding-member discount to a shop (T-160).

Usage:
    manage.py grant_founding_discount <shop_domain> <percent_off> [months]

Defaults to 12 months from now. Overwrites any existing discount.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.billing.models import FoundingDiscount
from apps.core.models import Shop


class Command(BaseCommand):
    help = "Grant a founding-member discount to a shop."

    def add_arguments(self, parser):
        parser.add_argument("shop_domain")
        parser.add_argument("percent_off", type=int)
        parser.add_argument("months", type=int, nargs="?", default=12)

    def handle(self, *args, **options):
        domain = options["shop_domain"].lower().strip()
        percent = options["percent_off"]
        months = options["months"]

        if not 1 <= percent <= 100:
            raise CommandError("percent_off must be between 1 and 100.")

        try:
            shop = Shop.objects.get(domain=domain)
        except Shop.DoesNotExist:
            raise CommandError(f"Shop not found: {domain}") from None

        valid_until = timezone.now() + timedelta(days=months * 30)
        discount, created = FoundingDiscount.objects.update_or_create(
            shop=shop,
            defaults={
                "percent_off": percent,
                "valid_until": valid_until,
                "note": f"Granted via management command ({months} months)",
            },
        )
        action = "created" if created else "updated"
        self.stdout.write(self.style.SUCCESS(
            f"Founding discount {percent}% off {action} for {domain} until {valid_until:%Y-%m-%d}"
        ))
