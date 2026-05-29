"""Encrypted-at-rest access token handling."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.broker.exceptions import KiteConfigError, KiteSessionError


class TokenCipher:
    """Encrypt and decrypt Kite access tokens with a configured Fernet key."""

    def __init__(self, encryption_key: str) -> None:
        if not encryption_key:
            raise KiteConfigError("Kite session encryption key is not configured.")
        try:
            self._fernet = Fernet(encryption_key.encode("utf-8"))
        except Exception as exc:
            raise KiteConfigError("Kite session encryption key is invalid.") from exc

    @staticmethod
    def generate_key() -> str:
        """Generate a URL-safe key for operator provisioning."""
        return Fernet.generate_key().decode("utf-8")

    def encrypt(self, plaintext_token: str) -> str:
        """Encrypt an access token for storage."""
        if not plaintext_token:
            raise KiteSessionError("Cannot encrypt an empty Kite access token.")
        return self._fernet.encrypt(plaintext_token.encode("utf-8")).decode("utf-8")

    def decrypt(self, encrypted_token: str) -> str:
        """Decrypt an access token for internal broker-session operations."""
        if not encrypted_token:
            raise KiteSessionError("No encrypted Kite access token is available.")
        try:
            return self._fernet.decrypt(encrypted_token.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise KiteSessionError("Stored Kite access token could not be decrypted.") from exc
