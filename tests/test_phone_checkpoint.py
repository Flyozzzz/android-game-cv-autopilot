import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_phone_checkpoint_exception_message():
    from scenarios.phone_checkpoint import PhoneVerificationReached

    exc = PhoneVerificationReached("phone_input")

    assert "phone_input" in str(exc)
    assert exc.stage == "phone_input"


def test_main_allows_missing_phone_when_stop_at_phone(monkeypatch):
    import main

    monkeypatch.setattr(main.config, "GOOGLE_PHONE_MODE", "manual")
    monkeypatch.setattr(main.config, "GOOGLE_PHONE_NUMBER", "")
    monkeypatch.setattr(main.config, "GOOGLE_EMAIL", "")
    monkeypatch.setattr(main.config, "GOOGLE_PASSWORD", "")
    monkeypatch.setattr(main.config, "TEST_RUN", False)
    monkeypatch.setattr(main.config, "GOOGLE_STOP_AT_PHONE_VERIFICATION", True, raising=False)

    assert main._manual_registration_missing_phone({"google"}) is False
