"""Safety policy for generated autopilots and builder actions."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from core.autobuilder.schemas import validate_schema
from core.autobuilder.util import clean_list


BLOCK_KEYWORDS = {
    "purchase": ("purchase", "buy", "pay", "billing", "subscribe", "оплат", "купить", "покуп"),
    "bypass_anticheat": ("anti-cheat", "anticheat", "stealth", "bypass", "обход"),
    "captcha": ("captcha", "капч"),
    "mass_registration": ("mass registration", "bulk account", "массов"),
    "multiplayer": ("pvp", "multiplayer", "online match", "ranked"),
}
REVIEW_KEYWORDS = {
    "login": ("login", "sign in", "account", "google", "парол", "аккаунт"),
    "permission": ("permission", "разреш", "contacts", "sms", "location"),
    "install": ("install", "apk", "download", "установ"),
}


@dataclass(frozen=True)
class SafetyDecision:
    allowed: bool
    reason: str
    required_review: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SafetyPolicy:
    allowed_scope: list[str] = field(default_factory=lambda: [
        "qa_automation",
        "onboarding_testing",
        "ui_testing",
        "visual_regression",
        "single_player_local_gameplay",
    ])
    forbidden_actions: list[str] = field(default_factory=lambda: [
        "purchase",
        "bypass_anticheat",
        "captcha",
        "mass_registration",
        "stealth",
        "multiplayer",
    ])
    review_required_actions: list[str] = field(default_factory=lambda: [
        "login",
        "install",
        "reset_data",
        "permission",
        "account_data_mutation",
    ])
    allow_network_downloads: bool = False
    allow_real_login: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        validate_schema("safety_policy", data)
        return data

    @classmethod
    def from_goal(cls, goal: Any) -> "SafetyPolicy":
        forbidden = set(getattr(goal, "forbidden_actions", []) or [])
        return cls(forbidden_actions=sorted(set(cls().forbidden_actions) | forbidden))

    def check_action(self, action: dict[str, Any] | str) -> SafetyDecision:
        text = _action_text(action)
        lowered = text.lower()
        for action_name in self.forbidden_actions:
            keywords = BLOCK_KEYWORDS.get(action_name, (action_name,))
            if any(keyword in lowered for keyword in keywords):
                return SafetyDecision(False, f"Forbidden action: {action_name}", True)
        if not self.allow_network_downloads and any(word in lowered for word in ("http://", "https://", "download apk")):
            return SafetyDecision(False, "Network downloads require allowlist or user-provided artifact", True)
        for action_name in self.review_required_actions:
            keywords = REVIEW_KEYWORDS.get(action_name, (action_name,))
            if any(keyword in lowered for keyword in keywords):
                if action_name == "login" and self.allow_real_login:
                    continue
                return SafetyDecision(True, f"Review required: {action_name}", True)
        return SafetyDecision(True, "allowed", False)

    def filter_safe_actions(self, actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [action for action in actions if self.check_action(action).allowed and not self.check_action(action).required_review]


def safety_policy_from_mapping(data: dict[str, Any]) -> SafetyPolicy:
    return SafetyPolicy(
        allowed_scope=clean_list(data.get("allowed_scope") or data.get("allowedScope")) or SafetyPolicy().allowed_scope,
        forbidden_actions=clean_list(data.get("forbidden_actions") or data.get("forbiddenActions")) or SafetyPolicy().forbidden_actions,
        review_required_actions=clean_list(data.get("review_required_actions") or data.get("reviewRequiredActions")) or SafetyPolicy().review_required_actions,
        allow_network_downloads=bool(data.get("allow_network_downloads", data.get("allowNetworkDownloads", False))),
        allow_real_login=bool(data.get("allow_real_login", data.get("allowRealLogin", False))),
    )


def _action_text(action: dict[str, Any] | str) -> str:
    if isinstance(action, dict):
        return " ".join(str(value) for value in action.values())
    return str(action or "")
