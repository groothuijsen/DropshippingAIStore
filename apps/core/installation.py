"""Installation helpers — ensure Shopify definitions exist idempotently.

See docs/03-shopify-integration.md §5.1, §5.2, §6.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from .shopify_client import ShopifyGraphQLClient, load_query

if TYPE_CHECKING:
    from .models import Shop

logger = logging.getLogger(__name__)


def _get_client(shop_domain: str, access_token: str) -> ShopifyGraphQLClient:
    """Create a GraphQL client for installation operations."""
    from django.conf import settings

    return ShopifyGraphQLClient(shop_domain, access_token, settings.SHOPIFY_API_VERSION)


# ── Shop population ───────────────────────────────────────────────────────


def populate_shop_from_info(
    data: dict[str, Any],
    *,
    domain: str,
) -> Shop:
    """Create or update a Shop from shop_info GraphQL response.

    The domain is extracted from the session token (request.shop_domain),
    not from the GraphQL response, to avoid spoofing.
    """
    from .crypto import encrypt_token
    from .models import Shop

    shop_data = data["shop"]
    locales = data.get("shopLocales", [])

    # Find primary locale
    primary_locale = "en"
    for locale in locales:
        if locale.get("primary"):
            primary_locale = locale["locale"]
            break

    # Extract country code from billing address
    billing = shop_data.get("billingAddress") or {}
    country_code = billing.get("countryCodeV2", "")

    # Extract shopify_gid from the full GID
    shopify_gid = shop_data["id"]

    # Get or create — use get_or_create with domain for idempotency
    shop, created = Shop.objects.get_or_create(
        domain=domain,
        defaults={
            "shopify_gid": shopify_gid,
            "name": shop_data.get("name", ""),
            "email": shop_data.get("email", ""),
            "currency_code": shop_data.get("currencyCode", "USD"),
            "iana_timezone": shop_data.get("ianaTimezone", "UTC"),
            "primary_locale": primary_locale,
            "country_code": country_code,
            "access_token_encrypted": encrypt_token("pending"),
            "refresh_token_encrypted": encrypt_token("pending"),
        },
    )

    if not created:
        # Update fields that may change
        shop.name = shop_data.get("name", shop.name)
        shop.email = shop_data.get("email", shop.email)
        shop.currency_code = shop_data.get("currencyCode", shop.currency_code)
        shop.iana_timezone = shop_data.get("ianaTimezone", shop.iana_timezone)
        shop.primary_locale = primary_locale
        shop.country_code = country_code
        shop.shopify_gid = shopify_gid
        shop.save()

    logger.info("Shop %s %s", domain, "created" if created else "updated")
    return shop


# ── Metaobject definitions ────────────────────────────────────────────────

# Field definitions for $app:page_content (03 §5.1)
PAGE_CONTENT_FIELDS = [
    {"key": "page_type", "name": "Page Type", "type": "single_line_text_field"},
    {"key": "locale", "name": "Locale", "type": "single_line_text_field"},
    {"key": "sections", "name": "Sections", "type": "json"},
    {"key": "image_hero", "name": "Hero Image", "type": "file_reference"},
    {"key": "image_lifestyle_1", "name": "Lifestyle Image 1", "type": "file_reference"},
    {"key": "image_lifestyle_2", "name": "Lifestyle Image 2", "type": "file_reference"},
    {"key": "image_detail_1", "name": "Detail Image 1", "type": "file_reference"},
    {"key": "image_detail_2", "name": "Detail Image 2", "type": "file_reference"},
    {"key": "ai_image_disclosure", "name": "AI Image Disclosure", "type": "boolean"},
    {"key": "version", "name": "Version", "type": "number_integer"},
]

# Field definitions for $app:offer_display (03 §5.1)
OFFER_DISPLAY_FIELDS = [
    {"key": "kind", "name": "Kind", "type": "single_line_text_field"},
    {"key": "tiers", "name": "Tiers", "type": "json"},
    {"key": "ends_at", "name": "Ends At", "type": "date_time"},
    {"key": "labels", "name": "Labels", "type": "json"},
]

METAOBJECT_TYPES = {
    "$app:page_content": PAGE_CONTENT_FIELDS,
    "$app:offer_display": OFFER_DISPLAY_FIELDS,
}


def ensure_metaobject_definitions(shop_domain: str, access_token: str) -> dict[str, dict[str, str]]:
    """Ensure metaobject definitions exist. Idempotent.

    Returns a dict with two keys:
    - "result": dict mapping type name to 'exists' or 'created'
    - "type_mapping": dict mapping metaobj_type to the actual API type string
      (e.g. "$app:page_content" -> "app--430212644865--page_content") so that
      metafield definitions can use the correct validation value.
    """
    result: dict[str, str] = {}
    type_mapping: dict[str, str] = {}
    client = _get_client(shop_domain, access_token)

    try:
        for type_name, fields in METAOBJECT_TYPES.items():
            # Check if definition already exists
            check_query = load_query("metaobject_definition_by_type")
            check_data = client.execute(check_query, {"type": type_name})
            existing = check_data.get("metaobjectDefinitionByType")

            if existing:
                logger.info("Metaobject definition %s already exists (%s)", type_name, existing["id"])
                result[type_name] = "exists"
                type_mapping[type_name] = existing["type"]  # Store the API type string
                continue

            # Create the definition
            create_query = load_query("metaobject_definition_create")
            definition_input = {
                "type": type_name,
                "name": type_name.replace("$app:", "").replace("_", " ").title(),
                # API 2026-07: fieldDefinitions[].type is a plain String
                # (e.g. "single_line_text_field"), not {name: ...} — verified
                # via introspection + real error on the dev store.
                "fieldDefinitions": [
                    {"key": f["key"], "name": f["name"], "type": f["type"]}
                    for f in fields
                ],
                "access": {
                    "admin": "MERCHANT_READ",
                    "storefront": "PUBLIC_READ",
                },
                "capabilities": {
                    "publishable": {"enabled": True},
                },
            }
            create_data = client.execute(create_query, {"definition": definition_input})
            user_errors = create_data.get("metaobjectDefinitionCreate", {}).get("userErrors", [])
            if user_errors:
                logger.error("Failed to create metaobject definition %s: %s", type_name, user_errors)
                result[type_name] = "error"
            else:
                created = create_data["metaobjectDefinitionCreate"]["metaobjectDefinition"]
                logger.info("Created metaobject definition %s (%s)", type_name, created["id"])
                result[type_name] = "created"
                # Fall back to the requested type name if the API omits "type".
                type_mapping[type_name] = created.get("type", type_name)
    finally:
        client.close()

    # Return both the status dict and the type mapping
    return {"result": result, "type_mapping": type_mapping}


# ── Metafield definitions ─────────────────────────────────────────────────

# Metafield definitions from 03 §5.2
# Each entry: (owner_type, key, type, name, metaobject_type_or_None)
# metaobject_reference types MUST carry a validation selecting the
# metaobject definition they point to — API 2026-07 rejects definitions
# without it: "Validations require that you select a metaobject".
METAFIELD_DEFINITIONS = [
    # Product metafields
    ("PRODUCT", "page", "list.metaobject_reference", "Page Content", "$app:page_content"),
    ("PRODUCT", "gpsr", "json", "GPSR", None),
    ("PRODUCT", "offer", "metaobject_reference", "Offer", "$app:offer_display"),
    ("PRODUCT", "delivery", "json", "Delivery", None),
    # Page metafields
    ("PAGE", "page", "list.metaobject_reference", "Page Content", "$app:page_content"),
    # Shop metafields
    ("SHOP", "home_page", "list.metaobject_reference", "Home Page", "$app:page_content"),
    ("SHOP", "design_tokens", "json", "Design Tokens", None),
    ("SHOP", "withdrawal", "json", "Withdrawal", None),
    ("SHOP", "settings", "json", "Settings", None),
    ("SHOP", "cart", "json", "Cart", None),
    # Variant metafields
    ("PRODUCTVARIANT", "unit_price", "json", "Unit Price", None),
    ("PRODUCTVARIANT", "prior_price", "json", "Prior Price", None),
]


def ensure_metafield_definitions(
    shop_domain: str,
    access_token: str,
    type_mapping: dict[str, str] | None = None,
) -> dict[str, str]:
    """Ensure metafield definitions exist. Idempotent.

    Returns a dict mapping 'owner_type:key' to 'exists' or 'created'.

    Args:
        type_mapping: Optional dict mapping metaobj_type (e.g. "$app:page_content")
            to the actual API type string (e.g. "app--430212644865--page_content")
            used for metaobject_reference validation values.
    """
    result: dict[str, str] = {}
    client = _get_client(shop_domain, access_token)

    try:
        # Get existing definitions grouped by owner type
        existing_by_owner: dict[str, set[str]] = {}
        owner_types = {"PRODUCT", "PAGE", "SHOP", "PRODUCTVARIANT"}

        for owner_type in owner_types:
            query = load_query("metafield_definitions_by_owner")
            data = client.execute(query, {"ownerType": owner_type})
            nodes = data.get("metafieldDefinitions", {}).get("nodes", [])
            existing_by_owner[owner_type] = {n["key"] for n in nodes}

        # Create missing definitions
        for owner_type, key, metafield_type, name, metaobj_type in METAFIELD_DEFINITIONS:
            lookup_key = f"{owner_type}:{key}"
            if key in existing_by_owner.get(owner_type, set()):
                result[lookup_key] = "exists"
                continue

            create_query = load_query("metafield_definition_create")
            definition_input = {
                "ownerType": owner_type,
                "namespace": "$app:mosaiq",
                "key": key,
                "name": name,
                "type": metafield_type,
                "access": {
                    "admin": "MERCHANT_READ",
                    "storefront": "PUBLIC_READ",
                },
            }
            # metaobject_reference metafields need a validation that selects the
            # metaobject definition they point to. API 2026-07: the option name is
            # metaobject_definition_type and the value is the full type string
            # "app--<app_id>--<type>" (e.g. "app--430212644865--page_content"),
            # NOT "metaobject_definition" and NOT the bare type name.
            # Verified against the dev store: introspection + live create call.
            if metaobj_type:
                # Use the type mapping if available, otherwise fall back to the metaobj_type
                validation_value = type_mapping.get(metaobj_type, metaobj_type) if type_mapping else metaobj_type
                definition_input["validations"] = [
                    {"name": "metaobject_definition_type", "value": validation_value}
                ]
            create_data = client.execute(create_query, {"definition": definition_input})
            user_errors = create_data.get("metafieldDefinitionCreate", {}).get("userErrors", [])
            if user_errors:
                logger.error("Failed to create metafield definition %s: %s", lookup_key, user_errors)
                result[lookup_key] = "error"
            else:
                logger.info("Created metafield definition %s", lookup_key)
                result[lookup_key] = "created"
    finally:
        client.close()

    return result


# ── Default shop metafields ───────────────────────────────────────────────

DEFAULT_DESIGN_TOKENS = {
    "colors": {
        "primary": "#000000",
        "secondary": "#ffffff",
        "accent": "#0066cc",
        "background": "#ffffff",
        "text": "#333333",
    },
    "fonts": {"heading": None, "body": None},
    "radius_px": 8,
    "spacing_scale": 1.0,
    "button_style": "filled",
    "heading_case": "normal",
}

DEFAULT_WITHDRAWAL = {
    "labels": {
        "nl": {"link": "Hier de overeenkomst ontbinden", "confirm": "Ontbinding bevestigen"},
        "en": {"link": "Withdraw from this agreement", "confirm": "Confirm withdrawal"},
        "de": {"link": "Von diesem Vertrag zurücktreten", "confirm": "Widerruf bestätigen"},
    },
    "url": "/apps/mosaiq/withdraw",
}

DEFAULT_SETTINGS = {
    "stock_threshold": 5,
    "ship_cutoff": {
        "time": "16:00",
        "days": ["mon", "tue", "wed", "thu", "fri"],
        "delivery_days": 1,
    },
    "labels": {
        "nl": {"in_stock": "Op voorraad", "low_stock": "Bijna uitverkocht"},
        "en": {"in_stock": "In stock", "low_stock": "Almost sold out"},
        "de": {"in_stock": "Auf Lager", "low_stock": "Fast ausverkauft"},
    },
}

DEFAULT_CART = {
    "enabled": True,
    "upsell_handles": [],
    "reward_thresholds": [
        {
            "amount": "50.00",
            "currency": "EUR",
            "label": {"nl": "Gratis verzending", "en": "Free shipping", "de": "Kostenloser Versand"},
        }
    ],
}

DEFAULT_SHOP_METAFIELDS = {
    "design_tokens": DEFAULT_DESIGN_TOKENS,
    "withdrawal": DEFAULT_WITHDRAWAL,
    "settings": DEFAULT_SETTINGS,
    "cart": DEFAULT_CART,
}


def write_default_shop_metafields(shop: Shop, access_token: str) -> bool:
    """Write default shop metafields. Idempotent — overwrites with same defaults.

    Returns True on success, False if any userErrors occurred.
    """
    client = _get_client(shop.domain, access_token)

    try:
        metafields_input = []
        for key, value in DEFAULT_SHOP_METAFIELDS.items():
            metafields_input.append(
                {
                    # ownerId must be the Shopify GID string, not the local
                    # UUID primary key — API 2026-07 rejects a UUID as
                    # "not JSON serializable" at the httpx encode step.
                    "ownerId": shop.shopify_gid,
                    "namespace": "$app:mosaiq",
                    "key": key,
                    "value": json.dumps(value),
                }
            )

        query = load_query("metafields_set")
        data = client.execute(query, {"metafields": metafields_input})

        user_errors = data.get("metafieldsSet", {}).get("userErrors", [])
        if user_errors:
            logger.error("Failed to write shop metafields for %s: %s", shop.domain, user_errors)
            return False

        logger.info("Wrote %d default shop metafields for %s", len(metafields_input), shop.domain)
        return True
    finally:
        client.close()


# ── Main installation task ────────────────────────────────────────────────


def on_install(shop_domain: str, access_token: str) -> Shop:
    """Run all installation tasks in order.

    Called after token exchange when a new Shop is created.
    Steps 4 (price snapshot) and 5 (source detection) are deferred to T-007/T-020.

    See docs/03-shopify-integration.md §6.
    """
    from .models import AuditLog

    logger.info("Starting installation for %s", shop_domain)

    client = _get_client(shop_domain, access_token)

    try:
        # Step 1: shop_info → populate Shop
        shop_info_query = load_query("shop_info")
        shop_info_data = client.execute(shop_info_query)
        shop = populate_shop_from_info(shop_info_data, domain=shop_domain)

        # Step 2: current_installation → cache installation ID
        installation_query = load_query("current_installation")
        installation_data = client.execute(installation_query)
        installation_id = installation_data.get("currentAppInstallation", {}).get("id", "")
        if installation_id and shop.installation_id != installation_id:
            shop.installation_id = installation_id
            shop.save(update_fields=["installation_id"])
            logger.info("Cached installation ID %s for %s", installation_id, shop_domain)
    finally:
        client.close()

    # Step 3: Ensure metaobject definitions (idempotent)
    metaobj_data = ensure_metaobject_definitions(shop_domain, access_token)
    metaobj_result = metaobj_data["result"]
    type_mapping = metaobj_data["type_mapping"]
    logger.info("Metaobject definitions: %s", metaobj_result)
    logger.info("Type mapping: %s", type_mapping)

    # Step 3: Ensure metafield definitions (idempotent)
    metafield_result = ensure_metafield_definitions(shop_domain, access_token, type_mapping)
    logger.info("Metafield definitions: %s", metafield_result)

    # Step 4: Price snapshot of all active variants
    from apps.compliance.price_snapshot import snapshot_prices

    try:
        snapshot_count = snapshot_prices(shop, access_token)
        logger.info("Price snapshot: %d variants recorded for %s", snapshot_count, shop_domain)
    except Exception as exc:
        logger.error("Price snapshot failed for %s: %s", shop_domain, exc)
        # Non-fatal — continue with installation

    # Step 6: Write default shop metafields
    write_result = write_default_shop_metafields(shop, access_token)
    logger.info("Default shop metafields written: %s", write_result)

    # Step 7: Log installed event
    AuditLog.objects.create(
        shop=shop,
        actor="system",
        action="installed",
        payload={
            "metaobject_definitions": metaobj_result,
            "metafield_definitions": metafield_result,
            "shop_metafields_written": write_result,
        },
    )
    logger.info("Installation completed for %s", shop_domain)

    return shop
