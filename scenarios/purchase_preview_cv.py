"""Safe purchase-preview flow for the configured game driven by CV autopilot."""
from __future__ import annotations

import asyncio

from loguru import logger

import config
from core.cv_autopilot import BLOCKER_WORDS, CVAutopilot
from core.cv_engine import CVEngine
from core.cv_prompt_templates import PURCHASE_GOAL_TEMPLATE, render_prompt_template
from core.game_profiles import GameProfile
from scenarios.base import BaseScenario
from scenarios.manual_control import ManualControlScenario


class PurchasePreviewCVScenario(BaseScenario):
    """Open an IAP preview or billing sheet, then stop before confirming payment."""

    NAME = "purchase_preview_cv"

    async def run(self) -> bool:
        logger.info("=" * 50)
        logger.info("SCENARIO: Purchase Preview (CV, no confirmation)")
        logger.info("=" * 50)

        self._log_step(f"Ensuring {self.game_name} is running...")
        pkg = (await self.action.get_current_package() or "").lower()
        if self.package_name.lower() not in pkg:
            await self.action.open_app(self.package_name)
            await asyncio.sleep(12)
        await self.dismiss_popups(max_attempts=3)

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
                {"coordinate_scale": getattr(config, "CV_COORDINATE_SCALE", "")},
            )
        except RuntimeError as e:
            if self._manual_fallback_enabled(e):
                logger.warning(f"CV purchase preview unavailable, switching to manual checkpoint: {e}")
                return await ManualControlScenario(
                    cv=None,
                    action=self.action,
                    stage_name="purchase_preview",
                    hint=(
                        "Open the shop manually and stop before any Buy/Pay/Confirm "
                        "button, then press Continue Automation in the dashboard."
                    ),
                ).run()
            raise
        logger.info(f"CV purchase preview result: {result.status} ({result.reason})")
        if not result.ok:
            raise RuntimeError(f"CV purchase preview failed: {result.reason}")

        if not getattr(config, "PURCHASE_PREVIEW_LEAVE_OPEN", False):
            self._log_step("Backing out of purchase preview without confirming payment")
            await self.action.press_back()
            await asyncio.sleep(1)
            await self.dismiss_popups(max_attempts=2)
        return True

    @property
    def game_name(self) -> str:
        return getattr(config, "GAME_NAME", "Brawl Stars") or "Brawl Stars"

    @property
    def package_name(self) -> str:
        return getattr(config, "GAME_PACKAGE", "")

    @property
    def profile(self) -> GameProfile:
        return getattr(config, "SELECTED_GAME_PROFILE", None) or GameProfile(
            id="custom",
            name=self.game_name,
            package=self.package_name,
        )

    def _blocker_words(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((
            *BLOCKER_WORDS,
            *self.profile.blocker_words,
            *getattr(config, "CV_EXTRA_BLOCKER_WORDS", ()),
        )))

    def _max_steps(self) -> int:
        profile_steps = int(getattr(self.profile, "max_purchase_steps", 0) or 0)
        return profile_steps or getattr(config, "CV_PURCHASE_PREVIEW_MAX_STEPS", 45)

    def _goal_text(self) -> str:
        profile_hints = " ".join(self.profile.purchase_hints)
        template = getattr(config, "CV_PURCHASE_GOAL_TEMPLATE", "") or PURCHASE_GOAL_TEMPLATE
        return render_prompt_template(
            template,
            {
                "game_name": self.game_name,
                "package_name": self.package_name,
                "profile_hints": profile_hints,
                "operator_instructions": getattr(config, "CV_PURCHASE_GOAL_EXTRA", ""),
            },
        )

    @staticmethod
    def _manual_fallback_enabled(error: RuntimeError) -> bool:
        if not getattr(config, "CV_FAILURE_FALLBACK_TO_MANUAL", False):
            return False
        return "CV models failed" in str(error)
