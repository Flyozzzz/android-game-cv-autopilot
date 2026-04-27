import asyncio
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scenarios.recorded_actions import RecordedActionsScenario


class FakeAction:
    def __init__(self):
        self.events = []

    async def tap(self, x, y, pause=0.0):
        self.events.append(("tap", x, y))

    async def swipe(self, x1, y1, x2, y2, duration_ms=300):
        self.events.append(("swipe", x1, y1, x2, y2, duration_ms))

    async def type_text(self, text, pause=0.0):
        self.events.append(("text", text))

    async def press_back(self):
        self.events.append(("key", "back"))


def test_recorded_actions_replays_json(tmp_path):
    path = tmp_path / "flow.json"
    path.write_text(json.dumps({
        "actions": [
            {"action": "tap", "x": 10, "y": 20},
            {"action": "text", "text": "hello"},
            {"action": "key", "key": "back"},
        ]
    }))
    action = FakeAction()

    ok = asyncio.run(
        RecordedActionsScenario(None, action, stage_name="tutorial", recording_path=str(path)).run()
    )

    assert ok is True
    assert action.events == [("tap", 10, 20), ("text", "hello"), ("key", "back")]


def test_recorded_purchase_replay_blocks_risky_label(tmp_path):
    path = tmp_path / "flow.json"
    path.write_text(json.dumps({
        "actions": [{"action": "tap", "x": 10, "y": 20, "label": "Buy button"}]
    }))

    try:
        asyncio.run(
            RecordedActionsScenario(None, FakeAction(), stage_name="purchase_preview", recording_path=str(path)).run()
        )
    except RuntimeError as exc:
        assert "Refusing" in str(exc)
    else:
        raise AssertionError("risky purchase replay should be blocked")
