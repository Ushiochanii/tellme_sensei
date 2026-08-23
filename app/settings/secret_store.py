"""OS-backed storage for named application secrets."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

SERVICE_NAME = "tellme-sensei"
ACCOUNT_NAME = "default"
GOOGLE_VISION_ACCOUNT_NAME = "google-vision-api-key"


class SecretStoreError(RuntimeError):
    """Raised when the operating-system secret store cannot be written."""


class SecretStore:
    """Small keyring adapter with separate named accounts."""

    def __init__(
        self,
        keyring_module: Any | None = None,
        service_name: str = SERVICE_NAME,
        account_name: str = ACCOUNT_NAME,
    ) -> None:
        self._keyring = keyring_module
        self.service_name = service_name
        self.account_name = account_name

    def _backend(self) -> Any:
        if self._keyring is None:
            try:
                import keyring
            except ImportError as exc:
                raise SecretStoreError("keyring is not installed") from exc
            self._keyring = keyring
        return self._keyring

    def get_api_key(self) -> str:
        """Return the legacy DeepSeek key from tellme-sensei/default."""

        return self.get_secret(self.account_name)

    def get_google_vision_api_key(self) -> str:
        """Return the separately stored Google Vision key."""

        return self.get_secret(GOOGLE_VISION_ACCOUNT_NAME)

    def get_secret(self, account_name: str) -> str:
        try:
            value = self._backend().get_password(self.service_name, account_name)
        except Exception as exc:  # keyring backends vary by operating system.
            logger.warning(
                "secret store unavailable; continuing without stored secret: %s",
                type(exc).__name__,
            )
            return ""
        return value.strip() if isinstance(value, str) else ""

    def set_api_key(self, value: str) -> None:
        """Store the legacy DeepSeek key without changing its account name."""

        self.set_secret(self.account_name, value)

    def set_google_vision_api_key(self, value: str) -> None:
        self.set_secret(GOOGLE_VISION_ACCOUNT_NAME, value)

    def set_secret(self, account_name: str, value: str) -> None:
        value = value.strip()
        if not value:
            raise SecretStoreError("API key cannot be empty")
        try:
            self._backend().set_password(self.service_name, account_name, value)
        except Exception as exc:
            raise SecretStoreError("Unable to save API key in the system credential store") from exc
        logger.info("secret updated account=%s", account_name)

    def delete_api_key(self) -> None:
        """Delete only the legacy DeepSeek account."""

        self.delete_secret(self.account_name)

    def delete_google_vision_api_key(self) -> None:
        self.delete_secret(GOOGLE_VISION_ACCOUNT_NAME)

    def delete_secret(self, account_name: str) -> None:
        try:
            self._backend().delete_password(self.service_name, account_name)
        except Exception as exc:
            name = type(exc).__name__.lower()
            if "password" not in name and "credential" not in name:
                raise SecretStoreError("Unable to delete the system credential") from exc
