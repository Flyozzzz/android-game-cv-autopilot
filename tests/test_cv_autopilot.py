import asyncio
import builtins
from io import BytesIO
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.cv_autopilot as cv_autopilot_module
from core.cv_autopilot import CVAutopilot
from core.cv_engine import UIActionPlan, UIElement
from core.frame_source import Frame
from core.metrics import metrics_snapshot, reset_metrics
from core.perception.defaults import reset_default_state_cache


def _png(width=300, height=600):
    image = Image.new("RGB", (width, height), "white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def setup_function():
    reset_default_state_cache()
    reset_metrics()


class FakeAction:
    def __init__(self):
        self.taps = []
        self.typed = []
        self.pressed = []
        self.swipes = []
        self.cleared = 0
        self.adb_calls = []

    async def screenshot(self):
        return _png()

    async def tap(self, x, y, pause=0.0):
        self.taps.append((x, y))

    async def type_text(self, text, pause=0.0):
        self.typed.append(text)

    async def clear_field(self, max_chars=50):
        self.cleared += 1

    async def press_back(self):
        self.pressed.append("back")

    async def press_home(self):
        self.pressed.append("home")

    async def press_enter(self):
        self.pressed.append("enter")

    async def press_tab(self):
        self.pressed.append("tab")

    async def swipe_up(self):
        self.swipes.append("up")

    async def swipe_down(self):
        self.swipes.append("down")

    async def swipe(self, x1, y1, x2, y2, duration_ms=300):
        self.swipes.append((x1, y1, x2, y2, duration_ms))

    async def _run_adb(self, *args, timeout=None):
        self.adb_calls.append(args)
        return "ok"


class FakeTextAction(FakeAction):
    def __init__(self, visible_texts):
        super().__init__()
        self.visible_texts = visible_texts

    async def get_visible_texts(self):
        return self.visible_texts


class FakeCV:
    def __init__(self, plans):
        self.plans = list(plans)
        self.finds = []

    async def plan_next_ui_action(self, *args, **kwargs):
        return self.plans.pop(0)

    async def find_element(self, screenshot, target):
        self.finds.append(target)
        return UIElement(name=target, x=111, y=222, confidence=0.9)


class NoFinderAutopilot(CVAutopilot):
    def _get_element_finder(self):
        return None


def test_cv_autopilot_taps_visual_target_then_done():
    reset_default_state_cache()
    action = FakeAction()
    cv = FakeCV([
        UIActionPlan(action="tap", target="Next button", reason="continue"),
        UIActionPlan(action="done", reason="goal reached"),
    ])

    result = asyncio.run(CVAutopilot(action, cv=cv).run("continue"))

    assert result.ok is True
    assert cv.finds == ["Next button"]
    assert action.taps == [(111, 222)]


def test_cv_autopilot_uses_configured_frame_source(monkeypatch):
    class FakeSource:
        def __init__(self):
            self.closed = False

        async def latest_frame(self):
            return Frame(1, 300, 600, None, _png(), "scrcpy_raw", 1.0)

        def close(self):
            self.closed = True

    source = FakeSource()
    monkeypatch.setattr(cv_autopilot_module, "create_frame_source", lambda **kwargs: source)
    action = FakeAction()
    cv = FakeCV([UIActionPlan(action="done", reason="ready")])

    result = asyncio.run(CVAutopilot(action, cv=cv).run("finish"))

    assert result.ok is True
    assert source.closed is True


def test_cv_autopilot_local_first_uses_uiautomator_before_llm(monkeypatch):
    reset_default_state_cache()
    monkeypatch.setattr("config.PERCEPTION_MODE", "local_first")
    monkeypatch.setattr("config.ENABLE_UIAUTOMATOR_PROVIDER", True)
    monkeypatch.setattr("config.ENABLE_TEMPLATE_PROVIDER", False)
    monkeypatch.setattr("config.ENABLE_LLM_FALLBACK", True)
    monkeypatch.setattr("config.ENABLE_DETECTOR_PROVIDER", False)
    action = FakeTextAction([("Continue", 33, 44)])
    cv = FakeCV([
        UIActionPlan(action="tap", target="Continue"),
        UIActionPlan(action="done"),
    ])

    result = asyncio.run(CVAutopilot(action, cv=cv).run("continue"))

    assert result.ok is True
    assert cv.finds == []
    assert action.taps == [(33, 44)]


def test_cv_autopilot_local_first_falls_back_to_llm_when_local_missing(monkeypatch):
    reset_default_state_cache()
    monkeypatch.setattr("config.PERCEPTION_MODE", "local_first")
    monkeypatch.setattr("config.ENABLE_UIAUTOMATOR_PROVIDER", True)
    monkeypatch.setattr("config.ENABLE_TEMPLATE_PROVIDER", False)
    monkeypatch.setattr("config.ENABLE_LLM_FALLBACK", True)
    monkeypatch.setattr("config.ENABLE_DETECTOR_PROVIDER", False)
    action = FakeTextAction([])
    cv = FakeCV([
        UIActionPlan(action="tap", target="Continue"),
        UIActionPlan(action="done"),
    ])

    result = asyncio.run(CVAutopilot(action, cv=cv).run("continue"))

    assert result.ok is True
    assert cv.finds == ["Continue"]
    assert action.taps == [(111, 222)]


def test_cv_autopilot_local_only_does_not_call_llm(monkeypatch):
    reset_default_state_cache()
    monkeypatch.setattr("config.PERCEPTION_MODE", "local_only")
    monkeypatch.setattr("config.ENABLE_UIAUTOMATOR_PROVIDER", True)
    monkeypatch.setattr("config.ENABLE_TEMPLATE_PROVIDER", False)
    monkeypatch.setattr("config.ENABLE_LLM_FALLBACK", True)
    monkeypatch.setattr("config.ENABLE_DETECTOR_PROVIDER", False)
    action = FakeTextAction([])
    cv = FakeCV([UIActionPlan(action="tap", target="Continue")])

    result = asyncio.run(CVAutopilot(action, cv=cv).run("continue"))

    assert result.status == "fail"
    assert result.reason == "fail:target_not_found"
    assert cv.finds == []
    assert action.taps == []


def test_cv_autopilot_execute_plan_failure_and_unknown_actions():
    action = FakeAction()
    autopilot = CVAutopilot(action, cv=FakeCV([]))

    assert asyncio.run(autopilot._execute_plan(UIActionPlan(action="fail", reason="bad"), _png(), {})) == "fail:bad"
    assert asyncio.run(autopilot._execute_plan(UIActionPlan(action="noop"), _png(), {})) == "fail:unknown_action:noop"


def test_cv_autopilot_execute_plan_press_variants():
    action = FakeAction()
    autopilot = CVAutopilot(action, cv=FakeCV([]))

    assert asyncio.run(autopilot._execute_plan(UIActionPlan(action="press", key="back"), _png(), {})) == "pressed:back"
    assert asyncio.run(autopilot._execute_plan(UIActionPlan(action="press", key="enter"), _png(), {})) == "pressed:enter"
    assert asyncio.run(autopilot._execute_plan(UIActionPlan(action="press", key="tab"), _png(), {})) == "pressed:tab"
    assert asyncio.run(autopilot._execute_plan(UIActionPlan(action="press", key="home"), _png(), {})) == "pressed:home"
    assert asyncio.run(autopilot._execute_plan(UIActionPlan(action="press", key="bad"), _png(), {})) == "fail:unknown_key"
    assert action.pressed == ["back", "enter", "tab", "home"]


def test_cv_autopilot_execute_plan_swipe_variants_and_unknown_direction():
    action = FakeAction()
    autopilot = CVAutopilot(action, cv=FakeCV([]))

    assert asyncio.run(autopilot._execute_plan(UIActionPlan(action="swipe", direction="down"), _png(), {})) == "swiped:down"
    assert asyncio.run(autopilot._execute_plan(UIActionPlan(action="swipe", direction="up"), _png(), {})) == "swiped:up"
    assert asyncio.run(autopilot._swipe(UIActionPlan(direction="sideways"), {})) == "swiped:up"
    assert action.swipes[:2] == ["down", "up"]

    class NoSwipeHelpers:
        pass

    assert asyncio.run(CVAutopilot(NoSwipeHelpers(), cv=FakeCV([]))._swipe(UIActionPlan(direction="down"), {})) == "fail:unknown_swipe_direction"


def test_cv_autopilot_missing_text_and_missing_target_paths():
    action = FakeAction()
    autopilot = CVAutopilot(action, cv=FakeCV([]))

    assert asyncio.run(autopilot._execute_plan(UIActionPlan(action="type"), _png(), {})) == "fail:missing_text_value"
    assert asyncio.run(autopilot._resolve_point(UIActionPlan(action="tap"), _png(), {})) is None
    assert asyncio.run(NoFinderAutopilot(action, cv=FakeCV([]))._resolve_with_element_finder("x", _png())) is None


def test_cv_autopilot_max_steps_and_risky_allowance():
    action = FakeAction()
    cv = FakeCV([UIActionPlan(action="wait", wait_seconds=0.01)])

    result = asyncio.run(CVAutopilot(action, cv=cv, max_steps=1).run("wait"))

    assert result.status == "max_steps"
    assert CVAutopilot(action, cv=FakeCV([]), allow_risky_actions=True)._is_risky(
        UIActionPlan(action="tap", target="Buy")
    ) is False


def test_cv_autopilot_coordinate_helpers_cover_edge_cases(monkeypatch):
    action = FakeAction()
    action._real_screen_w = 1000
    action._real_screen_h = 2000
    autopilot = CVAutopilot(action, cv=FakeCV([]))

    assert autopilot._screen_size() == (1000, 2000)
    assert autopilot._swipe_direction(UIActionPlan(target="move left")) == "left"
    assert autopilot._swipe_direction(UIActionPlan(reason="scroll down")) == "down"
    assert autopilot._swipe_points(UIActionPlan(x=500, y=500), "left", {}) == (500, 500, 50, 500)
    assert autopilot._swipe_points(UIActionPlan(), "left", {}) == (800, 1120, 240, 1120)
    assert autopilot._should_type_signup_url_after_tap(
        UIActionPlan(target="plain button"),
        {"signup_url": "https://example.com"},
    ) is False
    assert autopilot._scale_point(10, 20, {"coordinate_scale": "bad"}) == (10, 20)
    assert autopilot._scale_point(10, 20, {"coordinate_scale": "-1"}) == (10, 20)

    class BadSizeAction:
        @property
        def _real_screen_w(self):
            raise RuntimeError("bad")

    assert CVAutopilot(BadSizeAction(), cv=FakeCV([]))._screen_size() == (
        int(__import__("config").SCREEN_WIDTH),
        int(__import__("config").SCREEN_HEIGHT),
    )

    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "config":
            raise ImportError("blocked")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert CVAutopilot(BadSizeAction(), cv=FakeCV([]))._screen_size() == (1080, 2400)
    assert CVAutopilot(action, cv=FakeCV([]))._scale_point(1, 2, {"coordinate_scale": "2"}) == (2, 4)


def test_cv_autopilot_types_value_key_at_coordinates():
    action = FakeAction()
    cv = FakeCV([
        UIActionPlan(action="type", x=10, y=20, text_value_key="email"),
        UIActionPlan(action="done"),
    ])

    result = asyncio.run(
        CVAutopilot(action, cv=cv).run("enter email", {"email": "a@example.com"})
    )

    assert result.ok is True
    assert action.taps == [(10, 20)]
    assert action.typed == ["a@example.com"]
    assert action.cleared == 0


def test_cv_autopilot_can_clear_before_typing():
    action = FakeAction()
    cv = FakeCV([
        UIActionPlan(action="type", x=10, y=20, text_value_key="email"),
        UIActionPlan(action="done"),
    ])

    result = asyncio.run(
        CVAutopilot(action, cv=cv).run(
            "enter email",
            {"email": "a@example.com", "clear_before_type": "1"},
        )
    )

    assert result.ok is True
    assert action.taps == [(10, 20)]
    assert action.cleared == 1
    assert action.typed == ["a@example.com"]


def test_cv_autopilot_scales_coordinates_when_configured():
    action = FakeAction()
    cv = FakeCV([
        UIActionPlan(action="tap", x=10, y=20, reason="scaled tap"),
        UIActionPlan(action="done"),
    ])

    result = asyncio.run(
        CVAutopilot(action, cv=cv).run("tap scaled", {"coordinate_scale": "1.5"})
    )

    assert result.ok is True
    assert action.taps == [(15, 30)]


def test_cv_autopilot_records_inspector_trace_for_executed_tap():
    action = FakeAction()
    cv = FakeCV([
        UIActionPlan(action="tap", target="settings gear", x=40, y=50, reason="open settings"),
    ])

    result = asyncio.run(CVAutopilot(action, cv=cv, max_steps=1).run("open settings"))

    assert result.status == "max_steps"
    trace = metrics_snapshot()["latest_trace"]
    assert trace["goal"] == "open settings"
    assert trace["providers_called"] == ["llm_plan"]
    assert trace["selected_candidate"]["name"] == "settings gear"
    assert trace["selected_candidate"]["source"] == "llm_plan"
    assert trace["selected_candidate"]["center"] == (40, 50)
    assert trace["selected_candidate"]["bbox"] == (0, 6, 84, 94)
    assert trace["action"]["outcome"] == "tapped:40,50"


def test_cv_autopilot_does_not_scale_out_of_bounds_coordinates():
    action = FakeAction()
    cv = FakeCV([
        UIActionPlan(action="tap", x=800, y=2000, reason="bottom nav"),
        UIActionPlan(action="done"),
    ])

    result = asyncio.run(
        CVAutopilot(action, cv=cv).run("tap bottom nav", {"coordinate_scale": "2.0"})
    )

    assert result.ok is True
    assert action.taps == [(800, 2000)]


def test_cv_autopilot_blocks_risky_purchase_actions_by_default():
    action = FakeAction()
    cv = FakeCV([
        UIActionPlan(action="tap", target="Buy button", reason="confirm purchase"),
    ])

    result = asyncio.run(CVAutopilot(action, cv=cv).run("test"))

    assert result.status == "fail"
    assert result.reason == "fail:risky_action_blocked"
    assert action.taps == []


def test_cv_autopilot_allows_shop_navigation_even_if_reason_mentions_purchase():
    action = FakeAction()
    cv = FakeCV([
        UIActionPlan(
            action="tap",
            target="shopping cart icon",
            reason="Open store where real-money purchases are available",
        ),
        UIActionPlan(action="done"),
    ])

    result = asyncio.run(CVAutopilot(action, cv=cv).run("open shop"))

    assert result.ok is True
    assert action.taps == [(111, 222)]


def test_cv_autopilot_can_stop_cleanly_on_risky_purchase_action():
    action = FakeAction()
    cv = FakeCV([
        UIActionPlan(action="tap", target="Buy button", reason="billing dialog visible"),
    ])

    result = asyncio.run(
        CVAutopilot(action, cv=cv, stop_on_risky_action=True).run("preview purchase")
    )

    assert result.ok is True
    assert result.reason == "billing dialog visible"
    assert action.taps == []


def test_cv_autopilot_stops_on_russian_purchase_action():
    action = FakeAction()
    cv = FakeCV([
        UIActionPlan(action="tap", target="Купить", reason="платежная кнопка видна"),
    ])

    result = asyncio.run(
        CVAutopilot(action, cv=cv, stop_on_risky_action=True).run("preview purchase")
    )

    assert result.ok is True
    assert action.taps == []


def test_cv_autopilot_fails_after_repeated_external_blocker():
    action = FakeAction()
    cv = FakeCV([
        UIActionPlan(action="wait", reason="Войти не удалось, попробуй позже"),
        UIActionPlan(action="wait", reason="Войти не удалось, попробуй позже"),
    ])

    result = asyncio.run(
        CVAutopilot(action, cv=cv, max_steps=5, max_blocker_hits=2).run("tutorial")
    )

    assert result.status == "fail"
    assert result.reason.startswith("external_blocker:")


def test_cv_autopilot_can_swipe_right_for_slider_from_reason():
    action = FakeAction()
    cv = FakeCV([
        UIActionPlan(
            action="swipe",
            target="age slider",
            direction="up",
            reason="Drag the slider to the right",
        ),
        UIActionPlan(action="done"),
    ])

    result = asyncio.run(CVAutopilot(action, cv=cv).run("set age"))

    assert result.ok is True
    assert action.swipes == [(259, 1344, 864, 1344, 500)]


def test_cv_autopilot_can_swipe_right_from_coordinates():
    action = FakeAction()
    cv = FakeCV([
        UIActionPlan(action="swipe", x=200, y=300, direction="right"),
        UIActionPlan(action="done"),
    ])

    result = asyncio.run(CVAutopilot(action, cv=cv).run("drag"))

    assert result.ok is True
    assert action.swipes == [(200, 300, 686, 300, 500)]


def test_cv_autopilot_corrects_bottom_left_shop_coordinate():
    action = FakeAction()
    cv = FakeCV([
        UIActionPlan(
            action="tap",
            x=72,
            y=1960,
            target="Shopping cart button at bottom left",
        ),
        UIActionPlan(action="done"),
    ])

    result = asyncio.run(CVAutopilot(action, cv=cv).run("open shop"))

    assert result.ok is True
    assert action.taps == [(97, 2256)]


def test_cv_autopilot_types_signup_url_after_address_bar_tap():
    action = FakeAction()
    cv = FakeCV([
        UIActionPlan(
            action="tap",
            target="address bar",
            reason="navigate to the signup URL",
        ),
        UIActionPlan(action="done", reason="signup page opened"),
    ])

    result = asyncio.run(
        CVAutopilot(action, cv=cv).run(
            "open signup page",
            {"signup_url": "https://accounts.google.com/signup"},
        )
    )

    assert result.ok is True
    assert action.taps == [(111, 222)]
    assert action.cleared == 1
    assert action.typed == ["https://accounts.google.com/signup"]
    assert action.pressed == ["enter"]


def test_cv_autopilot_opens_signup_url_directly_when_browser_package_available():
    action = FakeAction()
    cv = FakeCV([
        UIActionPlan(
            action="tap",
            target="address bar",
            reason="navigate to the signup URL",
        ),
        UIActionPlan(action="done", reason="signup page opened"),
    ])

    result = asyncio.run(
        CVAutopilot(action, cv=cv).run(
            "open signup page",
            {
                "signup_url": "https://accounts.google.com/signup",
                "browser_package": "org.mozilla.firefox",
            },
        )
    )

    assert result.ok is True
    assert action.typed == []
    assert action.pressed == []
    assert action.adb_calls == [
        (
            "shell",
            "am start -a android.intent.action.VIEW "
            "-d 'https://accounts.google.com/signup' -p org.mozilla.firefox",
        )
    ]
