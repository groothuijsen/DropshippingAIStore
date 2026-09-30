"""Tests for T-007: price snapshot, PriceHistory, prior_price, webhook handler."""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from apps.compliance.models import PriceAttestation, PriceHistory
from apps.compliance.price_snapshot import snapshot_prices_small_shop
from apps.compliance.pricing import PriorPrice, Reduction, prior_price, reduction
from apps.core.crypto import encrypt_token
from apps.core.models import Shop, ShopStatus


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def shop(db):
    """Create a test shop."""
    now = timezone.now()
    return Shop.objects.create(
        domain="test-store.myshopify.com",
        shopify_gid="gid://shopify/Shop/123",
        access_token_encrypted=encrypt_token("shpat_test_access_token_12345"),
        access_token_expires_at=now + timedelta(hours=1),
        refresh_token_encrypted=encrypt_token("shpat_test_refresh_token_67890"),
        refresh_token_expires_at=now + timedelta(days=90),
        name="Test Store",
        email="merchant@example.com",
        currency_code="EUR",
        iana_timezone="Europe/Amsterdam",
        status=ShopStatus.ACTIVE,
    )


# ── PriceHistory model tests ──────────────────────────────────────────────


@pytest.mark.django_db
class TestPriceHistoryModel:
    def test_create_price_history(self, shop):
        """Create a PriceHistory row."""
        now = timezone.now()
        ph = PriceHistory.objects.create(
            shop=shop,
            variant_gid="gid://shopify/ProductVariant/1",
            market_handle="primary",
            price=Decimal("29.99"),
            currency="EUR",
            observed_at=now,
            source="install_snapshot",
        )
        assert ph.price == Decimal("29.99")
        assert ph.source == "install_snapshot"
        assert str(ph) == "gid://shopify/ProductVariant/1 @ 29.99 EUR (install_snapshot)"

    def test_price_history_index(self, shop):
        """Verify the composite index exists."""
        now = timezone.now()
        PriceHistory.objects.create(
            shop=shop,
            variant_gid="gid://shopify/ProductVariant/1",
            price=Decimal("29.99"),
            currency="EUR",
            observed_at=now,
            source="webhook",
        )
        # Query using the indexed fields
        qs = PriceHistory.objects.filter(
            shop=shop,
            variant_gid="gid://shopify/ProductVariant/1",
            market_handle="primary",
            observed_at__lte=now,
        )
        assert qs.count() == 1


@pytest.mark.django_db
class TestPriceAttestationModel:
    def test_create_attestation(self, shop):
        """Create a PriceAttestation row."""
        valid_until = timezone.now() + timedelta(days=30)
        att = PriceAttestation.objects.create(
            shop=shop,
            variant_gid="gid://shopify/ProductVariant/1",
            lowest_price_30d=Decimal("19.99"),
            valid_until=valid_until,
        )
        assert att.lowest_price_30d == Decimal("19.99")
        assert str(att) == "gid://shopify/ProductVariant/1 attested 19.99"


# ── prior_price algorithm tests ───────────────────────────────────────────


@pytest.mark.django_db
class TestPriorPrice:
    def test_no_history_returns_none(self, shop):
        """No price history → None."""
        result = prior_price(shop, "gid://shopify/ProductVariant/1", Decimal("29.99"))
        assert result is None

    def test_short_history_without_attestation(self, shop):
        """History shorter than 30 days without attestation → None."""
        now = timezone.now()
        PriceHistory.objects.create(
            shop=shop,
            variant_gid="gid://shopify/ProductVariant/1",
            price=Decimal("29.99"),
            currency="EUR",
            observed_at=now - timedelta(days=10),
            source="install_snapshot",
        )
        result = prior_price(shop, "gid://shopify/ProductVariant/1", Decimal("24.99"), now=now)
        assert result is None

    def test_short_history_with_attestation(self, shop):
        """History shorter than 30 days with attestation → attested price."""
        now = timezone.now()
        PriceHistory.objects.create(
            shop=shop,
            variant_gid="gid://shopify/ProductVariant/1",
            price=Decimal("29.99"),
            currency="EUR",
            observed_at=now - timedelta(days=10),
            source="install_snapshot",
        )
        PriceAttestation.objects.create(
            shop=shop,
            variant_gid="gid://shopify/ProductVariant/1",
            lowest_price_30d=Decimal("19.99"),
            valid_until=now + timedelta(days=30),
        )
        result = prior_price(shop, "gid://shopify/ProductVariant/1", Decimal("24.99"), now=now)
        assert result is not None
        assert result.amount == Decimal("19.99")

    def test_price_reduction_with_history(self, shop):
        """Price reduction with sufficient history → correct prior price."""
        now = timezone.now()
        # 55 days ago: price was 29.99 (anchor — at or before window_start)
        PriceHistory.objects.create(
            shop=shop,
            variant_gid="gid://shopify/ProductVariant/1",
            price=Decimal("29.99"),
            currency="EUR",
            observed_at=now - timedelta(days=55),
            source="install_snapshot",
        )
        # 20 days ago: price increased to 34.99
        PriceHistory.objects.create(
            shop=shop,
            variant_gid="gid://shopify/ProductVariant/1",
            price=Decimal("34.99"),
            currency="EUR",
            observed_at=now - timedelta(days=20),
            source="webhook",
        )
        # Now: price reduced to 24.99
        result = prior_price(shop, "gid://shopify/ProductVariant/1", Decimal("24.99"), now=now)
        assert result is not None
        assert result.amount == Decimal("29.99")  # Lowest in the 30-day window before reduction
        assert result.currency == "EUR"

    def test_no_reduction_same_price(self, shop):
        """Current price equals prior → no reduction."""
        now = timezone.now()
        PriceHistory.objects.create(
            shop=shop,
            variant_gid="gid://shopify/ProductVariant/1",
            price=Decimal("29.99"),
            currency="EUR",
            observed_at=now - timedelta(days=40),
            source="install_snapshot",
        )
        result = prior_price(shop, "gid://shopify/ProductVariant/1", Decimal("29.99"), now=now)
        # The algorithm finds the start of current price run, then looks before
        # If all prices are the same, there's no reduction start → None
        assert result is None

    def test_price_increase_before_promotion(self, shop):
        """Price increase just before promotion doesn't count as prior price."""
        now = timezone.now()
        # 40 days ago: price was 24.99
        PriceHistory.objects.create(
            shop=shop,
            variant_gid="gid://shopify/ProductVariant/1",
            price=Decimal("24.99"),
            currency="EUR",
            observed_at=now - timedelta(days=40),
            source="install_snapshot",
        )
        # 10 days ago: price increased to 34.99
        PriceHistory.objects.create(
            shop=shop,
            variant_gid="gid://shopify/ProductVariant/1",
            price=Decimal("34.99"),
            currency="EUR",
            observed_at=now - timedelta(days=10),
            source="webhook",
        )
        # Now: price reduced to 29.99
        result = prior_price(shop, "gid://shopify/ProductVariant/1", Decimal("29.99"), now=now)
        assert result is not None
        # The 24.99 was 40 days ago, which is outside the 30-day window before
        # the reduction started (10 days ago). Window is [10-30, 10) = [-20, 10) days ago
        # The only observation in that window is the 34.99 at day -10
        # Wait — the reduction start is when the current price (29.99) first appeared
        # But 29.99 hasn't appeared before! The current price IS the new price.
        # Let me re-think: current=29.99, rows are [24.99@-40d, 34.99@-10d]
        # i starts at len(rows)-1 = 1, rows[1].price=34.99 != 29.99, so i stays at 1
        # reduction_start = rows[1].observed_at = -10d
        # window_start = -10d - 30d = -40d
        # before = [rows[0]] (observed_at=-40d < -10d)
        # anchor = rows[0] (observed_at=-40d <= -40d)
        # in_window = [] (rows[0].observed_at=-40d is NOT > -40d)
        # candidates = [24.99]
        # result = 24.99
        assert result.amount == Decimal("24.99")

    def test_multiple_price_changes_in_window(self, shop):
        """Multiple price changes within the 30-day window."""
        now = timezone.now()
        # 45 days ago: 19.99
        PriceHistory.objects.create(
            shop=shop,
            variant_gid="gid://shopify/ProductVariant/1",
            price=Decimal("19.99"),
            currency="EUR",
            observed_at=now - timedelta(days=45),
            source="install_snapshot",
        )
        # 25 days ago: 24.99
        PriceHistory.objects.create(
            shop=shop,
            variant_gid="gid://shopify/ProductVariant/1",
            price=Decimal("24.99"),
            currency="EUR",
            observed_at=now - timedelta(days=25),
            source="webhook",
        )
        # 15 days ago: 29.99
        PriceHistory.objects.create(
            shop=shop,
            variant_gid="gid://shopify/ProductVariant/1",
            price=Decimal("29.99"),
            currency="EUR",
            observed_at=now - timedelta(days=15),
            source="webhook",
        )
        # Now: 22.99
        result = prior_price(shop, "gid://shopify/ProductVariant/1", Decimal("22.99"), now=now)
        assert result is not None
        # Window before reduction (15 days ago): [-45d, -15d)
        # anchor = 19.99 at -45d (<= -45d)
        # in_window = [24.99] (at -25d, which is > -45d and < -15d)
        # candidates = [24.99, 19.99]
        assert result.amount == Decimal("19.99")


# ── reduction() tests ─────────────────────────────────────────────────────


class TestReduction:
    def test_real_reduction(self):
        """Current < prior → reduction."""
        result = reduction(Decimal("24.99"), Decimal("29.99"))
        assert result is not None
        assert result.prior == Decimal("29.99")
        assert result.current == Decimal("24.99")
        assert result.percent == 16  # floor((29.99-24.99)/29.99*100) = floor(16.67) = 16

    def test_no_reduction_same_price(self):
        """Current == prior → None."""
        result = reduction(Decimal("29.99"), Decimal("29.99"))
        assert result is None

    def test_no_reduction_higher_price(self):
        """Current > prior → None."""
        result = reduction(Decimal("34.99"), Decimal("29.99"))
        assert result is None

    def test_percentage_rounds_down(self):
        """Percentage always rounds down."""
        result = reduction(Decimal("20.00"), Decimal("30.00"))
        assert result is not None
        assert result.percent == 33  # floor(33.33) = 33


# ── snapshot_prices_small_shop tests ──────────────────────────────────────


@pytest.mark.django_db
class TestSnapshotPricesSmallShop:
    @patch("apps.compliance.price_snapshot._get_client")
    def test_creates_price_history_rows(self, mock_get_client, shop):
        """Snapshot creates PriceHistory rows for variants."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_client.execute.return_value = {
            "products": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "nodes": [
                    {
                        "id": "gid://shopify/Product/1",
                        "variants": {
                            "nodes": [
                                {"id": "gid://shopify/ProductVariant/1", "price": "29.99"},
                                {"id": "gid://shopify/ProductVariant/2", "price": "34.99"},
                            ]
                        },
                    }
                ],
            }
        }

        count = snapshot_prices_small_shop(shop, "token123")

        assert count == 2
        assert PriceHistory.objects.filter(shop=shop).count() == 2

    @patch("apps.compliance.price_snapshot._get_client")
    def test_skips_same_price(self, mock_get_client, shop):
        """Snapshot skips if price matches the last recorded price."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Create existing price history
        PriceHistory.objects.create(
            shop=shop,
            variant_gid="gid://shopify/ProductVariant/1",
            price=Decimal("29.99"),
            currency="EUR",
            observed_at=timezone.now() - timedelta(hours=1),
            source="install_snapshot",
        )

        mock_client.execute.return_value = {
            "products": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "nodes": [
                    {
                        "id": "gid://shopify/Product/1",
                        "variants": {
                            "nodes": [
                                {"id": "gid://shopify/ProductVariant/1", "price": "29.99"},
                            ]
                        },
                    }
                ],
            }
        }

        count = snapshot_prices_small_shop(shop, "token123")

        assert count == 0  # Same price, no new row
        assert PriceHistory.objects.filter(shop=shop).count() == 1  # Only the existing one


# ── Webhook handler tests ─────────────────────────────────────────────────


@pytest.mark.django_db
class TestHandleProductUpdate:
    def test_creates_price_history_from_webhook(self, shop):
        """Webhook handler creates PriceHistory rows."""
        from apps.webhooks.tasks import handle_product_update
        from apps.webhooks.models import WebhookReceipt

        receipt = WebhookReceipt.objects.create(
            webhook_id="wh_product_update_1",
            topic="products/update",
            shop_domain="test-store.myshopify.com",
            body_json={
                "variants": [
                    {"admin_graphql_api_id": "gid://shopify/ProductVariant/1", "price": "29.99"},
                    {"admin_graphql_api_id": "gid://shopify/ProductVariant/2", "price": "34.99"},
                ]
            },
        )

        handle_product_update(receipt)

        assert PriceHistory.objects.filter(shop=shop).count() == 2

    def test_skips_same_price_in_webhook(self, shop):
        """Webhook handler skips if price matches last recorded."""
        from apps.webhooks.tasks import handle_product_update
        from apps.webhooks.models import WebhookReceipt

        # Existing price
        PriceHistory.objects.create(
            shop=shop,
            variant_gid="gid://shopify/ProductVariant/1",
            price=Decimal("29.99"),
            currency="EUR",
            observed_at=timezone.now() - timedelta(hours=1),
            source="install_snapshot",
        )

        receipt = WebhookReceipt.objects.create(
            webhook_id="wh_product_update_2",
            topic="products/update",
            shop_domain="test-store.myshopify.com",
            body_json={
                "variants": [
                    {"admin_graphql_api_id": "gid://shopify/ProductVariant/1", "price": "29.99"},
                ]
            },
        )

        handle_product_update(receipt)

        assert PriceHistory.objects.filter(shop=shop).count() == 1  # Only existing

    def test_records_new_price_from_webhook(self, shop):
        """Webhook handler records new price when it changes."""
        from apps.webhooks.tasks import handle_product_update
        from apps.webhooks.models import WebhookReceipt

        PriceHistory.objects.create(
            shop=shop,
            variant_gid="gid://shopify/ProductVariant/1",
            price=Decimal("29.99"),
            currency="EUR",
            observed_at=timezone.now() - timedelta(hours=1),
            source="install_snapshot",
        )

        receipt = WebhookReceipt.objects.create(
            webhook_id="wh_product_update_3",
            topic="products/update",
            shop_domain="test-store.myshopify.com",
            body_json={
                "variants": [
                    {"admin_graphql_api_id": "gid://shopify/ProductVariant/1", "price": "24.99"},
                ]
            },
        )

        handle_product_update(receipt)

        assert PriceHistory.objects.filter(shop=shop).count() == 2
        latest = PriceHistory.objects.filter(shop=shop).order_by("-observed_at").first()
        assert latest.price == Decimal("24.99")
        assert latest.source == "webhook"
