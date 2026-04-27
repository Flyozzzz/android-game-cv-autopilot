"""
Readable diagnostics for external device-farm failures.

Provider API checks can pass while session allocation still fails because the
account is out of quota, the license expired, or the device pool is unavailable.
Keeping these messages normalized makes main.py fail with a useful next action.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderFailure:
    code: str
    title: str
    action: str


def classify_provider_error(farm: str, error: object) -> ProviderFailure | None:
    """Return a known provider failure for an exception/message."""
    farm = (farm or "").strip().lower()
    lowered = str(error or "").lower()

    if farm == "lambdatest":
        if "lifetime minutes exhausted" in lowered or "minutes exhausted" in lowered:
            return ProviderFailure(
                code="lambdatest_quota_exhausted",
                title="LambdaTest mobile-automation minutes are exhausted",
                action=(
                    "Top up or renew LambdaTest mobile automation minutes, or run "
                    "with DEVICE_FARM=local against a local emulator."
                ),
            )
        if "unauthorized" in lowered or "invalid username" in lowered or "access key" in lowered:
            return ProviderFailure(
                code="lambdatest_auth_failed",
                title="LambdaTest credentials were rejected",
                action="Check LT_USERNAME and LT_ACCESS_KEY before starting a session.",
            )

    if farm == "genymotion":
        if "license_expired" in lowered or "license expired" in lowered:
            return ProviderFailure(
                code="genymotion_license_expired",
                title="Genymotion Cloud license is expired",
                action=(
                    "Renew the Genymotion license, choose another available account, "
                    "or run with DEVICE_FARM=local."
                ),
            )
        if "unauthorized" in lowered or "401" in lowered:
            return ProviderFailure(
                code="genymotion_auth_failed",
                title="Genymotion API token was rejected",
                action="Check GENYMOTION_API_TOKEN.",
            )

    if farm == "browserstack":
        if "parallel" in lowered and ("limit" in lowered or "exceeded" in lowered):
            return ProviderFailure(
                code="browserstack_parallel_limit",
                title="BrowserStack parallel session limit is reached",
                action="Wait for another BrowserStack session to finish or increase the plan.",
            )
        if "unauthorized" in lowered or "access key" in lowered:
            return ProviderFailure(
                code="browserstack_auth_failed",
                title="BrowserStack credentials were rejected",
                action="Check BROWSERSTACK_USERNAME and BROWSERSTACK_ACCESS_KEY.",
            )

    if farm == "local":
        if "install_failed_user_restricted" in lowered or "install canceled by user" in lowered:
            return ProviderFailure(
                code="local_usb_install_restricted",
                title="Android device blocks Appium helper APK installation",
                action=(
                    "On the device, enable Developer options settings that allow USB installs "
                    "(on Xiaomi/MIUI: USB debugging, USB debugging (Security settings), and "
                    "Install via USB), keep the phone unlocked, then rerun with LOCAL_DEVICE set."
                ),
            )
        if "more than one device" in lowered or "multiple devices" in lowered:
            return ProviderFailure(
                code="local_multiple_devices",
                title="Multiple Android devices are connected",
                action="Set LOCAL_DEVICE to the target adb serial, for example LOCAL_DEVICE=<adb-serial>.",
            )

    return None


def format_provider_error(farm: str, error: object) -> str:
    """Human-readable one-block explanation for known provider failures."""
    failure = classify_provider_error(farm, error)
    if not failure:
        return ""
    return (
        f"{failure.title} [{failure.code}]. "
        f"Action: {failure.action}"
    )
