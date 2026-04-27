import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.provider_errors import classify_provider_error, format_provider_error


def test_lambdatest_quota_error_is_actionable():
    failure = classify_provider_error(
        "lambdatest",
        "Message: Lifetime Minutes Exhausted for mobile-automation",
    )

    assert failure is not None
    assert failure.code == "lambdatest_quota_exhausted"
    assert "DEVICE_FARM=local" in failure.action


def test_genymotion_license_error_is_actionable():
    hint = format_provider_error(
        "genymotion",
        'HTTP 403: {"code":"LICENSE_EXPIRED","message":"Unknown error"}',
    )

    assert "Genymotion Cloud license is expired" in hint
    assert "genymotion_license_expired" in hint


def test_unknown_provider_error_has_no_hint():
    assert classify_provider_error("local", "connection refused") is None


def test_local_usb_install_restriction_is_actionable():
    failure = classify_provider_error(
        "local",
        "Failure [INSTALL_FAILED_USER_RESTRICTED: Install canceled by user]",
    )

    assert failure is not None
    assert failure.code == "local_usb_install_restricted"
    assert "Install via USB" in failure.action
