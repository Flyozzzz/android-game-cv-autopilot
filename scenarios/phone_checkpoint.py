"""Checkpoint exceptions for partial Google registration smoke tests."""
from __future__ import annotations


class PhoneVerificationReached(RuntimeError):
    """Raised when the flow intentionally stops at phone verification."""

    def __init__(self, stage: str = "phone_verification"):
        self.stage = stage
        super().__init__(
            f"Google phone verification checkpoint reached (stage={stage}). "
            "Stop requested before entering/verifying a phone number."
        )
