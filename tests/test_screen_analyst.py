import asyncio

import pytest

from core.autobuilder.goal_spec import GoalSpec
from core.autobuilder.safety_policy import SafetyPolicy
from core.autobuilder.screen_analyst import ScreenAnalyst
from core.autobuilder.screen_graph import ScreenGraph


def test_screen_analyst_validates_structured_output_and_filters_risky_elements():
    async def llm(_prompt, _screenshot):
        return {
            "screen_type": "menu",
            "summary": "Menu with play and shop",
            "safe_elements": [
                {"name": "play_button", "recommended_action": "tap", "bbox": [1, 1, 10, 10], "confidence": 0.9},
                {"name": "buy_coins", "recommended_action": "tap", "bbox": [12, 1, 20, 10], "confidence": 0.9},
            ],
            "risky_elements": [],
            "next_best_goal": "tap_play",
        }

    goal = GoalSpec(app_name="Game", goal="start")
    result = asyncio.run(
        ScreenAnalyst(llm=llm).analyze(
            screenshot=b"png",
            visible_texts=[],
            goal=goal,
            policy=SafetyPolicy.from_goal(goal),
            screen_graph=ScreenGraph(),
        )
    )

    assert [item["name"] for item in result.safe_elements] == ["play_button"]
    assert result.risky_elements[0]["name"] == "buy_coins"


def test_screen_analyst_rejects_invalid_llm_json():
    async def bad_llm(_prompt, _screenshot):
        return {"screen_type": "menu"}

    with pytest.raises(RuntimeError, match="screen analysis failed"):
        asyncio.run(
            ScreenAnalyst(llm=bad_llm, max_retries=0).analyze(
                screenshot=b"png",
                visible_texts=[],
                goal=GoalSpec(app_name="Game", goal="start"),
                policy=SafetyPolicy(),
                screen_graph=ScreenGraph(),
            )
        )
