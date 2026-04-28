"""Generate reusable app/game profile JSON from exploration results."""
from __future__ import annotations

from typing import Any

from core.autobuilder.goal_spec import GoalSpec
from core.autobuilder.schemas import validate_schema
from core.game_profiles import COMMON_SCREEN_ZONES, MATCH3_SCREEN_ZONES, RUNNER_SCREEN_ZONES


FORBIDDEN_WORDS = ["buy", "purchase", "subscribe", "pay", "купить", "оплатить"]
SAFE_WORDS = ["play", "continue", "skip", "ok", "allow", "next"]


def generate_profile(goal: GoalSpec, screen_graph: Any, analysis: dict[str, Any] | None = None) -> dict[str, Any]:
    zones = _default_zones(goal.runtime_strategy)
    analysis = analysis or {}
    for element in analysis.get("safe_elements", []) if isinstance(analysis.get("safe_elements"), list) else []:
        roi = str(element.get("roi") or "")
        box = element.get("normalized_box") or element.get("normalizedBox")
        if roi and isinstance(box, (list, tuple)) and len(box) == 4:
            zones[roi] = [float(part) for part in box]
    profile = {
        "app_name": goal.app_name,
        "package": goal.package,
        "strategy": goal.runtime_strategy,
        "screen_zones": zones,
        "blocker_words": sorted(set(FORBIDDEN_WORDS + goal.forbidden_actions)),
        "safe_words": SAFE_WORDS,
        "forbidden_words": sorted(set(FORBIDDEN_WORDS + goal.forbidden_actions)),
        "runtime": {
            "fast_gameplay": "local_only",
            "menu": "local_first",
            "unknown_screen": "local_first",
        },
        "llm_policy": {
            "fast_gameplay": "forbidden",
            "fallback": "allowed_for_menu_unknown",
            "model": "xiaomi/mimo-v2.5",
        },
        "provider_priority": ["cache", "uiautomator", "template", "ocr", "detector", "llm"],
    }
    validate_schema("profile", profile)
    return profile


def _default_zones(strategy: str) -> dict[str, list[float]]:
    if strategy == "runner":
        source = RUNNER_SCREEN_ZONES
    elif strategy == "match3":
        source = MATCH3_SCREEN_ZONES
    else:
        source = {
            **COMMON_SCREEN_ZONES,
            "dialog_actions": (0.10, 0.62, 0.90, 0.94),
            "main_canvas": (0.0, 0.12, 1.0, 0.90),
        }
    return {name: [float(part) for part in box] for name, box in source.items()}
