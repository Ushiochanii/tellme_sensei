"""OS-backed storage for named application secrets."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

SERVICE_NAME = "tellme-sensei"
ACCOUNT_NAME = "default"
GOOGLE_VISION_ACCOUNT_NAME = "google-vision-api-key"
QWEN_ACCOUNT_NAME = "qwen"
ZAI_ACCOUNT_NAME = "zai"
AI_PROVIDER_ACCOUNT_NAMES = {
    "deepseek": ACCOUNT_NAME,
    "qwen": QWEN_ACCOUNT_NAME,
    "zai": ZAI_ACCOUNT_NAME,
}


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

        return self.get_provider_api_key("deepseek")

    def get_provider_api_key(self, provider_id: str) -> str:
        """Return the key stored for one supported AI provider."""

        normalized = str(provider_id).strip().lower()
        account = self.account_name if normalized == "deepseek" else AI_PROVIDER_ACCOUNT_NAMES.get(normalized)
        if account is None:
            return ""
        return self.get_secret(account)

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

        self.set_provider_api_key("deepseek", value)

    def set_provider_api_key(self, provider_id: str, value: str) -> None:
        """Store one provider key in its named account."""

        normalized = str(provider_id).strip().lower()
        account = self.account_name if normalized == "deepseek" else AI_PROVIDER_ACCOUNT_NAMES.get(normalized)
        if account is None:
            raise SecretStoreError(f"Unsupported AI provider: {provider_id}")
        self.set_secret(account, value)

    def set_google_vision_api_key(self, value: str) -> None:
        self.set_secret(GOOGLE_VISION_ACCOUNT_NAME, value)

    def set_secret(self, account_name: str, value: str) -> None:
        value = value.strip()
        if not value:
            raise SecretStoreError("API key cannot be empty")
        try:
            self._backend().set_password(self.service_name, account_name, value)
        except Exception as exc:
            logger.warning(
                "secret store operation failed operation=set account=%s exception_type=%s",
                account_name,
                type(exc).__name__,
            )
            raise SecretStoreError("Unable to save API key in the system credential store") from exc
        logger.info("secret updated account=%s", account_name)

    def delete_api_key(self) -> None:
        """Delete only the legacy DeepSeek account."""

        self.delete_provider_api_key("deepseek")

    def delete_provider_api_key(self, provider_id: str) -> None:
        """Delete one provider key while leaving all other credentials intact."""

        normalized = str(provider_id).strip().lower()
        account = self.account_name if normalized == "deepseek" else AI_PROVIDER_ACCOUNT_NAMES.get(normalized)
        if account is None:
            raise SecretStoreError(f"Unsupported AI provider: {provider_id}")
        self.delete_secret(account)

    def delete_google_vision_api_key(self) -> None:
        self.delete_secret(GOOGLE_VISION_ACCOUNT_NAME)

    def delete_secret(self, account_name: str) -> None:
        try:
            self._backend().delete_password(self.service_name, account_name)
        except Exception as exc:
            name = type(exc).__name__.lower()
            logger.warning(
                "secret store operation failed operation=delete account=%s exception_type=%s",
                account_name,
                type(exc).__name__,
            )
            if "password" not in name and "credential" not in name:
                raise SecretStoreError("Unable to delete the system credential") from exc
