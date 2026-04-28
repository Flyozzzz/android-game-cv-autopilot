"""Dashboard helpers for perception inspector overlays and labels."""
from __future__ import annotations

from dataclasses import asdict
import base64
import glob
from io import BytesIO
import json
from pathlib import Path
import re
import time
from typing import Any
from urllib.parse import quote

import config
from PIL import Image
from core.game_profiles import game_profile_from_mapping, list_game_profiles
from core.metrics import metrics_snapshot


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_ROOT = ROOT / "assets" / "templates"
LABELS_ROOT = ROOT / "dashboard" / "vision_labels"
PROFILES_ROOT = ROOT / "dashboard" / "profiles"


def vision_inspector_payload(*, serial: str = "") -> dict[str, Any]:
    snapshot = metrics_snapshot()
    latest_trace = snapshot.get("latest_trace") or {}
    screenshot_url = "/api/device/screenshot"
    if serial:
        screenshot_url += f"?serial={quote(serial)}"
    return {
        "frame": {
            "source": latest_trace.get("frame_source") or getattr(config, "FRAME_SOURCE", "adb"),
            "screenshotUrl": screenshot_url,
        },
        "overlay": {
            "roi": latest_trace.get("roi"),
            "candidates": latest_trace.get("candidates") or [],
            "selectedCandidate": latest_trace.get("selected_candidate"),
        },
        "decision": {
            "goal": latest_trace.get("goal", ""),
            "providersCalled": latest_trace.get("providers_called") or [],
            "llmCalled": bool(latest_trace.get("llm_called", False)),
            "policyResult": latest_trace.get("policy_result", ""),
            "action": latest_trace.get("action"),
        },
        "latency": latest_trace.get("latency_breakdown") or snapshot.get("latencies", {}),
        "metrics": snapshot,
    }


def save_template_from_payload(
    payload: dict[str, Any],
    *,
    screenshot_bytes: bytes | None = None,
    templates_root: Path = TEMPLATES_ROOT,
) -> dict[str, Any]:
    template_id = _slug(payload.get("templateId") or payload.get("template_id") or payload.get("id"))
    namespace = _slug(payload.get("namespace") or payload.get("profileId") or payload.get("profile_id") or "common")
    bbox = _bbox(payload.get("bbox"))
    image_bytes = _payload_image_bytes(payload) or screenshot_bytes
    if not image_bytes:
        raise RuntimeError("Template save requires screenshot bytes or screenshotBase64")
    image = Image.open(BytesIO(image_bytes)).convert("RGB")
    crop = image.crop(_clamped_bbox(bbox, image.size))
    target_dir = templates_root / namespace / template_id
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"template_{int(time.time() * 1000)}.png"
    crop.save(path, format="PNG")
    registry_path = templates_root / "registry.json"
    spec = {
        "id": template_id,
        "paths": [_template_glob_path(templates_root, namespace, template_id)],
        "threshold": float(payload.get("threshold") or 0.82),
        "scales": payload.get("scales") or [0.75, 0.9, 1.0, 1.15, 1.3],
        "roi": str(payload.get("roi") or ""),
        "tap_offset": payload.get("tapOffset") or payload.get("tap_offset") or [0.5, 0.5],
        "negative_templates": payload.get("negativeTemplates") or payload.get("negative_templates") or [],
    }
    _upsert_template_spec(registry_path, spec)
    return {
        "saved": True,
        "templateId": template_id,
        "namespace": namespace,
        "path": _display_path(path),
        "registryPath": _display_path(registry_path),
        "bbox": bbox,
        "size": [crop.width, crop.height],
    }


def list_template_library(
    *,
    templates_root: Path = TEMPLATES_ROOT,
) -> dict[str, Any]:
    registry_path = templates_root / "registry.json"
    payload: Any = {"templates": []}
    if registry_path.exists():
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
    templates = payload.get("templates") if isinstance(payload, dict) else payload
    if not isinstance(templates, list):
        templates = []

    items: list[dict[str, Any]] = []
    for raw in templates:
        if not isinstance(raw, dict):
            continue
        paths = [str(path) for path in raw.get("paths") or []]
        files = _template_files(paths)
        item = {
            "id": str(raw.get("id") or ""),
            "roi": str(raw.get("roi") or ""),
            "threshold": raw.get("threshold"),
            "scales": raw.get("scales") or [],
            "tapOffset": raw.get("tap_offset") or raw.get("tapOffset") or [0.5, 0.5],
            "negativeTemplates": raw.get("negative_templates") or raw.get("negativeTemplates") or [],
            "paths": paths,
            "files": files,
            "fileCount": len(files),
        }
        item["namespace"] = _template_namespace(item)
        items.append(item)

    items.sort(key=lambda item: (str(item.get("namespace") or ""), str(item.get("id") or "")))
    return {
        "registryPath": _display_path(registry_path),
        "templatesRoot": _display_path(templates_root),
        "templates": items,
        "total": len(items),
    }


def create_roi_from_payload(
    payload: dict[str, Any],
    *,
    profiles_root: Path = PROFILES_ROOT,
) -> dict[str, Any]:
    profile_id = _slug(payload.get("profileId") or payload.get("profile_id"))
    zone_name = _slug(payload.get("zoneName") or payload.get("zone_name"))
    normalized = _normalized_box(payload)
    profile = _profile_payload(profile_id, profiles_root)
    zones = dict(profile.get("screen_zones") or profile.get("screenZones") or {})
    zones[zone_name] = list(normalized)
    profile["screen_zones"] = zones
    profiles_root.mkdir(parents=True, exist_ok=True)
    path = profiles_root / f"{profile_id}.json"
    path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "saved": True,
        "profileId": profile_id,
        "zoneName": zone_name,
        "normalizedBox": list(normalized),
        "path": _display_path(path),
    }


def export_label_from_payload(
    payload: dict[str, Any],
    *,
    labels_root: Path = LABELS_ROOT,
) -> dict[str, Any]:
    profile_id = _slug(payload.get("profileId") or payload.get("profile_id") or "unknown")
    label_id = _slug(payload.get("labelId") or payload.get("label_id") or payload.get("name") or "label")
    candidate = payload.get("candidate")
    if not isinstance(candidate, dict):
        raise RuntimeError("Label export requires candidate object")
    labels_root.mkdir(parents=True, exist_ok=True)
    path = labels_root / f"{profile_id}_{label_id}_{int(time.time() * 1000)}.json"
    data = {
        "profile_id": profile_id,
        "label_id": label_id,
        "goal": str(payload.get("goal") or ""),
        "screen_id": str(payload.get("screenId") or payload.get("screen_id") or ""),
        "roi": payload.get("roi"),
        "candidate": candidate,
        "created_at": int(time.time()),
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"saved": True, "path": _display_path(path), "label": data}


def _profile_payload(profile_id: str, profiles_root: Path) -> dict[str, Any]:
    custom_path = profiles_root / f"{profile_id}.json"
    if custom_path.exists():
        return json.loads(custom_path.read_text(encoding="utf-8"))
    for profile in list_game_profiles():
        if profile.id == profile_id:
            return asdict(profile)
    return asdict(game_profile_from_mapping({"id": profile_id, "name": profile_id}))


def _payload_image_bytes(payload: dict[str, Any]) -> bytes | None:
    raw = str(payload.get("screenshotBase64") or payload.get("imageBase64") or "").strip()
    if not raw:
        return None
    if "," in raw and raw.lower().startswith("data:"):
        raw = raw.split(",", 1)[1]
    return base64.b64decode(raw)


def _bbox(value: Any) -> tuple[int, int, int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise RuntimeError("bbox must be [x1, y1, x2, y2]")
    x1, y1, x2, y2 = (int(round(float(part))) for part in value)
    if x2 <= x1 or y2 <= y1:
        raise RuntimeError("bbox must satisfy x2>x1 and y2>y1")
    return x1, y1, x2, y2


def _normalized_box(payload: dict[str, Any]) -> tuple[float, float, float, float]:
    raw = payload.get("normalizedBox") or payload.get("normalized_box")
    if isinstance(raw, (list, tuple)) and len(raw) == 4:
        box = tuple(float(part) for part in raw)
    else:
        pixel = _bbox(payload.get("pixelBox") or payload.get("pixel_box") or payload.get("bbox"))
        width = float(payload.get("width") or payload.get("screenWidth") or 0)
        height = float(payload.get("height") or payload.get("screenHeight") or 0)
        if width <= 0 or height <= 0:
            raise RuntimeError("pixel ROI requires width and height")
        x1, y1, x2, y2 = pixel
        box = (x1 / width, y1 / height, x2 / width, y2 / height)
    x1, y1, x2, y2 = box
    if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
        raise RuntimeError("ROI must satisfy 0<=x1<x2<=1 and 0<=y1<y2<=1")
    return (round(x1, 6), round(y1, 6), round(x2, 6), round(y2, 6))


def _clamped_bbox(bbox: tuple[int, int, int, int], size: tuple[int, int]) -> tuple[int, int, int, int]:
    width, height = size
    x1, y1, x2, y2 = bbox
    return (
        max(0, min(width - 1, x1)),
        max(0, min(height - 1, y1)),
        max(1, min(width, x2)),
        max(1, min(height, y2)),
    )


def _upsert_template_spec(path: Path, spec: dict[str, Any]) -> None:
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        payload = {"templates": []}
    templates = payload.get("templates") if isinstance(payload, dict) else payload
    if not isinstance(templates, list):
        templates = []
    templates = [item for item in templates if item.get("id") != spec["id"]]
    templates.append(spec)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"templates": templates}, ensure_ascii=False, indent=2), encoding="utf-8")


def _template_files(paths: list[str]) -> list[str]:
    found: list[str] = []
    for pattern in paths:
        full_pattern = Path(pattern)
        if not full_pattern.is_absolute():
            full_pattern = ROOT / pattern
        for match in glob.glob(str(full_pattern)):
            path = Path(match)
            if path.is_file():
                found.append(_display_path(path))
    return sorted(dict.fromkeys(found))


def _template_namespace(item: dict[str, Any]) -> str:
    template_id = str(item.get("id") or "")
    for source in list(item.get("files") or []) + list(item.get("paths") or []):
        parts = str(source).replace("\\", "/").split("/")
        if len(parts) >= 4 and parts[0] == "assets" and parts[1] == "templates":
            return parts[2]
        if template_id and template_id in parts:
            index = parts.index(template_id)
            if index > 0:
                return parts[index - 1]
    return ""


def _template_glob_path(root: Path, namespace: str, template_id: str) -> str:
    default_root = TEMPLATES_ROOT.resolve()
    pattern = root / namespace / template_id / "*.png"
    try:
        if root.resolve() == default_root:
            return str(pattern.relative_to(ROOT))
    except Exception:
        pass
    return str(pattern)


def _slug(value: Any) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "-", str(value or "").strip().lower()).strip("-")
    if not slug:
        raise RuntimeError("A non-empty id/name is required")
    return slug


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)
