import asyncio
from io import BytesIO

from PIL import Image

from core.autobuilder.context import BuildContext
from core.autobuilder.goal_spec import GoalSpec
from core.autobuilder.safety_policy import SafetyPolicy
from core.autobuilder.explorer import Explorer
from core.frame_source import Frame, FrameSource


class OneFrameSource(FrameSource):
    async def latest_frame(self):
        image = Image.new("RGB", (32, 32), "white")
        buf = BytesIO()
        image.save(buf, format="PNG")
        return Frame(1, 32, 32, None, buf.getvalue(), "test", 0.0)


def test_explorer_records_safe_screen_and_transition_candidate():
    goal = GoalSpec(app_name="Game", goal="tap play")
    context = BuildContext.create(goal, SafetyPolicy.from_goal(goal))

    async def texts():
        return ["Play"]

    async def candidates(_goal):
        return [{"name": "play_button", "confidence": 0.9}]

    explorer = Explorer(frame_source=OneFrameSource(), visible_texts=texts, candidate_finder=candidates)
    updated, state = asyncio.run(explorer.explore(context))

    graph = updated.screen_graph
    assert state.status == "ok"
    assert graph.get("screen-001").type == "menu"
    assert graph.get("screen-001").safe_actions == ["tap_play_button"]
