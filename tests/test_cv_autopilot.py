import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.cv_autopilot import CVAutopilot
from core.cv_engine import UIActionPlan, UIElement


class FakeAction:
    def __init__(self):
        self.taps = []
        self.typed = []
        self.pressed = []
        self.swipes = []
        self.cleared = 0
        self.adb_calls = []

    async def screenshot(self):
        return b"\x89PNG\r\n\x1a\n" + b"0" * 32

    async def tap(self, x, y, pause=0.0):
        self.taps.append((x, y))

    async def type_text(self, text, pause=0.0):
        self.typed.append(text)

    async def clear_field(self, max_chars=50):
        self.cleared += 1

    async def press_back(self):
        self.pressed.append("back")

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


class FakeCV:
    def __init__(self, plans):
        self.plans = list(plans)
        self.finds = []

    async def plan_next_ui_action(self, *args, **kwargs):
        return self.plans.pop(0)

    async def find_element(self, screenshot, target):
        self.finds.append(target)
        return UIElement(name=target, x=111, y=222, confidence=0.9)


def test_cv_autopilot_taps_visual_target_then_done():
    action = FakeAction()
    cv = FakeCV([
        UIActionPlan(action="tap", target="Next button", reason="continue"),
        UIActionPlan(action="done", reason="goal reached"),
    ])

    result = asyncio.run(CVAutopilot(action, cv=cv).run("continue"))

    assert result.ok is True
    assert cv.finds == ["Next button"]
    assert action.taps == [(111, 222)]


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
