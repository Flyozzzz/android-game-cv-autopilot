import asyncio

from core.input_scheduler import InputScheduler


class FakeClock:
    def __init__(self):
        self.value = 10.0

    def __call__(self):
        return self.value

    def advance_ms(self, ms: float):
        self.value += ms / 1000.0


class FakeAction:
    def __init__(self):
        self.taps = []
        self.swipes = []

    async def tap(self, x, y, pause=0.3):
        self.taps.append((x, y, pause))

    async def swipe(self, x1, y1, x2, y2, duration_ms=300, pause=0.3):
        self.swipes.append((x1, y1, x2, y2, duration_ms, pause))


class LegacySwipeAction(FakeAction):
    async def swipe(self, x1, y1, x2, y2, duration_ms=300):
        self.swipes.append((x1, y1, x2, y2, duration_ms))


def test_scheduler_uses_menu_pause_by_default():
    action = FakeAction()
    scheduler = InputScheduler(action, mode="menu")

    result = asyncio.run(scheduler.tap(10, 20))

    assert result.executed is True
    assert action.taps == [(10, 20, 0.3)]


def test_scheduler_uses_no_pause_in_fast_mode():
    action = FakeAction()
    scheduler = InputScheduler(action, mode="fast")

    asyncio.run(scheduler.tap(10, 20))
    asyncio.run(scheduler.swipe(1, 2, 3, 4, duration_ms=90))

    assert action.taps == [(10, 20, 0.0)]
    assert action.swipes == [(1, 2, 3, 4, 90, 0.0)]


def test_scheduler_blocks_repeated_cooldown_until_time_advances():
    action = FakeAction()
    clock = FakeClock()
    scheduler = InputScheduler(
        action,
        mode="fast",
        cooldowns_ms={"lane_change": 180},
        clock=clock,
    )

    first = asyncio.run(
        scheduler.swipe(1, 2, 3, 4, duration_ms=90, cooldown_key="lane_change")
    )
    second = asyncio.run(
        scheduler.swipe(1, 2, 3, 4, duration_ms=90, cooldown_key="lane_change")
    )
    clock.advance_ms(181)
    third = asyncio.run(
        scheduler.swipe(1, 2, 3, 4, duration_ms=90, cooldown_key="lane_change")
    )

    assert first.executed is True
    assert second.executed is False
    assert second.reason == "cooldown"
    assert second.remaining_ms == 180
    assert third.executed is True
    assert len(action.swipes) == 2


def test_scheduler_blocks_tap_cooldown_and_accepts_pause_override():
    action = FakeAction()
    clock = FakeClock()
    scheduler = InputScheduler(action, mode="menu", cooldowns_ms={"tap_confirm": 100}, clock=clock)

    first = asyncio.run(scheduler.tap(10, 20, cooldown_key="tap_confirm", pause=-1))
    second = asyncio.run(scheduler.tap(10, 20, cooldown_key="tap_confirm"))

    assert first.executed is True
    assert second.executed is False
    assert second.reason == "cooldown"
    assert action.taps == [(10, 20, 0.0)]


def test_scheduler_batch_executes_supported_actions_and_reports_unknown():
    action = FakeAction()
    scheduler = InputScheduler(action, mode="fast")

    results = asyncio.run(
        scheduler.batch(
            [
                {"type": "tap", "x": 10, "y": 20},
                {"type": "swipe", "x1": 1, "y1": 2, "x2": 3, "y2": 4, "duration_ms": 90},
                {"type": "press", "key": "back"},
            ]
        )
    )

    assert [result.executed for result in results] == [True, True, False]
    assert results[2].reason == "unsupported_action"
    assert action.taps == [(10, 20, 0.0)]
    assert action.swipes == [(1, 2, 3, 4, 90, 0.0)]


def test_scheduler_supports_legacy_swipe_without_pause_argument():
    action = LegacySwipeAction()
    scheduler = InputScheduler(action, mode="fast")

    result = asyncio.run(scheduler.swipe(1, 2, 3, 4, duration_ms=90))

    assert result.executed is True
    assert action.swipes == [(1, 2, 3, 4, 90)]
