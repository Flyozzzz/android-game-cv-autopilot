import asyncio
import base64
from io import BytesIO

from PIL import Image

from core.cv_engine import CVEngine


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
