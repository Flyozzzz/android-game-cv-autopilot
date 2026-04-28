"""Replay validation for generated autopilot bundles without a phone."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from core.frame_source import ReplayFrameSource
from core.perception.providers.base import ProviderContext
from core.perception.providers.template_provider import TemplateProvider
from core.perception.template_registry import TemplateRegistry


async def run_replay_tests(bundle: dict[str, Any], *, frame_paths: list[str | Path], templates_root: str | Path | None = None) -> dict[str, Any]:
    failures: list[str] = []
    source = ReplayFrameSource(frame_paths)
    frame = await source.latest_frame()
    profile = bundle.get("profile", {})
    scenario = bundle.get("scenario", {})
    if not profile.get("screen_zones"):
        failures.append("profile has no screen_zones")
    if not scenario.get("steps"):
        failures.append("scenario has no steps")
    registry_path = Path(templates_root or "assets/templates") / "registry.json"
    template_hits: list[str] = []
    if registry_path.exists():
        provider = TemplateProvider(TemplateRegistry.from_file(registry_path))
        candidates = await provider.find(ProviderContext(frame=frame, goal="replay"))
        template_hits = sorted({candidate.name for candidate in candidates})
    if any(step.get("type") == "enter_fast_gameplay" for step in scenario.get("steps", [])):
        if profile.get("runtime", {}).get("fast_gameplay") != "local_only":
            failures.append("fast gameplay must be local_only")
    return {
        "status": "passed" if not failures else "failed",
        "failures": failures,
        "template_hits": template_hits,
        "llm_called": False,
        "frames_checked": len(frame_paths),
        "metrics": {
            "frames": len(frame_paths),
            "template_hits": len(template_hits),
            "failures": len(failures),
        },
    }
