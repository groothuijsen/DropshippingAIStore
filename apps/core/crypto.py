"""Fernet encryption for Shopify tokens."""

from __future__ import annotations

from cryptography.fernet import Fernet, MultiFernet
from django.conf import settings


def _get_fernet() -> MultiFernet:
    """Return a MultiFernet from FERNET_KEYS. First key is active; others are for rotation."""
    keys = [k.strip() for k in settings.FERNET_KEYS if k.strip()]
    if not keys:
        raise RuntimeError("FERNET_KEYS is not configured")
    return MultiFernet([Fernet(k.encode()) for k in keys])


def encrypt_token(plaintext: str) -> bytes:
    """Encrypt a token string and return bytes suitable for BinaryField storage."""
    f = _get_fernet()
    return f.encrypt(plaintext.encode())


def decrypt_token(encrypted: bytes) -> str:
    """Decrypt stored token bytes back to a plaintext string."""
    f = _get_fernet()
    return f.decrypt(encrypted).decode()
