from django.urls import path

from . import views

app_name = "marketing"

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
    # Dutch prefixed routes
    path("nl/", views.page_view, {"slug": "home"}, name="nl_home"),
    path("nl/features/", views.page_view, {"slug": "features"}, name="nl_features"),
    path("nl/pricing/", views.page_view, {"slug": "pricing"}, name="nl_pricing"),
    path("nl/eu-compliance/", views.page_view, {"slug": "eu-compliance"}, name="nl_eu_compliance"),
    # /de/ intentionally absent until T-158 (native review gate)
]
