"""
Сценарий: Покупка в магазине Clash Royale через Google Pay.

БЕЗ CV — всё через UIAutomator2 page_source.

Flow:
1. Открываем Shop в главном меню
2. Находим самый дешёвый товар за реальные деньги
3. Нажимаем покупку
4. Подтверждаем в диалоге Google Play Billing
5. Подтверждаем платёж
"""
import asyncio
from loguru import logger

from scenarios.base import BaseScenario
import config


class PaymentScenario(BaseScenario):

    NAME = "payment"

    async def run(self):
        """Полный flow покупки в Clash Royale."""
        logger.info("=" * 50)
        logger.info("SCENARIO: In-App Purchase")
        logger.info("=" * 50)

        # ─── Шаг 1: Убедимся что Clash Royale запущена ───
        self._log_step("Ensuring Clash Royale is running...")
        pkg = (await self.action.get_current_package() or "").lower()
        if "clashroyale" not in pkg and "supercell" not in pkg:
            logger.info(f"Not in game (pkg={pkg}), launching Clash Royale...")
            await self.action.open_app("com.supercell.clashroyale")
            await asyncio.sleep(12)
            await self.dismiss_popups(max_attempts=5)

        # Проверяем что мы в игре
        texts = await self.get_texts()
        all_text = " ".join(t.lower() for t, _, _ in texts)
        logger.info(f"Current screen texts: {[t for t, _, _ in texts[:5]]}")

        if not any(kw in all_text for kw in ("shop", "main", "lobby", "clash", "battle", "cards")):
            await self.action.press_back()
            await asyncio.sleep(1)
            await self.dismiss_popups(max_attempts=3)

        # ─── Шаг 2: Открываем Shop ───
        self._log_step("Opening Shop...")
        shop_found = await self.find_and_tap(
            "Shop button or Shop tab in Clash Royale bottom navigation",
            retries=5,
            pause_after=2.0,
        )

        if not shop_found:
            shop_found = await self.find_and_tap(
                "shopping cart icon, treasure chest icon, or 'Shop' text",
                retries=3,
                pause_after=2.0,
            )

        if not shop_found:
            logger.warning("Shop not found — trying navigation alternatives")
            # Ищем любой текст похожий на Shop
            texts = await self.get_texts()
            for text, cx, cy in texts:
                if any(kw in text.lower() for kw in ("shop", "store", "offer", "deal")):
                    await self.action.tap(cx, cy, pause=2.0)
                    break

        # ─── Шаг 3: Ищем IAP товар ───
        self._log_step("Looking for real-money items...")
        await asyncio.sleep(2)

        iap_tapped = False
        for scroll in range(3):
            texts = await self.get_texts()
            # Ищем элемент с ценой в реальной валюте
            for text, cx, cy in texts:
                text_lower = text.lower()
                if any(indicator in text_lower for indicator in ("$", "₽", "€", "£", "usd", "rub", "price")):
                    self._log_step(f"Found IAP item: '{text}' at ({cx}, {cy})")
                    await self.action.tap(cx, cy, pause=2.0)
                    iap_tapped = True
                    break

            if iap_tapped:
                break

            # Если не нашли — скроллим
            logger.debug(f"No IAP found, scrolling down... ({scroll + 1}/3)")
            await self.action.swipe_up(duration_ms=500)
            await asyncio.sleep(1.5)

        if not iap_tapped:
            # Fallback: тапаем любой подходящий элемент
            logger.warning("Could not find IAP specifically, tapping first buy-like element")
            tapped = await self.find_and_tap(
                "any purchasable item, special offer, or gems pack in Clash Royale shop",
                retries=3,
                pause_after=2.0,
            )
            if not tapped:
                raise RuntimeError("Could not find any IAP item in shop")

        # ─── Шаг 4: Google Play Purchase Dialog ───
        self._log_step("Handling Google Play purchase dialog...")
        await asyncio.sleep(2)

        buy_found = await self._handle_purchase_dialog()

        if buy_found:
            logger.success("🎉 Purchase initiated successfully!")
        else:
            logger.error("Failed to complete purchase")

    async def _handle_purchase_dialog(self) -> bool:
        """Обработать диалог покупки Google Play."""
        self._log_step("Waiting for Google Play billing dialog...")

        for attempt in range(5):
            texts = await self.get_texts()
            all_text = " ".join(t.lower() for t, _, _ in texts)

            # Если это диалог Google Play Purchase
            if any(kw in all_text for kw in ("purchase", "buy", "payment", "billing", "google play")):
                break

            await asyncio.sleep(2)

        # ─── Нажимаем Buy ───
        buy_tapped = await self.find_and_tap(
            "green 'Buy' button or '1-tap buy' button in Google Play purchase dialog",
            retries=5,
            pause_after=3.0,
        )

        if not buy_tapped:
            # Может нужно сначала выбрать/добавить способ оплаты
            add_card = await self.find_and_tap(
                "Add payment method, Add credit card, or Add card button",
                retries=2,
                pause_after=3.0,
            )
            if add_card and config.CARD_NUMBER:
                from scenarios.google_pay import GooglePayScenario
                pay = GooglePayScenario(cv=self.cv, action=self.action)
                await pay._add_card()
                await asyncio.sleep(3)
            else:
                await self.find_and_tap(
                    "payment method selector, Google Pay option, or credit card option",
                    retries=2,
                    pause_after=2.0,
                )

            # Снова пробуем Buy
            buy_tapped = await self.find_and_tap(
                "Buy button or Continue button in Google Play billing",
                retries=3,
                pause_after=3.0,
            )

        if not buy_tapped:
            return False

        # ─── Обработка подтверждения ───
        await asyncio.sleep(2)
        await self._handle_payment_confirmation()

        return True

    async def _handle_payment_confirmation(self):
        """Обработать экран подтверждения платежа."""
        self._log_step("Checking for payment confirmation...")

        texts = await self.get_texts()
        all_text = " ".join(t.lower() for t, _, _ in texts)

        if "password" in all_text:
            # Нужен ввод пароля Google
            self._log_step("Entering Google password for purchase confirmation...")
            await self.find_and_type(
                "Google password input field",
                config.GOOGLE_PASSWORD,
                press_enter=True,
                retries=3,
            )

        elif any(kw in all_text for kw in ("confirm", "verify")):
            # Нужно подтверждение
            await self.find_and_tap(
                "Confirm, Verify, or OK button",
                retries=3,
                pause_after=2.0,
            )

        elif any(kw in all_text for kw in ("success", "purchased", "complete")):
            logger.success("Purchase already confirmed!")
            return

        # Финальная проверка
        await asyncio.sleep(3)
        texts = await self.get_texts()
        all_text = " ".join(t.lower() for t, _, _ in texts)
        logger.info(f"Post-purchase screen: {all_text[:100]}")

        # Закрываем success диалог если есть
        await self.dismiss_popups(max_attempts=3)
