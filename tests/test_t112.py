"""Tests for T-112: StoreBlueprint, route choice, brief, names step (F15-1/3/4)."""

from unittest.mock import MagicMock, patch

import jwt as pyjwt
import pytest
from django.conf import settings
from django.test import Client
from pydantic import ValidationError

from apps.ai.schemas import NameIdea, NameSuggestions, NicheBrief
from apps.core.models import Shop
from apps.generator.models import BlueprintStatus, StoreBlueprint
from apps.themes.brand_blocklist import is_blocked_brand


@pytest.fixture()
def shop(db) -> Shop:
    return Shop.objects.create(
        domain="t112-test.myshopify.com",
        shopify_gid="gid://shopify/Shop/t112-test",
        access_token_encrypted=b"\x00" * 32,
        refresh_token_encrypted=b"\x00" * 32,
        onboarding_step="brand",
    )


def _token(shop: Shop) -> str:
    return pyjwt.encode(
        {
            "iss": f"https://{shop.domain}/admin",
            "dest": f"https://{shop.domain}",
            "aud": settings.SHOPIFY_API_KEY,
            "sub": "12345",
            "exp": 9999999999,
            "nbf": 1000000000,
        },
        settings.SHOPIFY_API_SECRET,
        algorithm="HS256",
    )


def _post(shop: Shop, url: str, data: dict, token: str | None = None) -> dict:
    t = token or _token(shop)
    return Client().post(f"{url}?id_token={t}", data=data)


GOOD_BRIEF = {
    "description": "Sleep wellness products for people who struggle to fall asleep.",
    "markets": ["NL", "BE"],
    "content_locales": ["nl"],
    "audience": "Adults 25-45 with sleep problems",
    "price_level": "mid",
    "import_app": "cj",
}


class TestSchemas:
    def test_niche_brief_valid(self):
        b = NicheBrief(**GOOD_BRIEF)
        assert b.markets == ["NL", "BE"]

    def test_niche_brief_description_bounds(self):
        with pytest.raises(ValidationError):
            NicheBrief(**{**GOOD_BRIEF, "description": "too short"})
        with pytest.raises(ValidationError):
            NicheBrief(**{**GOOD_BRIEF, "description": "x" * 501})

    def test_name_idea_pattern(self):
        NameIdea(name="Somnio", rationale="evokes sleep", pronunciation_ok=["nl"])
        with pytest.raises(ValidationError):
            NameIdea(name="bad name!", rationale="x", pronunciation_ok=["nl"])
        with pytest.raises(ValidationError):
            NameSuggestions(names=[{"name": "ab", "rationale": "x", "pronunciation_ok": ["nl"]}])


class TestBrandBlocklist:
    @pytest.mark.parametrize("name", ["EcoGlow", "Nike", "SwissSleep"])
    def test_rejected(self, name):
        assert is_blocked_brand(name) is not None

    @pytest.mark.parametrize("name", ["Somnio", "Velora", "Kavvo"])
    def test_accepted(self, name):
        assert is_blocked_brand(name) is None


class TestRouteChoice:
    def test_brand_step_renders_route_choice(self, db, shop):
        token = _token(shop)
        resp = Client().get(f"/app/onboarding/brand/?id_token={token}")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Start from zero" in content
        assert "name=\"route\"" in content

    def test_route_zero_creates_blueprint_and_redirects(self, db, shop):
        resp = _post(shop, "/app/onboarding/brand/", {"route": "zero"})
        assert resp.status_code == 302
        assert "/app/start/" in resp["Location"]
        shop.refresh_from_db()
        assert shop.onboarding_route == "zero"
        bp = StoreBlueprint.objects.get(shop=shop)
        assert bp.status == BlueprintStatus.BRIEF

    def test_route_existing_stores_route(self, db, shop):
        resp = _post(shop, "/app/onboarding/brand/", {"route": "existing"})
        assert resp.status_code == 302
        shop.refresh_from_db()
        assert shop.onboarding_route == "existing"

    def test_existing_without_brand_name_stays(self, db, shop):
        resp = _post(shop, "/app/onboarding/brand/", {"route": "existing"})
        assert "/app/onboarding/brand/" in resp["Location"]
        assert shop.onboarding_step == "brand"  # not advanced


class TestBriefScreen:
    def _url(self) -> str:
        return "/app/start/"

    def test_get_renders(self, db, shop):
        token = _token(shop)
        resp = Client().get(f"{self._url()}?id_token={token}")
        assert resp.status_code == 200
        assert "Build your store from zero" in resp.content.decode()

    def test_invalid_brief_shows_errors_no_task(self, db, shop):
        bp = StoreBlueprint.objects.create(shop=shop)
        with patch("apps.generator.tasks.generate_name_suggestions.delay") as mocked:
            resp = _post(
                shop,
                self._url(),
                {**GOOD_BRIEF, "description": "short", "markets": [], "action": "brief"},
            )
        assert resp.status_code == 302
        mocked.assert_not_called()
        bp.refresh_from_db()
        assert bp.status == BlueprintStatus.BRIEF  # nothing sent to AI

    @pytest.mark.parametrize(
        "override",
        [
            {"markets": []},
            {"markets": ["NL"] * 6},
            {"content_locales": []},
            {"price_level": "luxury"},
            {"import_app": "aliexpress"},
        ],
    )
    def test_invalid_fields_rejected(self, db, shop, override):
        StoreBlueprint.objects.create(shop=shop)
        with patch("apps.generator.tasks.generate_name_suggestions.delay") as mocked:
            _post(shop, self._url(), {**GOOD_BRIEF, **override, "action": "brief"})
        mocked.assert_not_called()

    def test_valid_brief_saves_and_enqueues(self, db, shop):
        bp = StoreBlueprint.objects.create(shop=shop)
        with patch("apps.generator.tasks.generate_name_suggestions.delay") as mocked:
            resp = _post(shop, self._url(), {**GOOD_BRIEF, "action": "brief"})
        assert resp.status_code == 302
        mocked.assert_called_once()
        bp.refresh_from_db()
        assert bp.status == BlueprintStatus.NAMES
        assert bp.description == GOOD_BRIEF["description"]
        assert bp.markets == ["NL", "BE"]
        assert bp.price_level == "mid"


def _ideas(names: list[str]) -> list[NameIdea]:
    return [
        NameIdea(name=n, rationale=f"{n} fits the niche", pronunciation_ok=["nl"])
        for n in names
    ]


GOOD_NAMES = ["Somnio", "Velora", "Kavvo", "Nuvra", "Slaapzo", "Dreampo", "Rustiq", "Nestra"]
BAD_MERGE = ["EcoGlow", "Nike", "SwissSleep"]


def _mock_call_ai(first: list[NameIdea], second: list[NameIdea] | None = None):
    responses = [MagicMock(names=first)]
    if second is not None:
        responses.append(MagicMock(names=second))
    mock = MagicMock(side_effect=responses)
    return mock


class TestNamesTask:
    def _bp(self, shop) -> StoreBlueprint:
        return StoreBlueprint.objects.create(
            shop=shop,
            status=BlueprintStatus.NAMES,
            description=GOOD_BRIEF["description"],
            markets=["NL"],
            content_locales=["nl"],
            audience="adults",
            price_level="mid",
            import_app="cj",
        )

    def test_filters_blocklisted_and_repeats_once(self, db, shop):
        from apps.generator.tasks import generate_name_suggestions

        bp = self._bp(shop)
        first = _ideas(BAD_MERGE + GOOD_NAMES[:5])  # 3 blocked → 5 kept
        second = _ideas(GOOD_NAMES[5:] + ["Somnio"])  # missing 3; Somnio deduped
        mock = _mock_call_ai(first, second)
        with (
            patch("apps.ai.anthropic_client.call_ai", mock),
            patch("apps.generator.tasks.check_domain_status", return_value="likely_free") as rdap,
        ):
            generate_name_suggestions(str(bp.id))
        bp.refresh_from_db()
        assert len(bp.name_suggestions) == 8
        stored = [n["name"] for n in bp.name_suggestions]
        assert not any(n in stored for n in BAD_MERGE)
        assert stored[:5] == GOOD_NAMES[:5]
        assert all(n["domain_status"] == "likely_free" for n in bp.name_suggestions)
        assert rdap.call_count == 8
        assert mock.call_count == 2  # one repeat only

    def test_rdap_failure_yields_unknown(self, db, shop):
        from apps.generator.tasks import generate_name_suggestions

        bp = self._bp(shop)
        mock = _mock_call_ai(_ideas(GOOD_NAMES))
        with (
            patch("apps.ai.anthropic_client.call_ai", mock),
            patch("apps.generator.tasks.check_domain_status", return_value="unknown"),
        ):
            generate_name_suggestions(str(bp.id))
        bp.refresh_from_db()
        assert all(n["domain_status"] == "unknown" for n in bp.name_suggestions)

    def test_wrong_status_skips(self, db, shop):
        from apps.generator.tasks import generate_name_suggestions

        bp = StoreBlueprint.objects.create(shop=shop, status=BlueprintStatus.BRIEF)
        mock = _mock_call_ai(_ideas(GOOD_NAMES))
        with patch("apps.ai.anthropic_client.call_ai", mock):
            generate_name_suggestions(str(bp.id))
        mock.assert_not_called()

    def test_missing_blueprint_no_error(self, db):
        from apps.generator.tasks import generate_name_suggestions

        generate_name_suggestions("00000000-0000-0000-0000-000000000000")


class TestNamesScreen:
    def _bp(self, shop) -> StoreBlueprint:
        return StoreBlueprint.objects.create(
            shop=shop,
            status=BlueprintStatus.NAMES,
            name_suggestions=[
                {"name": n, "rationale": "fits", "pronunciation_ok": ["nl"], "domain_status": "likely_free"}
                for n in GOOD_NAMES
            ],
        )

    def test_panel_renders_names(self, db, shop):
        self._bp(shop)
        token = _token(shop)
        resp = Client().get(f"/app/start/panel/?id_token={token}")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Somnio" in content
        assert "Not a trademark check" in content
        assert "TMview" in content
        assert "likely_free" in content

    def test_regenerate_increments_and_blocks_at_limit(self, db, shop):
        bp = self._bp(shop)
        bp.regenerate_count = 2
        bp.save(update_fields=["regenerate_count"])
        with patch("apps.generator.tasks.generate_name_suggestions.delay") as mocked:
            _post(shop, "/app/start/", {"action": "regenerate"})
        bp.refresh_from_db()
        assert bp.regenerate_count == 3
        assert bp.name_suggestions == []
        mocked.assert_called_once()
        # 4th regenerate refused
        with patch("apps.generator.tasks.generate_name_suggestions.delay") as mocked2:
            _post(shop, "/app/start/", {"action": "regenerate"})
        mocked2.assert_not_called()

    def test_pick_own_blocked_name(self, db, shop):
        bp = self._bp(shop)
        _post(shop, "/app/start/", {"action": "pick_own", "own_name": "NikeSleep"})
        bp.refresh_from_db()
        assert bp.brand_name == ""  # not picked
        assert bp.status == BlueprintStatus.NAMES

    def test_pick_own_good_name_advances(self, db, shop):
        bp = self._bp(shop)
        resp = _post(shop, "/app/start/", {"action": "pick_own", "own_name": "Helderz"})
        assert resp.status_code == 302
        assert "/app/onboarding/brand/" in resp["Location"]
        bp.refresh_from_db()
        assert bp.brand_name == "Helderz"
        assert bp.brand_slug == "helderz"
        assert bp.status == BlueprintStatus.BRAND
        assert "names" in bp.completed_steps

    def test_pick_suggestion(self, db, shop):
        bp = self._bp(shop)
        _post(shop, "/app/start/", {"action": "pick", "pick_index": "2"})
        bp.refresh_from_db()
        assert bp.brand_name == "Kavvo"
        assert bp.status == BlueprintStatus.BRAND


class TestDomainCheck:
    def test_rdap_404_means_likely_free(self, db, shop):
        from apps.generator.tasks import check_domain_status

        fake = MagicMock(status_code=404)
        with patch("httpx.get", return_value=fake):
            assert check_domain_status("somnio") == "likely_free"

    def test_rdap_200_means_taken(self, db, shop):
        from apps.generator.tasks import check_domain_status

        fake = MagicMock(status_code=200)
        with patch("httpx.get", return_value=fake):
            assert check_domain_status("nike") == "taken"

    def test_rdap_error_means_unknown(self, db, shop):
        from apps.generator.tasks import check_domain_status

        with patch("httpx.get", side_effect=RuntimeError("boom")):
            assert check_domain_status("somnio") == "unknown"
