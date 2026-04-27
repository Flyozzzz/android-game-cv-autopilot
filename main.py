"""
═══════════════════════════════════════════════════════════════════
 Clash Royale Automation Bot

 Полный автоматический сценарий (< 3 минут):
 1. Запуск Android-устройства (Genymotion Cloud)
 2. Регистрация нового Google-аккаунта (через 5sim.net)
 3. Настройка Google Pay (добавление карты)
 4. Установка Clash Royale из Play Store
 5. Прохождение туториала
 6. Покупка через Google Pay

 БЕЗ CV — всё через UIAutomator2 deterministic flow.
 Целевое время: < 3 минут.
═══════════════════════════════════════════════════════════════════
"""
import asyncio
import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx
from loguru import logger

import config
from core.action_engine import ActionEngine
from core.appium_action_engine import AppiumActionEngine
from core.game_profiles import format_profiles_for_cli, resolve_game_profile
from core.helpers import ensure_dir
from core.run_report import RunReport
from services.device_farm import GenymotionCloud
from services.browserstack_farm import BrowserStackFarm
from services.local_farm import LocalEmulatorFarm
from services.lambdatest_farm import LambdaTestFarm
from services.sms_service import SMSService
from scenarios.google_register import GoogleRegisterScenario
from scenarios.google_register_web import GoogleRegisterWebScenario
from scenarios.google_register_chrome import GoogleRegisterChromeScenario
from scenarios.google_register_cv import GoogleRegisterCVScenario
from scenarios.google_login import GoogleLoginScenario
from scenarios.google_play_signin import GooglePlaySigninScenario
from scenarios.google_pay import GooglePayScenario
from scenarios.install_game import InstallGameScenario
from scenarios.install_game_cv import InstallGameCVScenario
from scenarios.game_tutorial import GameTutorialScenario
from scenarios.game_tutorial_cv import GameTutorialCVScenario
from scenarios.fast_runner_gameplay import FastRunnerGameplayScenario
from scenarios.match3_gameplay import Match3GameplayScenario
from scenarios.manual_control import ManualControlScenario
from scenarios.recorded_actions import RecordedActionsScenario
from scenarios.payment import PaymentScenario
from scenarios.purchase_preview_cv import PurchasePreviewCVScenario
from scenarios.phone_checkpoint import PhoneVerificationReached
from bootstrap import check_all_apis, check_config
from services.provider_errors import format_provider_error


# ─── Настройка логов ───
logger.remove()
logger.add(
    sys.stdout,
    format=(
        "<green>{time:HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    ),
    level="INFO",
)
logger.add(
    "logs/run_{time:YYYYMMDD_HHmmss}.log",
    rotation="10 MB",
    level="DEBUG",
)


def save_credentials(credentials: dict):
    """Сохранить учётные данные нового аккаунта в credentials.json."""
    filepath = Path(getattr(config, "CREDENTIALS_JSON_PATH", "credentials.json"))
    existing = []
    if filepath.exists():
        try:
            existing = json.loads(filepath.read_text())
        except Exception:
            existing = []
    existing.append(credentials)
    filepath.write_text(json.dumps(existing, indent=2, ensure_ascii=False))
    logger.info(f"Credentials saved to {filepath}")


def load_last_saved_google_login() -> dict | None:
    """
    Последняя запись из credentials.json для входа (full_email + password).
    """
    filepath = Path(getattr(config, "CREDENTIALS_JSON_PATH", "credentials.json"))
    if not filepath.exists():
        return None
    try:
        data = json.loads(filepath.read_text())
    except Exception:
        return None
    if not data:
        return None
    if isinstance(data, dict):
        last = data
    else:
        last = data[-1]
    email = (last.get("full_email") or last.get("email") or "").strip()
    password = (last.get("password") or "").strip()
    if not email or not password:
        return None
    out = dict(last)
    out["full_email"] = email
    out["password"] = password
    return out


def _selected_stages() -> set[str]:
    raw = (config.RUN_STAGES or "").strip()
    if not raw:
        return {"device", "google", "pay", "install", "tutorial", "gameplay", "purchase_preview"}
    return {s.strip().lower() for s in raw.split(",") if s.strip()}


def _apply_cli_args(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Android game CV autopilot")
    parser.add_argument("--list-games", action="store_true", help="show built-in game profiles")
    parser.add_argument("--game", help="profile id, game name, alias, or package")
    parser.add_argument("--game-name", help="custom display/search name")
    parser.add_argument("--game-package", help="Android package name")
    parser.add_argument("--stages", help="comma-separated stages, e.g. install,tutorial,purchase_preview")
    parser.add_argument("--purchase-mode", choices=("preview", "real"), help="purchase mode")
    args, unknown = parser.parse_known_args(argv)
    if unknown:
        logger.warning(f"Ignoring unknown CLI args: {unknown}")

    if args.list_games:
        print(format_profiles_for_cli())
        raise SystemExit(0)

    if args.stages:
        config.RUN_STAGES = args.stages
    if args.purchase_mode:
        config.PURCHASE_MODE = args.purchase_mode

    if args.game or args.game_name or args.game_package:
        profile = resolve_game_profile(
            args.game or args.game_name or args.game_package or "",
            game_name=args.game_name or "",
            package=args.game_package or "",
        )
        config.SELECTED_GAME_PROFILE = profile
        config.GAME_PROFILE = profile.id
        config.GAME_PROFILE_ID = profile.id
        config.GAME_NAME = args.game_name or profile.name
        config.GAME_PACKAGE = args.game_package or profile.package
        config.GAME_PLAYER_NAME_PREFIX = profile.player_name_prefix


def _manual_registration_missing_phone(stages: set[str]) -> bool:
    """True when this run will create a Google account in manual mode but has no phone."""
    if "google" not in stages:
        return False
    if getattr(config, "GOOGLE_PHONE_MODE", "manual") != "manual":
        return False
    if getattr(config, "GOOGLE_STOP_AT_PHONE_VERIFICATION", False):
        return False
    if config.GOOGLE_EMAIL and config.GOOGLE_PASSWORD:
        return False
    if getattr(config, "TEST_RUN", False) and load_last_saved_google_login():
        return False
    return not bool(getattr(config, "GOOGLE_PHONE_NUMBER", "").strip())


async def main():
    """Главная точка входа: полный сценарий автоматизации."""

    # Создаём папки
    ensure_dir("logs")
    ensure_dir("screenshots")
    ensure_dir("reports")
    if getattr(config, "TRACE_ENABLED", False):
        ensure_dir(config.TRACE_DIR)
        ensure_dir(str(Path(config.TRACE_DIR) / "screenshots"))

    start_time = time.time()
    report: RunReport | None = None
    final_status = "failed"
    final_error = ""
    current_stage = "startup"

    def elapsed() -> str:
        return f"[{time.time() - start_time:.1f}s]"

    logger.info("=" * 65)
    logger.info(f"  🎮 ANDROID GAME CV AUTOPILOT: {config.GAME_NAME}")
    logger.info("  Auto-register/Login → Install → Tutorial → Purchase preview")
    mode_label = (
        "CV autopilot"
        if getattr(config, "GOOGLE_REGISTER_VIA", "") == "cv"
        else "UIAutomator2 (no CV)"
    )
    logger.info(f"  Mode: {mode_label}")
    logger.info("=" * 65)
    stages = _selected_stages()
    logger.info(f"Enabled stages: {sorted(stages)}")
    profile = getattr(config, "SELECTED_GAME_PROFILE", None)
    logger.info(
        f"Game profile: {getattr(config, 'GAME_PROFILE_ID', 'custom')} | "
        f"name={config.GAME_NAME!r} | package={config.GAME_PACKAGE!r} | "
        f"gameplay={getattr(profile, 'gameplay_strategy', 'none')}"
    )
    report = RunReport(
        game_profile_id=getattr(config, "GAME_PROFILE_ID", "custom"),
        game_name=config.GAME_NAME,
        game_package=config.GAME_PACKAGE,
        enabled_stages=sorted(stages),
    )

    # ═══════════════════════════════════════════
    # PHASE 0: Проверка конфигурации и API
    # ═══════════════════════════════════════════
    current_stage = "preflight"
    logger.info(f"\n{elapsed()} PHASE 0: Pre-flight checks")

    warnings = await check_config()
    if warnings:
        logger.warning(
            f"Config warnings: {warnings}. Continuing..."
        )

    if _manual_registration_missing_phone(stages):
        msg = (
            "GOOGLE_PHONE_MODE=manual registration requires your real phone number. "
            "Set GOOGLE_PHONE_NUMBER=+15551234567 and GOOGLE_SMS_CODE_FILE=/tmp/google_sms_code.txt "
            "before running."
        )
        logger.error(msg)
        report.record("preflight", "failed", msg)
        report.write(final_status="failed", error=msg)
        raise RuntimeError(msg)

    if {"install", "tutorial", "purchase", "purchase_preview"} & stages and not config.GAME_PACKAGE:
        msg = (
            "GAME_PACKAGE is empty. Use --game with a built-in profile, "
            "--game-package, or GAME_PACKAGE=com.example.game."
        )
        report.record("preflight", "failed", msg)
        report.write(final_status="failed", error=msg)
        raise RuntimeError(msg)

    # 5sim нужен только для стадии google при регистрации в legacy fivesim-режиме.
    phone_mode = getattr(config, "GOOGLE_PHONE_MODE", "manual")
    skip_fivesim = "google" not in stages or phone_mode != "fivesim"
    if "google" in stages:
        if config.GOOGLE_EMAIL and config.GOOGLE_PASSWORD:
            skip_fivesim = True
        elif getattr(config, "TEST_RUN", False) and load_last_saved_google_login():
            skip_fivesim = True

    api_status = await check_all_apis(skip_fivesim=skip_fivesim)
    if config.DEVICE_FARM == "browserstack":
        if not api_status.get("browserstack"):
            logger.error("BrowserStack API is required! Aborting.")
            report.record("preflight", "failed", "BrowserStack API is required")
            report.write(final_status="failed", error="BrowserStack API is required")
            return
    elif config.DEVICE_FARM == "lambdatest":
        if not api_status.get("lambdatest"):
            logger.error("LambdaTest API is required! Aborting.")
            report.record("preflight", "failed", "LambdaTest API is required")
            report.write(final_status="failed", error="LambdaTest API is required")
            return
    elif config.DEVICE_FARM == "local":
        if not api_status.get("local"):
            logger.error("Local Appium/emulator not ready! Aborting.")
            report.record("preflight", "failed", "Local Appium/emulator not ready")
            report.write(final_status="failed", error="Local Appium/emulator not ready")
            return
    else:
        if not api_status.get("genymotion"):
            logger.error("Genymotion API is required! Aborting.")
            report.record("preflight", "failed", "Genymotion API is required")
            report.write(final_status="failed", error="Genymotion API is required")
            return
    if "google" in stages and not skip_fivesim and not api_status.get("5sim"):
        logger.error("5sim API is required for registration! Aborting.")
        report.record("preflight", "failed", "5sim API is required")
        report.write(final_status="failed", error="5sim API is required")
        return
    report.record("preflight", "success", "configuration and API checks passed")

    # ═══════════════════════════════════════════
    # PHASE 1: Запуск Android-устройства
    # ═══════════════════════════════════════════
    current_stage = "device"
    logger.info(f"\n{elapsed()} PHASE 1: Starting Android device (farm={config.DEVICE_FARM})")

    sms = SMSService()
    action = None
    registered_credentials = None

    if config.DEVICE_FARM == "browserstack":
        farm = BrowserStackFarm()
    elif config.DEVICE_FARM == "lambdatest":
        farm = LambdaTestFarm()
    elif config.DEVICE_FARM == "local":
        farm = LocalEmulatorFarm()
    else:
        farm = GenymotionCloud()

    try:
        if config.DEVICE_FARM in ("browserstack", "lambdatest", "local"):
            # ── BrowserStack/LambdaTest/Local: запуск Appium-сессии ──
            driver = await farm.start_session()
            action = AppiumActionEngine(driver=driver)
            await action.connect()

            resolution = await action.get_screen_resolution()
            config.SCREEN_WIDTH, config.SCREEN_HEIGHT = resolution[0], resolution[1]
            device_info = await action.get_device_info()
            farm_label = (
                "Local Android"
                if config.DEVICE_FARM == "local"
                else "BrowserStack"
                if config.DEVICE_FARM == "browserstack"
                else "LambdaTest"
            )
            logger.success(
                f"{elapsed()} {farm_label} device ready: "
                f"{device_info['model']} "
                f"(Android {device_info['android_version']}, "
                f"{resolution[0]}x{resolution[1]})"
            )

        else:
            # ── Genymotion Cloud: старт инстанса + ADB ──
            if getattr(config, "STOP_RUNNING_INSTANCES_ON_START", False):
                logger.info(f"{elapsed()} Stopping existing cloud instances before start...")
                try:
                    await farm.stop_all_instances()
                except Exception as e:
                    logger.warning(f"Could not stop existing instances: {e}")
                logger.info(f"{elapsed()} Waiting for instances to terminate...")
                for _w in range(24):
                    await asyncio.sleep(5)
                    try:
                        remaining = await farm.list_instances()
                        if not remaining:
                            logger.info(f"{elapsed()} All instances stopped.")
                            break
                        logger.debug(f"  Still {len(remaining)} instance(s) running...")
                    except Exception:
                        break
                else:
                    logger.warning("Instances still running after 120s wait — proceeding anyway")

            recipe = await farm.resolve_startup_recipe()
            logger.info(
                f"{elapsed()} Selected recipe: {recipe.get('name')} "
                f"(Android {recipe.get('android_version')})"
            )

            started = False
            start_errors: list[str] = []
            candidate_recipes = [recipe]
            custom_recipe = bool(
                (getattr(config, "GENYMOTION_RECIPE_UUID", "") or "").strip()
                or (getattr(config, "GENYMOTION_RECIPE_NAME_CONTAINS", "") or "").strip()
            )
            allow_recipe_fallback = bool(
                getattr(config, "GENYMOTION_RECIPE_ALLOW_FALLBACK", True)
            )
            if (not custom_recipe) or allow_recipe_fallback:
                try:
                    all_recipes = await farm.list_recipes()
                    seen_recipe_ids = {recipe.get("uuid")}
                    for r in all_recipes:
                        if r.get("uuid") in seen_recipe_ids:
                            continue
                        seen_recipe_ids.add(r.get("uuid"))
                        candidate_recipes.append(r)
                except Exception:
                    pass

            for idx, rec in enumerate(candidate_recipes[:8], start=1):
                try:
                    logger.info(
                        f"{elapsed()} Start attempt {idx}: {rec.get('name')} "
                        f"(Android {rec.get('android_version')})"
                    )
                    await farm.start_instance(recipe_uuid=rec["uuid"])
                    started = True
                    recipe = rec
                    break
                except httpx.HTTPStatusError as e:
                    msg = f"{rec.get('name')}: HTTP {e.response.status_code}"
                    start_errors.append(msg)
                    logger.warning(f"Start failed ({msg}), trying next recipe...")
                    continue
                except Exception as e:
                    msg = f"{rec.get('name')}: {e}"
                    start_errors.append(msg)
                    logger.warning(f"Start failed ({msg}), trying next recipe...")
                    continue

            if not started:
                raise RuntimeError(
                    "Could not start any recipe. Errors: " + " | ".join(start_errors)
                )

            await farm.wait_for_ready(timeout=90)
            adb_serial = await farm.connect_adb()
            action = ActionEngine(adb_serial=adb_serial)
            connected = await action.connect()
            if not connected:
                raise RuntimeError(f"Cannot connect ADB to {adb_serial}")

            device_info = await action.get_device_info()
            resolution = await action.get_screen_resolution()
            config.SCREEN_WIDTH, config.SCREEN_HEIGHT = resolution[0], resolution[1]
            logger.success(
                f"{elapsed()} Device ready: "
                f"{device_info['model']} "
                f"(Android {device_info['android_version']}, "
                f"{resolution[0]}x{resolution[1]})"
            )

            # Google Play / GMS check
            has_gms = await action.is_package_installed("com.google.android.gms")
            has_store = await action.is_package_installed("com.android.vending")
            if has_gms and has_store:
                logger.success(f"{elapsed()} Google services: gms=OK, play_store=OK")
            else:
                logger.warning(
                    f"{elapsed()} Google Play / GMS не готовы "
                    f"(gms={has_gms}, play_store={has_store}). "
                    "Установи GApps через веб-портал Genymotion."
                )
                zip_path = getattr(config, "GENYMOTION_ADB_GAPPS_ZIP", "").strip()
                if getattr(config, "GENYMOTION_TRY_ADB_GAPPS", False):
                    has_fa = await action.has_genymotion_flash_archive()
                    logger.info(
                        f"{elapsed()} GENYMOTION_TRY_ADB_GAPPS=1: flash-archive.sh "
                        f"на устройстве={'да' if has_fa else 'нет'}"
                    )
                    if zip_path and Path(zip_path).is_file():
                        ok_flash, flash_msg = await action.try_flash_genymotion_gapps_zip(
                            zip_path
                        )
                        if ok_flash:
                            logger.success(f"{elapsed()} ADB flash GApps: {flash_msg}")
                            await asyncio.sleep(8)
                            adb_serial = await farm.connect_adb()
                            action = ActionEngine(adb_serial=adb_serial)
                            if await action.connect():
                                await asyncio.sleep(20)
                                has_gms = await action.is_package_installed(
                                    "com.google.android.gms"
                                )
                                has_store = await action.is_package_installed(
                                    "com.android.vending"
                                )
                                logger.info(
                                    f"{elapsed()} После flash+reboot: gms={has_gms}, "
                                    f"play_store={has_store}"
                                )
                        else:
                            logger.error(
                                f"{elapsed()} ADB flash GApps не вышел: {flash_msg}"
                            )
                    elif zip_path:
                        logger.warning(
                            f"{elapsed()} GENYMOTION_ADB_GAPPS_ZIP задан, но файл "
                            f"не найден: {zip_path}"
                        )
                    else:
                        logger.warning(
                            f"{elapsed()} Задай GENYMOTION_ADB_GAPPS_ZIP=/путь.zip "
                            "для flash-archive (на свой риск)."
                        )

        # Включаем экран
        await action.wake_up()

        # Пропускаем setup wizard (OOBE) если устройство новое
        logger.info(f"{elapsed()} Checking for setup wizard / OOBE...")
        from scenarios.base import BaseScenario
        _oobe_helper = type('_OOBE', (BaseScenario,), {'NAME': 'oobe', 'run': lambda self: None})(cv=None, action=action)
        await _oobe_helper.dismiss_setup_wizard()
        await asyncio.sleep(1)
        report.record("device", "success", "Android device/session ready")

        # ═══════════════════════════════════════════
        # PHASE 2: Register new Google account or login existing
        # ═══════════════════════════════════════════
        current_stage = "google"
        if "google" in stages:
            logger.info(f"\n{elapsed()} PHASE 2: Google account setup")
            use_login = bool(config.GOOGLE_EMAIL and config.GOOGLE_PASSWORD)
            reused_from_file = False

            if not use_login and getattr(config, "TEST_RUN", False):
                saved = load_last_saved_google_login()
                if saved:
                    config.GOOGLE_EMAIL = saved["full_email"]
                    config.GOOGLE_PASSWORD = saved["password"]
                    use_login = True
                    reused_from_file = True
                    logger.info(
                        f"{elapsed()} TEST_RUN=1: вход по сохранённому аккаунту "
                        f"({config.CREDENTIALS_JSON_PATH}), без новой регистрации"
                    )

            if use_login:
                google_login = GoogleLoginScenario(
                    cv=None,
                    action=action,
                    sms_service=sms,
                )
                login_ok = await google_login.run()
                if not login_ok:
                    raise RuntimeError(
                        "Google Login did not add the account to Android AccountManager"
                    )
                if reused_from_file:
                    registered_credentials = {
                        "full_email": config.GOOGLE_EMAIL,
                        "password": config.GOOGLE_PASSWORD,
                    }
                    logger.success(
                        f"{elapsed()} ✅ Google Login complete (saved test account)"
                    )
                else:
                    logger.success(f"{elapsed()} ✅ Google Login complete")
            else:
                reg_via = getattr(config, "GOOGLE_REGISTER_VIA", "chrome")
                if reg_via == "web":
                    logger.info(
                        f"{elapsed()} Google registration: WEB (Playwright), "
                        "not on device"
                    )
                    web_reg = GoogleRegisterWebScenario(sms_service=sms)
                    try:
                        registered_credentials = await web_reg.run()
                    except PhoneVerificationReached as e:
                        report.record("google", "phone_verification", str(e))
                        final_status = "phone_verification"
                        logger.success(f"{elapsed()} ✅ {e}")
                        return
                elif reg_via == "chrome":
                    logger.info(
                        f"{elapsed()} Google registration: CHROME browser on device"
                    )
                    chrome_reg = GoogleRegisterChromeScenario(
                        cv=None, action=action, sms_service=sms
                    )
                    try:
                        registered_credentials = await chrome_reg.run()
                    except PhoneVerificationReached as e:
                        report.record("google", "phone_verification", str(e))
                        final_status = "phone_verification"
                        logger.success(f"{elapsed()} ✅ {e}")
                        return
                elif reg_via == "cv":
                    logger.info(
                        f"{elapsed()} Google registration: CV autopilot on device"
                    )
                    cv_reg = GoogleRegisterCVScenario(
                        cv=None, action=action, sms_service=sms
                    )
                    try:
                        registered_credentials = await cv_reg.run()
                    except PhoneVerificationReached as e:
                        report.record("google", "phone_verification", str(e))
                        final_status = "phone_verification"
                        logger.success(f"{elapsed()} ✅ {e}")
                        return
                else:
                    logger.info(
                        f"{elapsed()} Google registration: ANDROID (Play Store)"
                    )
                    register = GoogleRegisterScenario(
                        cv=None, action=action, sms_service=sms
                    )
                    try:
                        registered_credentials = await register.run()
                    except PhoneVerificationReached as e:
                        report.record("google", "phone_verification", str(e))
                        final_status = "phone_verification"
                        logger.success(f"{elapsed()} ✅ {e}")
                        return
                save_credentials(registered_credentials)
                logger.success(
                    f"{elapsed()} ✅ Google Account registered: "
                    f"{registered_credentials['full_email']}"
                )
            report.record("google", "success", "Google account setup complete")
            # ── Google Play Sign-in после регистрации ──
            current_stage = "play_signin"
            logger.info(f"\n{elapsed()} PHASE 3: Google Play Sign-in")
            try:
                play_signin = GooglePlaySigninScenario(cv=None, action=action)
                play_ok = await play_signin.run()
                if play_ok:
                    logger.success(f"{elapsed()} ✅ Google Play signed in")
                else:
                    raise RuntimeError("Google Play sign-in returned False")
            except Exception as e:
                logger.error(f"{elapsed()} ❌ Google Play sign-in failed: {e}")
                raise
            report.record("play_signin", "success", "Google Play signed in")
        else:
            logger.info("PHASE 2 skipped by RUN_STAGES")
            report.record("google", "skipped", "stage disabled")

        # ═══════════════════════════════════════════
        # PHASE 4: Google Pay Setup
        # ═══════════════════════════════════════════
        current_stage = "pay"
        if "pay" in stages:
            logger.info(f"\n{elapsed()} PHASE 4: Google Pay Setup")
            if config.CARD_NUMBER:
                google_pay = GooglePayScenario(cv=None, action=action)
                await google_pay.run()
                logger.success(f"{elapsed()} ✅ Google Pay configured")
                report.record("pay", "success", "Google Pay configured")
            else:
                logger.warning("No card data — skipping Google Pay setup")
                report.record("pay", "skipped", "no card data")
        else:
            logger.info("PHASE 4 skipped by RUN_STAGES")
            report.record("pay", "skipped", "stage disabled")

        # ═══════════════════════════════════════════
        # PHASE 5: Install configured game
        # ═══════════════════════════════════════════
        current_stage = "install"
        if "install" in stages:
            logger.info(f"\n{elapsed()} PHASE 5: Install {config.GAME_NAME}")
            install_via = getattr(config, "INSTALL_AUTOPILOT_VIA", "cv")
            if install_via == "manual":
                install = ManualControlScenario(
                    cv=None,
                    action=action,
                    stage_name="install",
                    hint=f"Install and launch {config.GAME_NAME}, then press Continue Automation.",
                )
            elif install_via == "recorded":
                install = RecordedActionsScenario(
                    cv=None,
                    action=action,
                    stage_name="install",
                    recording_path=getattr(config, "RECORDED_INSTALL_PATH", ""),
                )
            elif install_via == "cv":
                install = InstallGameCVScenario(cv=None, action=action)
            else:
                install = InstallGameScenario(cv=None, action=action)
            await install.run()
            logger.success(f"{elapsed()} ✅ {config.GAME_NAME} installed and launched")
            report.record("install", "success", f"{config.GAME_NAME} installed/launched")
        else:
            logger.info("PHASE 5 skipped by RUN_STAGES")
            report.record("install", "skipped", "stage disabled")

        # ═══════════════════════════════════════════
        # PHASE 6: Game Tutorial
        # ═══════════════════════════════════════════
        current_stage = "tutorial"
        if "tutorial" in stages:
            logger.info(f"\n{elapsed()} PHASE 6: Game Tutorial")
            game_via = getattr(config, "GAME_AUTOPILOT_VIA", "cv")
            if game_via == "manual":
                tutorial = ManualControlScenario(
                    cv=None,
                    action=action,
                    stage_name="tutorial",
                    hint=(
                        "Pass onboarding/tutorial manually and stop at the lobby or "
                        "safe shop-ready screen, then press Continue Automation."
                    ),
                )
            elif game_via == "recorded":
                tutorial = RecordedActionsScenario(
                    cv=None,
                    action=action,
                    stage_name="tutorial",
                    recording_path=getattr(config, "RECORDED_TUTORIAL_PATH", ""),
                )
            elif game_via == "cv":
                tutorial = GameTutorialCVScenario(cv=None, action=action)
            else:
                tutorial = GameTutorialScenario(cv=None, action=action)
            await tutorial.run()
            logger.success(f"{elapsed()} ✅ Tutorial completed")
            report.record("tutorial", "success", "tutorial/onboarding complete")
        else:
            logger.info("PHASE 6 skipped by RUN_STAGES")
            report.record("tutorial", "skipped", "stage disabled")

        # ═══════════════════════════════════════════
        # PHASE 6.5: Optional realtime gameplay helper
        # ═══════════════════════════════════════════
        current_stage = "gameplay"
        if "gameplay" in stages:
            profile = getattr(config, "SELECTED_GAME_PROFILE", None)
            strategy = getattr(profile, "gameplay_strategy", "none")
            gameplay_via = getattr(config, "GAMEPLAY_AUTOPILOT_VIA", "fast")
            if gameplay_via == "manual":
                logger.info(f"\n{elapsed()} PHASE 6.5: Manual gameplay")
                gameplay = ManualControlScenario(
                    cv=None,
                    action=action,
                    stage_name="gameplay",
                    hint="Play the required gameplay manually, then press Continue Automation.",
                )
                await gameplay.run()
                report.record("gameplay", "success", "manual gameplay checkpoint complete")
            elif gameplay_via == "recorded":
                logger.info(f"\n{elapsed()} PHASE 6.5: Recorded gameplay")
                gameplay = RecordedActionsScenario(
                    cv=None,
                    action=action,
                    stage_name="gameplay",
                    recording_path=getattr(config, "RECORDED_GAMEPLAY_PATH", ""),
                )
                await gameplay.run()
                report.record("gameplay", "success", "recorded gameplay replay complete")
            elif strategy == "fast_runner" and gameplay_via == "fast":
                logger.info(f"\n{elapsed()} PHASE 6.5: Fast runner gameplay")
                gameplay = FastRunnerGameplayScenario(cv=None, action=action)
                await gameplay.run()
                report.record("gameplay", "success", "fast runner gesture loop complete")
            elif strategy == "match3_solver":
                logger.info(f"\n{elapsed()} PHASE 6.5: Match-3 solver gameplay")
                gameplay = Match3GameplayScenario(cv=None, action=action)
                await gameplay.run()
                report.record("gameplay", "success", "match-3 solver loop complete")
            elif strategy == "solver_required":
                msg = "game requires a dedicated solver; generic gameplay skipped"
                if getattr(config, "GAMEPLAY_REQUIRED", False):
                    raise RuntimeError(msg)
                logger.warning(msg)
                report.record("gameplay", "skipped", msg)
            else:
                logger.info("PHASE 6.5 skipped: no profile gameplay helper needed")
                report.record("gameplay", "skipped", "no gameplay helper needed")
        else:
            logger.info("PHASE 6.5 skipped by RUN_STAGES")
            report.record("gameplay", "skipped", "stage disabled")

        # ═══════════════════════════════════════════
        # PHASE 7: In-App Purchase
        # ═══════════════════════════════════════════
        current_stage = "purchase_preview"
        if "purchase" in stages or "purchase_preview" in stages:
            purchase_mode = getattr(config, "PURCHASE_MODE", "preview")
            if "purchase_preview" in stages or purchase_mode != "real":
                logger.info(f"\n{elapsed()} PHASE 7: Purchase Preview (no payment)")
                if getattr(config, "PURCHASE_AUTOPILOT_VIA", "cv") == "manual":
                    preview = ManualControlScenario(
                        cv=None,
                        action=action,
                        stage_name="purchase_preview",
                        hint=(
                            "Open the shop and stop before any final Buy/Pay/Confirm "
                            "button, then press Continue Automation."
                        ),
                    )
                else:
                    preview = PurchasePreviewCVScenario(cv=None, action=action)
                await preview.run()
                logger.success(f"{elapsed()} ✅ Purchase preview reached without confirmation")
                report.record("purchase_preview", "success", "purchase preview reached safely")
            elif not config.CARD_NUMBER and not getattr(config, "ALLOW_PURCHASE_WITHOUT_CARD", False):
                logger.warning(
                    "No card data and ALLOW_PURCHASE_WITHOUT_CARD=0 — skipping purchase"
                )
                report.record("purchase", "skipped", "no card data and override disabled")
            else:
                current_stage = "purchase"
                logger.info(f"\n{elapsed()} PHASE 7: In-App Purchase")
                payment = PaymentScenario(cv=None, action=action)
                await payment.run()
                logger.success(f"{elapsed()} ✅ Payment completed")
                report.record("purchase", "success", "payment completed")
        else:
            logger.info("PHASE 7 skipped by RUN_STAGES")
            report.record("purchase_preview", "skipped", "stage disabled")

        # ═══════════════════════════════════════════
        # DONE!
        # ═══════════════════════════════════════════
        total_time = time.time() - start_time
        logger.info("\n" + "=" * 65)
        logger.success(f"  🏆 ALL COMPLETE! Time: {total_time:.1f}s ({total_time / 60:.1f} min)")
        if registered_credentials:
            logger.success(f"  📧 Account: {registered_credentials['full_email']}")
            logger.success(f"  🔑 Password: {registered_credentials['password']}")
        logger.info("=" * 65)

        if total_time <= config.TOTAL_TIMEOUT_SECONDS:
            logger.success(f"  ⚡ Within 3-minute target! ({total_time:.0f}s < 180s)")
        else:
            logger.warning(
                f"  ⏰ Exceeded 3-minute target "
                f"({total_time:.0f}s > 180s)"
            )
        final_status = "success"

    except Exception as e:
        total_time = time.time() - start_time
        final_error = str(e)
        logger.error(f"\n❌ FATAL ERROR after {total_time:.1f}s: {e}")
        if report is not None:
            report.record(current_stage, "failed", str(e))
        provider_hint = format_provider_error(config.DEVICE_FARM, e)
        if provider_hint:
            logger.error(f"Provider diagnostics: {provider_hint}")
        raise

    finally:
        # ═══════════════════════════════════════════
        # Cleanup
        # ═══════════════════════════════════════════
        logger.info("\n🧹 Cleaning up...")

        # Завершаем SMS-заказ если активен
        if sms.current_order_id:
            try:
                await sms.cancel_order()
            except Exception:
                pass

        # Останавливаем устройство
        try:
            if config.DEVICE_FARM in ("browserstack", "lambdatest", "local"):
                await farm.stop_session()
            else:
                await farm.stop_instance()
        except Exception as e:
            logger.warning(f"Error stopping device: {e}")

        # Закрываем HTTP-клиенты
        try:
            await farm.close()
            await sms.close()
        except Exception:
            pass

        if report is not None:
            try:
                report_path = report.write(final_status=final_status, error=final_error)
                logger.info(f"Run report written: {report_path}")
            except Exception as e:
                logger.warning(f"Could not write run report: {e}")

        logger.info("Cleanup done. Bye! 👋")


if __name__ == "__main__":
    _apply_cli_args(sys.argv[1:])
    asyncio.run(main())
