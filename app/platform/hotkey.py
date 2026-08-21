"""Platform-neutral parsing and normalization for simple global shortcuts."""

from __future__ import annotations

from dataclasses import dataclass

SUPPORTED_MODIFIERS = ("Ctrl", "Alt", "Shift")
DEFAULT_SHORTCUT = "Ctrl+Shift+Q"
_SUPPORTED_KEYS = {
    *"ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    *"0123456789",
    *(f"F{number}" for number in range(1, 13)),
}


class HotkeySpecError(ValueError):
    """Raised when a shortcut is outside the supported simple format."""


@dataclass(frozen=True)
class HotkeySpec:
    modifiers: frozenset[str]
    key: str

    @classmethod
    def parse(cls, value: str) -> "HotkeySpec":
        if not isinstance(value, str):
            raise HotkeySpecError("快捷键必须是文本")
        tokens = [token.strip() for token in value.split("+")]
        if not tokens or any(not token for token in tokens):
            raise HotkeySpecError("快捷键格式无效")

        modifiers: set[str] = set()
        keys: list[str] = []
        modifier_lookup = {modifier.lower(): modifier for modifier in SUPPORTED_MODIFIERS}
        for token in tokens:
            canonical_modifier = modifier_lookup.get(token.lower())
            if canonical_modifier is not None:
                if canonical_modifier in modifiers:
                    raise HotkeySpecError("快捷键不能重复修饰键")
                modifiers.add(canonical_modifier)
                continue
            keys.append(token.upper())

        if not modifiers:
            raise HotkeySpecError("快捷键至少需要一个修饰键")
        if len(keys) != 1 or keys[0] not in _SUPPORTED_KEYS:
            raise HotkeySpecError("快捷键只支持 A-Z、0-9 和 F1-F12")
        return cls(frozenset(modifiers), keys[0])

    @property
    def canonical(self) -> str:
        ordered_modifiers = [
            modifier for modifier in SUPPORTED_MODIFIERS if modifier in self.modifiers
        ]
        return "+".join([*ordered_modifiers, self.key])
