"""Withdrawal labels — per store language (07 §8.2).

The merchant cannot modify the labels in the MVP (prevents errors).
The confirmation button carries ONLY these words (directive).
"""

# Labels per language: (link_label, confirm_label)
WITHDRAWAL_LABELS: dict[str, tuple[str, str]] = {
    "nl": ("Hier de overeenkomst ontbinden", "Ontbinding bevestigen"),
    "de": ("Vertrag widerrufen", "Widerruf bestätigen"),
    "en": ("Withdraw from contract here", "Confirm withdrawal"),
}

DEFAULT_LOCALE = "en"


def get_withdrawal_labels(locale: str) -> tuple[str, str]:
    """Get (link_label, confirm_label) for a store language.

    Falls back to English for unsupported languages.
    """
    return WITHDRAWAL_LABELS.get(locale, WITHDRAWAL_LABELS[DEFAULT_LOCALE])


def get_all_labels() -> dict[str, dict[str, str]]:
    """Get all labels as a dict for the withdrawal metafield."""
    result = {}
    for lang, (link, confirm) in WITHDRAWAL_LABELS.items():
        result[lang] = {"link": link, "confirm": confirm}
    return result
