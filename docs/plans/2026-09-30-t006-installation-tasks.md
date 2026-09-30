# T-006 — Installation Tasks Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Implement the `on_install` Celery task that populates Shop data, ensures metaobject/metafield definitions exist (idempotent), writes default shop metafields, and logs an `installed` event.

**Architecture:** A single orchestrator task `core.tasks.on_install` calls helper functions in order. Each helper uses the existing `ShopifyGraphQLClient` to run GraphQL operations. All mutations are idempotent — running `on_install` twice produces no errors and no duplicates (F00-6, F00-8). Definitions are looked up by owner type + namespace + key (or type), never by stored ID.

**Tech Stack:** Django 5.2, Celery 5.x, httpx (via existing ShopifyGraphQLClient), pytest + pytest-django + respx (HTTP mocking).

---

## Scope — What T-006 covers (from 03 §6)

| Step | Description | Ticket |
|------|-------------|--------|
| 1 | `shop_info` → populate `Shop` | T-006 |
| 2 | `current_installation` → cache installation ID | T-006 |
| 3 | Ensure metaobject definitions (idempotent) | T-006 |
| 3 | Ensure metafield definitions (idempotent) | T-006 |
| 4 | Price snapshot → `PriceHistory` | T-007 |
| 5 | Source detection | T-020 |
| 6 | Write shop metafields with defaults | T-006 |
| 7 | Event `installed` | T-006 |

**Out of scope for T-006:** Steps 4 (price snapshot) and 5 (source detection) belong to T-007 and T-020 respectively. The `on_install` task will call stubs for those steps.

---

## Task 1: Add `installation_id` field to `Shop` model

**Objective:** Store the current app installation ID from `currentAppInstallation` so metafield definitions can reference it.

**Files:**
- Create: none (modify existing)
- Modify: `apps/core/models.py`
- Test: `tests/test_t006.py`

**Step 1: Write failing test**

```python
# tests/test_t006.py
def test_shop_has_installation_id_field(shop):
    """Shop model has an installation_id field."""
    assert hasattr(shop, "installation_id")
    shop.installation_id = "gid://shopify/AppInstallation/456"
    shop.save(update_fields=["installation_id"])
    shop.refresh_from_db()
    assert shop.installation_id == "gid://shopify/AppInstallation/456"
```

**Step 2: Run test to verify failure**

Run: `uv run pytest tests/test_t006.py::test_shop_has_installation_id_field -v`
Expected: FAIL — `AttributeError` or `FieldError`

**Step 3: Add field to Shop model**

In `apps/core/models.py`, add after the `uninstalled_at` field:

```python
installation_id = models.CharField(max_length=255, blank=True, default="")
```

**Step 4: Create migration**

Run: `uv run python manage.py makemigrations core`

**Step 5: Run test to verify pass**

Run: `uv run pytest tests/test_t006.py::test_shop_has_installation_id_field -v`
Expected: PASS

**Step 6: Commit**

```bash
git add apps/core/models.py apps/core/migrations/
git commit -m "feat(core): add installation_id field to Shop model"
```

---

## Task 2: Create GraphQL queries for metaobject/metafield definitions

**Objective:** Create the `.graphql` files needed for installation — checking and creating metaobject definitions, metafield definitions, and setting shop metafields.

**Files:**
- Create: `queries/metaobject_definition_by_type.graphql`
- Create: `queries/metaobject_definition_create.graphql`
- Create: `queries/metafield_definitions_by_owner.graphql`
- Create: `queries/metafield_definition_create.graphql`
- Create: `queries/metafields_set.graphql`
- Test: `tests/test_t006.py` (loader tests)

**Step 1: Write failing tests for query loading**

```python
# tests/test_t006.py
from apps.core.shopify_client import load_query

def test_load_metaobject_definition_by_type():
    q = load_query("metaobject_definition_by_type")
    assert "metaobjectDefinitionByType" in q

def test_load_metaobject_definition_create():
    q = load_query("metaobject_definition_create")
    assert "metaobjectDefinitionCreate" in q

def test_load_metafield_definitions_by_owner():
    q = load_query("metafield_definitions_by_owner")
    assert "metafieldDefinitions" in q

def test_load_metafield_definition_create():
    q = load_query("metafield_definition_create")
    assert "metafieldDefinitionCreate" in q

def test_load_metafields_set():
    q = load_query("metafields_set")
    assert "metafieldsSet" in q
```

**Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_t006.py -k "load_" -v`
Expected: FAIL — `FileNotFoundError`

**Step 3: Create GraphQL files**

`queries/metaobject_definition_by_type.graphql`:
```graphql
query MetaobjectDefinitionByType($type: String!) {
  metaobjectDefinitionByType(type: $type) {
    id
    type
    fieldDefinitions {
      key
      name
      type {
        name
      }
    }
  }
}
```

`queries/metaobject_definition_create.graphql`:
```graphql
mutation MetaobjectDefinitionCreate($definition: MetaobjectDefinitionInput!) {
  metaobjectDefinitionCreate(definition: $definition) {
    metaobjectDefinition {
      id
      type
    }
    userErrors {
      field
      message
      code
    }
  }
}
```

`queries/metafield_definitions_by_owner.graphql`:
```graphql
query MetafieldDefinitionsByOwner($ownerType: MetafieldOwnerType!) {
  metafieldDefinitions(first: 50, ownerType: $ownerType, namespace: "$app:mosaiq") {
    nodes {
      id
      namespace
      key
      type {
        name
      }
      ownerType
    }
  }
}
```

`queries/metafield_definition_create.graphql`:
```graphql
mutation MetafieldDefinitionCreate($definition: MetafieldDefinitionInput!) {
  metafieldDefinitionCreate(definition: $definition) {
    metafieldDefinition {
      id
      namespace
      key
    }
    userErrors {
      field
      message
      code
    }
  }
}
```

`queries/metafields_set.graphql`:
```graphql
mutation MetafieldsSet($metafields: [MetafieldsSetInput!]!) {
  metafieldsSet(metafields: $metafields) {
    metafields {
      id
      namespace
      key
      value
    }
    userErrors {
      field
      message
      code
    }
  }
}
```

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_t006.py -k "load_" -v`
Expected: PASS

**Step 5: Commit**

```bash
git add queries/
git commit -m "feat(queries): add GraphQL operations for installation definitions"
```

---

## Task 3: Create `ensure_metaobject_definitions` helper

**Objective:** Idempotent function that checks if `$app:page_content` and `$app:offer_display` metaobject definitions exist, and creates them if not.

**Files:**
- Create: `apps/core/installation.py`
- Modify: none
- Test: `tests/test_t006.py`

**Step 1: Write failing tests**

```python
# tests/test_t006.py
from unittest.mock import MagicMock, patch
from apps.core.installation import ensure_metaobject_definitions

MOCK_PAGE_CONTENT_DEF = {
    "metaobjectDefinitionByType": {
        "id": "gid://shopify/MetaobjectDefinition/1",
        "type": "$app:page_content",
        "fieldDefinitions": [],
    }
}

MOCK_OFFER_DISPLAY_DEF = {
    "metaobjectDefinitionByType": {
        "id": "gid://shopify/MetaobjectDefinition/2",
        "type": "$app:offer_display",
        "fieldDefinitions": [],
    }
}

MOCK_NOT_FOUND = {"metaobjectDefinitionByType": None}


class TestEnsureMetaobjectDefinitions:
    @patch("apps.core.installation._get_client")
    def test_skips_when_both_exist(self, mock_get_client):
        """No API calls if both definitions already exist."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.execute.side_effect = [MOCK_PAGE_CONTENT_DEF, MOCK_OFFER_DISPLAY_DEF]

        result = ensure_metaobject_definitions("test.myshopify.com", "token123")

        assert result == {"page_content": "exists", "offer_display": "exists"}
        assert mock_client.execute.call_count == 2
        # No mutations should be called
        for call_args in mock_client.execute.call_args_list:
            query_str = call_args[0][0]
            assert "mutation" not in query_str.lower() or "Mutation" not in query_str

    @patch("apps.core.installation._get_client")
    def test_creates_when_missing(self, mock_get_client):
        """Creates definition when not found."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # First call: check page_content → not found
        # Second call: create page_content → success
        # Third call: check offer_display → not found
        # Fourth call: create offer_display → success
        mock_client.execute.side_effect = [
            MOCK_NOT_FOUND,  # check page_content
            {"metaobjectDefinitionCreate": {"metaobjectDefinition": {"id": "gid://shopify/MetaobjectDefinition/10"}, "userErrors": []}},
            MOCK_NOT_FOUND,  # check offer_display
            {"metaobjectDefinitionCreate": {"metaobjectDefinition": {"id": "gid://shopify/MetaobjectDefinition/11"}, "userErrors": []}},
        ]

        result = ensure_metaobject_definitions("test.myshopify.com", "token123")

        assert result == {"page_content": "created", "offer_display": "created"}
        assert mock_client.execute.call_count == 4
```

**Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_t006.py::TestEnsureMetaobjectDefinitions -v`
Expected: FAIL — `ModuleNotFoundError` or `ImportError`

**Step 3: Implement `ensure_metaobject_definitions`**

Create `apps/core/installation.py`:

```python
"""Installation helpers — ensure Shopify definitions exist idempotently.

See docs/03-shopify-integration.md §5.1, §5.2, §6.
"""

from __future__ import annotations

import logging
from typing import Any

from .shopify_client import ShopifyGraphQLClient, load_query

logger = logging.getLogger(__name__)


def _get_client(shop_domain: str, access_token: str) -> ShopifyGraphQLClient:
    """Create a GraphQL client for installation operations."""
    from django.conf import settings

    return ShopifyGraphQLClient(shop_domain, access_token, settings.SHOPIFY_API_VERSION)


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


def ensure_metaobject_definitions(
    shop_domain: str, access_token: str
) -> dict[str, str]:
    """Ensure metaobject definitions exist. Idempotent.

    Returns a dict mapping type name to 'exists' or 'created'.
    """
    result: dict[str, str] = {}
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
                continue

            # Create the definition
            create_query = load_query("metaobject_definition_create")
            definition_input = {
                "type": type_name,
                "name": type_name.replace("$app:", "").replace("_", " ").title(),
                "fieldDefinitions": [
                    {"key": f["key"], "name": f["name"], "type": {"name": f["type"]}}
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
                new_id = create_data["metaobjectDefinitionCreate"]["metaobjectDefinition"]["id"]
                logger.info("Created metaobject definition %s (%s)", type_name, new_id)
                result[type_name] = "created"
    finally:
        client.close()

    return result


# ── Metafield definitions ─────────────────────────────────────────────────

# Metafield definitions from 03 §5.2
# Each entry: (owner_type, key, type, name)
METAFIELD_DEFINITIONS = [
    # Product metafields
    ("PRODUCT", "page", "list.metaobject_reference", "Page Content"),
    ("PRODUCT", "gpsr", "json", "GPSR"),
    ("PRODUCT", "offer", "metaobject_reference", "Offer"),
    # Page metafields
    ("PAGE", "page", "list.metaobject_reference", "Page Content"),
    # Shop metafields
    ("SHOP", "home_page", "list.metaobject_reference", "Home Page"),
    ("SHOP", "design_tokens", "json", "Design Tokens"),
    ("SHOP", "withdrawal", "json", "Withdrawal"),
    ("SHOP", "settings", "json", "Settings"),
    ("SHOP", "cart", "json", "Cart"),
    # Variant metafields
    ("PRODUCTVARIANT", "unit_price", "json", "Unit Price"),
    ("PRODUCTVARIANT", "prior_price", "json", "Prior Price"),
]


def ensure_metafield_definitions(
    shop_domain: str, access_token: str
) -> dict[str, str]:
    """Ensure metafield definitions exist. Idempotent.

    Returns a dict mapping 'owner_type:key' to 'exists' or 'created'.
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
        for owner_type, key, metafield_type, name in METAFIELD_DEFINITIONS:
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
```

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_t006.py::TestEnsureMetaobjectDefinitions -v`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/core/installation.py
git commit -m "feat(core): add ensure_metaobject_definitions helper"
```

---

## Task 4: Create `ensure_metafield_definitions` helper

**Objective:** Idempotent function that checks and creates all metafield definitions from 03 §5.2.

**Files:**
- Modify: `apps/core/installation.py` (already created in Task 3)
- Test: `tests/test_t006.py`

Note: The implementation is already included in Task 3. This task is for the additional tests.

**Step 1: Write tests**

```python
# tests/test_t006.py
from apps.core.installation import ensure_metafield_definitions

MOCK_EXISTING_DEFS = {
    "metafieldDefinitions": {
        "nodes": [
            {"id": "gid://shopify/MetafieldDefinition/1", "namespace": "$app:mosaiq", "key": "page", "type": {"name": "list.metaobject_reference"}, "ownerType": "PRODUCT"},
        ]
    }
}

MOCK_EMPTY_DEFS = {"metafieldDefinitions": {"nodes": []}}


class TestEnsureMetafieldDefinitions:
    @patch("apps.core.installation._get_client")
    def test_skips_existing(self, mock_get_client):
        """Existing definitions are not re-created."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        # All owner types return the same existing defs
        mock_client.execute.return_value = MOCK_EXISTING_DEFS

        result = ensure_metafield_definitions("test.myshopify.com", "token123")

        # PRODUCT:page should be 'exists', others should be 'created'
        assert result.get("PRODUCT:page") == "exists"
        assert mock_client.execute.call_count >= 4  # 4 owner types queried

    @patch("apps.core.installation._get_client")
    def test_creates_missing(self, mock_get_client):
        """Missing definitions are created."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Return empty for all queries
        mock_client.execute.return_value = MOCK_EMPTY_DEFS

        result = ensure_metafield_definitions("test.myshopify.com", "token123")

        # All definitions should be 'created'
        for key, status in result.items():
            assert status == "created", f"{key} should be 'created' but was '{status}'"
```

**Step 2: Run tests**

Run: `uv run pytest tests/test_t006.py::TestEnsureMetafieldDefinitions -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/test_t006.py
git commit -m "test(core): add tests for ensure_metafield_definitions"
```

---

## Task 5: Create `populate_shop_from_info` helper

**Objective:** Parse the `shop_info` GraphQL response and create/update the `Shop` record.

**Files:**
- Modify: `apps/core/installation.py`
- Test: `tests/test_t006.py`

**Step 1: Write tests**

```python
# tests/test_t006.py
from apps.core.installation import populate_shop_from_info

MOCK_SHOP_INFO_RESPONSE = {
    "shop": {
        "id": "gid://shopify/Shop/123",
        "name": "Test Store",
        "email": "merchant@example.com",
        "currencyCode": "EUR",
        "ianaTimezone": "Europe/Amsterdam",
        "primaryDomain": {"url": "https://test-store.myshopify.com"},
        "billingAddress": {"countryCodeV2": "NL"},
    },
    "shopLocales": [
        {"locale": "nl", "primary": True, "published": True},
        {"locale": "en", "primary": False, "published": True},
        {"locale": "de", "primary": False, "published": False},
    ],
}


class TestPopulateShopFromInfo:
    @pytest.mark.django_db
    def test_creates_new_shop(self):
        """A new shop is created from shop_info response."""
        shop = populate_shop_from_info(
            MOCK_SHOP_INFO_RESPONSE,
            domain="test-store.myshopify.com",
        )

        assert shop is not None
        assert shop.domain == "test-store.myshopify.com"
        assert shop.shopify_gid == "gid://shopify/Shop/123"
        assert shop.name == "Test Store"
        assert shop.email == "merchant@example.com"
        assert shop.currency_code == "EUR"
        assert shop.iana_timezone == "Europe/Amsterdam"
        assert shop.country_code == "NL"
        assert shop.primary_locale == "nl"

    @pytest.mark.django_db
    def test_updates_existing_shop(self):
        """An existing shop is updated, not duplicated."""
        from apps.core.models import Shop
        from apps.core.crypto import encrypt_token
        from django.utils import timezone

        existing = Shop.objects.create(
            domain="test-store.myshopify.com",
            shopify_gid="gid://shopify/Shop/123",
            access_token_encrypted=encrypt_token("old_token"),
            refresh_token_encrypted=encrypt_token("old_refresh"),
            name="Old Name",
            status="active",
        )

        updated_info = dict(MOCK_SHOP_INFO_RESPONSE)
        updated_info["shop"] = dict(updated_info["shop"])
        updated_info["shop"]["name"] = "New Store Name"

        shop = populate_shop_from_info(
            updated_info,
            domain="test-store.myshopify.com",
        )

        assert shop.id == existing.id  # Same shop, not a new one
        assert shop.name == "New Store Name"
```

**Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_t006.py::TestPopulateShopFromInfo -v`
Expected: FAIL — `ImportError`

**Step 3: Implement `populate_shop_from_info`**

Add to `apps/core/installation.py`:

```python
# ── Shop population ───────────────────────────────────────────────────────

def populate_shop_from_info(
    data: dict[str, Any],
    *,
    domain: str,
) -> "Shop":
    """Create or update a Shop from shop_info GraphQL response.

    The domain is extracted from the session token (request.shop_domain),
    not from the GraphQL response, to avoid spoofing.
    """
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

    # Get or create
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
```

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_t006.py::TestPopulateShopFromInfo -v`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/core/installation.py
git commit -m "feat(core): add populate_shop_from_info helper"
```

---

## Task 6: Create `write_default_shop_metafields` helper

**Objective:** Write default values for shop metafields (`design_tokens`, `withdrawal`, `settings`, `cart`) as described in 03 §5.2.

**Files:**
- Modify: `apps/core/installation.py`
- Test: `tests/test_t006.py`

**Step 1: Write tests**

```python
# tests/test_t006.py
from apps.core.installation import write_default_shop_metafields

MOCK_METAFIELDS_SET_RESPONSE = {
    "metafieldsSet": {
        "metafields": [
            {"id": "gid://shopify/Metafield/1", "namespace": "$app:mosaiq", "key": "design_tokens", "value": "{}"},
        ],
        "userErrors": [],
    }
}


class TestWriteDefaultShopMetafields:
    @patch("apps.core.installation._get_client")
    def test_writes_all_default_metafields(self, mock_get_client):
        """All four shop metafields are written with defaults."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.execute.return_value = MOCK_METAFIELDS_SET_RESPONSE

        shop = MagicMock()
        shop.id = "gid://shopify/Shop/123"

        result = write_default_shop_metafields(shop, "token123")

        assert result is True
        # Should have called execute at least once with metafieldsSet
        assert mock_client.execute.call_count >= 1

    @patch("apps.core.installation._get_client")
    def test_handles_user_errors(self, mock_get_client):
        """User errors in metafieldsSet are logged but don't crash."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.execute.return_value = {
            "metafieldsSet": {
                "metafields": [],
                "userErrors": [{"field": "metafields", "message": "Invalid value", "code": "INVALID"}],
            }
        }

        shop = MagicMock()
        shop.id = "gid://shopify/Shop/123"

        result = write_default_shop_metafields(shop, "token123")
        assert result is False
```

**Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_t006.py::TestWriteDefaultShopMetafields -v`
Expected: FAIL

**Step 3: Implement `write_default_shop_metafields`**

Add to `apps/core/installation.py`:

```python
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


def write_default_shop_metafields(shop: Any, access_token: str) -> bool:
    """Write default shop metafields. Idempotent — overwrites with same defaults.

    Returns True on success, False if any userErrors occurred.
    """
    import json

    client = _get_client(shop.domain, access_token)

    try:
        metafields_input = []
        for key, value in DEFAULT_SHOP_METAFIELDS.items():
            metafields_input.append({
                "ownerId": shop.id,
                "namespace": "$app:mosaiq",
                "key": key,
                "value": json.dumps(value),
            })

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
```

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_t006.py::TestWriteDefaultShopMetafields -v`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/core/installation.py
git commit -m "feat(core): add write_default_shop_metafields helper"
```

---

## Task 7: Create the `on_install` orchestrator task

**Objective:** Wire all helpers into a single Celery task that runs in order: shop_info → current_installation → ensure definitions → write metafields → log event.

**Files:**
- Modify: `apps/core/tasks.py`
- Modify: `apps/core/installation.py` (add `on_install` task)
- Test: `tests/test_t006.py`

**Step 1: Write tests**

```python
# tests/test_t006.py
from apps.core.installation import on_install

MOCK_INSTALLATION_RESPONSE = {
    "currentAppInstallation": {
        "id": "gid://shopify/AppInstallation/456",
        "activeSubscriptions": [],
    }
}


class TestOnInstall:
    @pytest.mark.django_db
    @patch("apps.core.installation.write_default_shop_metafields")
    @patch("apps.core.installation.ensure_metafield_definitions")
    @patch("apps.core.installation.ensure_metaobject_definitions")
    @patch("apps.core.installation._get_client")
    def test_full_installation_flow(
        self, mock_get_client, mock_metaobj, mock_metafield, mock_write_meta
    ):
        """Full installation: shop_info → installation → definitions → metafields."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Call 1: shop_info
        # Call 2: current_installation
        mock_client.execute.side_effect = [
            MOCK_SHOP_INFO_RESPONSE,
            MOCK_INSTALLATION_RESPONSE,
        ]

        mock_metaobj.return_value = {"$app:page_content": "created", "$app:offer_display": "created"}
        mock_metafield.return_value = {"PRODUCT:page": "created"}
        mock_write_meta.return_value = True

        shop = on_install("test-store.myshopify.com", "access_token_123")

        assert shop is not None
        assert shop.domain == "test-store.myshopify.com"
        assert shop.installation_id == "gid://shopify/AppInstallation/456"
        assert mock_metaobj.called
        assert mock_metafield.called
        assert mock_write_meta.called

    @pytest.mark.django_db
    @patch("apps.core.installation.write_default_shop_metafields")
    @patch("apps.core.installation.ensure_metafield_definitions")
    @patch("apps.core.installation.ensure_metaobject_definitions")
    @patch("apps.core.installation._get_client")
    def test_idempotent(
        self, mock_get_client, mock_metaobj, mock_metafield, mock_write_meta
    ):
        """Running on_install twice does not create duplicate shops."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.execute.side_effect = [
            MOCK_SHOP_INFO_RESPONSE,
            MOCK_INSTALLATION_RESPONSE,
            MOCK_SHOP_INFO_RESPONSE,
            MOCK_INSTALLATION_RESPONSE,
        ]
        mock_metaobj.return_value = {"$app:page_content": "exists", "$app:offer_display": "exists"}
        mock_metafield.return_value = {"PRODUCT:page": "exists"}
        mock_write_meta.return_value = True

        shop1 = on_install("test-store.myshopify.com", "access_token_123")
        shop2 = on_install("test-store.myshopify.com", "access_token_123")

        assert shop1.id == shop2.id  # Same shop, not duplicated
```

**Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_t006.py::TestOnInstall -v`
Expected: FAIL

**Step 3: Implement `on_install` task**

Add to `apps/core/installation.py`:

```python
# ── Main installation task ────────────────────────────────────────────────

def on_install(shop_domain: str, access_token: str) -> "Shop":
    """Run all installation tasks in order.

    Called after token exchange when a new Shop is created.
    Steps 4 (price snapshot) and 5 (source detection) are deferred to T-007/T-020.

    See docs/03-shopify-integration.md §6.
    """
    from .models import Shop

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
    metaobj_result = ensure_metaobject_definitions(shop_domain, access_token)
    logger.info("Metaobject definitions: %s", metaobj_result)

    # Step 3: Ensure metafield definitions (idempotent)
    metafield_result = ensure_metafield_definitions(shop_domain, access_token)
    logger.info("Metafield definitions: %s", metafield_result)

    # Step 6: Write default shop metafields
    write_result = write_default_shop_metafields(shop, access_token)
    logger.info("Default shop metafields written: %s", write_result)

    # Step 7: Log installed event
    from .models import AuditLog

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
```

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_t006.py::TestOnInstall -v`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/core/installation.py
git commit -m "feat(core): add on_install orchestrator task"
```

---

## Task 8: Add `on_install` Celery task wrapper

**Objective:** Wrap the `on_install` function as a Celery task so it can be dispatched asynchronously after token exchange.

**Files:**
- Modify: `apps/core/tasks.py`
- Test: `tests/test_t006.py`

**Step 1: Write test**

```python
# tests/test_t006.py
from apps.core.tasks import run_on_install

class TestRunOnInstallTask:
    @patch("apps.core.tasks.get_access_token")
    @patch("apps.core.installation.on_install")
    def test_dispatches_installation(self, mock_on_install, mock_get_token):
        """The Celery task calls on_install with decrypted token."""
        mock_get_token.return_value = "decrypted_access_token"
        mock_on_install.return_value = MagicMock(domain="test.myshopify.com")

        # We need a shop in the DB for this task
        from apps.core.models import Shop
        from apps.core.crypto import encrypt_token
        from django.utils import timezone
        from datetime import timedelta

        shop = Shop.objects.create(
            domain="test.myshopify.com",
            shopify_gid="gid://shopify/Shop/999",
            access_token_encrypted=encrypt_token("shpat_test"),
            access_token_expires_at=timezone.now() + timedelta(hours=1),
            refresh_token_encrypted=encrypt_token("refresh_test"),
            refresh_token_expires_at=timezone.now() + timedelta(days=90),
        )

        run_on_install(str(shop.id))

        mock_on_install.assert_called_once_with("test.myshopify.com", "decrypted_access_token")
```

**Step 2: Run test to verify failure**

Run: `uv run pytest tests/test_t006.py::TestRunOnInstallTask -v`
Expected: FAIL

**Step 3: Add task to `apps/core/tasks.py`**

Add after the existing `keep_tokens_fresh` task:

```python
@shared_task(name="core.tasks.run_on_install")
def run_on_install(shop_id: str) -> dict:
    """Celery task wrapper for on_install.

    Fetches the shop, decrypts the access token, and runs the installation flow.
    """
    from .crypto import decrypt_token
    from .installation import on_install

    try:
        shop = Shop.objects.get(id=shop_id)
    except Shop.DoesNotExist:
        logger.error("Shop %s not found for on_install", shop_id)
        return {"error": "shop_not_found"}

    try:
        access_token = decrypt_token(shop.access_token_encrypted)
    except Exception:
        logger.error("Cannot decrypt access token for %s", shop.domain)
        return {"error": "token_decrypt_failed"}

    try:
        on_install(shop.domain, access_token)
        return {"status": "completed", "shop": shop.domain}
    except Exception as exc:
        logger.error("Installation failed for %s: %s", shop.domain, exc)
        return {"error": str(exc)}
```

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_t006.py::TestRunOnInstallTask -v`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/core/tasks.py
git commit -m "feat(core): add run_on_install Celery task"
```

---

## Task 9: Integration test — full installation flow

**Objective:** End-to-end test that mocks all Shopify API calls and verifies the complete installation flow produces the correct DB state.

**Files:**
- Test: `tests/test_t006.py`

**Step 1: Write integration test**

```python
# tests/test_t006.py
class TestOnInstallIntegration:
    """Integration test: full installation flow with mocked Shopify API."""

    @pytest.mark.django_db
    @patch("apps.core.installation._get_client")
    def test_complete_installation(self, mock_get_client):
        """Full installation from scratch produces correct Shop state."""
        from apps.core.installation import on_install

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Simulate API responses in order
        mock_client.execute.side_effect = [
            # shop_info
            MOCK_SHOP_INFO_RESPONSE,
            # current_installation
            MOCK_INSTALLATION_RESPONSE,
            # ensure_metaobject_definitions - check page_content
            MOCK_PAGE_CONTENT_DEF,
            # ensure_metaobject_definitions - check offer_display
            MOCK_OFFER_DISPLAY_DEF,
            # ensure_metafield_definitions - PRODUCT
            {"metafieldDefinitions": {"nodes": [{"key": "page", "type": {"name": "list.metaobject_reference"}}]}},
            # ensure_metafield_definitions - PAGE
            {"metafieldDefinitions": {"nodes": []}},
            # ensure_metafield_definitions - SHOP
            {"metafieldDefinitions": {"nodes": []}},
            # ensure_metafield_definitions - PRODUCTVARIANT
            {"metafieldDefinitions": {"nodes": []}},
            # metafieldsSet (shop metafields)
            MOCK_METAFIELDS_SET_RESPONSE,
        ]

        shop = on_install("integration-test.myshopify.com", "token_integration")

        # Verify Shop state
        assert shop.domain == "integration-test.myshopify.com"
        assert shop.shopify_gid == "gid://shopify/Shop/123"
        assert shop.installation_id == "gid://shopify/AppInstallation/456"
        assert shop.name == "Test Store"
        assert shop.currency_code == "EUR"
        assert shop.primary_locale == "nl"

        # Verify AuditLog
        from apps.core.models import AuditLog
        log = AuditLog.objects.filter(shop=shop, action="installed").first()
        assert log is not None
        assert log.actor == "system"
        assert "metaobject_definitions" in log.payload
        assert "metafield_definitions" in log.payload
```

**Step 2: Run test**

Run: `uv run pytest tests/test_t006.py::TestOnInstallIntegration -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/test_t006.py
git commit -m "test(core): add full installation integration test"
```

---

## Task 10: Run full test suite and lint

**Objective:** Ensure all tests pass and code meets quality standards.

**Step 1: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests pass

**Step 2: Run linting**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: No errors

**Step 3: Run type checking**

Run: `uv run mypy apps/core/installation.py apps/core/tasks.py`
Expected: No errors

**Step 4: Final commit if any fixes needed**

```bash
git add -A
git commit -m "chore: fix lint and type issues for T-006"
```

---

## Summary

After completing all tasks:

1. **New files:**
   - `apps/core/installation.py` — all installation helpers
   - `queries/metaobject_definition_by_type.graphql`
   - `queries/metaobject_definition_create.graphql`
   - `queries/metafield_definitions_by_owner.graphql`
   - `queries/metafield_definition_create.graphql`
   - `queries/metafields_set.graphql`
   - `tests/test_t006.py`

2. **Modified files:**
   - `apps/core/models.py` — added `installation_id` field
   - `apps/core/tasks.py` — added `run_on_install` Celery task
   - `apps/core/migrations/` — new migration for `installation_id`

3. **Acceptance criteria covered:**
   - F00-6: metaobject and metafield definitions exist after `on_install`; running again produces no errors/duplicates ✓
   - F00-8: definitions looked up by owner type + namespace + key, never by ID ✓
   - 03 §6 steps 1-3, 6-7: all covered ✓

4. **Deferred to other tickets:**
   - Step 4 (price snapshot) → T-007
   - Step 5 (source detection) → T-020
