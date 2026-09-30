"""Merchant data export — JSON export of pages, offers, BrandKit.

See docs/specs/F13-uninstall-gdpr.md criterion 7.
Merchant can take their content with them via Settings.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from django.utils import timezone

if TYPE_CHECKING:
    from apps.core.models import Shop

logger = logging.getLogger(__name__)


def export_shop_data(shop: Shop) -> dict[str, Any]:
    """Export all merchant content as a JSON-serializable dict.

    Contains: pages, offers, brandkit, shop settings.
    NO tokens, NO personal data of shoppers.
    """
    from apps.generator.models import Page
    from apps.offers.models import Offer
    from apps.themes.models import BrandKit

    # Pages
    pages = []
    for page in Page.objects.filter(shop=shop):
        pages.append(
            {
                "id": str(page.id),
                "page_type": page.page_type,
                "title": page.title,
                "content_locale": page.content_locale,
                "sections": page.sections,
                "images": page.images,
                "status": page.status,
                "version": page.version,
                "metaobject_handles": page.metaobject_handles,
            }
        )

    # Offers
    offers = []
    for offer in Offer.objects.filter(shop=shop):
        offers.append(
            {
                "id": str(offer.id),
                "title": offer.title,
                "kind": offer.kind,
                "config": offer.config,
                "status": offer.status,
            }
        )

    # BrandKit
    brandkit_data = None
    try:
        brandkit = BrandKit.objects.get(shop=shop)
        brandkit_data = {
            "palette": brandkit.palette,
            "font_heading": brandkit.font_heading,
            "font_body": brandkit.font_body,
            "style_preset": brandkit.style_preset,
        }
    except BrandKit.DoesNotExist:
        pass

    # Shop settings (NO tokens)
    shop_data = {
        "domain": shop.domain,
        "name": shop.name,
        "currency_code": shop.currency_code,
        "primary_locale": shop.primary_locale,
        "guarantee_policy": shop.guarantee_policy,
        "stock_threshold": shop.stock_threshold,
        "ai_label_default": shop.ai_label_default,
        "ship_cutoff": shop.ship_cutoff,
    }

    return {
        "exported_at": timezone.now().isoformat(),
        "shop": shop_data,
        "pages": pages,
        "offers": offers,
        "brandkit": brandkit_data,
    }


def export_to_json(shop: Shop) -> str:
    """Export shop data as a JSON string."""
    data = export_shop_data(shop)
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)
