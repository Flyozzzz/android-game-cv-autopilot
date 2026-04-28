"""Budget limits for builder, exploration, LLM, repair, and runtime loops."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any


@dataclass(frozen=True)
class BuilderBudgets:
    max_build_steps: int = 100
    max_exploration_depth: int = 5
    max_actions_per_screen: int = 3
    max_llm_calls_per_build: int = 12
    max_llm_calls_per_screen: int = 2
    max_repair_attempts_per_run: int = 2
    max_runtime_minutes: int = 5
    max_unknown_screens: int = 5
    max_patch_size: int = 8

    def to_dict(self) -> dict[str, int]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "BuilderBudgets":
        data = data or {}
        values = {}
        for field in cls.__dataclass_fields__:
            raw = data.get(field, data.get(_camel(field), getattr(cls(), field)))
            values[field] = _positive_int(raw, getattr(cls(), field))
        return cls(**values)

    @classmethod
    def from_prompt(cls, prompt: str) -> "BuilderBudgets":
        text = str(prompt or "").lower()
        data: dict[str, int] = {}
        for field in cls.__dataclass_fields__:
            pattern = re.escape(field).replace("_", r"[_ -]?")
            if match := re.search(rf"{pattern}\s*[:= ]\s*(\d+)", text):
                data[field] = int(match.group(1))
        if match := re.search(r"(\d+)\s*(?:seconds|сек|секунд)", text):
            seconds = int(match.group(1))
            data["max_runtime_minutes"] = max(1, min(60, (seconds + 59) // 60))
        if match := re.search(r"(?:max[_ -]?steps|шаг(?:ов|а)?)\D+(\d+)", text):
            data["max_build_steps"] = int(match.group(1))
        if match := re.search(r"(?:depth|глубин[аы])\D+(\d+)", text):
            data["max_exploration_depth"] = int(match.group(1))
        return cls.from_mapping(data)


class BudgetCounter:
    """Small explicit counter that fails closed when a budget is exhausted."""

    def __init__(self, budgets: BuilderBudgets):
        self.budgets = budgets
        self.counts: dict[str, int] = {}

    def consume(self, name: str, amount: int = 1) -> None:
        limit = getattr(self.budgets, name)
        current = self.counts.get(name, 0) + int(amount)
        if current > limit:
            raise RuntimeError(f"budget exhausted: {name} ({current}>{limit})")
        self.counts[name] = current

    def snapshot(self) -> dict[str, int]:
        return dict(self.counts)


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = int(default)
    return max(1, parsed)


def _camel(field: str) -> str:
    first, *rest = field.split("_")
    return first + "".join(part[:1].upper() + part[1:] for part in rest)
