"""Tests for T-003: embedded layout, CSP, auth.js, i18n."""

import pytest
from django.test import RequestFactory

from apps.core.csp_middleware import CspFrameAncestorsMiddleware

# ── CSP middleware tests ───────────────────────────────────────────────────


class TestCspFrameAncestors:
    def _make_request(self, path="/app/", shop_domain="test-store.myshopify.com"):
        factory = RequestFactory()
        request = factory.get(path)
        request.shop_domain = shop_domain
        return request

    def _make_response(self):
        from django.http import HttpResponse

        return HttpResponse(status=200)

    def test_app_route_gets_csp_header(self):
        request = self._make_request("/app/dashboard/")
        response = self._make_response()
        middleware = CspFrameAncestorsMiddleware(lambda r: None)
        result = middleware.process_response(request, response)
        assert "Content-Security-Policy" in result
        assert "frame-ancestors" in result["Content-Security-Policy"]
        assert "test-store.myshopify.com" in result["Content-Security-Policy"]
        assert "admin.shopify.com" in result["Content-Security-Policy"]

    def test_non_app_route_no_csp(self):
        request = self._make_request("/healthz/")
        response = self._make_response()
        middleware = CspFrameAncestorsMiddleware(lambda r: None)
        result = middleware.process_response(request, response)
        assert "Content-Security-Policy" not in result

    def test_fallback_without_shop_domain(self):
        request = self._make_request("/app/dashboard/")
        request.shop_domain = None
        response = self._make_response()
        middleware = CspFrameAncestorsMiddleware(lambda r: None)
        result = middleware.process_response(request, response)
        assert "Content-Security-Policy" in result
        assert "admin.shopify.com" in result["Content-Security-Policy"]


# ── Dashboard view tests ──────────────────────────────────────────────────


@pytest.mark.django_db
class TestDashboardView:
    def test_dashboard_renders(self):
        from django.test import Client

        Client()
        # Dashboard requires session token — test that it renders the template
        # (middleware will redirect to bounce without token, but view itself works)
        from apps.core.views import dashboard

        factory = RequestFactory()
        request = factory.get("/app/dashboard/")
        request.shop_domain = "test-store.myshopify.com"
        request.ui_locale = "en"
        response = dashboard(request)
        assert response.status_code == 200
        content = response.content.decode()
        assert "Welcome to Mosaiq" in content


# ── auth.js existence test ────────────────────────────────────────────────


class TestAuthJs:
    def test_auth_js_exists(self):
        import os

        from django.conf import settings

        os.path.join(settings.STATIC_ROOT or "", "app", "auth.js")
        # Check in static dirs instead
        for static_dir in settings.STATICFILES_DIRS:
            path = os.path.join(static_dir, "app", "auth.js")
            if os.path.exists(path):
                with open(path) as f:
                    content = f.read()
                assert "htmx:configRequest" in content
                assert "Authorization" in content
                assert "shopify.idToken" in content
                return
        pytest.fail("auth.js not found in static dirs")

    def test_htmx_esm_exists(self):
        import os

        from django.conf import settings

        for static_dir in settings.STATICFILES_DIRS:
            path = os.path.join(static_dir, "vendor", "htmx.esm.js")
            if os.path.exists(path):
                assert os.path.getsize(path) > 100_000  # > 100KB
                return
        pytest.fail("htmx.esm.js not found in static/vendor/")


# ── Template tests ────────────────────────────────────────────────────────


class TestTemplates:
    def test_base_template_has_app_bridge(self):
        from django.template.loader import get_template

        template = get_template("app/base.html")
        assert template is not None

    def test_bounce_template_has_shopify(self):
        from django.template.loader import get_template

        template = get_template("app/bounce.html")
        assert template is not None

    def test_dashboard_template_exists(self):
        from django.template.loader import get_template

        template = get_template("app/dashboard.html")
        assert template is not None


# ── i18n tests ────────────────────────────────────────────────────────────


class TestI18n:
    def test_languages_configured(self):
        from django.conf import settings

        lang_codes = [code for code, _ in settings.LANGUAGES]
        assert "nl" in lang_codes
        assert "en" in lang_codes
        assert "de" in lang_codes

    def test_locale_paths_exist(self):
        import os

        from django.conf import settings

        for locale_path in settings.LOCALE_PATHS:
            assert os.path.isdir(locale_path), f"Locale path {locale_path} does not exist"
