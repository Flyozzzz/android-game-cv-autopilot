import asyncio
import base64
from io import BytesIO

from PIL import Image

from core.cv_engine import CVEngine, validate_ui_action_plan_payload


def _png(width=320, height=480):
    image = Image.new("RGB", (width, height), "#34346f")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_cv_coordinate_grid_keeps_original_dimensions_and_changes_payload(monkeypatch):
    monkeypatch.setattr("config.CV_COORDINATE_GRID", True)
    monkeypatch.setattr("config.CV_COORDINATE_GRID_STEP", 160)
    original = _png()
    cv = CVEngine(api_key="key", models=["test/model"])

    image_b64, width, height, note = cv._prepare_coordinate_vision_image(original)
    rendered = base64.b64decode(image_b64)

    assert width == 320
    assert height == 480
    assert "coordinate ruler" in note
    assert rendered != original
    assert CVEngine._get_png_dimensions(rendered) == (320, 480)


def test_plan_next_ui_action_sends_coordinate_grid_prompt_and_image(monkeypatch):
    monkeypatch.setattr("config.CV_COORDINATE_GRID", True)
    monkeypatch.setattr("config.CV_COORDINATE_GRID_STEP", 160)
    original = _png()
    captured = {}

    class FakeResponse:
        status_code = 200
        text = "{}"

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"action":"tap","target":"gear","x":300,"y":60,"reason":"open settings"}'
                        }
                    }
                ]
            }

    class FakeClient:
        async def post(self, *args, **kwargs):
            captured["json"] = kwargs["json"]
            return FakeResponse()

        async def aclose(self):
            pass

    cv = CVEngine(api_key="key", models=["test/model"])
    cv.client = FakeClient()

    plan = asyncio.run(cv.plan_next_ui_action(original, goal="open settings", available_values={}))
    asyncio.run(cv.close())

    content = captured["json"]["messages"][0]["content"]
    prompt = content[0]["text"]
    image_url = content[1]["image_url"]["url"]
    sent_image = base64.b64decode(image_url.split(",", 1)[1])

    assert plan.target == "gear"
    assert "COORDINATE_OVERLAY:" in prompt
    assert "coordinate ruler labels" in prompt
    assert sent_image != original
    assert CVEngine._get_png_dimensions(sent_image) == (320, 480)


def test_plan_next_ui_action_repairs_invalid_json_shape(monkeypatch):
    monkeypatch.setattr("config.CV_COORDINATE_GRID", False)
    monkeypatch.setattr("config.CV_JSON_REPAIR_ATTEMPTS", 1)
    calls = []

    class FakeResponse:
        status_code = 200
        text = "{}"

        def __init__(self, content):
            self._content = content

        def json(self):
            return {"choices": [{"message": {"content": self._content}}]}

    class FakeClient:
        async def post(self, *args, **kwargs):
            calls.append(kwargs["json"]["messages"][0]["content"][0]["text"])
            if len(calls) == 1:
                return FakeResponse('{"action":"drag","reason":"bad"}')
            return FakeResponse('{"action":"swipe","direction":"up","reason":"scroll"}')

        async def aclose(self):
            pass

    cv = CVEngine(api_key="key", models=["test/model"])
    cv.client = FakeClient()

    plan = asyncio.run(cv.plan_next_ui_action(_png(), goal="scroll", available_values={}))
    asyncio.run(cv.close())

    assert plan.action == "swipe"
    assert plan.direction == "up"
    assert len(calls) == 2
    assert "previous response was invalid" in calls[1]


def test_validate_ui_action_plan_payload_enforces_action_contract():
    valid = validate_ui_action_plan_payload(
        {"action": "click", "target": "OK", "x": 10, "y": 20, "reason": "confirm"},
        img_w=100,
        img_h=200,
    )
    assert valid.action == "tap"

    for payload in (
        {"action": "drag", "reason": "bad"},
        {"action": "tap", "x": 999, "y": 1, "reason": "bad"},
        {"action": "swipe", "direction": "sideways", "reason": "bad"},
        {"action": "press", "key": "power", "reason": "bad"},
        {"action": "type", "target": "field", "x": 1, "y": 1, "reason": "bad"},
        {"target": "OK", "x": 10, "y": 20, "reason": "missing action"},
        {"action": "wait", "reason": "ok", "unsafe": True},
    ):
        try:
            validate_ui_action_plan_payload(payload, img_w=100, img_h=200)
        except ValueError:
            pass
        else:
            raise AssertionError(f"payload should be rejected: {payload}")
