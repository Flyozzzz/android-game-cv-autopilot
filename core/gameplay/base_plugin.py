"""Shared gameplay plugin result models."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GameplayAction:
    gesture: str
    reason: str
    cooldown_key: str = ""
    confidence: float = 0.0

    @property
    def is_noop(self) -> bool:
        return self.gesture == "none"
