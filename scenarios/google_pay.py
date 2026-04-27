"""
Сценарий: Настройка Google Pay (добавление платёжной карты).

БЕЗ CV — всё через UIAutomator2.
"""
import asyncio
from loguru import logger

from scenarios.base import BaseScenario
import config


class GooglePayScenario(BaseScenario):

    NAME = "google_pay"

    def __init__(self, cv, action, card_data: dict = None):
        super().__init__(cv, action)
        self.card = card_data or {
            "number": config.CARD_NUMBER,
            "expiry": config.CARD_EXPIRY,
            "cvv": config.CARD_CVV,
        }

    async def run(self):
        """Полный flow добавления карты в Google Pay."""
        logger.info("=" * 50)
        logger.info("SCENARIO: Google Pay Setup")
        logger.info("=" * 50)

        # Пробуем основной путь через Play Store
        success = await self._setup_via_play_store()

        if not success:
            # Fallback через Google Pay app
            success = await self._setup_via_google_pay_app()

        if not success:
            # Последний fallback — через URL
            success = await self._setup_via_url()

        if success:
            logger.success("Google Pay card added successfully!")
        else:
            logger.error("Failed to add card to Google Pay")

    async def _setup_via_play_store(self) -> bool:
        """Добавить карту через Google Play Store → Payment Methods."""
        self._log_step("Opening Play Store...")

        await self.action.open_app(
            "com.android.vending",
            "com.google.android.finsky.activities.MainActivity",
        )
        await asyncio.sleep(3)

        # Тапаем на аватар/профиль
        self._log_step("Opening profile menu...")
        found = False
        for label in ["Profile", "Avatar", "Account", "photo", "circle"]:
            if await self.tap_text_contains(label, pause=2.0):
                found = True
                break
        if not found:
            # Пробуем page_source поиск иконки профиля
            texts = await self.get_texts()
            for text, cx, cy in texts:
                if any(kw in text.lower() for kw in ("profile", "account", "avatar")):
                    await self.action.tap(cx, cy, pause=2.0)
                    found = True
                    break
        if not found:
            return False

        # Payments & subscriptions
        self._log_step("Opening Payments & subscriptions...")
        found = await self.tap_any_contains(
            ["Payments & subscriptions", "Payments", "Payment methods", "Платежи"],
            pause=2.0,
        )
        if not found:
            await self.action.swipe_up()
            await asyncio.sleep(1)
            found = await self.tap_any_contains(
                ["Payments & subscriptions", "Payments", "Payment methods"],
                pause=2.0,
            )

        if not found:
            return False

        # Payment methods
        self._log_step("Opening Payment methods...")
        found = await self.tap_any_contains(
            ["Payment methods", "Payment method", "Способы оплаты"],
            pause=2.0,
        )
        if not found:
            return False

        # Add payment method
        return await self._add_card()

    async def _setup_via_google_pay_app(self) -> bool:
        """Добавить карту через Google Pay / Wallet приложение."""
        self._log_step("Trying Google Pay/Wallet app...")

        packages = [
            "com.google.android.apps.walletnfcrel",
            "com.google.android.apps.nbu.paisa.user",
            "com.google.android.gms",
        ]

        for pkg in packages:
            installed = await self.action.is_package_installed(pkg)
            if installed:
                await self.action.open_app(pkg)
                await asyncio.sleep(3)

                found = await self.tap_any_contains(
                    ["Add payment", "Add card", "Add credit"],
                    pause=2.0,
                )
                if found:
                    return await self._add_card()

        return False

    async def _setup_via_url(self) -> bool:
        """Добавить карту через URL (fallback)."""
        self._log_step("Trying via URL...")

        await self.action.open_url("https://play.google.com/store/paymentmethods")
        await asyncio.sleep(5)

        found = await self.tap_any_contains(
            ["Add payment", "Add card", "Add credit", "Add credit or debit"],
            pause=2.0,
        )
        if found:
            return await self._add_card()

        return False

    async def _add_card(self) -> bool:
        """Ввести данные карты в форму."""
        self._log_step("Entering card details...")

        # Выбираем "Credit or debit card" если есть выбор типа
        await self.tap_any_contains(
            ["Credit or debit", "Credit", "Debit", "Кредитная", "дебетовая"],
            pause=2.0,
        )

        # ─── Номер карты ───
        self._log_step("Entering card number...")
        card_entered = await self.find_and_type(
            "Card number input field (поле ввода номера карты)",
            self.card["number"],
            retries=5,
        )

        if not card_entered:
            logger.error("Could not find card number field!")
            return False

        await asyncio.sleep(0.5)

        # ─── Срок действия (MM/YY) ───
        self._log_step("Entering expiry date...")
        expiry_entered = await self.find_and_type(
            "Expiry date field (MM/YY) or expiration",
            self.card["expiry"],
            retries=3,
        )

        if not expiry_entered:
            await self.action.press_tab()
            await asyncio.sleep(0.3)
            await self.action.type_text(self.card["expiry"])

        await asyncio.sleep(0.5)

        # ─── CVV/CVC ───
        self._log_step("Entering CVV...")
        cvv_entered = await self.find_and_type(
            "CVC or CVV input field (код безопасности)",
            self.card["cvv"],
            retries=3,
        )

        if not cvv_entered:
            await self.action.press_tab()
            await asyncio.sleep(0.3)
            await self.action.type_text(self.card["cvv"])

        await asyncio.sleep(1)

        # ─── Save / Сохранить ───
        self._log_step("Saving card...")
        saved = await self.tap_any(
            ["Save", "Сохранить", "Submit", "Confirm"],
            pause=3.0,
        )

        if not saved:
            await self.action.swipe_up()
            await asyncio.sleep(1)
            saved = await self.tap_any(
                ["Save", "Сохранить", "Submit", "Confirm"],
                pause=3.0,
            )

        # Обработка возможных подтверждений
        await asyncio.sleep(2)
        await self.dismiss_popups(max_attempts=3)

        return True
