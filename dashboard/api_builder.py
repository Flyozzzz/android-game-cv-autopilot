"""Dashboard API helpers for LLM Autopilot Builder."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import config
from core.autobuilder.builder import AutopilotBuilder, BuildOptions
from dashboard.cv_bridge import payload_api_key, payload_models


ROOT = Path(__file__).resolve().parents[1]


def build_autopilot_from_payload(payload: dict[str, Any], *, adb_path: str = "adb") -> dict[str, Any]:
    prompt = str(payload.get("prompt") or payload.get("goal") or "").strip()
    if not prompt:
        raise RuntimeError("Autopilot builder prompt is required")
    options = BuildOptions(
        mode=str(payload.get("mode") or "create"),
        serial=str(payload.get("serial") or ""),
        package=str(payload.get("package") or payload.get("gamePackage") or ""),
        api_key=payload_api_key(payload),
        models=payload_models(payload) or getattr(config, "CV_MODELS", None),
        adb_path=adb_path,
        output_root=ROOT / "autopilots",
        templates_root=ROOT / "assets" / "templates",
        frame_paths=[str(path) for path in payload.get("framePaths", []) if str(path).strip()],
        live_validation=bool(payload.get("liveValidation", False)),
        launch_app=bool(payload.get("launchApp", True)),
    )
    return AutopilotBuilder().build(prompt, options)


def builder_state() -> dict[str, Any]:
    root = ROOT / "autopilots"
    bundles = []
    if root.exists():
        for path in sorted(root.iterdir()):
            autopilot = path / "autopilot.json"
            if autopilot.exists():
                bundles.append({"id": path.name, "path": str(autopilot)})
    return {
        "bundles": bundles,
        "models": getattr(config, "CV_MODELS", []),
        "outputRoot": str(root),
    }
