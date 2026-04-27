"""
Регистрация нового Google-аккаунта через сайт (браузер Playwright).

Не зависит от Android/CV — только 5sim + Chromium.
После успеха выставляет config.GOOGLE_EMAIL / GOOGLE_PASSWORD.

Перед первым запуском:
  pip install playwright
  playwright install chromium

Переменные:
  GOOGLE_REGISTER_VIA=web (по умолчанию в config)
  GOOGLE_WEB_HEADLESS=0|1
  GOOGLE_WEB_PROXY — опционально прокси только для Chromium (5sim по-прежнему FIVESIM_PROXY).
"""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

# Запуск как `python scenarios/google_register_web.py` — корень проекта в PYTHONPATH
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import asyncio
import random
import re
from typing import Any

from loguru import logger

import config
from core.credentials import CredentialsGenerator, MONTHS
from core.helpers import ensure_dir, timestamp
from services.sms_service import SMSService


SIGNUP_ENTRY_URL = (
    "https://accounts.google.com/signup"
    "?continue=https://myaccount.google.com"
)


def _raw_browser_proxy_url() -> str:
    """GOOGLE_WEB_PROXY если задан, иначе без прокси."""
    return (getattr(config, "GOOGLE_WEB_PROXY", "") or "").strip()


def _playwright_proxy_settings(url: str) -> dict[str, Any] | None:
    """http(s)://user:pass@host:port → dict для browser.new_context(proxy=...)."""
    u = (url or "").strip()
    if not u:
        return None
    if not u.startswith(("http://", "https://")):
        u = "http://" + u
    parsed = urlparse(u)
    if not parsed.hostname:
        return None
    scheme = parsed.scheme or "http"
    port = parsed.port
    if port is None:
        port = 443 if scheme == "https" else 80
    server = f"{scheme}://{parsed.hostname}:{port}"
    out: dict[str, Any] = {"server": server}
    if parsed.username:
        out["username"] = unquote(parsed.username)
    if parsed.password is not None:
        out["password"] = unquote(parsed.password)
    return out


class GoogleRegisterWebScenario:
    """Регистрация Google через accounts.google.com в браузере."""

    def __init__(self, sms_service: SMSService):
        self.sms = sms_service
        self.creds_gen = CredentialsGenerator()

    async def run(self) -> dict[str, Any]:
        try:
            from playwright.async_api import async_playwright
        except ImportError as e:
            raise RuntimeError(
                "Playwright не установлен. Выполни: pip install playwright && "
                "playwright install chromium"
            ) from e

        logger.info("=" * 60)
        logger.info("  SCENARIO: Register NEW Google Account (WEB / Playwright)")
        logger.info("=" * 60)

        creds = self.creds_gen.generate()
        logger.info(f"  Name:     {creds['first_name']} {creds['last_name']}")
        logger.info(f"  Email:    {creds['full_email']}")

        self._log("Buying phone number for verification...")
        phone_data = await self.sms.buy_number_with_retry(
            service="google",
            countries=["russia", "kazakhstan", "indonesia", "india", "philippines"],
        )
        order_id = phone_data["id"]
        phone_raw = phone_data["phone"]
        phone_digits = re.sub(r"\D", "", phone_raw.lstrip("+"))
        logger.success(f"Phone: {phone_raw}")

        headless = bool(getattr(config, "GOOGLE_WEB_HEADLESS", False))
        slow_mo = int(getattr(config, "GOOGLE_WEB_SLOW_MO_MS", 0) or 0)
        launch_kw: dict[str, Any] = {"headless": headless}
        if slow_mo > 0:
            launch_kw["slow_mo"] = slow_mo

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    **launch_kw,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--disable-features=IsolateOrigins,site-per-process",
                    ],
                )
                context_kw: dict[str, Any] = {
                    "locale": "en-US",
                    "viewport": {"width": 1280, "height": 900},
                    "user_agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
                    ),
                }
                proxy_cfg = _playwright_proxy_settings(_raw_browser_proxy_url())
                if proxy_cfg:
                    context_kw["proxy"] = proxy_cfg
                    auth = "с авторизацией" if proxy_cfg.get("username") else "без логина"
                    self._log(f"Chromium через прокси {proxy_cfg['server']} ({auth})")
                context = await browser.new_context(**context_kw)
                page = await context.new_page()
                # Anti-detection: скрыть navigator.webdriver
                await page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    delete navigator.__proto__.webdriver;
                """)
                # Через HTTP-прокси первая загрузка Google часто >45s
                nav_timeout = 180_000 if proxy_cfg else 45_000
                page.set_default_timeout(max(45_000, nav_timeout))

                await page.goto(
                    SIGNUP_ENTRY_URL,
                    wait_until="domcontentloaded",
                    timeout=nav_timeout,
                )
                await asyncio.sleep(3)
                await self._debug_web_state(page, "page_loaded")
                await self._dismiss_cookies(page)
                await asyncio.sleep(1)

                # Имя / фамилия
                await self._fill_visible(
                    page,
                    [
                        'input[name="firstName"]',
                        "#firstName",
                        'input[autocomplete="given-name"]',
                        'input[aria-label*="First name" i]',
                        'input[aria-label*="name" i]',
                        'input[type="text"]',
                    ],
                    creds["first_name"],
                )
                await self._fill_visible(
                    page,
                    [
                        'input[name="lastName"]',
                        "#lastName",
                        'input[autocomplete="family-name"]',
                    ],
                    creds["last_name"],
                )
                await self._click_next(page)

                # День рождения / пол
                month_name = MONTHS[int(creds["birth_month"]) - 1]
                await self._try_select_month(page, month_name)
                await page.keyboard.press("Escape")
                await asyncio.sleep(0.3)
                await self._fill_visible(
                    page,
                    ['input[name="day"]', "#day", 'input[aria-label*="day" i]'],
                    str(int(creds["birth_day"])),
                )
                await self._fill_visible(
                    page,
                    ['input[name="year"]', "#year", 'input[aria-label*="year" i]'],
                    creds["birth_year"],
                )
                await self._select_gender(page, creds["gender"])
                await self._click_next(page)

                # Username: при «That username is taken» — новый username и повтор
                await self._submit_username_until_unique(page, creds)

                # Пароль — здесь чаще всего «зависание»: Google не показывает Passwd,
                # пока на экране ещё username / ошибка / капча / другой порядок шагов.
                # #passwd — часто внешний div (Material), не <input>; целим только input.
                pwd_loc = page.locator(
                    'input[name="Passwd"], input[name="password"], '
                    'div#passwd input[type="password"], '
                    '[id="passwd"] input[type="password"], '
                    'input[type="password"]'
                )
                for attempt in range(4):
                    await self._debug_web_state(
                        page,
                        f"before_password_attempt_{attempt + 1}",
                    )
                    try:
                        await pwd_loc.first.wait_for(state="visible", timeout=12_000)
                        break
                    except Exception:
                        if attempt == 3:
                            await self._debug_web_state(
                                page, "password_field_never_appeared"
                            )
                            raise RuntimeError(
                                "Не появилось поле пароля после username. "
                                "Смотри screenshots/google_web_*.png и URL в логе — "
                                "часто это проверка username, занятость адреса или капча."
                            )
                        await self._click_next(page)
                        await asyncio.sleep(2.0)
                await pwd_loc.first.fill(creds["password"])
                # #confirm-passwd — снова обёртка-div, не input
                confirm = page.locator(
                    'input[name="ConfirmPasswd"], input[name="confirmationPasswd"], '
                    'div#confirm-passwd input[type="password"], '
                    '[id="confirm-passwd"] input[type="password"]'
                )
                if await confirm.count():
                    await confirm.first.fill(creds["password"])
                elif await page.locator('input[type="password"]').count() >= 2:
                    await page.locator('input[type="password"]').nth(1).fill(creds["password"])

                await self._click_next(page)

                await asyncio.sleep(2.0)
                # После пароля Google иногда ведёт на /signup/error/1 — не шаг телефона
                if await self._signup_creation_blocked(page):
                    await self._debug_web_state(page, "signup_rejected_after_password")
                    raise RuntimeError(
                        "Google отклонил создание аккаунта (сообщение после пароля). "
                        "Обычно IP/прокси, виртуальный номер, fingerprint или частые попытки. "
                        "См. screenshots/google_web_signup_rejected_after_password_*.png и URL в логе."
                    )

                # Телефон — возможны три экрана:
                # 1. crossflowverification — QR-код, нажать "Use phone number instead"
                # 2. mophoneverification/initial — "Verify some info", нажать кнопку
                # 3. phonenumber — сразу поле ввода
                await self._debug_web_state(page, "before_phone")
                await self._handle_crossflow_verification(page)
                await self._handle_mophone_verification(page, phone_digits)
                # Если crossflow/mophone уже продвинули нас дальше — пропускаем fill+next
                _at_phone_step = (
                    "mophoneverification" in page.url
                    or "crossflow" in page.url
                    or "phonenumber" in page.url
                )
                if _at_phone_step:
                    # _fill_phone_number нужен только если ещё на шаге ввода
                    if "mophoneverification" not in page.url:
                        await self._fill_phone_number(page, phone_digits)
                    await self._click_next(page)

                # SMS-код
                self._log("Waiting for SMS code...")
                code = await self.sms.wait_for_code(
                    order_id=order_id, timeout=120, poll_interval=3
                )
                await self._fill_visible(
                    page,
                    [
                        "#code",
                        'input[name="code"]',
                        'input[type="tel"]',
                        'input[inputmode="numeric"]',
                    ],
                    code,
                )
                await self._click_next(page)
                await self.sms.finish_order(order_id)

                # Пост-экраны (I agree / Next / Skip)
                for _ in range(12):
                    await asyncio.sleep(1.5)
                    if await self._looks_like_success(page):
                        break
                    await self._dismiss_cookies(page)
                    clicked = await self._click_any(
                        page,
                        [
                            "button:has-text('I agree')",
                            "button:has-text('Agree')",
                            "button:has-text('Next')",
                            "button:has-text('Continue')",
                            "text=Skip",
                            "text=Not now",
                        ],
                    )
                    if not clicked:
                        await page.keyboard.press("Escape")

                await context.close()
                await browser.close()

        except Exception as e:
            try:
                await self.sms.cancel_order(order_id)
            except Exception:
                pass
            logger.error(f"[google_register_web] Ошибка: {e}")
            raise

        logger.success("=" * 60)
        logger.success("  ✅ Google Account REGISTERED (web)")
        logger.success(f"  Email:    {creds['full_email']}")
        logger.success("=" * 60)

        config.GOOGLE_EMAIL = creds["full_email"]
        config.GOOGLE_PASSWORD = creds["password"]
        return creds

    @staticmethod
    def _log(msg: str) -> None:
        logger.info(f"[google_register_web] {msg}")

    async def _debug_web_state(self, page, label: str) -> None:
        """Полный скриншот + URL + заголовок — чтобы видеть, где застряли."""
        try:
            out_dir = getattr(config, "SCREENSHOT_DIR", "screenshots")
            ensure_dir(out_dir)
            safe = re.sub(r"[^\w\-.]+", "_", label)[:60]
            path = _root / out_dir / f"google_web_{safe}_{timestamp()}.png"
            await page.screenshot(path=str(path), full_page=True)
            title = await page.title()
            logger.warning(
                f"[google_register_web] DEBUG {label}: url={page.url!r} "
                f"title={title!r} -> {path}"
            )
        except Exception as ex:
            logger.debug(f"[google_register_web] screenshot skip: {ex}")

    async def _dismiss_cookies(self, page) -> None:
        for sel in (
            "button:has-text('Accept all')",
            "button:has-text('I agree')",
            "button:has-text('Tout accepter')",
        ):
            loc = page.locator(sel).first
            if await loc.count() and await loc.is_visible():
                await loc.click()
                await asyncio.sleep(0.5)
                break

    async def _fill_visible(
        self,
        page,
        selectors: list[str],
        value: str,
        index: int = 0,
    ) -> None:
        for sel in selectors:
            loc = page.locator(sel).nth(index)
            try:
                if await loc.count() == 0:
                    continue
                await loc.wait_for(state="visible", timeout=15_000)
                await loc.click()
                await loc.fill("")
                await loc.fill(value)
                return
            except Exception:
                continue
        raise RuntimeError(f"Could not fill field with selectors: {selectors}")

    async def _fill_username_step(self, page, username: str) -> None:
        """Шаг выбора/ввода Gmail username (разные варианты формы Google)."""
        await asyncio.sleep(1.0)
        await self._click_any(
            page,
            [
                "text=Create your own Gmail address",
                "text=Create your own",
                "div:has-text('Create your own Gmail')",
            ],
        )
        await asyncio.sleep(0.6)
        await self._fill_visible(
            page,
            [
                'input[type="text"][name="Username"]',
                'input[name="Username"]',
                'input[name="username"]',
                "#username",
                'input[autocomplete="username"]',
                'input[type="email"]',
                'input[aria-label="Username"]',
                'input[aria-label*="username" i]',
                'input[aria-label*="Gmail" i]',
                'input[aria-label*="email address" i]',
                'input[placeholder*="username" i]',
                'input[placeholder*="Gmail" i]',
            ],
            username,
        )

    async def _username_taken_visible(self, page) -> bool:
        """Google показывает, что логин @gmail.com уже занят."""
        loc = page.get_by_text(
            re.compile(
                r"username is taken|that username|not available|already been taken|"
                r"уже занят|недоступен",
                re.I,
            ),
        )
        try:
            return await loc.count() > 0 and await loc.first.is_visible()
        except Exception:
            return False

    async def _signup_creation_blocked(self, page) -> bool:
        """Страница отказа: не удалось создать аккаунт (часто /signup/error/1)."""
        try:
            if "signup/error" in page.url:
                return True
        except Exception:
            pass
        loc = page.get_by_text(
            re.compile(
                r"could not create your Google Account|не удалось создать|"
                r"unable to create your account",
                re.I,
            ),
        )
        try:
            return await loc.count() > 0 and await loc.first.is_visible()
        except Exception:
            return False

    async def _password_field_ready(self, page) -> bool:
        loc = page.locator(
            'input[name="Passwd"], input[name="password"], '
            'div#passwd input[type="password"], [id="passwd"] input[type="password"]'
        )
        try:
            if await loc.count() == 0:
                return False
            return await loc.first.is_visible()
        except Exception:
            return False

    async def _submit_username_until_unique(
        self,
        page,
        creds: dict[str, Any],
        max_retries: int = 8,
    ) -> None:
        """Ввод username → Next; при ошибке «taken» — новый username и снова."""
        for i in range(max_retries):
            await self._fill_username_step(page, creds["email_username"])
            await asyncio.sleep(1.5)
            await self._click_next(page)
            await asyncio.sleep(2.5)
            if "username" in (page.url or "").lower():
                await self._click_next(page)
                await asyncio.sleep(1.5)

            if await self._password_field_ready(page):
                self._log(f"Username accepted: {creds['full_email']}")
                return

            if await self._username_taken_visible(page):
                suf = random.randint(10000, 999999)
                old = creds["email_username"]
                creds["email_username"] = f"{old}{suf}"[:64]
                creds["full_email"] = f"{creds['email_username']}@gmail.com"
                logger.warning(
                    f"Gmail username taken ({old}), retry as {creds['full_email']}"
                )
                await self._debug_web_state(page, f"username_taken_retry_{i + 1}")
                continue

            # Нет явной ошибки «taken», но и пароля нет — ещё один Next (медленная проверка)
            await asyncio.sleep(2.0)
            await self._click_next(page)
            await asyncio.sleep(2.5)
            if await self._password_field_ready(page):
                self._log(f"Username accepted: {creds['full_email']}")
                return
            if await self._username_taken_visible(page):
                suf = random.randint(10000, 999999)
                old = creds["email_username"]
                creds["email_username"] = f"{old}{suf}"[:64]
                creds["full_email"] = f"{creds['email_username']}@gmail.com"
                logger.warning(
                    f"Gmail username taken ({old}), retry as {creds['full_email']}"
                )
                await self._debug_web_state(page, f"username_taken_retry_b_{i + 1}")
                continue

            await self._debug_web_state(page, f"username_step_stuck_{i + 1}")
            raise RuntimeError(
                "Не удалось перейти к шагу пароля после username "
                "(возможна капча, сеть или неизвестный UI). См. скриншот "
                f"google_web_username_step_stuck_{i + 1}_*.png"
            )

        raise RuntimeError(
            f"Не удалось подобрать свободный username за {max_retries} попыток."
        )

    async def _click_next(self, page) -> None:
        candidates = [
            page.get_by_role("button", name=re.compile(r"^(Next|Continue)$", re.I)),
            page.locator('div[role="button"]:has-text("Next")'),
            page.locator('span:has-text("Next")'),
            page.locator('button:has-text("Next")'),
            page.locator('button:has-text("Continue")'),
            page.locator('button[type="submit"]'),
        ]
        for loc in candidates:
            try:
                if await loc.count() == 0:
                    continue
                el = loc.first
                if await el.is_visible():
                    await el.click()
                    await asyncio.sleep(1.2)
                    return
            except Exception:
                continue
        raise RuntimeError("Next/Continue button not found")

    async def _try_select_month(self, page, month_name: str) -> None:
        # Классический <select>
        for sel in ('select#month', 'select[id="month"]', 'select[name="month"]'):
            loc = page.locator(sel).first
            if await loc.count() == 0:
                continue
            if not await loc.is_visible():
                continue
            tag = (await loc.evaluate("el => el.tagName") or "").upper()
            if tag == "SELECT":
                await loc.select_option(label=month_name)
                return

        # Новый Google lifecycle: #month — это div (Material), не <select>
        combo = page.get_by_role("combobox", name=re.compile(r"month|birth", re.I))
        if await combo.count():
            await combo.first.click()
            await asyncio.sleep(0.5)
        else:
            month_div = page.locator("#month").first
            if await month_div.count() and await month_div.is_visible():
                await month_div.click()
                await asyncio.sleep(0.5)
            else:
                raise RuntimeError("Month field (select or combobox) not found")

        opt = page.get_by_role(
            "option",
            name=re.compile(re.escape(month_name), re.I),
        )
        if await opt.count():
            await opt.first.click()
            return
        alt = page.get_by_text(month_name, exact=True)
        if await alt.count():
            await alt.first.click()
            return
        raise RuntimeError(f"Could not pick month option: {month_name}")

    async def _select_gender(self, page, gender: str) -> None:
        label = "Male" if gender == "male" else "Female"
        # Новый lifecycle: Gender — Material combobox; не путать с Month (закрыть listbox).
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.2)
        gender_combo = page.locator('[role="combobox"]').filter(has_text=re.compile(r"^Gender", re.I))
        if await gender_combo.count():
            await gender_combo.first.click()
            await asyncio.sleep(0.5)
            opt = page.get_by_role(
                "option",
                name=re.compile(rf"^{re.escape(label)}$|woman|man", re.I),
            )
            if await opt.count():
                await opt.first.click()
                return
            await page.get_by_text(label, exact=True).first.click()
            return
        combo = page.get_by_role("combobox", name=re.compile(r"gender", re.I))
        if await combo.count():
            await combo.first.click()
            await asyncio.sleep(0.5)
            opt = page.get_by_role(
                "option",
                name=re.compile(rf"^{re.escape(label)}$|woman|man", re.I),
            )
            if await opt.count():
                await opt.first.click()
                return
            await page.get_by_text(label, exact=True).first.click()
            return
        radio = page.get_by_role("radio", name=re.compile(label, re.I))
        if await radio.count():
            await radio.first.click()
            return
        sel = page.locator('select[id="gender"], select[name="gender"]').first
        if await sel.count() and await sel.is_visible():
            await sel.select_option(label=label)

    async def _handle_crossflow_verification(self, page) -> None:
        """QR crossflow: декодируем QR, открываем URL на эмуляторе, ждём завершения."""
        if "crossflow" not in page.url:
            return
        self._log("crossflowverification detected — trying 'Use phone number instead'...")

        # 1. Сначала проверим кнопку (на некоторых регионах она есть)
        for attempt in range(2):
            clicked = await self._click_any(page, [
                "text=Use your phone number instead",
                "text=Use a phone number instead",
                "text=phone number instead",
                "a:has-text('phone number')",
                "button:has-text('phone number')",
                "[role='link']:has-text('phone number')",
            ])
            if clicked:
                self._log("Clicked 'Use phone number instead'")
                await asyncio.sleep(2.0)
                return
            await asyncio.sleep(0.5)

        # 2. Нет кнопки — декодируем QR и открываем на эмуляторе
        self._log("No 'phone number' link — decoding QR and opening on emulator...")
        qr_url = await self._decode_qr_from_page(page)
        if not qr_url:
            await self._debug_web_state(page, "crossflow_qr_decode_failed")
            raise RuntimeError("crossflowverification: не удалось декодировать QR-код")

        self._log(f"QR URL: {qr_url[:80]}...")
        # Открываем на эмуляторе
        import os
        device = getattr(config, "LOCAL_DEVICE", "emulator-5554")
        escaped = qr_url.replace("'", "\\'").replace("&", "\\&")
        os.system(f"adb -s {device} shell am start -a android.intent.action.VIEW -d '{escaped}'")
        self._log("Opened QR URL on emulator, waiting for phone verification to complete...")

        # Ждём пока браузерная страница перейдёт дальше (max 120s)
        await self._debug_web_state(page, "crossflow_qr_opened_on_emulator")
        for i in range(24):  # 24 * 5s = 120s
            await asyncio.sleep(5)
            url = page.url
            self._log(f"  Waiting crossflow [{i+1}/24]: {url[:60]}")
            if "crossflow" not in url:
                self._log("crossflow resolved!")
                return
        await self._debug_web_state(page, "crossflow_timeout")
        raise RuntimeError("crossflowverification: timeout — эмулятор не завершил верификацию за 120s")

    async def _decode_qr_from_page(self, page) -> str | None:
        """Скриншот страницы → декодировать QR через zbarimg."""
        import subprocess, tempfile
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            tmp = f.name
        try:
            data = await page.screenshot()
            with open(tmp, "wb") as f:
                f.write(data)
            result = subprocess.run(
                ["zbarimg", "--raw", "-q", tmp],
                capture_output=True, text=True, timeout=10
            )
            url = result.stdout.strip()
            return url if url.startswith("http") else None
        except Exception as e:
            self._log(f"QR decode error: {e}")
            return None

    async def _handle_mophone_verification(self, page, phone_digits: str = "") -> None:
        """Если Google показал 'Verify some info' (mophoneverification/initial) — заполняем телефон и кликаем."""
        if "mophoneverification" not in page.url:
            return
        self._log("mophoneverification detected — filling phone and clicking...")
        await self._debug_web_state(page, "mophoneverification")

        # Если на странице QR-код (нет phone input) — ищем ссылку "Verify your phone number"
        has_phone_input = False
        for sel in ['input[autocomplete="tel"]', 'input[type="tel"]', 'input[inputmode="tel"]']:
            loc = page.locator(sel).first
            try:
                if await loc.count() and await loc.is_visible():
                    has_phone_input = True
                    break
            except Exception:
                pass
        if not has_phone_input:
            self._log("No phone input found — trying 'Verify your phone number' link...")
            clicked = await self._click_any(page, [
                "text=Verify your phone number",
                "a:has-text('Verify your phone number')",
                "[role='link']:has-text('phone number')",
                "text=phone number",
                "text=Use your phone number instead",
                "text=Use a phone number instead",
            ])
            if clicked:
                self._log("Clicked 'Verify your phone number' link — waiting for phone form...")
                await asyncio.sleep(3.0)
                await self._debug_web_state(page, "mophone_after_phone_link")
                # Check if we now have a phone input
                for sel in ['input[autocomplete="tel"]', 'input[type="tel"]', 'input[inputmode="tel"]']:
                    loc = page.locator(sel).first
                    try:
                        if await loc.count() and await loc.is_visible():
                            has_phone_input = True
                            self._log("Phone input appeared after clicking link!")
                            break
                    except Exception:
                        pass
            if not has_phone_input:
                # Try JS to find hidden phone link
                try:
                    js_result = await page.evaluate("""() => {
                        const links = document.querySelectorAll('a, [role="link"]');
                        for (const a of links) {
                            const text = (a.innerText || a.textContent || '').trim().toLowerCase();
                            if (text.includes('phone number') || text.includes('verify your')) {
                                a.click();
                                return 'clicked: ' + text;
                            }
                        }
                        return null;
                    }""")
                    if js_result:
                        self._log(f"JS click on phone link: {js_result}")
                        await asyncio.sleep(3.0)
                        await self._debug_web_state(page, "mophone_after_js_phone_link")
                except Exception as e:
                    self._log(f"JS phone link click failed: {e}")
            if not has_phone_input:
                self._log("Still no phone input — trying QR decode as last resort...")
                qr_url = await self._decode_qr_from_page(page)
                if qr_url:
                    self._log(f"QR URL decoded: {qr_url[:80]}...")
                    import os
                    device = getattr(config, "LOCAL_DEVICE", "emulator-5554")
                    escaped = qr_url.replace("'", "\\'").replace("&", "\\&")
                    os.system(f"adb -s {device} shell am start -a android.intent.action.VIEW -d '{escaped}'")
                    self._log("Opened QR URL on emulator — waiting for browser to advance (max 60s)...")
                    await self._debug_web_state(page, "mophone_qr_opened")
                    for i in range(12):
                        await asyncio.sleep(5)
                        url = page.url
                        self._log(f"  Waiting mophone QR [{i+1}/12]: {url[:60]}")
                        if "mophoneverification" not in url and "crossflow" not in url:
                            self._log("mophone QR resolved!")
                            return
                    await self._debug_web_state(page, "mophone_qr_timeout")
                    raise RuntimeError("mophoneverification QR: timeout — эмулятор не завершил верификацию за 60s")
                else:
                    self._log("Could not decode QR — proceeding with normal flow anyway")

        # Шаг 1: Найти и заполнить поле телефона (оно уже на странице с предзаполненным номером)
        if phone_digits:
            phone_selectors = [
                'input[autocomplete="tel"]',
                'input[inputmode="tel"]',
                'input[type="tel"]',
                'input[aria-label*="Phone" i]',
                'input[aria-label*="phone number" i]',
                'input[placeholder*="phone" i]',
                'input[autocomplete="tel-national"]',
                'div#phoneNumberId input',
                '[id="phoneNumberId"] input',
                'input[name="phoneNumberId"]',
            ]
            for sel in phone_selectors:
                loc = page.locator(sel).first
                try:
                    if await loc.count() and await loc.is_visible():
                        await loc.click()
                        await loc.fill("")
                        await loc.fill(phone_digits)
                        self._log(f"Phone filled on mophoneverification: {phone_digits}")
                        await asyncio.sleep(1.0)
                        break
                except Exception:
                    continue

        # Шаг 2: Нажать кнопку отправки — пробуем разные способы
        for attempt in range(5):
            # Playwright-локаторы: текст кнопок + arrow/submit
            clicked = await self._click_any(page, [
                "text=Get a verification code",
                "text=Send code",
                "text=Send verification code",
                "text=Verify",
                "text=Next",
                "text=Continue",
                "[role='button']:has-text('verification')",
                "[role='button']:has-text('code')",
                "[role='button']:has-text('→')",
                "[aria-label='Next']",
                "[aria-label='Submit']",
                "button[aria-label='Next']",
                "button[type='submit']",
                "[jsname='LgbsSe']",  # Google's standard button jsname
                "[role='button']",
                "button",
            ])
            if clicked:
                self._log(f"Clicked action button on mophoneverification (attempt {attempt+1})")
                await asyncio.sleep(3.0)
                await self._debug_web_state(page, f"after_mophone_click_{attempt+1}")
                if "mophoneverification" not in page.url:
                    return  # ушли со страницы — успех
                continue

            # Fallback: JS click — ищем по тексту И по стрелке/submit
            try:
                js_clicked = await page.evaluate("""() => {
                    // 1. По тексту кнопки
                    const texts = ['Get a verification code', 'Send code', 'Send verification code',
                                   'Verify', 'Next', 'Continue', '→'];
                    const tags = ['button', '[role="button"]', 'div[role="button"]',
                                  'span[role="button"]', 'a', 'div.btn', 'div'];
                    for (const tag of tags) {
                        for (const el of document.querySelectorAll(tag)) {
                            const text = (el.innerText || el.textContent || '').trim();
                            for (const t of texts) {
                                if (text.includes(t)) {
                                    el.click();
                                    return 'clicked-text: ' + text;
                                }
                            }
                        }
                    }
                    // 2. По aria-label
                    for (const el of document.querySelectorAll('[aria-label]')) {
                        const label = el.getAttribute('aria-label') || '';
                        if (label.match(/next|submit|send|verify|continue/i)) {
                            el.click();
                            return 'clicked-aria: ' + label;
                        }
                    }
                    // 3. По jsname (Google internal)
                    for (const el of document.querySelectorAll('[jsname="LgbsSe"]')) {
                        el.click();
                        return 'clicked-jsname';
                    }
                    // 4. button[type=submit]
                    const submit = document.querySelector('button[type="submit"]');
                    if (submit) { submit.click(); return 'clicked-submit'; }
                    // 5. Любая форма — submit
                    const form = document.querySelector('form');
                    if (form) { form.submit(); return 'form-submitted'; }
                    return null;
                }""")
                if js_clicked:
                    self._log(f"JS click on mophoneverification: {js_clicked}")
                    await asyncio.sleep(3.0)
                    await self._debug_web_state(page, f"after_mophone_js_click_{attempt+1}")
                    if "mophoneverification" not in page.url:
                        return
            except Exception as e:
                self._log(f"JS click failed: {e}")

            await asyncio.sleep(2.0)

    async def _fill_phone_number(self, page, phone_digits: str) -> None:
        """Ввести номер телефона — ждём появления поля до 30 сек."""
        phone_selectors = [
            'input[autocomplete="tel"]',
            'input[inputmode="tel"]',
            'input[type="tel"]',
            'input[aria-label*="Phone" i]',
            'input[aria-label*="phone number" i]',
            'input[placeholder*="phone" i]',
            'input[autocomplete="tel-national"]',
            'div#phoneNumberId input',
            '[id="phoneNumberId"] input',
            'input[name="phoneNumberId"]',
            'input[type="text"][inputmode="tel"]',
            # Фоллбек: любой input рядом с текстом "phone"
            'input[type="text"]',
        ]
        # Ждём появления поля (после crossflow редирект может занять секунды)
        for _ in range(6):
            for sel in phone_selectors:
                loc = page.locator(sel).first
                try:
                    if await loc.count() and await loc.is_visible():
                        await loc.click()
                        # Очищаем поле: select all + delete, затем fill
                        await page.keyboard.press("Control+a")
                        await page.keyboard.press("Backspace")
                        await loc.fill(phone_digits)
                        self._log(f"Phone entered: {phone_digits}")
                        return
                except Exception:
                    continue

            # JS-фоллбек: ищем input[type=tel] или input[inputmode=tel]
            try:
                filled = await page.evaluate(f"""(digits) => {{
                    const inputs = document.querySelectorAll(
                        'input[type="tel"], input[inputmode="tel"], input[autocomplete="tel"]'
                    );
                    for (const inp of inputs) {{
                        if (inp.offsetParent !== null) {{
                            inp.focus();
                            inp.value = digits;
                            inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                            inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                            return true;
                        }}
                    }}
                    return false;
                }}""", phone_digits)
                if filled:
                    self._log(f"Phone entered via JS: {phone_digits}")
                    return
            except Exception:
                pass

            await asyncio.sleep(5.0)
            await self._debug_web_state(page, "waiting_for_phone_field")
        raise RuntimeError(f"Поле ввода телефона не появилось. selectors={phone_selectors}")

    async def _click_any(self, page, selectors: list[str]) -> bool:
        for sel in selectors:
            loc = page.locator(sel).first
            try:
                if await loc.count() and await loc.is_visible():
                    await loc.click()
                    await asyncio.sleep(1.0)
                    return True
            except Exception:
                continue
        return False

    async def _looks_like_success(self, page) -> bool:
        url = page.url or ""
        if "myaccount.google.com" in url or "ManageAccount" in url:
            return True
        try:
            title = await page.title()
            if title and "Google Account" in title:
                return True
        except Exception:
            pass
        return False


async def _cli_main() -> None:
    """Запуск только веб-регистрации: python scenarios/google_register_web.py"""
    import sys

    from loguru import logger

    logger.remove()
    logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level} | {message}")

    sms = SMSService()
    try:
        if not await sms.check_api():
            raise SystemExit(1)
        await GoogleRegisterWebScenario(sms_service=sms).run()
    finally:
        await sms.close()


if __name__ == "__main__":
    asyncio.run(_cli_main())
