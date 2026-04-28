"""Serializable screen graph for discovered app states."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from core.autobuilder.schemas import validate_schema
from core.autobuilder.util import clean_list, slugify


@dataclass(frozen=True)
class ScreenNode:
    screen_id: str
    hash: str
    type: str = "unknown"
    texts: list[str] = field(default_factory=list)
    elements: list[str] = field(default_factory=list)
    safe_actions: list[str] = field(default_factory=list)
    risky_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ScreenTransition:
    from_screen: str
    action: str
    to_screen: str

    def to_dict(self) -> dict[str, Any]:
        return {"from": self.from_screen, "action": self.action, "to": self.to_screen}


class ScreenGraph:
    def __init__(self, screens: list[ScreenNode] | None = None, transitions: list[ScreenTransition] | None = None):
        self.screens: dict[str, ScreenNode] = {screen.screen_id: screen for screen in screens or []}
        self.transitions: list[ScreenTransition] = list(transitions or [])

    def add_screen(
        self,
        *,
        screen_id: str = "",
        screen_hash: str = "",
        screen_type: str = "unknown",
        texts: list[str] | None = None,
        elements: list[str] | None = None,
        safe_actions: list[str] | None = None,
        risky_actions: list[str] | None = None,
    ) -> ScreenNode:
        screen_id = slugify(screen_id or screen_type or screen_hash, "screen")
        node = ScreenNode(
            screen_id=screen_id,
            hash=screen_hash or screen_id,
            type=screen_type or "unknown",
            texts=clean_list(texts),
            elements=clean_list(elements),
            safe_actions=clean_list(safe_actions),
            risky_actions=clean_list(risky_actions),
        )
        self.screens[screen_id] = node
        return node

    def add_transition(self, from_screen: str, action: str, to_screen: str) -> ScreenTransition:
        transition = ScreenTransition(from_screen=from_screen, action=action, to_screen=to_screen)
        if transition not in self.transitions:
            self.transitions.append(transition)
        return transition

    def outgoing(self, screen_id: str) -> list[ScreenTransition]:
        return [transition for transition in self.transitions if transition.from_screen == screen_id]

    def get(self, screen_id: str) -> ScreenNode | None:
        return self.screens.get(screen_id)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "screens": [screen.to_dict() for screen in self.screens.values()],
            "transitions": [transition.to_dict() for transition in self.transitions],
        }
        validate_schema("screen_graph", payload)
        return payload

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "ScreenGraph":
        validate_schema("screen_graph", payload)
        screens = [
            ScreenNode(
                screen_id=str(item.get("screen_id") or item.get("id") or ""),
                hash=str(item.get("hash") or ""),
                type=str(item.get("type") or "unknown"),
                texts=clean_list(item.get("texts")),
                elements=clean_list(item.get("elements")),
                safe_actions=clean_list(item.get("safe_actions") or item.get("safeActions")),
                risky_actions=clean_list(item.get("risky_actions") or item.get("riskyActions")),
            )
            for item in payload.get("screens", [])
            if isinstance(item, dict)
        ]
        transitions = [
            ScreenTransition(
                from_screen=str(item.get("from") or item.get("from_screen") or ""),
                action=str(item.get("action") or ""),
                to_screen=str(item.get("to") or item.get("to_screen") or ""),
            )
            for item in payload.get("transitions", [])
            if isinstance(item, dict)
        ]
        return cls(screens=screens, transitions=transitions)
