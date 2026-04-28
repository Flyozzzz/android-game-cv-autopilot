"""Safe app explorer that records screens and transitions into ScreenGraph."""
from __future__ import annotations

import hashlib
from typing import Any, Awaitable, Callable

from core.autobuilder.context import BuildContext
from core.autobuilder.exploration_state import ExplorationState, ExplorationStep
from core.autobuilder.screen_graph import ScreenGraph
from core.frame_source import FrameSource


VisibleTextGetter = Callable[[], Awaitable[list[str]]]
ActionExecutor = Callable[[dict[str, Any]], Awaitable[str]]
CandidateFinder = Callable[[str], Awaitable[list[dict[str, Any]]]]


class Explorer:
    def __init__(
        self,
        *,
        frame_source: FrameSource,
        visible_texts: VisibleTextGetter | None = None,
        candidate_finder: CandidateFinder | None = None,
        action_executor: ActionExecutor | None = None,
    ):
        self.frame_source = frame_source
        self.visible_texts = visible_texts
        self.candidate_finder = candidate_finder
        self.action_executor = action_executor

    async def explore(self, context: BuildContext) -> tuple[BuildContext, ExplorationState]:
        counter = context.budget_counter
        graph = context.screen_graph or ScreenGraph()
        steps: list[ExplorationStep] = []
        failures: list[str] = []
        current_screen_id = ""
        depth = context.goal_spec.budgets.max_exploration_depth

        for index in range(depth):
            if counter:
                counter.consume("max_exploration_depth")
            frame = await self.frame_source.latest_frame()
            screen_hash = _hash_frame(frame.png_bytes or b"")
            texts = await self._visible_texts()
            candidates = await self._candidates(context.goal_spec.goal)
            safe_actions = _candidate_actions(candidates)
            risky_actions = [
                action["name"]
                for action in safe_actions
                if context.safety_policy.check_action(action).required_review
                or not context.safety_policy.check_action(action).allowed
            ]
            safe_actions = [
                action
                for action in safe_actions
                if context.safety_policy.check_action(action).allowed
                and not context.safety_policy.check_action(action).required_review
            ]
            node = graph.add_screen(
                screen_id=f"screen_{index + 1:03d}",
                screen_hash=screen_hash,
                screen_type=_screen_type(texts, candidates),
                texts=texts,
                elements=[candidate.get("name", "") for candidate in candidates],
                safe_actions=[action["name"] for action in safe_actions],
                risky_actions=risky_actions,
            )
            if current_screen_id and steps:
                graph.add_transition(current_screen_id, steps[-1].action.get("name", "wait"), node.screen_id)
            current_screen_id = node.screen_id
            if not safe_actions or self.action_executor is None:
                break
            action = safe_actions[0]
            if counter:
                counter.consume("max_actions_per_screen")
            try:
                result = await self.action_executor(action)
            except Exception as exc:
                failures.append(str(exc))
                break
            steps.append(
                ExplorationStep(
                    index=index + 1,
                    screen_id=node.screen_id,
                    action=action,
                    result_screen_id="pending_next_screen",
                    policy_result=result,
                )
            )

        status = "ok" if graph.screens else "empty"
        if failures:
            status = "failed"
        return context.with_updates(screen_graph=graph), ExplorationState(status=status, steps=steps, failures=failures)

    async def _visible_texts(self) -> list[str]:
        if self.visible_texts is None:
            return []
        return [str(item) for item in await self.visible_texts()]

    async def _candidates(self, goal: str) -> list[dict[str, Any]]:
        if self.candidate_finder is None:
            return []
        return [dict(item) for item in await self.candidate_finder(goal)]


def _hash_frame(png: bytes) -> str:
    return hashlib.sha256(png or b"").hexdigest()[:16]


def _candidate_actions(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actions = []
    for candidate in candidates:
        name = str(candidate.get("name") or candidate.get("text") or "candidate")
        actions.append({"type": "tap", "name": f"tap_{name}", "target": name, "candidate": candidate})
    return actions


def _screen_type(texts: list[str], candidates: list[dict[str, Any]]) -> str:
    haystack = " ".join(texts + [str(candidate.get("name", "")) for candidate in candidates]).lower()
    if any(word in haystack for word in ("play", "settings", "continue", "skip", "tap to play")):
        return "menu"
    if any(word in haystack for word in ("buy", "purchase", "subscribe")):
        return "purchase"
    return "unknown"
