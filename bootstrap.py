"""
Bootstrap — проверка всех API и конфигурации.
"""
import asyncio
from loguru import logger

from services.device_farm import GenymotionCloud
from services.sms_service import SMSService
import config


async def check_all_apis(skip_fivesim: bool = False) -> dict:
    """Проверить все API. skip_fivesim — если Google только вход без регистрации."""
    logger.info("=" * 60)
    logger.info(f"   BOOTSTRAP: Checking APIs (farm={config.DEVICE_FARM})")
    logger.info("=" * 60)

    results = {}
    sms = SMSService()

    if config.DEVICE_FARM == "browserstack":
        from services.browserstack_farm import BrowserStackFarm
        farm = BrowserStackFarm()
    elif config.DEVICE_FARM == "lambdatest":
        from services.lambdatest_farm import LambdaTestFarm
        farm = LambdaTestFarm()
    elif config.DEVICE_FARM == "local":
        from services.local_farm import LocalEmulatorFarm
        farm = LocalEmulatorFarm()
    else:
        farm = GenymotionCloud()

    try:
        # ─── 1. Device farm ───
        if config.DEVICE_FARM == "browserstack":
            logger.info("\n[1/2] BrowserStack App Automate API...")
            results["browserstack"] = await farm.check_api()
            results["genymotion"] = True
            logger.info(
                f"  browserstack: {'✅ OK' if results['browserstack'] else '❌ FAIL'}"
            )
        elif config.DEVICE_FARM == "lambdatest":
            logger.info("\n[1/2] LambdaTest Real Device API...")
            results["lambdatest"] = await farm.check_api()
            results["genymotion"] = True
            logger.info(
                f"  lambdatest: {'✅ OK' if results['lambdatest'] else '❌ FAIL'}"
            )
        elif config.DEVICE_FARM == "local":
            logger.info("\n[1/2] Local Appium + Android device...")
            results["local"] = await farm.check_api()
            logger.info(
                f"  local: {'✅ OK' if results['local'] else '❌ FAIL'}"
            )
        else:
            logger.info("\n[1/2] Genymotion Cloud API...")
            results["genymotion"] = await farm.check_api()
            logger.info(
                f"  genymotion: {'✅ OK' if results['genymotion'] else '❌ FAIL'}"
            )
            if results["genymotion"]:
                recipes = await farm.list_recipes()
                if recipes:
                    logger.info(f"  Recipes available: {len(recipes)}")
                    for r in recipes[:5]:
                        logger.info(
                            f"    • {r.get('name', '?')} — "
                            f"Android {r.get('android_version', '?')}"
                        )

        # ─── 2. 5sim.net (SMS) ───
        if skip_fivesim:
            logger.info("\n[2/2] 5sim.net API... skipped (not needed for this flow)")
            results["5sim"] = True
        else:
            logger.info("\n[2/2] 5sim.net API...")
            results["5sim"] = await sms.check_api()
            logger.info(f"  5sim: {'✅ OK' if results['5sim'] else '❌ FAIL'}")

        # ─── Summary ───
        logger.info("\n" + "=" * 60)
        all_ok = all(results.values())
        for name, ok in results.items():
            logger.info(f"  {name}: {'✅ OK' if ok else '❌ FAIL'}")
        if all_ok:
            logger.success("\nALL APIs READY ✅")
        else:
            failed = [k for k, v in results.items() if not v]
            logger.error(f"\nFAILED: {', '.join(failed)}")
        logger.info("=" * 60)

        return results
    finally:
        await farm.close()
        await sms.close()


async def check_config() -> list[str]:
    """Проверить конфигурацию. Возвращает список warnings."""
    warnings = []

    if not config.GENYMOTION_API_TOKEN:
        warnings.append("GENYMOTION_API_TOKEN (REQUIRED)")
    if getattr(config, "GOOGLE_PHONE_MODE", "manual") == "fivesim" and not config.FIVESIM_API_KEY:
        warnings.append("FIVESIM_API_KEY (REQUIRED for registration)")

    if getattr(config, "TEST_RUN", False):
        logger.info(
            "TEST_RUN=1 — при отсутствии GOOGLE_EMAIL будет вход из "
            f"{config.CREDENTIALS_JSON_PATH} (если есть запись), иначе регистрация"
        )
    if not config.GOOGLE_EMAIL:
        if getattr(config, "TEST_RUN", False):
            logger.info(
                "GOOGLE_EMAIL not set — при наличии сохранённого аккаунта будет вход, "
                "иначе новая регистрация"
            )
        else:
            logger.info("GOOGLE_EMAIL not set — will register new account automatically")

    if not config.CARD_NUMBER:
        logger.warning(
            "CARD_NUMBER not set — Google Pay/payment will be skipped "
            "(set CARD_NUMBER, CARD_EXPIRY, CARD_CVV)"
        )

    return warnings


if __name__ == "__main__":
    asyncio.run(check_all_apis())
