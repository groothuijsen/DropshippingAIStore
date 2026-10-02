"""Generate the 1200x630 OG image (T-151, Studio Contrast). Self-hosted Outfit TTF."""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

BG = (250, 250, 248)
FG = (20, 20, 20)
ACC = (232, 84, 47)
MUTED = (107, 107, 102)

HEADLINE = "Sell in the EU without the compliance risk"


class Command(BaseCommand):
    help = "Write marketing/og/home-1200x630.png"

    def handle(self, *args, **options):
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError as exc:  # pragma: no cover
            raise SystemExit("Pillow required: uv add pillow") from exc

        fonts_dir = Path(settings.BASE_DIR) / "apps/marketing/static/marketing/fonts"
        out = Path(settings.BASE_DIR) / "apps/marketing/static/marketing/og/home-1200x630.png"
        out.parent.mkdir(parents=True, exist_ok=True)

        img = Image.new("RGB", (1200, 630), BG)
        draw = ImageDraw.Draw(img)

        logo_font = ImageFont.truetype(str(fonts_dir / "Outfit.ttf"), 46)
        logo_font.set_variation_by_axes([800])
        head_font = ImageFont.truetype(str(fonts_dir / "Outfit.ttf"), 72)
        head_font.set_variation_by_axes([800])
        small_font = ImageFont.truetype(str(fonts_dir / "Outfit.ttf"), 28)
        small_font.set_variation_by_axes([600])

        draw.text((80, 70), "Mosaiq", font=logo_font, fill=FG)
        w_logo = draw.textlength("Mosaiq", font=logo_font)
        draw.text((80 + w_logo, 70), ".app", font=logo_font, fill=ACC)
        draw.rectangle([80, 140, 200, 150], fill=ACC)

        words, lines, cur = HEADLINE.split(), [], ""
        for word in words:
            trial = f"{cur} {word}".strip()
            if draw.textlength(trial, font=head_font) <= 1040:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
        y = 210
        for line in lines:
            draw.text((80, y), line, font=head_font, fill=FG)
            y += 92

        draw.text((80, 540), "GPSR compliance for Shopify stores", font=small_font, fill=MUTED)

        img.save(out)
        self.stdout.write(self.style.SUCCESS(f"wrote {out}"))
