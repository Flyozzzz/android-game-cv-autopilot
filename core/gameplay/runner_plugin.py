"""Stateful runner-game plugin built on top of local lane detection."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from core.fast_runner import FastRunnerDecision, FastRunnerDetector
from core.frame_source import Frame
from core.gameplay.base_plugin import GameplayAction


class RunnerState(str, Enum):
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    JUMPING = "JUMPING"
    DUCKING = "DUCKING"
    LANE_SWITCHING = "LANE_SWITCHING"
    RECOVERING = "RECOVERING"
    GAME_OVER = "GAME_OVER"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class RunnerPluginDecision:
    action: GameplayAction
    state: RunnerState
    lane_scores: tuple[float, float, float]
    score_velocity: tuple[float, float, float]
    danger: bool
    frame_index: int


class RunnerPlugin:
    """Track runner lane danger and emit cooldown-aware gesture actions."""

    def __init__(
        self,
        *,
        detector: FastRunnerDetector | None = None,
        danger_threshold: float = 42.0,
        rising_danger_ratio: float = 0.75,
        frame_skip: int = 1,
    ):
        self.detector = detector or FastRunnerDetector(obstacle_threshold=danger_threshold)
        self.danger_threshold = float(danger_threshold)
        self.rising_danger_ratio = float(rising_danger_ratio)
        self.frame_skip = max(1, int(frame_skip or 1))
        self.state = RunnerState.STARTING
        self._last_scores: tuple[float, float, float] | None = None
        self._frame_index = 0

    def should_process(self) -> bool:
        return (self._frame_index - 1) % self.frame_skip == 0

    def decide(self, frame: Frame | bytes) -> RunnerPluginDecision:
        self._frame_index += 1
        if not self.should_process():
            return RunnerPluginDecision(
                action=GameplayAction("none", "frame skipped", confidence=0.0),
                state=self.state,
                lane_scores=self._last_scores or (0.0, 0.0, 0.0),
                score_velocity=(0.0, 0.0, 0.0),
                danger=False,
                frame_index=self._frame_index,
            )

        png = frame.png_bytes if isinstance(frame, Frame) else frame
        if not png:
            self.state = RunnerState.UNKNOWN
            return RunnerPluginDecision(
                action=GameplayAction("none", "missing frame", confidence=0.0),
                state=self.state,
                lane_scores=(0.0, 0.0, 0.0),
                score_velocity=(0.0, 0.0, 0.0),
                danger=False,
                frame_index=self._frame_index,
            )

        base_decision = self.detector.decide(png)
        velocity = self._velocity(base_decision.lane_scores)
        danger = self._danger(base_decision, velocity)
        action = self._action_from_decision(base_decision, danger)
        self._last_scores = base_decision.lane_scores
        self.state = self._next_state(action)
        return RunnerPluginDecision(
            action=action,
            state=self.state,
            lane_scores=base_decision.lane_scores,
            score_velocity=velocity,
            danger=danger,
            frame_index=self._frame_index,
        )

    @staticmethod
    def gesture_points(
        width: int,
        height: int,
        gesture: str,
    ) -> tuple[int, int, int, int]:
        points = {
            "left": (int(width * 0.55), int(height * 0.74), int(width * 0.25), int(height * 0.74)),
            "right": (int(width * 0.45), int(height * 0.74), int(width * 0.75), int(height * 0.74)),
            "up": (int(width * 0.50), int(height * 0.76), int(width * 0.50), int(height * 0.42)),
            "down": (int(width * 0.50), int(height * 0.42), int(width * 0.50), int(height * 0.78)),
        }
        return points[gesture]

    def _velocity(self, scores: tuple[float, float, float]) -> tuple[float, float, float]:
        if self._last_scores is None:
            return (0.0, 0.0, 0.0)
        return tuple(round(current - previous, 3) for current, previous in zip(scores, self._last_scores))

    def _danger(self, decision: FastRunnerDecision, velocity: tuple[float, float, float]) -> bool:
        center_score = decision.lane_scores[1]
        return (
            center_score >= self.danger_threshold
            or (
                center_score >= self.danger_threshold * self.rising_danger_ratio
                and velocity[1] > 0
            )
        )

    @staticmethod
    def _action_from_decision(decision: FastRunnerDecision, danger: bool) -> GameplayAction:
        if decision.gesture == "none" or not danger:
            return GameplayAction("none", decision.reason, confidence=0.0)
        cooldown_key = {
            "left": "lane_change",
            "right": "lane_change",
            "up": "jump",
            "down": "duck",
        }.get(decision.gesture, "runner_gesture")
        confidence = min(1.0, max(decision.lane_scores) / 100.0)
        return GameplayAction(
            decision.gesture,
            decision.reason,
            cooldown_key=cooldown_key,
            confidence=round(confidence, 3),
        )

    @staticmethod
    def _next_state(action: GameplayAction) -> RunnerState:
        if action.gesture == "left" or action.gesture == "right":
            return RunnerState.LANE_SWITCHING
        if action.gesture == "up":
            return RunnerState.JUMPING
        if action.gesture == "down":
            return RunnerState.DUCKING
        return RunnerState.RUNNING
