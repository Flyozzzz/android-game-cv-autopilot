import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_manual_phone_data_from_env(monkeypatch):
    from services.manual_verification import ManualVerification

    monkeypatch.setenv("GOOGLE_PHONE_NUMBER", "+15551234567")

    data = ManualVerification().phone_data()

    assert data == {
        "id": "manual",
        "phone": "+15551234567",
        "operator": "manual",
        "status": "MANUAL",
        "price": 0,
    }


def test_manual_phone_requires_number_when_not_interactive(monkeypatch):
    from services.manual_verification import ManualVerification

    monkeypatch.delenv("GOOGLE_PHONE_NUMBER", raising=False)

    with pytest.raises(RuntimeError, match="GOOGLE_PHONE_NUMBER"):
        ManualVerification(input_func=None).phone_data()


def test_manual_sms_code_from_env(monkeypatch):
    from services.manual_verification import ManualVerification

    monkeypatch.setenv("GOOGLE_SMS_CODE", "123456")

    code = asyncio.run(ManualVerification().wait_for_code(timeout=1, poll_interval=0.01))

    assert code == "123456"


def test_manual_sms_code_from_file(monkeypatch, tmp_path: Path):
    from services.manual_verification import ManualVerification

    code_file = tmp_path / "sms_code.txt"
    code_file.write_text("G-654321\n")
    monkeypatch.delenv("GOOGLE_SMS_CODE", raising=False)
    monkeypatch.setenv("GOOGLE_SMS_CODE_FILE", str(code_file))

    code = asyncio.run(ManualVerification().wait_for_code(timeout=1, poll_interval=0.01))

    assert code == "654321"
