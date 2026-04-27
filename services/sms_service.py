"""
5sim.net — SMS-аренда номеров для верификации.
Замена закрытого SMS-Activate.
API Docs: https://5sim.net/docs
"""
import re
import asyncio

import httpx
from loguru import logger

import config


def _normalize_proxy_url(raw: str) -> str:
    u = (raw or "").strip()
    if not u:
        return ""
    if not u.startswith(("http://", "https://")):
        u = "http://" + u
    return u


class SMSService:
    """
    Клиент для 5sim.net API.
    Покупает временные номера телефонов
    и получает SMS-коды для верификации.
    """

    def __init__(self, api_key: str = None):
        self.api_key = api_key or config.FIVESIM_API_KEY
        self.base_url = config.FIVESIM_BASE_URL
        headers = {"Accept": "application/json"}
        if str(self.api_key or "").strip():
            headers["Authorization"] = f"Bearer {self.api_key}"
        proxy = _normalize_proxy_url(getattr(config, "FIVESIM_PROXY", "") or "")
        client_kw: dict = {"headers": headers, "timeout": 45.0}
        if proxy:
            client_kw["proxy"] = proxy
            logger.info("5sim: запросы идут через HTTP-прокси")
        self.client = httpx.AsyncClient(**client_kw)
        # Текущий заказ
        self.current_order_id = None
        self.current_phone = None

    # ══════════════════════════════════════════
    # Баланс и информация
    # ══════════════════════════════════════════

    async def check_balance(self) -> float:
        """Проверить баланс аккаунта (в рублях)."""
        resp = await self.client.get(f"{self.base_url}/user/profile")
        resp.raise_for_status()
        data = resp.json()
        balance = data.get("balance", 0)
        logger.info(f"5sim balance: {balance} RUB")
        return float(balance)

    async def check_prices(
        self,
        service: str = "google",
        country: str = "russia",
    ) -> dict:
        """Проверить цены на номера для конкретного сервиса."""
        resp = await self.client.get(
            f"{self.base_url}/guest/prices",
            params={"product": service, "country": country},
        )
        data = resp.json()
        return data

    # ══════════════════════════════════════════
    # Покупка номера
    # ══════════════════════════════════════════

    async def buy_number(
        self,
        service: str = "google",
        country: str = "russia",
        operator: str = "any",
    ) -> dict:
        """
        Купить временный номер телефона.

        Параметры:
            service: "google", "telegram", "whatsapp", etc.
            country: "russia", "usa", "indonesia", "india", etc.
            operator: "any", "megafon", "mts", "beeline", etc.

        Возвращает:
            {"id": "123456", "phone": "+79001234567", "operator": "megafon"}
        """
        url = f"{self.base_url}/user/buy/activation/{country}/{operator}/{service}"
        logger.info(f"Buying number: service={service}, country={country}")

        resp = await self.client.get(url)

        if resp.status_code == 200:
            data = resp.json()
            self.current_order_id = str(data["id"])
            self.current_phone = data["phone"]

            logger.success(
                f"Number purchased: {self.current_phone} "
                f"(order #{self.current_order_id}, "
                f"operator: {data.get('operator', '?')})"
            )

            return {
                "id": self.current_order_id,
                "phone": self.current_phone,
                "operator": data.get("operator", "unknown"),
                "status": data.get("status", "PENDING"),
                "price": data.get("price", 0),
            }

        elif resp.status_code == 400:
            error = resp.json() if resp.text else {}
            logger.error(f"Buy number error: {error}")
            raise RuntimeError(f"Cannot buy number: {resp.text}")

        else:
            logger.error(f"Buy number HTTP {resp.status_code}: {resp.text}")
            raise RuntimeError(f"Buy number failed: HTTP {resp.status_code}")

    async def buy_number_with_retry(
        self,
        service: str = "google",
        countries: list[str] = None,
        max_retries: int = 3,
        operator: str = "any",
        operators: list[str] | None = None,
    ) -> dict:
        """
        Купить номер с фолбэком по странам и операторам.
        operators — список операторов для перебора (приоритет выше чем operator).
        """
        if countries is None:
            countries = ["russia", "kazakhstan", "ukraine", "indonesia", "india"]

        operator_list = operators if operators else [operator]
        last_error = None
        for country in countries:
            for op in operator_list:
                for attempt in range(max_retries):
                    try:
                        return await self.buy_number(
                            service=service, country=country, operator=op
                        )
                    except Exception as e:
                        last_error = e
                        logger.warning(
                            f"Country={country} op={op} attempt {attempt + 1} failed: {e}"
                        )
                        await asyncio.sleep(1)

        raise RuntimeError(
            f"Failed to buy number in all countries/operators. Last error: {last_error}"
        )

    # ══════════════════════════════════════════
    # Получение SMS-кода
    # ══════════════════════════════════════════

    async def wait_for_code(
        self,
        order_id: str = None,
        timeout: int = 90,
        poll_interval: int = 3,
    ) -> str:
        """
        Ждать получения SMS-кода.

        Параметры:
            order_id: ID заказа (если None — используется текущий)
            timeout: макс. время ожидания в секундах
            poll_interval: интервал проверки в секундах

        Возвращает: строку с кодом (напр. "123456")
        """
        order_id = order_id or self.current_order_id
        if not order_id:
            raise ValueError("No order_id provided and no current order")

        logger.info(f"Waiting for SMS code (order #{order_id})...")
        elapsed = 0

        while elapsed < timeout:
            try:
                resp = await self.client.get(
                    f"{self.base_url}/user/check/{order_id}"
                )
                resp.raise_for_status()
                data = resp.json()

                status = data.get("status", "")
                sms_list = data.get("sms", [])

                logger.debug(
                    f"Order #{order_id}: status={status}, "
                    f"sms_count={len(sms_list)} ({elapsed}s)"
                )

                if status == "RECEIVED" and sms_list:
                    # Берём последнее SMS
                    last_sms = sms_list[-1]
                    code = last_sms.get("code", "")

                    if code:
                        logger.success(f"Got code from API: {code}")
                        return str(code)

                    # Если code не распарсен — извлекаем из текста
                    text = last_sms.get("text", "")
                    extracted = self._extract_code(text)
                    if extracted:
                        logger.success(f"Extracted code from text: {extracted}")
                        return extracted

                    logger.warning(f"SMS received but no code found. Text: {text}")

                elif status == "CANCELED":
                    raise RuntimeError(f"Order #{order_id} was canceled")

                elif status == "TIMEOUT":
                    raise TimeoutError(f"Order #{order_id} timed out on server")

                elif status == "FINISHED":
                    # Уже завершён — может быть переиспользование
                    if sms_list:
                        code = sms_list[-1].get("code", "")
                        if code:
                            return str(code)

            except httpx.HTTPError as e:
                logger.warning(f"HTTP error checking SMS: {e}")

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        raise TimeoutError(
            f"SMS code not received in {timeout}s for order #{order_id}"
        )

    # ══════════════════════════════════════════
    # Управление заказом
    # ══════════════════════════════════════════

    async def finish_order(self, order_id: str = None):
        """Завершить заказ (подтвердить получение кода)."""
        order_id = order_id or self.current_order_id
        if not order_id:
            return

        try:
            resp = await self.client.get(
                f"{self.base_url}/user/finish/{order_id}"
            )
            logger.info(f"Order #{order_id} finished. Status: {resp.status_code}")
        except Exception as e:
            logger.warning(f"Error finishing order: {e}")

    async def cancel_order(self, order_id: str = None):
        """Отменить заказ (если SMS не пришёл)."""
        order_id = order_id or self.current_order_id
        if not order_id:
            return

        try:
            resp = await self.client.get(
                f"{self.base_url}/user/cancel/{order_id}"
            )
            logger.info(f"Order #{order_id} canceled. Status: {resp.status_code}")
        except Exception as e:
            logger.warning(f"Error canceling order: {e}")

    async def ban_number(self, order_id: str = None):
        """Забанить номер (если номер плохой — получит другой при повторной покупке)."""
        order_id = order_id or self.current_order_id
        if not order_id:
            return

        try:
            resp = await self.client.get(
                f"{self.base_url}/user/ban/{order_id}"
            )
            logger.info(f"Number for order #{order_id} banned.")
        except Exception as e:
            logger.warning(f"Error banning number: {e}")

    # ══════════════════════════════════════════
    # Утилиты
    # ══════════════════════════════════════════

    @staticmethod
    def _extract_code(text: str) -> str:
        """
        Извлечь числовой код подтверждения из текста SMS.
        Пробует 6-значный, потом 5-значный, потом 4-значный.
        """
        if not text:
            return ""

        # G-XXXXXX (формат Google)
        google_match = re.search(r"G-(\d{5,6})", text)
        if google_match:
            return google_match.group(1)

        # 6 цифр
        match6 = re.search(r"\b(\d{6})\b", text)
        if match6:
            return match6.group(1)

        # 5 цифр
        match5 = re.search(r"\b(\d{5})\b", text)
        if match5:
            return match5.group(1)

        # 4 цифры
        match4 = re.search(r"\b(\d{4})\b", text)
        if match4:
            return match4.group(1)

        return ""

    async def check_api(self) -> bool:
        """Проверить работоспособность 5sim API."""
        if not str(self.api_key or "").strip():
            logger.warning("5sim API: FIVESIM_API_KEY не задан")
            return False
        try:
            resp = await self.client.get(f"{self.base_url}/user/profile")
            if resp.status_code == 200:
                data = resp.json()
                logger.success(
                    f"5sim API: OK (balance={data.get('balance', '?')} RUB)"
                )
                return True
            elif resp.status_code == 401:
                logger.error("5sim API: UNAUTHORIZED (bad token)")
                return False
            else:
                logger.error(f"5sim API: HTTP {resp.status_code}")
                return False
        except Exception as e:
            msg = str(e).strip() or type(e).__name__
            logger.error(f"5sim API: {msg}")
            return False

    async def close(self):
        """Закрыть HTTP-клиент."""
        await self.client.aclose()
