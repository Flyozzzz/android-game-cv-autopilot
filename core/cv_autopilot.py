"""Goal-driven CV autopilot for Android UI flows."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from loguru import logger

from core.cv_engine import CVEngine, UIActionPlan


RISKY_TARGET_WORDS = (
    "buy",
    "purchase",
    "pay",
    "payment",
    "1-tap",
    "subscribe",
    "confirm purchase",
    "купить",
    "покуп",
    "оплат",
    "платеж",
    "платёж",
    "подпис",
    "подтверд",
)

BLOCKER_WORDS = (
    "login failed",
    "server connection failed",
    "connection failed",
    "try again later",
    "maintenance",
    "войти не удалось",
    "попробуй позже",
    "попробуйте позже",
    "ошибка подключения",
    "сервер",
)


@dataclass
class AutopilotStep:
    index: int
    action: str
    target: str
    reason: str
    outcome: str


@dataclass
class AutopilotResult:
    status: str  # done | fail | max_steps
    steps: list[AutopilotStep]
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "done"


class CVAutopilot:
    """Screenshot -> Vision plan -> execute one action -> repeat."""

    def __init__(
        self,
        action: Any,
        cv: CVEngine | None = None,
        *,
        max_steps: int = 30,
        tap_confidence: float = 0.45,
        allow_risky_actions: bool = False,
        stop_on_risky_action: bool = False,
        risky_target_words: tuple[str, ...] | None = None,
        blocker_words: tuple[str, ...] | None = None,
        max_blocker_hits: int = 4,
    ):
        self.action = action
        self.cv = cv or CVEngine()
        self.max_steps = max_steps
        self.tap_confidence = tap_confidence
        self.allow_risky_actions = allow_risky_actions
        self.stop_on_risky_action = stop_on_risky_action
        self.risky_target_words = risky_target_words or RISKY_TARGET_WORDS
        self.blocker_words = blocker_words or BLOCKER_WORDS
        self.max_blocker_hits = max(1, int(max_blocker_hits or 1))
        self._blocker_hits = 0
        self.recent_actions: list[str] = []

    async def run(
        self,
        goal: str,
        available_values: dict[str, str] | None = None,
    ) -> AutopilotResult:
        values = available_values or {}
        steps: list[AutopilotStep] = []

        for index in range(1, self.max_steps + 1):
            screenshot = await self.action.screenshot()
            plan = await self.cv.plan_next_ui_action(
                screenshot,
                goal=goal,
                available_values=values,
                recent_actions=self.recent_actions,
            )
            outcome = await self._execute_plan(plan, screenshot, values)
            step = AutopilotStep(
                index=index,
                action=plan.action,
                target=plan.target,
                reason=plan.reason,
                outcome=outcome,
            )
            steps.append(step)
            self.recent_actions.append(
                f"{plan.action}:{plan.target or plan.x}:{plan.y}:{outcome}"
            )

            logger.info(
                f"CV autopilot step {index}: action={plan.action} "
                f"target={plan.target!r} outcome={outcome} reason={plan.reason!r}"
            )

            if outcome == "done":
                return AutopilotResult(status="done", steps=steps, reason=plan.reason)
            if outcome.startswith("fail"):
                return AutopilotResult(status="fail", steps=steps, reason=outcome)
            if self._is_blocker(plan):
                self._blocker_hits += 1
                if self._blocker_hits >= self.max_blocker_hits:
                    return AutopilotResult(
                        status="fail",
                        steps=steps,
                        reason=f"external_blocker:{plan.reason or plan.target}",
                    )
            else:
                self._blocker_hits = 0

        return AutopilotResult(status="max_steps", steps=steps, reason="step limit reached")

    async def _execute_plan(
        self,
        plan: UIActionPlan,
        screenshot: bytes,
        available_values: dict[str, str],
    ) -> str:
        action = (plan.action or "wait").lower()

        if action == "done":
            return "done"
        if action == "fail":
            return f"fail:{plan.reason or 'planner_failed'}"
        if action == "wait":
            await asyncio.sleep(max(0.2, min(float(plan.wait_seconds or 1.0), 10.0)))
            return "waited"
        if self._is_risky(plan):
            return "done" if self.stop_on_risky_action else "fail:risky_action_blocked"
        if action == "press":
            return await self._press(plan.key)
        if action == "swipe":
            return await self._swipe(plan, available_values)
        if action == "tap":
            return await self._tap(plan, screenshot, available_values)
        if action == "type":
            return await self._type(plan, screenshot, available_values)

        await asyncio.sleep(1.0)
        return f"fail:unknown_action:{action}"

    async def _tap(
        self,
        plan: UIActionPlan,
        screenshot: bytes,
        available_values: dict[str, str],
    ) -> str:
        point = await self._resolve_point(plan, screenshot, available_values)
        if not point:
            return "fail:target_not_found"
        await self.action.tap(point[0], point[1], pause=1.0)
        if self._should_type_signup_url_after_tap(plan, available_values):
            await self._type_signup_url(available_values)
            return f"typed_signup_url:{point[0]},{point[1]}"
        return f"tapped:{point[0]},{point[1]}"

    async def _type(
        self,
        plan: UIActionPlan,
        screenshot: bytes,
        available_values: dict[str, str],
    ) -> str:
        value = ""
        if plan.text_value_key:
            value = available_values.get(plan.text_value_key, "")
        value = value or plan.text
        if not value:
            return "fail:missing_text_value"

        point = await self._resolve_point(plan, screenshot, available_values)
        if point:
            await self.action.tap(point[0], point[1], pause=0.2)
        if self._should_clear_before_type(available_values) and hasattr(self.action, "clear_field"):
            await self.action.clear_field(max_chars=180)
        await self.action.type_text(value, pause=0.5)
        return "typed"

    async def _resolve_point(
        self,
        plan: UIActionPlan,
        screenshot: bytes,
        available_values: dict[str, str] | None = None,
    ) -> tuple[int, int] | None:
        if plan.x > 0 and plan.y > 0:
            point = self._scale_point(int(plan.x), int(plan.y), available_values)
            return self._correct_named_point(plan, point)
        if not plan.target:
            return None

        element = await self.cv.find_element(screenshot, plan.target)
        if not element or element.confidence < self.tap_confidence:
            return None
        point = self._scale_point(int(element.x), int(element.y), available_values)
        return self._correct_named_point(plan, point)

    def _correct_named_point(
        self,
        plan: UIActionPlan,
        point: tuple[int, int],
    ) -> tuple[int, int]:
        haystack = " ".join([plan.target or "", plan.reason or ""]).lower()
        width, height = self._screen_size()
        if (
            "bottom left" in haystack
            and any(word in haystack for word in ("shop", "store", "cart", "магазин", "корзин"))
            and point[1] < int(height * 0.88)
        ):
            return int(width * 0.09), int(height * 0.94)
        return point

    async def _press(self, key: str) -> str:
        key = (key or "").lower()
        if key == "back":
            await self.action.press_back()
            return "pressed:back"
        if key == "enter":
            await self.action.press_enter()
            return "pressed:enter"
        if key == "tab":
            await self.action.press_tab()
            return "pressed:tab"
        if key == "home" and hasattr(self.action, "press_home"):
            await self.action.press_home()
            return "pressed:home"
        return "fail:unknown_key"

    async def _swipe(self, plan: UIActionPlan, available_values: dict[str, str]) -> str:
        direction = self._swipe_direction(plan)
        if direction in {"left", "right"} and hasattr(self.action, "swipe"):
            x1, y1, x2, y2 = self._swipe_points(plan, direction, available_values)
            await self.action.swipe(x1, y1, x2, y2, 500)
            return f"swiped:{direction}"
        if direction == "down":
            await self.action.swipe_down()
            return "swiped:down"
        if direction == "up":
            await self.action.swipe_up()
            return "swiped:up"
        return "fail:unknown_swipe_direction"

    @staticmethod
    def _swipe_direction(plan: UIActionPlan) -> str:
        direction = (plan.direction or "").strip().lower()
        haystack = " ".join([direction, plan.target or "", plan.reason or ""]).lower()
        if "right" in haystack or "вправ" in haystack:
            return "right"
        if "left" in haystack or "влев" in haystack:
            return "left"
        if direction in {"up", "down", "left", "right"}:
            return direction
        if "down" in haystack or "вниз" in haystack:
            return "down"
        return "up"

    def _swipe_points(
        self,
        plan: UIActionPlan,
        direction: str,
        available_values: dict[str, str],
    ) -> tuple[int, int, int, int]:
        width, height = self._screen_size()
        if plan.x > 0 and plan.y > 0:
            x, y = self._scale_point(int(plan.x), int(plan.y), available_values)
            delta = max(240, int(width * 0.45))
            if direction == "right":
                return x, y, min(width - 8, x + delta), y
            return x, y, max(8, x - delta), y

        y = int(height * 0.56)
        if direction == "right":
            return int(width * 0.24), y, int(width * 0.80), y
        return int(width * 0.80), y, int(width * 0.24), y

    def _screen_size(self) -> tuple[int, int]:
        try:
            width = int(getattr(self.action, "_real_screen_w", 0) or 0)
            height = int(getattr(self.action, "_real_screen_h", 0) or 0)
        except Exception:
            width = height = 0
        if width > 0 and height > 0:
            return width, height
        try:
            import config
            return int(getattr(config, "SCREEN_WIDTH", 1080)), int(getattr(config, "SCREEN_HEIGHT", 2400))
        except Exception:
            return 1080, 2400

    async def _type_signup_url(self, available_values: dict[str, str]):
        signup_url = available_values["signup_url"]
        browser_package = available_values.get("browser_package", "")
        if browser_package and hasattr(self.action, "_run_adb"):
            await self.action._run_adb(
                "shell",
                (
                    "am start -a android.intent.action.VIEW "
                    f"-d '{signup_url}' -p {browser_package}"
                ),
                timeout=15,
            )
            await asyncio.sleep(5.0)
            return

        if hasattr(self.action, "clear_field"):
            await self.action.clear_field(max_chars=180)
        await self.action.type_text(signup_url, pause=0.2)
        await self.action.press_enter()
        await asyncio.sleep(4.0)

    def _should_type_signup_url_after_tap(
        self,
        plan: UIActionPlan,
        available_values: dict[str, str],
    ) -> bool:
        if not available_values.get("signup_url"):
            return False
        haystack = " ".join([plan.target or "", plan.reason or ""]).lower()
        address_words = ("address bar", "url bar", "search bar", "omnibox")
        if not any(word in haystack for word in address_words):
            return False
        return "signup" in haystack or "url" in haystack or "navigate" in haystack

    @staticmethod
    def _should_clear_before_type(available_values: dict[str, str]) -> bool:
        raw = str(available_values.get("clear_before_type", "")).strip().lower()
        return raw in {"1", "true", "yes", "on"}

    @staticmethod
    def _scale_point(
        x: int,
        y: int,
        available_values: dict[str, str] | None,
    ) -> tuple[int, int]:
        values = available_values or {}
        raw_scale = values.get("coordinate_scale", "")
        if not raw_scale:
            return x, y
        try:
            scale = float(raw_scale)
        except (TypeError, ValueError):
            return x, y
        if scale <= 0:
            return x, y
        sx, sy = int(round(x * scale)), int(round(y * scale))
        try:
            import config
            max_w = int(getattr(config, "SCREEN_WIDTH", 0) or 0)
            max_h = int(getattr(config, "SCREEN_HEIGHT", 0) or 0)
        except Exception:
            max_w = max_h = 0
        if (max_w and sx >= max_w) or (max_h and sy >= max_h):
            return x, y
        return sx, sy

    def _is_risky(self, plan: UIActionPlan) -> bool:
        if self.allow_risky_actions:
            return False
        target = (plan.target or "").lower()
        final_words = (
            "buy",
            "1-tap",
            "pay",
            "payment",
            "subscribe",
            "confirm",
            "price",
            "купить",
            "оплат",
            "подпис",
            "подтверд",
            "₽",
            "$",
            "€",
        )
        navigation_words = (
            "shop",
            "store",
            "cart",
            "offer card",
            "item card",
            "магазин",
            "корзин",
        )
        if (
            any(word in target for word in navigation_words)
            and not any(word in target for word in final_words)
        ):
            return False
        haystack = " ".join(
            [plan.target or "", plan.reason or "", plan.text or ""]
        ).lower()
        return any(word in haystack for word in self.risky_target_words)

    def _is_blocker(self, plan: UIActionPlan) -> bool:
        haystack = " ".join(
            [plan.target or "", plan.reason or "", plan.text or ""]
        ).lower()
        return any(word in haystack for word in self.blocker_words)
