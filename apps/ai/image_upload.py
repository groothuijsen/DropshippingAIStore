"""Image upload — staged upload + fileCreate + wait until READY.

See docs/05-ai-pipeline.md §4.4, docs/specs/F04-images.md criterion 5.
Upload via staged_uploads_create → file_create; wait until READY (max 60 s);
timeout → skip slot with error log.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

from apps.core.shopify_client import ShopifyGraphQLClient, load_query

if TYPE_CHECKING:
    from apps.core.models import Shop

logger = logging.getLogger(__name__)

# Max wait for file to become READY (04 criterion 5)
MAX_READY_WAIT_SECONDS = 60
READY_POLL_INTERVAL = 2


@dataclass
class UploadedImage:
    """Result of a successful image upload."""

    file_gid: str
    status: str = "READY"
    alt: str = ""


@dataclass
class UploadResult:
    """Result of the upload flow."""

    success: bool
    file_gid: str = ""
    error: str = ""


def build_alt_text(description: str, locale: str = "en") -> str:
    """Build alt text in content language, max 125 characters (04 criterion 6).

    Truncates at word boundary if needed.
    """
    if not description:
        return ""

    alt = description.strip()
    if len(alt) <= 125:
        return alt

    # Truncate at word boundary
    truncated = alt[:125]
    last_space = truncated.rfind(" ")
    if last_space > 0:
        truncated = truncated[:last_space]

    return truncated.rstrip()


def _get_client(shop: Shop) -> ShopifyGraphQLClient:
    """Get a ShopifyGraphQLClient for the shop."""
    from apps.core.crypto import decrypt_token

    token = decrypt_token(shop.access_token_encrypted)
    return ShopifyGraphQLClient(
        shop_domain=shop.domain,
        access_token=token,
        api_version="2026-07",
    )


def upload_image(
    shop: Shop,
    image_bytes: bytes,
    filename: str,
    alt: str = "",
) -> UploadResult:
    """Upload an image via staged upload + fileCreate.

    See docs/05-ai-pipeline.md §4.4.

    Args:
        shop: Shop instance
        image_bytes: Image content
        filename: Filename for the upload
        alt: Alt text (max 125 chars)

    Returns:
        UploadResult with file_gid on success
    """
    client = _get_client(shop)
    try:
        # Step 1: staged_uploads_create
        staged_data = client.execute(
            load_query("staged_uploads_create"),
            variables={
                "input": {
                    "filename": filename,
                    "resource": "IMAGE",
                    "httpMethod": "POST",
                    "parameters": [{"name": "key", "value": filename}],
                }
            },
        )

        staged = staged_data.get("stagedUploadsCreate", {})
        targets = staged.get("stagedTargets", [])
        if not targets:
            error = staged.get("userErrors", [{}])[0].get("message", "No staged targets")
            return UploadResult(success=False, error=error)

        target = targets[0]
        upload_url = target["url"]
        resource_url = target["resourceUrl"]
        parameters = target.get("parameters", [])

        # Step 2: Upload to staged URL
        form_data = {p["name"]: p["value"] for p in parameters}
        form_data["file"] = (filename, image_bytes, "image/png")

        with httpx.Client(timeout=30.0) as http_client:
            resp = http_client.post(upload_url, files=form_data)
            if resp.status_code not in (200, 204):
                return UploadResult(
                    success=False,
                    error=f"Upload failed: HTTP {resp.status_code}",
                )

        # Step 3: fileCreate
        file_data = client.execute(
            load_query("file_create"),
            variables={
                "files": [
                    {
                        "originalSource": resource_url,
                        "filename": filename,
                        "alt": alt[:125] if alt else None,
                    }
                ]
            },
        )

        files = file_data.get("fileCreate", {}).get("files", [])
        if not files:
            error = file_data.get("fileCreate", {}).get("userErrors", [{}])[0].get("message", "No files created")
            return UploadResult(success=False, error=error)

        file_gid = files[0]["id"]
        status = files[0].get("status", "UPLOADING")

        # Step 4: Wait until READY
        if status != "READY":
            ready = _wait_until_ready(client, file_gid)
            if not ready:
                logger.warning("File %s did not become READY within %ds — skipping", file_gid, MAX_READY_WAIT_SECONDS)
                return UploadResult(
                    success=False,
                    file_gid=file_gid,
                    error=f"Timeout waiting for READY ({MAX_READY_WAIT_SECONDS}s)",
                )

        return UploadResult(success=True, file_gid=file_gid)

    except Exception as e:
        logger.warning("Image upload failed: %s", e)
        return UploadResult(success=False, error=str(e))

    finally:
        client.close()


def _wait_until_ready(client: ShopifyGraphQLClient, file_gid: str) -> bool:
    """Poll file status until READY or timeout."""
    deadline = time.monotonic() + MAX_READY_WAIT_SECONDS

    while time.monotonic() < deadline:
        try:
            data = client.execute(
                load_query("file_status"),
                variables={"id": file_gid},
            )
            status = data.get("file", {}).get("status", "")
            if status == "READY":
                return True
            if status in ("FAILED", "ERROR"):
                logger.warning("File %s status: %s", file_gid, status)
                return False
        except Exception as e:
            logger.warning("File status check failed: %s", e)

        time.sleep(READY_POLL_INTERVAL)

    return False
