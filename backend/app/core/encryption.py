"""Local symmetric encryption helpers for stored provider tokens."""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class TokenEncryptionError(RuntimeError):
    """Raised when token encryption or decryption fails."""


def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_secret(value: str) -> str:
    """Encrypt a secret string for local database storage."""
    if not value:
        raise TokenEncryptionError("Cannot encrypt an empty secret.")
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str) -> str:
    """Decrypt a secret string from local database storage."""
    try:
        return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise TokenEncryptionError("Stored secret could not be decrypted.") from exc
