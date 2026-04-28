"""LLM Autopilot Builder package.

The builder creates reusable autopilot bundles. LLM calls are limited to
analysis/generation/repair; runtime execution remains local-first.
"""

from core.autobuilder.builder import AutopilotBuilder, BuildOptions

__all__ = ["AutopilotBuilder", "BuildOptions"]
