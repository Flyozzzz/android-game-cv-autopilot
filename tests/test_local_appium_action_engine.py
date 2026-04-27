import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config
from core.appium_action_engine import AppiumActionEngine


class OrientationExplodesDriver:
    @property
    def orientation(self):
        raise AssertionError("local force_portrait must not read Appium orientation")

    @orientation.setter
    def orientation(self, value):
        raise AssertionError("local force_portrait must not write Appium orientation")


def test_local_force_portrait_does_not_touch_appium_orientation(monkeypatch):
    monkeypatch.setattr(config, "DEVICE_FARM", "local")
    engine = AppiumActionEngine(OrientationExplodesDriver())

    ok = asyncio.run(engine.force_portrait())

    assert ok is True
