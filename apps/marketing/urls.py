from django.urls import path

from . import views

app_name = "marketing"

# NL routes use the Dutch slugs from site-copy.nl.md; the loader reads
# content/marketing/nl/<english-stem>.md (language parity is file-based).
_NL = [
    ("", "home", "nl_home"),
    ("functies/", "features", "nl_features"),
    ("prijzen/", "pricing", "nl_pricing"),
    ("eu-regels/", "eu-compliance", "nl_eu_compliance"),
    ("begin-vanaf-nul/", "start-from-zero", "nl_start_from_zero"),
    ("vroege-toegang/", "early-access", "nl_early_access"),
    ("vergelijken/", "compare", "nl_compare"),
    ("bureaus/", "agencies", "nl_agencies"),
    ("affiliates/", "affiliates", "nl_affiliates"),
    ("changelog/", "changelog", "nl_changelog"),
    ("juridisch/privacy/", "privacy", "nl_privacy"),
    ("juridisch/voorwaarden/", "terms", "nl_terms"),
    ("juridisch/dpa/", "dpa", "nl_dpa"),
    ("juridisch/subverwerkers/", "subprocessors", "nl_subprocessors"),
    ("juridisch/cookies/", "cookies", "nl_cookies"),
    ("juridisch/bedrijfsgegevens/", "company", "nl_company"),
]

urlpatterns = [
    path("", views.page_view, {"slug": "home"}, name="home"),
    path("features/", views.page_view, {"slug": "features"}, name="features"),
    path("pricing/", views.page_view, {"slug": "pricing"}, name="pricing"),
    path("eu-compliance/", views.page_view, {"slug": "eu-compliance"}, name="eu_compliance"),
    path("start-from-zero/", views.page_view, {"slug": "start-from-zero"}, name="start_from_zero"),
    path("early-access/", views.early_access_view, {"slug": "early-access"}, name="early_access"),
    path("early-access/confirm/", views.early_access_confirm, name="early_access_confirm"),
    path("compare/", views.page_view, {"slug": "compare"}, name="compare"),
    path("agencies/", views.page_view, {"slug": "agencies"}, name="agencies"),
    path("affiliates/", views.page_view, {"slug": "affiliates"}, name="affiliates"),
    path("changelog/", views.page_view, {"slug": "changelog"}, name="changelog"),
    path("legal/privacy/", views.page_view, {"slug": "privacy"}, name="legal_privacy"),
    path("legal/terms/", views.page_view, {"slug": "terms"}, name="legal_terms"),
    path("legal/dpa/", views.page_view, {"slug": "dpa"}, name="legal_dpa"),
    path("legal/subprocessors/", views.page_view, {"slug": "subprocessors"}, name="legal_subprocessors"),
    path("legal/cookies/", views.page_view, {"slug": "cookies"}, name="legal_cookies"),
    path("legal/company/", views.page_view, {"slug": "company"}, name="legal_company"),
    path("blog/", views.blog_index, name="blog_index"),
    path("sitemap.xml", views.sitemap_view, name="sitemap"),
    path("robots.txt", views.robots_view, name="robots"),
    path("t.gif", views.beacon_view, name="beacon"),
    # /de/ intentionally absent until T-158 (native review gate)
]
urlpatterns += [
    path(f"nl/{route}", views.early_access_view if stem == "early-access" else views.page_view, {"slug": stem}, name=name)
    for route, stem, name in _NL
]
urlpatterns += [path("nl/vroege-toegang/confirm/", views.early_access_confirm, name="nl_early_access_confirm")]
