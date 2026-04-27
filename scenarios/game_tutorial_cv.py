"""Configured game onboarding driven by CV autopilot."""
from __future__ import annotations

import random

from loguru import logger

import config
from core.cv_autopilot import BLOCKER_WORDS, CVAutopilot
from core.cv_engine import CVEngine
from core.cv_prompt_templates import TUTORIAL_GOAL_TEMPLATE, render_prompt_template
from core.game_profiles import GameProfile
from scenarios.base import BaseScenario
from scenarios.manual_control import ManualControlScenario


class GameTutorialCVScenario(BaseScenario):
    """Use screenshots and Vision plans to reach the configured game's lobby."""

    NAME = "game_tutorial_cv"

    async def run(self) -> bool:
        logger.info("=" * 50)
        logger.info(f"SCENARIO: {self.game_name} Tutorial (CV)")
        logger.info("=" * 50)

        self._log_step(f"Ensuring {self.game_name} is running...")
        pkg = (await self.action.get_current_package() or "").lower()
        if self.package_name.lower() not in pkg:
            await self.action.open_app(self.package_name)
        await self.action.wake_up()
        await self.dismiss_popups(max_attempts=3)

        player_name = f"{self.player_name_prefix}{random.randint(10000, 99999)}"
        autopilot = CVAutopilot(
            action=self.action,
            cv=CVEngine(),
            max_steps=self._max_steps(),
            allow_risky_actions=False,
            stop_on_risky_action=True,
            blocker_words=self._blocker_words(),
        )
        try:
            result = await autopilot.run(
                self._goal_text(),
                {
                    "player_name": player_name,
                    "clear_before_type": "1",
                    "coordinate_scale": getattr(config, "CV_COORDINATE_SCALE", ""),
                },
            )
        except RuntimeError as e:
            if self._manual_fallback_enabled(e):
                logger.warning(f"CV tutorial unavailable, switching to manual checkpoint: {e}")
                return await ManualControlScenario(
                    cv=None,
                    action=self.action,
                    stage_name="tutorial",
                    hint=(
                        f"Complete {self.game_name} onboarding/tutorial manually, "
                        "then press Continue Automation in the dashboard."
                    ),
                ).run()
            raise
        logger.info(f"CV tutorial result: {result.status} ({result.reason})")
        if not result.ok:
            raise RuntimeError(f"CV tutorial failed: {result.reason}")
        return True

    @property
    def game_name(self) -> str:
        return getattr(config, "GAME_NAME", "Brawl Stars") or "Brawl Stars"

    @property
    def package_name(self) -> str:
        return getattr(config, "GAME_PACKAGE", "")

    @property
    def player_name_prefix(self) -> str:
        return getattr(config, "GAME_PLAYER_NAME_PREFIX", "Player") or "Player"

    @property
    def profile(self) -> GameProfile:
        return getattr(config, "SELECTED_GAME_PROFILE", None) or GameProfile(
            id="custom",
            name=self.game_name,
            package=self.package_name,
        )

    def _max_steps(self) -> int:
        profile_steps = int(getattr(self.profile, "max_tutorial_steps", 0) or 0)
        return profile_steps or getattr(config, "CV_GAME_TUTORIAL_MAX_STEPS", 70)

    def _blocker_words(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((
            *BLOCKER_WORDS,
            *self.profile.blocker_words,
            *getattr(config, "CV_EXTRA_BLOCKER_WORDS", ()),
        )))

    def _goal_text(self) -> str:
        profile_hints = " ".join(self.profile.tutorial_hints)
        strategy = self.profile.gameplay_strategy
        strategy_hint = ""
        if strategy == "fast_runner":
            strategy_hint = (
                "This is a realtime runner: complete menus/onboarding and use done "
                "as soon as active running gameplay starts so the fast local gesture "
                "loop can take over. "
            )
        elif strategy == "solver_required":
            strategy_hint = (
                "This game may require a puzzle solver for unguided levels; follow "
                "only clearly highlighted tutorial moves and use done at the main map, "
                "lobby, or first shop-ready screen. "
            )
        template = getattr(config, "CV_TUTORIAL_GOAL_TEMPLATE", "") or TUTORIAL_GOAL_TEMPLATE
        return render_prompt_template(
            template,
            {
                "game_name": self.game_name,
                "package_name": self.package_name,
                "player_name_prefix": self.player_name_prefix,
                "player_name_key": "player_name",
                "strategy_hint": strategy_hint,
                "profile_hints": profile_hints,
                "operator_instructions": getattr(config, "CV_TUTORIAL_GOAL_EXTRA", ""),
            },
        )

    @staticmethod
    def _manual_fallback_enabled(error: RuntimeError) -> bool:
        if not getattr(config, "CV_FAILURE_FALLBACK_TO_MANUAL", False):
            return False
        return "CV models failed" in str(error)
