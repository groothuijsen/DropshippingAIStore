"""Import-app names and deep links for the product-ideas screen (F15-6).

Deep links point at the merchant-facing app surfaces (06 §4 app list).
Search-style links append the merchant's search phrase URL-encoded;
apps without a stable public search surface link to their homepage.
"""

from urllib.parse import quote

IMPORT_APP_NAMES: dict[str, str] = {
    "cj": "CJ Dropshipping",
    "dsers": "DSers",
    "zendrop": "Zendrop",
    "autods": "AutoDS",
    "printify": "Printify",
    "printful": "Printful",
    "manual": "your import app",
    "other": "your import app",
}

# Base URLs; a trailing "=" means "append the URL-encoded search phrase".
IMPORT_APP_URLS: dict[str, str] = {
    "cj": "https://cjdropshipping.com/product/search?query=",
    "dsers": "https://www.dsers.com",
    "zendrop": "https://app.zendrop.com",
    "autods": "https://www.autods.com",
    "printify": "https://printify.com/app/products/search?query=",
    "printful": "https://www.printful.com",
    "manual": "",
    "other": "",
}


def import_app_name(app: str) -> str:
    return IMPORT_APP_NAMES.get(app, "your import app")


def import_app_link(app: str, query: str = "") -> str:
    """Deep link for the chosen import app; '' when there is no public link."""
    base = IMPORT_APP_URLS.get(app, "")
    if not base:
        return ""
    if base.endswith("=") and query:
        return base + quote(query)
    return base
