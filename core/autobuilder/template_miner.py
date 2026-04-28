"""Mine template crops from high-confidence screen-analysis elements."""
from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import tempfile
from typing import Any

from PIL import Image

from core.autobuilder.util import slugify
from core.frame_source import Frame
from core.perception.providers.base import ProviderContext
from core.perception.providers.template_provider import TemplateProvider
from core.perception.template_registry import TemplateRegistry


def mine_templates(
    *,
    frame: Frame,
    elements: list[dict[str, Any]],
    output_root: str | Path,
    namespace: str,
    min_confidence: float = 0.75,
) -> dict[str, Any]:
    if not frame.png_bytes:
        return {"templates": [], "verified": []}
    image = Image.open(BytesIO(frame.png_bytes)).convert("RGB")
    output_root = Path(output_root)
    specs = []
    saved = []
    for element in elements:
        confidence = float(element.get("confidence", 0.0) or 0.0)
        bbox = element.get("bbox")
        if confidence < min_confidence or not _valid_bbox(bbox, image.size):
            continue
        template_id = slugify(str(element.get("name") or element.get("description") or "template"), "template")
        x1, y1, x2, y2 = (int(float(part)) for part in bbox)
        target_dir = output_root / namespace / template_id
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / "template_000.png"
        image.crop((x1, y1, x2, y2)).save(path, format="PNG")
        spec = {
            "id": template_id,
            "paths": [str(target_dir / "*.png")],
            "threshold": 0.82,
            "scales": [0.9, 1.0, 1.1],
            "roi": str(element.get("roi") or ""),
            "tap_offset": [0.5, 0.5],
            "negative_templates": [],
            "source_screen_id": str(element.get("screen_id") or ""),
        }
        specs.append(spec)
        saved.append({"id": template_id, "path": str(path), "bbox": [x1, y1, x2, y2]})
    registry_path = output_root / "registry.json"
    _write_registry(registry_path, specs)
    verified = _verify_templates(frame, specs)
    return {"templates": saved, "registry_path": str(registry_path), "verified": verified}


def _valid_bbox(bbox: Any, size: tuple[int, int]) -> bool:
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return False
    width, height = size
    x1, y1, x2, y2 = (int(float(part)) for part in bbox)
    return 0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height and (x2 - x1) >= 4 and (y2 - y1) >= 4


def _write_registry(path: Path, specs: list[dict[str, Any]]) -> None:
    existing = []
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        existing = payload if isinstance(payload, list) else payload.get("templates", [])
    by_id = {str(item.get("id")): item for item in existing if isinstance(item, dict)}
    for spec in specs:
        by_id[spec["id"]] = spec
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"templates": list(by_id.values())}
    with tempfile.NamedTemporaryFile("w", delete=False, dir=path.parent, encoding="utf-8") as tmp:
        json.dump(payload, tmp, ensure_ascii=False, indent=2)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def _verify_templates(frame: Frame, specs: list[dict[str, Any]]) -> list[str]:
    if not specs:
        return []
    registry = TemplateRegistry.from_mappings(specs)
    provider = TemplateProvider(registry)
    import asyncio

    candidates = asyncio.run(provider.find(ProviderContext(frame=frame, goal="verify template")))
    return sorted({candidate.name for candidate in candidates})
