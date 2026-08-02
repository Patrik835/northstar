import base64
import json
import os
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings


class CredentialCipher:
    _associated_data = b"northstar:broker-credentials:v1"

    def __init__(self, key: str | None = None) -> None:
        configured_key = key or get_settings().credential_encryption_key
        self._cipher = AESGCM(base64.urlsafe_b64decode(configured_key.encode()))

    def encrypt(self, credentials: dict[str, str]) -> bytes:
        nonce = os.urandom(12)
        plaintext = json.dumps(credentials, separators=(",", ":")).encode()
        return nonce + self._cipher.encrypt(nonce, plaintext, self._associated_data)

    def decrypt(self, payload: bytes) -> dict[str, Any]:
        nonce, ciphertext = payload[:12], payload[12:]
        plaintext = self._cipher.decrypt(nonce, ciphertext, self._associated_data)
        return json.loads(plaintext.decode())


def mask_secret(value: str) -> str:
    return f"••••{value[-4:]}" if len(value) >= 4 else "••••"
