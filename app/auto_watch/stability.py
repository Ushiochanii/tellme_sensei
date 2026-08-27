from __future__ import annotations

from dataclasses import dataclass


@dataclass
class StabilityTracker:
    threshold: float = 0.015
    required: int = 3
    stable_count: int = 0

    def __post_init__(self) -> None:
        if self.threshold < 0 or self.required < 1:
            raise ValueError("threshold must be non-negative and required must be positive")

    def update(self, change_ratio: float) -> bool:
        if change_ratio <= self.threshold:
            self.stable_count += 1
        else:
            self.stable_count = 0
        return self.stable_count >= self.required

    def reset(self) -> None:
        self.stable_count = 0
