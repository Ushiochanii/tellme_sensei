"""OS-backed storage for the DeepSeek API key."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

SERVICE_NAME = "tellme-sensei"
ACCOUNT_NAME = "default"


class SecretStoreError(RuntimeError):
    """Raised when the operating-system secret store cannot be written."""


class SecretStore:
    """Small keyring adapter with an injectable backend for tests."""

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
                raise SecretStoreError("未安装 keyring，无法使用系统凭据存储") from exc
            self._keyring = keyring
        return self._keyring

    def get_api_key(self) -> str:
        """Return the stored key, or empty when the store is unavailable."""

        try:
            value = self._backend().get_password(self.service_name, self.account_name)
        except Exception as exc:  # keyring backends vary by operating system.
            logger.warning(
                "secret store unavailable; continuing without stored API key: %s",
                type(exc).__name__,
            )
            return ""
        return value.strip() if isinstance(value, str) else ""

    def set_api_key(self, value: str) -> None:
        value = value.strip()
        if not value:
            raise SecretStoreError("API Key 不能为空")
        try:
            self._backend().set_password(self.service_name, self.account_name, value)
        except Exception as exc:
            raise SecretStoreError("无法保存 API Key，请检查系统凭据存储") from exc
        logger.info("API key updated")

    def delete_api_key(self) -> None:
        try:
            self._backend().delete_password(self.service_name, self.account_name)
        except Exception as exc:
            name = type(exc).__name__.lower()
            if "password" not in name and "credential" not in name:
                raise SecretStoreError("无法删除 API Key，请检查系统凭据存储") from exc
