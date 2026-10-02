"""Tests for T-161: GPSR form + GPSR loaded from the product metafield.

F11-E, 07 §5: the merchant fills GPSR per product; publish refuses without
complete GPSR (05 §4.6); the mq-gpsr block reads the same metafield.
"""

from unittest.mock import MagicMock, patch

import jwt as pyjwt
import pytest
from django.conf import settings
from django.test import Client

from apps.compliance.gpsr import GpsrInfo
from apps.core.models import AuditLog, Shop

PRODUCT_GID = "gid://shopify/Product/111"

COMPLETE = {
    "manufacturer_name": "Acme BV",
    "manufacturer_address": "Dorpsstraat 1, Venlo",
    "manufacturer_email": "gpsr@acme.nl",
    "manufacturer_in_eu": True,
    "eu_rp_name": "",
    "eu_rp_address": "",
    "eu_rp_email": "",
    "product_identifier": "ACM-001",
    "warnings": "Niet geschikt voor kinderen onder 3 jaar.",
    "no_warnings_confirmed": False,
    "content_locale": "nl",
}


@pytest.fixture()
def shop(db) -> Shop:
    return Shop.objects.create(
        domain="t161-test.myshopify.com",
        shopify_gid="gid://shopify/Shop/t161",
        access_token_encrypted=b"\x00" * 32,
        refresh_token_encrypted=b"\x00" * 32,
        onboarding_step="building",
        onboarding_route="zero",
    )


def _auth(shop: Shop) -> str:
    return pyjwt.encode(
        {
            "iss": f"https://{shop.domain}/admin",
            "dest": f"https://{shop.domain}",
            "aud": settings.SHOPIFY_API_KEY,
            "sub": "1",
            "exp": 9999999999,
            "nbf": 1,
        },
        settings.SHOPIFY_API_SECRET,
        algorithm="HS256",
    )


def _client_mock(existing_value: dict | None = None):
    client = MagicMock()

    def execute(query, variables=None):
        variables = variables or {}
        if "ProductMetafield" in query:
            return {
                "product": {
                    "id": variables.get("id"),
                    "metafield": (
                        {"value": __import__("json").dumps(existing_value)} if existing_value else None
                    ),
                }
            }
        if "metafieldsSet" in query:
            return {"metafieldsSet": {"metafields": [{"id": "gid://shopify/Metafield/1"}], "userErrors": []}}
        return {}

    client.execute.side_effect = execute
    return client


class TestGpsrForm:
    def test_get_renders_empty_form_without_metafield(self, db, shop):
        token = _auth(shop)
        client = _client_mock(None)
        with patch("apps.compliance.views._get_client", return_value=client):
            resp = Client().get(f"/app/products/{PRODUCT_GID}/gpsr/?id_token={token}")
        assert resp.status_code == 200
        text = resp.content.decode()
        assert "GPSR" in text
        assert "manufacturer_name" in text
        assert "no_warnings_confirmed" in text

    def test_get_prefills_from_metafield(self, db, shop):
        token = _auth(shop)
        client = _client_mock(COMPLETE)
        with patch("apps.compliance.views._get_client", return_value=client):
            resp = Client().get(f"/app/products/{PRODUCT_GID}/gpsr/?id_token={token}")
        text = resp.content.decode()
        assert "Acme BV" in text
        assert "ACM-001" in text

    def test_post_writes_metafield_and_auditlog(self, db, shop):
        token = _auth(shop)
        client = _client_mock(None)
        with patch("apps.compliance.views._get_client", return_value=client):
            resp = Client().post(
                f"/app/products/{PRODUCT_GID}/gpsr/?id_token={token}",
                data={k: v for k, v in COMPLETE.items() if isinstance(v, str)} | {"no_warnings_confirmed": ""},
            )
        assert resp.status_code == 302
        calls = [c for c in client.execute.call_args_list if "metafieldsSet" in c.args[0]]
        assert len(calls) == 1
        metafields = calls[0].args[1]["metafields"]
        assert metafields[0]["namespace"] == "$app:mosaiq"
        assert metafields[0]["key"] == "gpsr"
        value = __import__("json").loads(metafields[0]["value"])
        assert value["manufacturer_name"] == "Acme BV"
        assert value["product_identifier"] == "ACM-001"
        assert AuditLog.objects.filter(shop=shop, action="gpsr_saved").exists()

    def test_post_incomplete_still_saves_with_warning(self, db, shop):
        """Saving incomplete GPSR is allowed; the form says publish stays blocked."""
        token = _auth(shop)
        client = _client_mock(None)
        django_client = Client()
        with patch("apps.compliance.views._get_client", return_value=client):
            resp = django_client.post(
                f"/app/products/{PRODUCT_GID}/gpsr/?id_token={token}",
                data={"manufacturer_name": "Acme BV"},
            )
            assert resp.status_code == 302
            # Same client keeps the session -> the warning message renders.
            resp = django_client.get(f"/app/products/{PRODUCT_GID}/gpsr/?id_token={token}")
        assert resp.status_code == 200
        text = resp.content.decode()
        assert "publish" in text.lower()
        calls = [c for c in client.execute.call_args_list if "metafieldsSet" in c.args[0]]
        assert len(calls) == 1
        value = __import__("json").loads(calls[0].args[1]["metafields"][0]["value"])
        info = GpsrInfo.from_metafield(value)
        assert info.complete is False
        assert "manufacturer_email" in info.missing_fields

    def test_post_shows_user_errors_from_api(self, db, shop):
        token = _auth(shop)
        client = _client_mock(None)

        def failing(query, variables=None):
            if "metafieldsSet" in query:
                return {"metafieldsSet": {"metafields": [], "userErrors": [{"field": "metafields", "message": "boom"}]}}
            return _client_mock().execute(query, variables)

        client.execute.side_effect = failing
        django_client = Client()
        with patch("apps.compliance.views._get_client", return_value=client):
            resp = django_client.post(
                f"/app/products/{PRODUCT_GID}/gpsr/?id_token={token}",
                data={k: v for k, v in COMPLETE.items() if isinstance(v, str)},
            )
            assert resp.status_code == 302
            resp = django_client.get(f"/app/products/{PRODUCT_GID}/gpsr/?id_token={token}")
        assert "boom" in resp.content.decode()


class TestGpsrLoadedFromMetafield:
    """publish/go_live must load GPSR from the product metafield (the TODOs)."""

    def test_publish_step_reads_metafield(self, db, shop):
        """Complete GPSR in the metafield -> publish proceeds past the gate."""
        from apps.generator.models import (
            GenerationJob,
            JobKind,
            JobStatus,
            Page,
            PageStatus,
            StepStatus,
        )
        from apps.generator.publish_step import run_publish

        job = GenerationJob.objects.create(
            shop=shop,
            kind=JobKind.PAGE,
            page_type="pdp",
            content_locale="nl",
            input={"blueprint_id": "x", "product_gid": PRODUCT_GID},
            status=JobStatus.RUNNING,
            idempotency_key="t161-pdp",
        )
        Page.objects.create(
            shop=shop,
            job=job,
            page_type="pdp",
            content_locale="nl",
            title="T",
            sections={"nl": {"sections": []}},
            status=PageStatus.DRAFT,
            product_gid=PRODUCT_GID,
        )
        step = job.steps.create(name="publish", status=StepStatus.RUNNING)

        client = _client_mock(COMPLETE)
        with patch("apps.generator.publish_step._get_client", return_value=client):
            # Must NOT raise GpsrIncomplete; the layout step is missing so
            # run_publish returns early AFTER the GPSR gate.
            run_publish(job, step)

    def test_check_can_go_live_uses_metafield(self, db, shop):
        from apps.generator.go_live import check_can_go_live
        from apps.generator.models import Page, PageStatus

        page = Page.objects.create(
            shop=shop,
            page_type="pdp",
            content_locale="nl",
            title="T",
            sections={"nl": {"sections": []}},
            status=PageStatus.DRAFT,
            product_gid=PRODUCT_GID,
        )
        client = _client_mock(COMPLETE)
        with patch("apps.generator.go_live._get_client", return_value=client):
            allowed, missing = check_can_go_live(page)
        assert allowed is True, missing

    def test_check_can_go_live_blocked_without_metafield(self, db, shop):
        from apps.generator.go_live import check_can_go_live
        from apps.generator.models import Page, PageStatus

        page = Page.objects.create(
            shop=shop,
            page_type="pdp",
            content_locale="nl",
            title="T",
            sections={"nl": {"sections": []}},
            status=PageStatus.DRAFT,
            product_gid=PRODUCT_GID,
        )
        client = _client_mock(None)
        with patch("apps.generator.go_live._get_client", return_value=client):
            allowed, missing = check_can_go_live(page)
        assert allowed is False
        assert any("GPSR" in m for m in missing)


class TestBuildPanelGpsrLink:
    def test_blocked_pdp_links_to_gpsr_form(self, db, shop):
        """The build panel links the merchant to the GPSR form for blocked PDPs."""
        from apps.core.models import BusinessDetails
        from apps.generator.models import (
            BlueprintStatus,
            GenerationJob,
            JobKind,
            JobStatus,
            StoreBlueprint,
        )

        bp = StoreBlueprint.objects.create(
            shop=shop,
            status=BlueprintStatus.BUILDING,
            onboarding_route="zero",
            brand_name="Helderz",
            selected_product_gids=[PRODUCT_GID],
            store_structure={"collections": [], "menu": [], "pages": []},
            standard_pages={"shipping": {"title": "S", "sections": [], "warnings": []}},
            publish_result={
                "published_pages": {},
                "blocked_pages": [
                    {"page_type": "pdp", "product_gid": PRODUCT_GID, "reasons": ["GPSR data incomplete"]}
                ],
                "collections_published": [],
            },
        )
        job = GenerationJob.objects.create(
            shop=shop,
            kind=JobKind.STORE,
            idempotency_key=f"store-build-{bp.id}",
            content_locale="nl",
            input={"blueprint_id": str(bp.id)},
            status=JobStatus.SUCCEEDED,
        )
        bp.build_job = job
        bp.save(update_fields=["build_job", "updated_at"])
        BusinessDetails.objects.create(
            shop=shop, legal_name="X", street="Y 1", postal_code="1AB", city="Z", country_code="NL", return_address_same=True
        )
        token = _auth(shop)
        resp = Client().get(f"/app/start/?id_token={token}")
        text = resp.content.decode()
        assert f"/app/products/{PRODUCT_GID}/gpsr/" in text
