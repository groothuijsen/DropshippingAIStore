"""Marketing site views — host-guarded (F19-1, 13 §2 D-19.1)."""

from __future__ import annotations

import secrets
from datetime import UTC, date, datetime

import markdown
from django.conf import settings
from django.core.cache import cache
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET

from apps.billing.plans import PLAN_LIMITS, PLAN_NAMES, PLAN_PRICES

from .articles import get_article, list_articles
from .content import LANGUAGES, load_page
from .emails import send_email
from .forms import EarlyAccessForm, UninstallFeedbackForm
from .freshness import annotate_comparisons
from .models import Lead, MarketingHit
from .schemas import validate_sections

MARKETING_HOST = "shopify.mosaiq.marketing"
APP_HOST = "shop.mosaiq.marketing"


def _guard(request: HttpRequest) -> str | None:
    """Return the language for this request, None when the host must not
    serve marketing content (handled by the caller)."""
    host = request.get_host().split(":")[0]
    if host == APP_HOST:
        return "app"
    if host == MARKETING_HOST:
        return "en"
    return "deny"


@require_GET
def page_view(request: HttpRequest, slug: str = "home") -> HttpResponse:
    lang = "de" if request.path.startswith("/de/") else ("nl" if request.path.startswith("/nl/") else "en")
    mode = _guard(request)
    if request.path.startswith("/de/") and not settings.MARKETING_DE_ENABLED:
        raise Http404  # T-158 native review gate: German ships only after approval
    if mode == "app":
        if slug == "home" and not request.path.startswith("/nl/"):
            return HttpResponseRedirect("/app/")
        raise Http404
    if mode == "deny":
        raise Http404

    try:
        page = load_page(lang, slug)
    except FileNotFoundError:
        raise Http404 from None

    errors = validate_sections(page["sections"])
    if errors:
        raise Http404  # broken content never ships (check_marketing_content catches it in CI)

    annotate_comparisons(page["sections"])
    _attach_seo(page)
    page["body_html"] = _resolve_placeholders(markdown.markdown(page["body"], extensions=["extra"])) if page["body"] else ""
    return render(request, page["template"], {
        "page": page, "lang": lang, "languages": LANGUAGES, "plans": _plans_context(page),
        "install_href": _install_href(lang), "form": None, "form_message": ""})


def _attach_seo(page: dict) -> None:
    """Canonical alternates + JSON-LD (price rendered from plans.py, never typed)."""
    for paths in _PAGE_PATHS.values():
        if page["slug"] in paths:
            page["alts"] = [("nl" if p.startswith("/nl/") else "en", p) for p in paths]
            break
    else:
        page["alts"] = []
    price = PLAN_PRICES["starter"]["every_30_days"].normalize()
    page["jsonld"] = (
        '{"@context":"https://schema.org","@type":"SoftwareApplication","name":"Mosaiq",'
        '"applicationCategory":"BusinessApplication","operatingSystem":"Shopify",'
        f'"offers":{{"@type":"Offer","price":"{price}","priceCurrency":"USD"}},'
        '"url":"https://shopify.mosaiq.marketing/"}'
    )


def _plans_context(page: dict) -> list[dict]:
    """Pricing cards rendered from plans.py — prices are never typed in copy."""
    cards: list[dict] = []
    for slug, prices in PLAN_PRICES.items():
        limits = PLAN_LIMITS[slug]
        cards.append({
            "slug": slug,
            "name": PLAN_NAMES[slug],
            "monthly": f"${prices['every_30_days'].normalize()}",
            "annual": f"${prices['annual'].normalize()}",
            "blurb": page.get("blurbs", {}).get(slug, ""),
            "limits": [
                ("Store generations / 30 days", limits["store_generations"]),
                ("Live pages", limits["live_pages"] if limits["live_pages"] is not None else "Unlimited"),
                ("AI images / 30 days", limits["ai_images"]),
                ("Page edits / 30 days", limits["page_edits"]),
            ],
        })
    return cards


@require_GET
def blog_index(request: HttpRequest) -> HttpResponse:
    _mode = _guard(request)
    if _mode != "en" and not (request.path.startswith("/nl/") and _mode == "en"):
        raise Http404
    lang = "de" if request.path.startswith("/de/") else ("nl" if request.path.startswith("/nl/") else "en")
    blog_page = {"title": "Blog", "slug": "/blog/", "description": "", "sections": [], "body": "", "lang": lang, "alts": [], "jsonld": ""}
    return render(request, "marketing/page_default.html", {
        "page": blog_page,
        "lang": lang, "languages": LANGUAGES, "plans": [],
    })


# ── SEO (T-154): sitemap + robots ─────────────────────────────────────

_PAGE_PATHS = {
    "home": ("/", "/nl/"),
    "features": ("/features/", "/nl/functies/"),
    "pricing": ("/pricing/", "/nl/prijzen/"),
    "eu-compliance": ("/eu-compliance/", "/nl/eu-regels/"),
    "start-from-zero": ("/start-from-zero/", "/nl/begin-vanaf-nul/"),
    "early-access": ("/early-access/", "/nl/vroege-toegang/"),
    "compare": ("/compare/", "/nl/vergelijken/"),
    "agencies": ("/agencies/", "/nl/bureaus/"),
    "affiliates": ("/affiliates/", "/nl/affiliates/"),
    "changelog": ("/changelog/", "/nl/changelog/"),
}


@require_GET
def sitemap_view(request: HttpRequest) -> HttpResponse:
    if _guard(request) == "deny":
        raise Http404
    host = request.get_host().split(":")[0]
    today = date.today().isoformat()
    urls: list[str] = []
    for slug, paths in _PAGE_PATHS.items():
        try:
            load_page("en", slug)
        except FileNotFoundError:
            continue
        alts = "".join(
            f'    <xhtml:link rel="alternate" hreflang="{"nl" if p.startswith("/nl/") else "en"}" href="https://{host}{p}"/>'
            for p in paths
        )
        entry = "".join(
            f"  <url><loc>https://{host}{p}</loc>{alts if i == 0 else ''}<lastmod>{today}</lastmod></url>"
            for i, p in enumerate(paths)
        )
        urls.append(entry)
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        'xmlns:xhtml="http://www.w3.org/1999/xhtml">\n' + "\n".join(urls) + "\n</urlset>\n"
    )
    return HttpResponse(body, content_type="application/xml")


@require_GET
def robots_view(request: HttpRequest) -> HttpResponse:
    host = request.get_host().split(":")[0]
    if host == APP_HOST:
        body = "User-agent: *\nDisallow: /app/\nDisallow: /api/\n"
    elif host == MARKETING_HOST:
        body = f"User-agent: *\nAllow: /\nSitemap: https://{host}/sitemap.xml\n"
    else:
        raise Http404
    return HttpResponse(body, content_type="text/plain")


_PIXEL = bytes.fromhex('47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b')


@require_GET
def beacon_view(request: HttpRequest) -> HttpResponse:
    if _guard(request) != "en":
        raise Http404
    path = request.GET.get('p', '')[:300]
    if path.startswith('/'):
        raw_ref = request.GET.get('r', '')[:200]
        ref_host = raw_ref.split('/')[2] if '://' in raw_ref else ''
        lang = request.GET.get('l', '')[:5]
        if lang not in LANGUAGES:
            lang = ''
        MarketingHit.objects.create(path=path, referrer_host=ref_host[:200], lang=lang)
    resp = HttpResponse(_PIXEL, content_type='image/gif')
    resp['Cache-Control'] = 'no-store'
    return resp


def _resolve_placeholders(text: str) -> str:
    from django.conf import settings as st
    mapping = {
        "{legal_name}": st.MARKETING_LEGAL_NAME or "[company legal name]",
        "{address}": st.MARKETING_ADDRESS or "[address]",
        "{company_reg_no}": st.MARKETING_REG_NO or "[KvK number]",
        "{vat_id}": st.MARKETING_VAT_ID or "[VAT id]",
        "{email}": st.MARKETING_CONTACT_EMAIL,
        "{provider}": st.MARKETING_HOSTING_PROVIDER or st.MARKETING_EMAIL_PROVIDER or "[provider]",
        "{country}": "[country]",
        "{hours}": st.MARKETING_BREACH_HOURS,
        "{period}": "[retention period]",
        "{city}": "[city]",
        "{amount}": "[cap amount]",
    }
    for k, val in mapping.items():
        text = text.replace(k, val)
    return text


def _install_href(lang: str) -> str:
    if settings.MARKETING_APP_LISTED and settings.MARKETING_APP_HANDLE:
        return f'https://apps.shopify.com/{settings.MARKETING_APP_HANDLE}/install'
    return {'nl': '/nl/vroege-toegang/', 'de': '/de/fruehzugang/'}.get(lang, '/early-access/')

def _rate_limited(ip: str) -> bool:
    key = f'mkt:ea:{ip}'
    n = cache.get(key, 0)
    if n >= 5:
        return True
    cache.set(key, n + 1, 3600)
    return False


@csrf_protect
def early_access_view(request: HttpRequest, slug: str = 'early-access') -> HttpResponse:
    lang = 'de' if request.path.startswith('/de/') else ('nl' if request.path.startswith('/nl/') else 'en')
    if _guard(request) == 'deny':
        raise Http404
    if request.path.startswith('/de/') and not settings.MARKETING_DE_ENABLED:
        raise Http404  # T-158 native review gate
    try:
        page = load_page(lang, slug)
    except FileNotFoundError:
        raise Http404 from None
    annotate_comparisons(page['sections'])
    _attach_seo(page)
    page['body_html'] = markdown.markdown(page['body'], extensions=['extra']) if page['body'] else ''
    form = EarlyAccessForm(request.POST or None, initial={'lang': lang})
    message = ''
    if request.method == 'POST' and form.is_valid():
        if form.cleaned_data.get('website') or _rate_limited(request.META.get('REMOTE_ADDR', '')):
            message = 'check' if lang == 'nl' else 'check'
        else:
            token = secrets.token_urlsafe(32)
            Lead.objects.update_or_create(
                email=form.cleaned_data['email'],
                defaults={'shop_domain': form.cleaned_data.get('shop_domain', ''), 'lang': lang, 'confirm_token': token},
            )
            confirm_url = f"https://shopify.mosaiq.marketing{'/nl/' if lang == 'nl' else '/'}early-access/confirm/?token={token}" if lang == 'en' else f"https://shopify.mosaiq.marketing/nl/vroege-toegang/confirm/?token={token}"
            subject = 'Confirm your early access - Mosaiq' if lang == 'en' else 'Bevestig je vroege toegang - Mosaiq'
            send_email(form.cleaned_data['email'], subject, f'<p>{confirm_url}</p>')
            message = 'sent'
            form = EarlyAccessForm(initial={'lang': lang})
    return render(request, page['template'], {
        'page': page, 'lang': lang, 'languages': LANGUAGES, 'plans': _plans_context(page),
        'form': form, 'form_message': message, 'install_href': _install_href(lang),
    })


@require_GET
def early_access_confirm(request: HttpRequest) -> HttpResponse:
    if _guard(request) == 'deny':
        raise Http404
    token = request.GET.get('token', '')
    lang = 'de' if request.path.startswith('/de/') else ('nl' if request.path.startswith('/nl/') else 'en')
    lead = Lead.objects.filter(confirm_token=token, confirmed_at__isnull=True).first()
    if lead is None:
        ok = False
    else:
        lead.confirmed_at = datetime.now(UTC)
        lead.save(update_fields=['confirmed_at'])
        ok = True
        subject = 'Welcome to Mosaiq early access' if lang == 'en' else 'Welkom bij Mosaiq vroege toegang'
        send_email(lead.email, subject, '<p>confirmed</p>')
    text = 'Confirmed - you are on the list.' if ok else 'This link is invalid or already used.'
    if lang == 'nl':
        text = 'Bevestigd - je staat op de lijst.' if ok else 'Deze link is ongeldig of al gebruikt.'
    return HttpResponse(f'<html lang="{lang}"><body><p>{text}</p></body></html>', content_type='text/html')


import markdown as _md


def _article_page(request, section, slug):
    lang = 'de' if request.path.startswith('/de/') else ('nl' if request.path.startswith('/nl/') else 'en')
    if _guard(request) == 'deny':
        raise Http404
    show = getattr(settings, 'MARKETING_SHOW_DRAFTS', False)
    article = get_article(lang, section, slug, include_drafts=show)
    if article is None:
        raise Http404
    article['body_html'] = _resolve_placeholders(_md.markdown(article['body'], extensions=['extra']))
    section_titles = {'blog': ('Blog', 'Blog'), 'help': ('Help centre', 'Helpcentrum')}
    t_en, t_nl = section_titles.get(section, (section, section))
    return render(request, 'marketing/article.html', {
        'article': article, 'section': section,
        'section_title': t_nl if lang == 'nl' else t_en,
        'lang': lang, 'languages': LANGUAGES,
        'list_href': f'/nl/{section}/' if (lang == 'nl' and section == 'blog') else (f'/{section}/'),
        'page': {'title': article['title'], 'slug': f'/{section}/{article[chr(39)+chr(39)] if False else article["slug"]}/', 'alts': [], 'jsonld': '', 'draft': article['draft']},
        'plans': [], 'install_href': _install_href(lang), 'form': None, 'form_message': '',
    })


@require_GET
def blog_list_view(request: HttpRequest) -> HttpResponse:
    return _article_list(request, 'blog')


@require_GET
def help_index_view(request: HttpRequest) -> HttpResponse:
    return _article_list(request, 'help')


def _article_list(request, section):
    lang = 'de' if request.path.startswith('/de/') else ('nl' if request.path.startswith('/nl/') else 'en')
    if _guard(request) == 'deny':
        raise Http404
    show = getattr(settings, 'MARKETING_SHOW_DRAFTS', False)
    articles = list_articles(lang, section, include_drafts=show)
    section_titles = {'blog': ('Blog', 'Blog'), 'help': ('Help centre', 'Helpcentrum')}
    t_en, t_nl = section_titles.get(section, (section, section))
    return render(request, 'marketing/article_list.html', {
        'articles': articles, 'section': section,
        'section_title': t_nl if lang == 'nl' else t_en,
        'lang': lang, 'languages': LANGUAGES,
        'page': {'title': t_nl if lang == 'nl' else t_en, 'slug': f'/{section}/', 'alts': [], 'jsonld': '', 'draft': False},
        'plans': [], 'install_href': _install_href(lang), 'form': None, 'form_message': '',
    })


@require_GET
def blog_rss_view(request: HttpRequest) -> HttpResponse:
    if _guard(request) == 'deny':
        raise Http404
    posts = list_articles('en', 'blog', include_drafts=getattr(settings, 'MARKETING_SHOW_DRAFTS', False))
    host = request.get_host().split(':')[0]
    items = ''.join(
        f'<item><title>{p["title"]}</title><link>https://{host}/blog/{p["slug"]}/</link>'
        f'<guid>https://{host}/blog/{p["slug"]}/</guid><pubDate>{p["date"]}</pubDate></item>'
        for p in posts
    )
    body = '<?xml version="1.0"?><rss version="2.0"><channel><title>Mosaiq blog</title>' \
        f'<link>https://{host}/blog/</link>{items}</channel></rss>'
    return HttpResponse(body, content_type='application/rss+xml')


@require_GET
def blog_post_view(request: HttpRequest, slug: str) -> HttpResponse:
    return _article_page(request, 'blog', slug)


@require_GET
def help_article_view(request: HttpRequest, slug: str) -> HttpResponse:
    return _article_page(request, 'help', slug)


def uninstall_feedback_view(request: HttpRequest) -> HttpResponse:
    lang = 'nl' if request.path.startswith('/nl/') else 'en'
    if _guard(request) == 'deny':
        raise Http404
    if request.method == 'POST':
        form = UninstallFeedbackForm(request.POST)
        if form.is_valid():
            honeypot = request.POST.get('website', '')
            if not honeypot and not _rate_limited(request.META.get('REMOTE_ADDR', '')):
                form.save()
                msg = 'Bedankt voor je feedback!' if lang == 'nl' else 'Thank you for your feedback!'
            else:
                msg = 'Bedankt!' if lang == 'nl' else 'Thank you!'
            return render(request, 'marketing/uninstall_feedback.html', {
                'form': None, 'message': msg, 'lang': lang,
                'languages': LANGUAGES,
                'page': {'title': 'Feedback', 'slug': f'/{"nl/" if lang == "nl" else ""}feedback/uninstall/', 'alts': [], 'jsonld': '', 'draft': False},
                'plans': [], 'install_href': _install_href(lang), 'form_message': '',
            })
        form = UninstallFeedbackForm()
        msg = 'Er ging iets mis. Probeer het opnieuw.' if lang == 'nl' else 'Something went wrong. Please try again.'
    else:
        form = UninstallFeedbackForm()
        msg = ''
    return render(request, 'marketing/uninstall_feedback.html', {
        'form': form, 'message': msg, 'lang': lang,
        'languages': LANGUAGES,
        'page': {'title': 'Feedback', 'slug': f'/{"nl/" if lang == "nl" else ""}feedback/uninstall/', 'alts': [], 'jsonld': '', 'draft': False},
        'plans': [], 'install_href': _install_href(lang), 'form_message': '',
    })
