import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config
from core.appium_action_engine import AppiumActionEngine


class NoTextLambdaTestDriver:
    def find_elements(self, *args, **kwargs):
        return []

    @property
    def page_source(self):
        raise AssertionError("LambdaTest flow must not call page_source fallback")


def test_lambdatest_visible_texts_skip_page_source_fallback(monkeypatch):
    monkeypatch.setattr(config, "DEVICE_FARM", "lambdatest")
    engine = AppiumActionEngine(NoTextLambdaTestDriver())

    texts = asyncio.run(engine.get_visible_texts())

    assert texts == []
