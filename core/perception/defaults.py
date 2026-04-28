"""Default perception provider wiring for menu/tutorial flows."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

import config
from core.perception.finder import ElementFinder
from core.perception.providers.base import ElementProvider
from core.perception.providers.detector_provider import DetectorProvider
from core.perception.providers.llm_provider import LLMProvider
from core.perception.providers.template_provider import TemplateProvider
from core.perception.providers.uiautomator_provider import UIAutomatorProvider
from core.perception.state_cache import ScreenStateCache
from core.perception.template_registry import TemplateRegistry


DEFAULT_TEMPLATE_REGISTRY = Path("assets/templates/registry.json")
DEFAULT_STATE_CACHE = ScreenStateCache()


def reset_default_state_cache() -> None:
    DEFAULT_STATE_CACHE.clear()


def build_default_element_finder(
    *,
    action: Any,
    cv: Any | None = None,
    template_registry_path: str | Path | None = None,
) -> ElementFinder:
    """Build the local-first provider chain from runtime config.

    Missing optional assets or optional detector runtime are non-fatal. Invalid
    template registry files are treated as configuration errors and are raised,
    because silently ignoring a broken registry would make rollout debugging
    misleading.
    """

    providers: list[ElementProvider] = []
    if bool(getattr(config, "ENABLE_UIAUTOMATOR_PROVIDER", True)):
        providers.append(UIAutomatorProvider(action))
    if bool(getattr(config, "ENABLE_TEMPLATE_PROVIDER", True)):
        registry = _load_template_registry(template_registry_path)
        if registry is not None and registry.all():
            providers.append(TemplateProvider(registry))
    if bool(getattr(config, "ENABLE_DETECTOR_PROVIDER", False)):
        providers.append(
            DetectorProvider(
                model_path=str(getattr(config, "DETECTOR_MODEL_PATH", "") or ""),
                threshold=float(getattr(config, "DETECTOR_CONFIDENCE_THRESHOLD", 0.5)),
            )
        )
    llm_provider = LLMProvider(cv) if bool(getattr(config, "ENABLE_LLM_FALLBACK", True)) else None
    return ElementFinder(
        providers,
        llm_provider=llm_provider,
        mode=str(getattr(config, "PERCEPTION_MODE", "llm_first") or "llm_first"),
        enable_llm_fallback=bool(getattr(config, "ENABLE_LLM_FALLBACK", True)),
        state_cache=DEFAULT_STATE_CACHE,
    )


def _load_template_registry(path: str | Path | None) -> TemplateRegistry | None:
    registry_path = Path(path) if path else DEFAULT_TEMPLATE_REGISTRY
    if not registry_path.exists():
        logger.debug(f"Template registry not found: {registry_path}")
        return None
    return TemplateRegistry.from_file(registry_path)
