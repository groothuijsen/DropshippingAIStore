"""Brand-name blocklist for the start-from-zero wizard (F15-4, 07 §4.1).

Three layers, all substring matches on the lowercased name:
1. GEO_ORIGINS — geographic origin words (never true unless the brief says so).
2. BRAND_BLOCKLIST — well-known consumer brands (start with a solid list;
   maintained as data — extend as new collisions appear).
3. Generic claims — reused from compliance.claims.BLOCKLIST (severity "block",
   all locales), flattened to substrings: "eco", "green", "sustainable",
   health promises, fake urgency, etc.

Returns a reason string (for the merchant message) or None when the name
passes.
"""

from __future__ import annotations

from apps.compliance.claims import BLOCKLIST

GEO_ORIGINS: tuple[str, ...] = (
    "swiss",
    "dutch",
    "holland",
    "france",
    "french",
    "german",
    "deutsch",
    "italy",
    "italian",
    "japan",
    "japanese",
    "america",
    "american",
    "england",
    "english",
    "british",
    "scandinavian",
    "nordic",
    "european",
    "korea",
    "korean",
    "china",
    "chinese",
    "oslo",
    "berlin",
    "paris",
    "london",
    "amsterdam",
)

# Well-known consumer brands (lowercase, no spaces). Start of the top-500
# list per 07 §4.1; maintained as data.
BRAND_BLOCKLIST: frozenset[str] = frozenset(
    {
        "nike", "adidas", "puma", "reebok", "newbalance", "asics", "underarmour",
        "apple", "samsung", "sony", "xiaomi", "huawei", "google", "microsoft",
        "amazon", "ebay", "alibaba", "tesla", "bmw", "mercedes", "audi", "volkswagen",
        "toyota", "honda", "ford", "volvo", "porsche", "ferrari", "lamborghini",
        "coca cola", "pepsi", "nestle", "unilever", "philips", "ikea", "lego",
        "disney", "netflix", "spotify", "airbnb", "uber", "booking",
        "zara", "h&m", "uniqlo", "gucci", "prada", "louis vuitton", "chanel",
        "hermes", "rolex", "omega", "seiko", "casio", "fossil",
        "dell", "hp", "lenovo", "asus", "acer", "nvidia", "intel", "amd",
        "nintendo", "playstation", "xbox", "sega", "atari",
        "mcdonalds", "burger king", "kfc", "starbucks", "dunkin",
        "heineken", "budweiser", "corona", "guinness", "jägermeister",
        "johnson", "colgate", "pampers", "gillette", "nivea", "loreal",
        "maybelline", "revlon", "dove", "olds spice", "axe",
        "bol", "coolblue", "zalando", "hema", "action", "kruidvat",
        "aliexpress", "wish", "temu", "shein", "asos", "boohoo",
        "gopro", "dji", "insta364", "roborock", "dyson", "shark",
        "garmin", "fitbit", "withings", "oura", "whoop",
        "anbernic", "retroid", "ayn", "rpi", "raspberrypi", "arduino",
        "gymshark", "lululemon", "decathlon", "salomon", "merrell",
        "blackdecker", "bosch", "makita", "dewalt", "hilti",
    }
)

# Flatten generic-claim substrings from the compliance blocklist (severity
# "block", every locale) — e.g. "eco", "green", "sustainable", "cures".
def _generic_claim_terms() -> frozenset[str]:
    terms: set[str] = set()
    for rule in BLOCKLIST.values():
        if rule.get("severity") != "block":
            continue
        for patterns in rule.get("patterns", {}).values():
            for pattern in patterns:
                terms.add(pattern.lower())
    return frozenset(terms)


GENERIC_CLAIM_TERMS: frozenset[str] = _generic_claim_terms()


def is_blocked_brand(name: str) -> str | None:
    """Return a rejection reason when the name must not be used, else None."""
    lowered = (name or "").strip().lower()
    if not lowered:
        return "Name is empty"

    for brand in BRAND_BLOCKLIST:
        # Short brand names match exactly; longer ones as substrings too
        # (e.g. "Nike" must block "Nikeshop").
        if lowered == brand or (len(brand) >= 4 and brand in lowered):
            return f"Looks like the existing brand '{brand.title()}'"

    for origin in GEO_ORIGINS:
        if origin in lowered:
            return f"Contains a geographic origin word ('{origin.title()}') that is likely not true"

    for term in GENERIC_CLAIM_TERMS:
        if len(term) >= 3 and term in lowered:
            return f"Contains a generic claim term ('{term.title()}')"

    return None
