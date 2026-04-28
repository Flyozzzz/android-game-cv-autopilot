"""Element finder that runs providers and fuses their candidates."""
from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Sequence

import config
from core.frame_source import Frame
from core.metrics import TraceEvent, new_run_id, record_latency, record_trace
from core.perception.element import ElementCandidate
from core.perception.fusion import FusionEngine, RankedCandidate
from core.perception.providers.base import ElementProvider, ProviderContext
from core.perception.roi import PixelBox
from core.perception.state_cache import ScreenStateCache


@dataclass(frozen=True)
class ElementFindResult:
    candidate: ElementCandidate | None
    ranked_candidates: list[RankedCandidate]
    providers_called: list[str]
    llm_called: bool

    @property
    def found(self) -> bool:
        return self.candidate is not None


class ElementFinder:
    """Run local providers first, then optional LLM fallback by rollout mode."""

    def __init__(
        self,
        providers: Sequence[ElementProvider],
        *,
        llm_provider: ElementProvider | None = None,
        fusion: FusionEngine | None = None,
        mode: str | None = None,
        min_confidence: float = 0.65,
        enable_llm_fallback: bool | None = None,
        state_cache: ScreenStateCache | None = None,
    ):
        self.providers = list(providers)
        self.llm_provider = llm_provider
        self.fusion = fusion or FusionEngine()
        self.mode = (mode or getattr(config, "PERCEPTION_MODE", "llm_first")).strip().lower()
        self.min_confidence = max(0.0, min(1.0, float(min_confidence)))
        self.enable_llm_fallback = (
            bool(getattr(config, "ENABLE_LLM_FALLBACK", True))
            if enable_llm_fallback is None
            else bool(enable_llm_fallback)
        )
        self.state_cache = state_cache

    async def find(
        self,
        frame: Frame,
        *,
        goal: str,
        roi: PixelBox | None = None,
        screen_id: str = "",
        profile_id: str = "",
        run_id: str | None = None,
    ) -> ElementFindResult:
        run_id = run_id or new_run_id()
        context = ProviderContext(
            frame=frame,
            goal=goal,
            roi=roi,
            screen_id=screen_id,
            profile_id=profile_id,
        )
        providers_called: list[str] = []
        candidates: list[ElementCandidate] = []
        latency_breakdown: dict[str, float] = {}
        llm_called = False

        cached = self.state_cache.get(frame, profile_id=profile_id, roi=roi) if self.state_cache else None
        if cached and cached.last_elements:
            candidates = list(cached.last_elements)
            ranked = self.fusion.rank(candidates, goal=goal, roi=roi)
            selected = ranked[0].candidate if ranked else None
            record_trace(
                TraceEvent(
                    run_id=run_id,
                    profile_id=profile_id,
                    screen_id=cached.screen_id,
                    frame_source=frame.source_name,
                    goal=goal,
                    roi={"pixel_box": roi} if roi else None,
                    providers_called=["cache"],
                    candidates=[candidate.to_dict() for candidate in candidates],
                    selected_candidate=selected.to_dict() if selected else None,
                    latency_breakdown={},
                    llm_called=False,
                )
            )
            return ElementFindResult(
                candidate=selected,
                ranked_candidates=ranked,
                providers_called=["cache"],
                llm_called=False,
            )

        if self.mode == "llm_first" and self._llm_allowed():
            llm_candidates, elapsed = await self._run_provider(self.llm_provider, context)
            providers_called.append(self.llm_provider.name)
            latency_breakdown[_metric_name(self.llm_provider.name)] = elapsed
            llm_called = True
            candidates.extend(llm_candidates)
        else:
            local_candidates, local_calls, local_latencies = await self._run_local(context)
            candidates.extend(local_candidates)
            providers_called.extend(local_calls)
            latency_breakdown.update(local_latencies)
            ranked_local = self.fusion.rank(candidates, goal=goal, roi=roi)
            best_local = ranked_local[0].candidate if ranked_local else None
            if self._should_call_llm(best_local):
                llm_candidates, elapsed = await self._run_provider(self.llm_provider, context)
                providers_called.append(self.llm_provider.name)
                latency_breakdown[_metric_name(self.llm_provider.name)] = elapsed
                llm_called = True
                if self.mode == "shadow":
                    candidates = llm_candidates + candidates
                else:
                    candidates.extend(llm_candidates)

        ranked = self.fusion.rank(candidates, goal=goal, roi=roi)
        selected = self._select_candidate(ranked, llm_called=llm_called)
        if self.state_cache is not None and candidates:
            cached_screen_id = screen_id or ((selected.screen_id or "") if selected else "")
            self.state_cache.put(
                frame,
                screen_id=cached_screen_id,
                profile_id=profile_id,
                elements=candidates,
            )
        record_trace(
            TraceEvent(
                run_id=run_id,
                profile_id=profile_id,
                screen_id=screen_id,
                frame_source=frame.source_name,
                goal=goal,
                roi={"pixel_box": roi} if roi else None,
                providers_called=providers_called,
                candidates=[candidate.to_dict() for candidate in candidates],
                selected_candidate=selected.to_dict() if selected else None,
                latency_breakdown=latency_breakdown,
                llm_called=llm_called,
            )
        )
        return ElementFindResult(
            candidate=selected,
            ranked_candidates=ranked,
            providers_called=providers_called,
            llm_called=llm_called,
        )

    async def _run_local(
        self,
        context: ProviderContext,
    ) -> tuple[list[ElementCandidate], list[str], dict[str, float]]:
        candidates: list[ElementCandidate] = []
        providers_called: list[str] = []
        latencies: dict[str, float] = {}
        for provider in self.providers:
            found, elapsed = await self._run_provider(provider, context)
            candidates.extend(found)
            providers_called.append(provider.name)
            latencies[_metric_name(provider.name)] = elapsed
        return candidates, providers_called, latencies

    async def _run_provider(
        self,
        provider: ElementProvider | None,
        context: ProviderContext,
    ) -> tuple[list[ElementCandidate], float]:
        if provider is None:
            return [], 0.0
        started = perf_counter()
        candidates = await provider.find(context)
        elapsed = round((perf_counter() - started) * 1000.0, 3)
        record_latency(_metric_name(provider.name), elapsed)
        return candidates, elapsed

    def _should_call_llm(self, best_local: ElementCandidate | None) -> bool:
        if not self._llm_allowed():
            return False
        if self.mode == "shadow":
            return True
        if self.mode == "local_first":
            return best_local is None or best_local.confidence < self.min_confidence
        return False

    def _llm_allowed(self) -> bool:
        return (
            self.llm_provider is not None
            and self.enable_llm_fallback
            and self.mode not in {"local_only"}
        )

    def _select_candidate(
        self,
        ranked: list[RankedCandidate],
        *,
        llm_called: bool,
    ) -> ElementCandidate | None:
        if not ranked:
            return None
        if self.mode == "shadow" and llm_called and self.llm_provider is not None:
            for item in ranked:
                if item.candidate.source == self.llm_provider.name:
                    return item.candidate
        return ranked[0].candidate


def _metric_name(provider_name: str) -> str:
    name = (provider_name or "unknown").strip().lower()
    if name in {"uiautomator", "template", "ocr", "detector", "llm"}:
        return f"provider_{name}_ms"
    return f"provider_{name}_ms"
