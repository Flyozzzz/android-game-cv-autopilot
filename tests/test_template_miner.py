from io import BytesIO
import json

from PIL import Image, ImageDraw

from core.autobuilder.template_miner import mine_templates
from core.frame_source import Frame


def _frame():
    image = Image.new("RGB", (80, 80), "white")
    ImageDraw.Draw(image).rectangle((20, 25, 39, 44), fill="red")
    buf = BytesIO()
    image.save(buf, format="PNG")
    return Frame(1, 80, 80, None, buf.getvalue(), "test", 0)


def test_template_miner_crops_high_confidence_elements_and_writes_registry(tmp_path):
    result = mine_templates(
        frame=_frame(),
        elements=[{"name": "play_button", "bbox": [20, 25, 40, 45], "confidence": 0.95, "roi": "bottom_buttons"}],
        output_root=tmp_path,
        namespace="game",
    )

    template_path = tmp_path / "game" / "play-button" / "template_000.png"
    registry = json.loads((tmp_path / "registry.json").read_text(encoding="utf-8"))
    assert template_path.exists()
    assert registry["templates"][0]["id"] == "play-button"
    assert result["verified"] == ["play-button"]
