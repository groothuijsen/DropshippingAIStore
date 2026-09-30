"""Field guards — prevents writing to locked product fields.

See docs/06-dropship-integrations.md §3.
The client layer enforces this: assert_writable raises LockedFieldError
before every product mutation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.core.models import Shop


class LockedFieldError(Exception):
    """Raised when code attempts to write to a locked product field."""

    def __init__(self, fields: list[str], product_gid: str):
        self.fields = fields
        self.product_gid = product_gid
        super().__init__(
            f"Cannot write to locked fields {fields} on product {product_gid}. "
            "Mosaiq only writes content to its own metaobjects/metafields on "
            "products it did not create."
        )


def assert_writable(shop: Shop, product_gid: str, fields: set[str]) -> None:
    """Verify that all given fields are writable for this product.

    Raises LockedFieldError if any field is locked.
    """
    from .models import ProductSource
    from .rules import ALWAYS_WRITABLE_FIELDS, get_locked_fields

    # Check if Mosaiq created this product
    ps = ProductSource.objects.filter(shop=shop, product_gid=product_gid).first()

    if ps and ps.created_by_mosaiq:
        # Fully editable — Mosaiq created it
        return

    # Determine locked fields
    locked = set(ps.locked_fields) if ps else set(get_locked_fields("unknown_app"))

    # Fields always writable
    writable = set(ALWAYS_WRITABLE_FIELDS)
    locked -= writable

    # Check requested fields
    forbidden = fields & locked
    if forbidden:
        raise LockedFieldError(sorted(forbidden), product_gid)
