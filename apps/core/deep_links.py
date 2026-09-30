"""Deep links to the Shopify theme editor.

See docs/03-shopify-integration.md §7.
The ID is the API key (client_id), not the extension UUID.
"""

from __future__ import annotations


def get_add_block_link(
    shop_domain: str,
    api_key: str,
    block_handle: str,
    template: str,
    target: str = "mainSection",
) -> str:
    """Generate a deep link to add an app block to the theme editor.

    Args:
        shop_domain: e.g. "mystore.myshopify.com"
        api_key: Shopify API key (client_id)
        block_handle: File name without .liquid (e.g. "mq-price")
        template: Template name (e.g. "product", "page", "index")
        target: "mainSection" for blocks in main section

    Returns:
        Deep link URL to open the theme editor with the block added.
    """
    return (
        f"https://{shop_domain}/admin/themes/current/editor"
        f"?template={template}"
        f"&addAppBlockId={api_key}/{block_handle}"
        f"&target={target}"
    )


def get_configure_embed_link(
    shop_domain: str,
    api_key: str,
    embed_handle: str,
) -> str:
    """Generate a deep link to configure an app embed in the theme editor.

    App embeds are configured in the Theme Editor under App embeds.
    """
    return (
        f"https://{shop_domain}/admin/themes/current/editor"
        f"?template=index"
        f"&addAppBlockId={api_key}/{embed_handle}"
        f"&target=body"
    )


# Block targets from 03 §7
BLOCK_TARGETS = {
    "mq-page-sections": "mainSection",
    "mq-price": "mainSection",
    "mq-bundle-picker": "mainSection",
    "mq-gpsr": "mainSection",
}

# Embed targets
EMBED_TARGETS = {
    "mq-tokens": "head",
    "mq-cart-drawer": "body",
    "mq-withdrawal-link": "body",
}
