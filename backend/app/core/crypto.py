"""Authenticated encryption for third-party tokens at rest (Module 20: GitHub access tokens).

AES-256-GCM with a random 96-bit nonce per value. The ciphertext is bound to its owner through the
associated data (for example the user id), so a stored value copied to another user's row does not
decrypt. Stored form: ``v1.<key id>.<base64url(nonce + ciphertext + tag)>``; the key id (the first
8 bytes of SHA-256 of the key, hex) says which key encrypted it.

Key rotation: set the new key as CODEWALK_TOKEN_ENCRYPTION_KEY and move the old one to
CODEWALK_TOKEN_ENCRYPTION_OLD_KEYS. Values encrypted with an old key still decrypt, and
``needs_rotation`` tells the caller to store them again under the current key.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import Settings, decode_encryption_key

VERSION = "v1"
NONCE_BYTES = 12


class TokenDecryptionError(Exception):
    """The value is corrupt, was encrypted with an unknown key, or belongs to another owner."""


def key_id(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest()[:16]


class TokenCipher:
    def __init__(self, current: bytes, previous: list[bytes] | None = None) -> None:
        self.current_id = key_id(current)
        self._keys = {key_id(key): AESGCM(key) for key in [*(previous or []), current]}

    @classmethod
    def from_settings(cls, settings: Settings) -> TokenCipher | None:
        if settings.token_encryption_key is None:
            return None
        current = decode_encryption_key(settings.token_encryption_key.get_secret_value())
        if current is None:  # rejected by Settings already
            return None
        old = (
            settings.token_encryption_old_keys.get_secret_value()
            if settings.token_encryption_old_keys
            else ""
        )
        previous = [key for key in (decode_encryption_key(v) for v in old.split(",") if v.strip()) if key]
        return cls(current, previous)

    def encrypt(self, plaintext: str, *, associated_data: str) -> str:
        nonce = os.urandom(NONCE_BYTES)
        sealed = self._keys[self.current_id].encrypt(
            nonce, plaintext.encode("utf-8"), associated_data.encode()
        )
        payload = base64.urlsafe_b64encode(nonce + sealed).decode().rstrip("=")
        return f"{VERSION}.{self.current_id}.{payload}"

    def decrypt(self, stored: str, *, associated_data: str) -> str:
        try:
            version, kid, payload = stored.split(".", 2)
            raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        except (ValueError, binascii.Error):
            raise TokenDecryptionError() from None
        aead = self._keys.get(kid)
        if version != VERSION or aead is None or len(raw) <= NONCE_BYTES:
            raise TokenDecryptionError()
        try:
            return aead.decrypt(raw[:NONCE_BYTES], raw[NONCE_BYTES:], associated_data.encode()).decode(
                "utf-8"
            )
        except (InvalidTag, UnicodeDecodeError):
            raise TokenDecryptionError() from None

    def needs_rotation(self, stored: str) -> bool:
        parts = stored.split(".", 2)
        return len(parts) != 3 or parts[1] != self.current_id
