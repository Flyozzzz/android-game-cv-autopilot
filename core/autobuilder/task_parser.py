"""Prompt-to-GoalSpec parser for the autopilot builder."""
from __future__ import annotations

import re

from core.autobuilder.budgets import BuilderBudgets
from core.autobuilder.goal_spec import GoalSpec
from core.game_profiles import list_game_profiles


DEFAULT_ALLOWED = ["install", "launch", "tap", "swipe", "wait", "analyze"]
DEFAULT_FORBIDDEN = ["purchase", "real_login", "subscribe", "bypass_anticheat", "captcha", "mass_registration"]


def parse_goal_prompt(prompt: str, *, mode: str = "create", package: str = "") -> GoalSpec:
    text = str(prompt or "").strip()
    app_name = _extract_app_name(text)
    profile = _matching_profile(app_name, text)
    if profile is not None:
        app_name = profile.name
        package = package or profile.package
    strategy = _infer_strategy(text, app_name, profile.gameplay_strategy if profile else "")
    forbidden = _forbidden_from_prompt(text)
    allowed = [action for action in DEFAULT_ALLOWED if action not in forbidden]
    return GoalSpec(
        app_name=app_name,
        goal=_extract_goal(text, app_name),
        mode=mode,
        allowed_actions=allowed,
        forbidden_actions=forbidden,
        runtime_strategy=strategy,
        budgets=BuilderBudgets.from_prompt(text),
        requires_human_review=True,
        package=package,
    )


def _extract_app_name(text: str) -> str:
    patterns = [
        r"(?:for|для)\s+([A-ZА-ЯЁ0-9][^\n.]{2,60})(?:[.\n]|$)",
        r"(?:app|game|игр[уы]|приложени[ея])[: ]+([A-ZА-ЯЁ0-9][^\n.]{2,60})(?:[.\n]|$)",
        r"(?:Создай|create|build)\s+.*?(?:для|for)\s+([A-ZА-ЯЁ0-9][^\n.]{2,60})(?:[.\n]|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip(" .")
    for profile in list_game_profiles():
        if any(_selector_matches(selector, text) for selector in profile.selectors):
            return profile.name
    return "Custom App"


def _extract_goal(text: str, app_name: str) -> str:
    if not text:
        return f"Build autopilot for {app_name}"
    return text[:500]


def _matching_profile(app_name: str, text: str):
    haystack = f"{app_name} {text}".lower()
    for profile in list_game_profiles():
        if any(_selector_matches(selector, haystack) for selector in profile.selectors):
            return profile
    return None


def _selector_matches(selector: str, text: str) -> bool:
    selector = str(selector or "").strip().lower()
    if not selector:
        return False
    if len(selector) <= 3:
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(selector)}(?![a-z0-9])", text.lower()))
    return selector in text.lower()


def _infer_strategy(text: str, app_name: str, profile_strategy: str = "") -> str:
    haystack = f"{text} {app_name} {profile_strategy}".lower()
    if any(word in haystack for word in ("runner", "subway", "surfers", "temple run", "lane", "survive")):
        return "runner"
    if any(word in haystack for word in ("match-3", "match3", "candy", "crush", "swap")):
        return "match3"
    if any(word in haystack for word in ("menu", "tutorial", "onboarding", "settings", "настрой")):
        return "menu"
    return "generic_app"


def _forbidden_from_prompt(text: str) -> list[str]:
    forbidden = list(DEFAULT_FORBIDDEN)
    lowered = text.lower()
    if "no login" in lowered or "не логин" in lowered or "без логин" in lowered:
        forbidden.append("login")
    if "no multiplayer" in lowered or "без multiplayer" in lowered:
        forbidden.append("multiplayer")
    if "no purchases" in lowered or "без покуп" in lowered or "не делать покупки" in lowered:
        forbidden.append("purchase")
    return sorted(set(forbidden))
