"""Add 5 long-delivery evalset cases (T-142, F18-9, 10 §4)."""

import json
from pathlib import Path

PATH = Path("tests/evalset/eval_products.json")

CASES = [
    # (id, category, language, title, price, ship_from, min, max)
    ("eval-longdelivery-01", "wellness", "nl", "Ashwagandha KSM-66 Capsules 90st", "27.95", "CN", 10, 20),
    ("eval-longdelivery-02", "car_accessories", "de", "Karbonspoiler Universal schwarz", "189.00", "CN", 12, 25),
    ("eval-longdelivery-03", "pod_merch", "en", "Custom Logo Hoodie Heavyweight", "44.95", "CN", 9, 18),
    ("eval-longdelivery-04", "wellness", "en", "Red Light Therapy Belt 660nm", "129.00", "CN", 11, 22),
    ("eval-longdelivery-05", "car_accessories", "nl", "Dashcam 4K met Nachtzicht", "89.95", "CN", 10, 21),
]


def main() -> None:
    data = json.loads(PATH.read_text())
    existing = {p["id"] for p in data}
    for case_id, category, language, title, price, ship_from, dmin, dmax in CASES:
        if case_id in existing:
            continue
        data.append(
            {
                "id": case_id,
                "category": category,
                "language": language,
                "title": title,
                "description": f"Direct-from-supplier product ({category}).",
                "price": price,
                "currency": "EUR",
                "specs": {"Herkomst/Land": "China", "Levering": f"{dmin}-{dmax} werkdagen"},
                "vendor": "GlobalSupply",
                "tags": [category, "dropship"],
                "delivery_estimate": {"min_days": dmin, "max_days": dmax, "ship_from": ship_from},
            }
        )
    PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    long_cases = [p for p in data if (p.get("delivery_estimate") or {}).get("max_days", 0) > 10]
    print(f"total products: {len(data)}, long-delivery cases: {len(long_cases)}")


if __name__ == "__main__":
    main()
