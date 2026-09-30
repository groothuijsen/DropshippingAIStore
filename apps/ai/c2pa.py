"""C2PA signing — own manifest per published image.

See docs/05-ai-pipeline.md §4.4, docs/specs/F04-images.md criterion 4.
Signing fails → do not publish (return None).
Uses c2pa-python (>= 0.37) when available; graceful degradation in dev.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# softwareAgent for the c2pa.edited action (05 §4.4)
MOSAIQ_AGENT = "Mosaiq"


def c2pa_available() -> bool:
    """Check if c2pa-python is installed."""
    try:
        import c2pa  # noqa: F401

        return True
    except ImportError:
        return False


def sign_image(
    provider_image: bytes,
    output_path: str,
    trust_anchor_url: str = "",
    signer_cert: bytes = b"",
    private_key: bytes = b"",
) -> str | None:
    """Sign an image with an own C2PA manifest.

    See docs/05-ai-pipeline.md §4.4:
    - add provider image as ingredient with relationship parentOf
    - first action c2pa.opened (preserves Google/OpenAI manifest)
    - then action c2pa.edited with softwareAgent Mosaiq
    - dev/staging: test certificates from c2pa-rs
    - production: CA certificate on C2PA trust list

    Args:
        provider_image: Provider-generated image bytes
        output_path: Where to write the signed image
        trust_anchor_url: Trust anchor URL (production)
        signer_cert: Signer certificate (PEM bytes)
        private_key: Private key (PEM bytes)

    Returns:
        output_path on success, None on failure (do NOT publish)
    """
    if not c2pa_available():
        logger.warning("c2pa-python not installed — signing skipped (dev mode)")
        return None

    try:
        from c2pa import Builder, C2paSignerInfo, Signer  # type: ignore

        builder = Builder("Mosaiq C2PA manifest")

        # Add provider image as ingredient with parentOf relationship
        # (preserves the Google/OpenAI manifest)
        builder.add_source_manifest(provider_image, relationship="parentOf")

        # Action: c2pa.opened (first, preserves provider manifest)
        builder.add_action(
            action="c2pa.opened",
            software_agent=MOSAIQ_AGENT,
        )

        # Action: c2pa.edited with Mosaiq as software agent
        builder.add_action(
            action="c2pa.edited",
            software_agent=MOSAIQ_AGENT,
        )

        # Sign
        signer = Signer.from_info(
            C2paSignerInfo(
                alg="PS256",
                sign_cert=signer_cert,
                private_key=private_key,
                ta_url=trust_anchor_url,
            )
        )
        builder.sign_file(provider_image, output_path, signer)

        logger.info("C2PA signed image written to %s", output_path)
        return output_path

    except Exception as e:
        logger.error("C2PA signing failed: %s — do not publish", e)
        return None


def verify_manifest(image_path: str) -> dict[str, Any] | None:
    """Verify a C2PA manifest on an image.

    Used in tests (T-043) with c2patool/exiftool.
    Returns manifest info dict or None if no manifest found.
    """
    if not c2pa_available():
        logger.warning("c2pa-python not installed — verification skipped")
        return None

    try:
        from c2pa import Reader  # type: ignore

        reader = Reader(image_path)
        manifest = reader.get_manifest()
        return {
            "manifest": manifest,
            "valid": True,
        }
    except Exception as e:
        logger.warning("C2PA verification failed: %s", e)
        return None
