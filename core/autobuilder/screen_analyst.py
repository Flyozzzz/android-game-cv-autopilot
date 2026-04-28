"""LLM-backed structured screen analyst for unknown stable screens."""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from core.autobuilder.budgets import BudgetCounter
from core.autobuilder.safety_policy import SafetyPolicy
from core.autobuilder.schemas import SchemaValidationError, validate_schema
from core.cv_engine import CVEngine


LLMCallable = Callable[[str, bytes], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class ScreenAnalysisResult:
    screen_type: str
    summary: str
    safe_elements: list[dict[str, Any]] = field(default_factory=list)
    risky_elements: list[dict[str, Any]] = field(default_factory=list)
    next_best_goal: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "screen_type": self.screen_type,
            "summary": self.summary,
            "safe_elements": self.safe_elements,
            "risky_elements": self.risky_elements,
            "next_best_goal": self.next_best_goal,
        }


class ScreenAnalyst:
    def __init__(
        self,
        *,
        api_key: str = "",
        models: list[str] | None = None,
        llm: LLMCallable | None = None,
        max_retries: int = 1,
    ):
        self.api_key = api_key
        self.models = models
        self.llm = llm
        self.max_retries = max(0, int(max_retries))

    async def analyze(
        self,
        *,
        screenshot: bytes,
        visible_texts: list[str],
        goal: Any,
        policy: SafetyPolicy,
        screen_graph: Any,
        budget_counter: BudgetCounter | None = None,
    ) -> ScreenAnalysisResult:
        prompt = _analysis_prompt(visible_texts, goal, screen_graph)
        last_error = ""
        for attempt in range(self.max_retries + 1):
            if budget_counter:
                budget_counter.consume("max_llm_calls_per_build")
            try:
                raw = await self._call(prompt, screenshot)
                result = _parse_analysis(raw)
                safe = []
                risky = list(result.risky_elements)
                for element in result.safe_elements:
                    decision = policy.check_action(element)
                    if decision.allowed and not decision.required_review:
                        safe.append(element)
                    else:
                        risky.append({**element, "reason": decision.reason})
                return ScreenAnalysisResult(
                    screen_type=result.screen_type,
                    summary=result.summary,
                    safe_elements=safe,
                    risky_elements=risky,
                    next_best_goal=result.next_best_goal,
                )
            except Exception as exc:
                last_error = str(exc)
                if attempt >= self.max_retries:
                    raise RuntimeError(f"screen analysis failed: {last_error}") from exc
    async def _call(self, prompt: str, screenshot: bytes) -> dict[str, Any]:
        if self.llm is not None:
            return await self.llm(prompt, screenshot)
        if not self.api_key:
            raise RuntimeError("ScreenAnalyst requires api_key or llm callable")
        async with CVEngine(api_key=self.api_key, models=self.models) as cv:
            result = await cv._call_vision(prompt, base64.b64encode(screenshot).decode("utf-8"))
        data = cv._extract_json_from_text(result)
        if not isinstance(data, dict):
            raise RuntimeError("LLM screen analysis returned invalid JSON")
        return data


def _analysis_prompt(visible_texts: list[str], goal: Any, screen_graph: Any) -> str:
    return f"""Analyze this Android screen for an autopilot builder.
Return ONLY JSON:
{{
  "screen_type": "menu|dialog|gameplay|loading|purchase|login|unknown",
  "summary": "short summary",
  "safe_elements": [
    {{"name":"play_button","description":"visible Play button","roi":"bottom_buttons","recommended_action":"tap","bbox":[0,0,1,1],"confidence":0.9}}
  ],
  "risky_elements": [
    {{"name":"shop_button","reason":"may lead to purchase"}}
  ],
  "next_best_goal": "tap_play_button"
}}
Goal: {getattr(goal, 'goal', goal)}
Visible texts: {json.dumps(visible_texts, ensure_ascii=False)}
Known screens: {json.dumps(getattr(screen_graph, 'to_dict', lambda: {})(), ensure_ascii=False)[:4000]}
Never execute actions; analysis only."""


def _parse_analysis(data: dict[str, Any]) -> ScreenAnalysisResult:
    validate_schema("screen_analysis", data)
    safe = data.get("safe_elements")
    risky = data.get("risky_elements")
    return ScreenAnalysisResult(
        screen_type=str(data.get("screen_type") or "unknown"),
        summary=str(data.get("summary") or ""),
        safe_elements=[dict(item) for item in safe if isinstance(item, dict)],
        risky_elements=[dict(item) for item in risky if isinstance(item, dict)],
        next_best_goal=str(data.get("next_best_goal") or ""),
    )
