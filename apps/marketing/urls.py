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
]

urlpatterns = [
    path("", views.page_view, {"slug": "home"}, name="home"),
    path("features/", views.page_view, {"slug": "features"}, name="features"),
    path("pricing/", views.page_view, {"slug": "pricing"}, name="pricing"),
    path("eu-compliance/", views.page_view, {"slug": "eu-compliance"}, name="eu_compliance"),
    path("start-from-zero/", views.page_view, {"slug": "start-from-zero"}, name="start_from_zero"),
    path("early-access/", views.page_view, {"slug": "early-access"}, name="early_access"),
    path("compare/", views.page_view, {"slug": "compare"}, name="compare"),
    path("agencies/", views.page_view, {"slug": "agencies"}, name="agencies"),
    path("affiliates/", views.page_view, {"slug": "affiliates"}, name="affiliates"),
    path("changelog/", views.page_view, {"slug": "changelog"}, name="changelog"),
    path("blog/", views.blog_index, name="blog_index"),
    path("sitemap.xml", views.sitemap_view, name="sitemap"),
    path("robots.txt", views.robots_view, name="robots"),
    path("t.gif", views.beacon_view, name="beacon"),
    # /de/ intentionally absent until T-158 (native review gate)
]
urlpatterns += [
    path(f"nl/{route}", views.page_view, {"slug": stem}, name=name)
    for route, stem, name in _NL
]
