"""
Регистрация нового Google-аккаунта через Chrome-браузер на Android-устройстве.

Открывает WebView Browser с accounts.google.com/signup.
Навигация и заполнение форм — через Chrome DevTools Protocol (CDP) over ADB.
CDP запололяет поля напрямую через DOM.
UIAutomator2 — fallback для незнакомых экранов (БЕЗ CV).
"""
from __future__ import annotations

import asyncio
import json

from loguru import logger

from scenarios.google_register import GoogleRegisterScenario, _DONE_SCREENS, _STALL_THRESHOLD
from scenarios.phone_checkpoint import PhoneVerificationReached
from services.sms_service import SMSService
from core.action_engine import ActionEngine


SIGNUP_URL = (
    "https://accounts.google.com/signup/v2/webcreateaccount"
    "?flowName=GlifWebSignIn&flowEntry=SignUp"
)
CDP_PORT = 9222


class GoogleRegisterChromeScenario(GoogleRegisterScenario):
    """
    Регистрация Google через WebView на Android.
    Навигация — CDP JS + UIAutomator2 fallback (БЕЗ CV).
    """

    NAME = "google_register_chrome"

    def __init__(self, cv, action: ActionEngine, sms_service: SMSService):
        super().__init__(cv=cv, action=action, sms_service=sms_service)
        self._cdp_ws = None
        self._cdp_id = 0
        self._sms_failed: set = set()  # (country, operator) с таймаумом

    # ──────────────────────────────────────────────────────────────
    # CDP helpers
    # ──────────────────────────────────────────────────────────────

    async def _cdp_forward(self) -> bool:
        # Try com.android.chrome first (standard Chrome on emulator)
        for pkg, socket_name in [
            ("com.android.chrome", "chrome_devtools_remote"),
            ("org.chromium.webview_shell", None),  # socket = webview_devtools_remote_{pid}
        ]:
            try:
                pid = await self.action._run_adb("shell", "pidof", pkg, timeout=5)
                pid = pid.strip().split()[0] if pid.strip() else ""
            except Exception:
                pid = ""
            if not pid:
                logger.debug(f"CDP: {pkg} not running")
                continue
            if socket_name is None:
                socket_name = f"webview_devtools_remote_{pid}"
            result = await self.action._run_adb(
                "forward", f"tcp:{CDP_PORT}", f"localabstract:{socket_name}", timeout=5
            )
            logger.info(f"ADB forward: {result!r} pkg={pkg} pid={pid} socket={socket_name}")
            return True
        logger.warning("No browser with DevTools found (tried com.android.chrome, org.chromium.webview_shell)")
        return False

    async def _cdp_get_ws_url(self) -> str | None:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=5, trust_env=False) as c:
                r = await c.get(f"http://localhost:{CDP_PORT}/json")
                tabs = r.json()
                if not tabs:
                    return None
                # Prefer tabs with accounts.google.com (skip new tab, blank pages)
                google_tabs = [t for t in tabs if "accounts.google.com" in t.get("url", "")]
                if google_tabs:
                    tab = google_tabs[0]
                    logger.info(f"CDP selected tab: {tab.get('title', '?')[:60]}")
                    return tab["webSocketDebuggerUrl"]
                return tabs[0]["webSocketDebuggerUrl"]
        except Exception as e:
            logger.warning(f"CDP /json error: {e}")
        return None

    async def _cdp_connect(self) -> bool:
        try:
            import websockets
        except ImportError:
            import subprocess
            subprocess.run(["pip", "install", "websockets", "-q"], check=True)
            import websockets  # noqa

        ws_url = await self._cdp_get_ws_url()
        if not ws_url:
            return False
        try:
            import websockets
            self._cdp_ws = await websockets.connect(ws_url, max_size=10_000_000)
            logger.success(f"CDP connected: {ws_url}")
            return True
        except Exception as e:
            logger.error(f"CDP connect failed: {e}")
            return False

    async def _cdp_send(self, method: str, params: dict | None = None) -> dict:
        if self._cdp_ws is None:
            raise RuntimeError("CDP not connected")
        self._cdp_id += 1
        msg = json.dumps({"id": self._cdp_id, "method": method, "params": params or {}})
        await self._cdp_ws.send(msg)
        for _ in range(30):
            raw = await asyncio.wait_for(self._cdp_ws.recv(), timeout=10)
            data = json.loads(raw)
            if data.get("id") == self._cdp_id:
                return data
        return {}

    async def _js(self, expression: str) -> str:
        try:
            result = await self._cdp_send("Runtime.evaluate", {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
            })
        except Exception as e:
            logger.warning(f"CDP WS error in _js: {e} — reconnecting")
            self._cdp_ws = None
            if not await self._cdp_reconnect():
                return ""
            try:
                result = await self._cdp_send("Runtime.evaluate", {
                    "expression": expression,
                    "returnByValue": True,
                    "awaitPromise": True,
                })
            except Exception:
                return ""
        val = result.get("result", {}).get("result", {}).get("value", "")
        return str(val) if val is not None else ""

    async def _js_click_text(self, text: str) -> bool:
        """Кликнуть элемент по точному тексту через DOM."""
        expr = f"""
(function() {{
    var t = {json.dumps(text.lower())};
    var all = document.querySelectorAll('a,button,li,span,div[role]');
    for (var i=0; i<all.length; i++) {{
        if (all[i].textContent.trim().toLowerCase() === t) {{
            all[i].scrollIntoView({{block:'center'}});
            all[i].click();
            return 'ok:' + all[i].tagName + ':' + all[i].textContent.trim().substring(0,30);
        }}
    }}
    // fallback: contains
    for (var i=0; i<all.length; i++) {{
        if (all[i].textContent.trim().toLowerCase().indexOf(t) === 0) {{
            all[i].scrollIntoView({{block:'center'}});
            all[i].click();
            return 'ok_partial:' + all[i].tagName;
        }}
    }}
    return 'not_found';
}})()
"""
        result = await self._js(expr)
        logger.info(f"js_click_text({text!r}) → {result}")
        return result.startswith("ok")

    async def _js_get_url(self) -> str:
        try:
            return await self._js("window.location.href")
        except Exception:
            return ""

    # ──────────────────────────────────────────────────────────────
    # JS form helpers (React-compatible input filling)
    # ──────────────────────────────────────────────────────────────

    async def _js_set_input(self, selector: str, value: str) -> bool:
        """Заполнить input/select через CDP."""
        escaped = json.dumps(value)
        expr = f"""
(function() {{
    var el = document.querySelector({json.dumps(selector)});
    if (!el) return 'not_found';
    el.scrollIntoView({{block:'center'}});
    el.focus();
    var tag = el.tagName.toLowerCase();
    if (tag === 'select') {{
        el.value = {escaped};
        el.dispatchEvent(new Event('change', {{bubbles:true}}));
        return 'ok_select:' + el.value;
    }}
    var desc = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
    if (desc && desc.set) desc.set.call(el, {escaped});
    else el.value = {escaped};
    el.dispatchEvent(new Event('input', {{bubbles:true}}));
    el.dispatchEvent(new Event('change', {{bubbles:true}}));
    return 'ok:' + el.value.length;
}})()
"""
        result = await self._js(expr)
        logger.info(f"_js_set_input({selector!r}, ***) → {result}")
        return result.startswith("ok")

    async def _js_click_next(self) -> bool:
        """Нажать кнопку Next/Далее через CDP."""
        expr = """
(function() {
    var selectors = [
        'button[jsname="LgbsSe"]',
        'button[type="submit"]',
        'button.VfPpkd-LgbsSe',
        '[data-primary-action-label]',
    ];
    for (var s of selectors) {
        var els = document.querySelectorAll(s);
        for (var el of els) {
            var txt = el.textContent.trim().toLowerCase();
            if (txt && !el.disabled) {
                el.scrollIntoView({block:'center'});
                el.click();
                return 'ok:' + txt.substring(0,20);
            }
        }
    }
    // fallback: ищем по тексту
    var all = document.querySelectorAll('button,a[role="button"]');
    var kw = ['next','далee','continue','вперёд','вперед'];
    for (var el of all) {
        var t = el.textContent.trim().toLowerCase();
        if (kw.some(k => t === k || t.startsWith(k)) && !el.disabled) {
            el.click();
            return 'ok_text:' + t.substring(0,20);
        }
    }
    return 'not_found';
})()
"""
        result = await self._js(expr)
        logger.info(f"_js_click_next → {result}")
        return result.startswith("ok")

    async def _cdp_fill_name(self) -> bool:
        """CDP: заполнить First/Last name и нажать Next."""
        vals = self._signup_values()
        ok1 = await self._js_set_input('input[name="firstName"]', vals["first_name"])
        if not ok1:
            ok1 = await self._js_set_input('#firstName', vals["first_name"])
        await asyncio.sleep(0.3)
        ok2 = await self._js_set_input('input[name="lastName"]', vals["last_name"])
        if not ok2:
            ok2 = await self._js_set_input('#lastName', vals["last_name"])
        await asyncio.sleep(0.3)
        if not ok1 or not ok2:
            logger.warning(f"cdp_fill_name partial: first={ok1} last={ok2}")
            return False
        return await self._js_click_next()

    async def _js_close_any_open_listbox(self):
        """Закрыть любой открытый листбокс нажатием Escape."""
        await self._js("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))")
        await asyncio.sleep(0.3)

    async def _js_select_combobox(self, container_selector: str, data_value: str) -> bool:
        """Открыть Material Design combobox и выбрать опцию по data-value."""
        await self._js_close_any_open_listbox()

        open_expr = f"""
(function() {{
    var container = document.querySelector({json.dumps(container_selector)});
    if (!container) return 'no_container';
    var btn = container.querySelector('div[role="combobox"]');
    if (!btn) btn = container.querySelector('.VfPpkd-TkwUic');
    if (!btn) btn = container;
    btn.click();
    btn.focus();
    return 'opened:' + (btn.getAttribute('aria-label')||btn.className.substring(0,30));
}})()
"""
        open_result = await self._js(open_expr)
        logger.info(f"  combobox open ({container_selector}): {open_result}")
        if "no_container" in open_result:
            return False
        await asyncio.sleep(0.5)

        select_expr = f"""
(function() {{
    var container = document.querySelector({json.dumps(container_selector)});
    if (!container) return 'no_container';
    var val = {json.dumps(str(data_value))};

    // 1) li внутри самого контейнера
    var opts = container.querySelectorAll('li[data-value]');
    for (var o of opts) {{
        if (o.getAttribute('data-value') === val) {{
            o.scrollIntoView({{block:'center'}});
            o.click();
            return 'ok_inner:' + o.textContent.trim().substring(0,25);
        }}
    }}

    // 2) листбокс через aria-owns / aria-controls
    var trigger = container.querySelector('div[role="combobox"]');
    if (trigger) {{
        var lbId = trigger.getAttribute('aria-owns') || trigger.getAttribute('aria-controls');
        if (lbId) {{
            var lb = document.getElementById(lbId);
            if (lb) {{
                var lbOpts = lb.querySelectorAll('li[data-value]');
                for (var o of lbOpts) {{
                    if (o.getAttribute('data-value') === val) {{
                        o.scrollIntoView({{block:'center'}});
                        o.click();
                        return 'ok_aria:' + o.textContent.trim().substring(0,25);
                    }}
                }}
            }}
        }}
    }}

    // 3) глобально — только видимые (offsetParent != null)
    var all = document.querySelectorAll('li[data-value]');
    for (var o of all) {{
        if (o.getAttribute('data-value') === val && o.offsetParent !== null) {{
            o.scrollIntoView({{block:'center'}});
            o.click();
            return 'ok_visible:' + o.textContent.trim().substring(0,25);
        }}
    }}

    return 'not_found:' + val;
}})()
"""
        result = await self._js(select_expr)
        logger.info(f"_js_select_combobox({container_selector!r}, {data_value!r}) → {result}")
        await asyncio.sleep(0.3)
        return result.startswith("ok")

    async def _cdp_fill_birthday(self) -> bool:
        """CDP: заполнить день рождения и пол."""
        vals = self._signup_values()
        month_val = str(int(vals["birth_month"]))
        gender_raw = str(vals.get("gender", "")).lower()
        gender_val = "1" if ("male" in gender_raw and "fe" not in gender_raw) else "2"

        ok_day = await self._js_set_input('input[aria-label="Day"]', str(vals["birth_day"]))
        if not ok_day:
            ok_day = await self._js_set_input('input#day', str(vals["birth_day"]))
        await asyncio.sleep(0.2)

        ok_year = await self._js_set_input('input[aria-label="Year"]', str(vals["birth_year"]))
        if not ok_year:
            ok_year = await self._js_set_input('input#year', str(vals["birth_year"]))
        await asyncio.sleep(0.2)

        ok_month = await self._js_select_combobox('#month', month_val)
        await asyncio.sleep(0.8)
        await self._ensure_cdp()

        ok_gender = await self._js_select_combobox('#gender', gender_val)
        await asyncio.sleep(0.8)
        await self._ensure_cdp()

        logger.info(f"birthday: day={ok_day} month={ok_month} year={ok_year} gender={ok_gender}")
        if not ok_day or not ok_year:
            return False
        return await self._js_click_next()

    async def _cdp_check_username_error(self) -> str:
        """Вернуть текст ошибки поля username если есть."""
        result = await self._js("""
(function() {
    var errs = document.querySelectorAll('.o6cuMc,[role=alert],[aria-live],.Ekjuhf');
    for (var e of errs) {
        var t = e.textContent.trim().toLowerCase();
        if (t && (t.includes('taken') || t.includes('unavailable') || t.includes('try another') || t.includes('not available')))
            return t.substring(0, 80);
    }
    return '';
})()
""")
        return result

    async def _js_clear_and_set_input(self, selector: str, value: str) -> bool:
        """Очистить поле и ввести значение."""
        escaped = json.dumps(value)
        expr = f"""
(function() {{
    var el = document.querySelector({json.dumps(selector)});
    if (!el) return 'not_found';
    el.scrollIntoView({{block:'center'}});
    el.focus();
    var desc = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
    if (desc && desc.set) desc.set.call(el, '');
    else el.value = '';
    el.dispatchEvent(new Event('input', {{bubbles:true}}));
    el.dispatchEvent(new Event('change', {{bubbles:true}}));
    if (desc && desc.set) desc.set.call(el, {escaped});
    else el.value = {escaped};
    el.dispatchEvent(new Event('input', {{bubbles:true}}));
    el.dispatchEvent(new Event('change', {{bubbles:true}}));
    return 'ok:' + el.value.length;
}})()
"""
        result = await self._js(expr)
        logger.info(f"_js_clear_and_set_input({selector!r}) → {result}")
        return result.startswith("ok")

    async def _cdp_fill_email(self) -> bool:
        """CDP: вести username для Gmail."""
        await self._js_click_text("create your own gmail address")
        await asyncio.sleep(0.5)

        for attempt in range(5):
            username = self.credentials.get("email_username", "")
            if attempt > 0:
                suggested = await self._js_get_suggested_username()
                if suggested:
                    logger.info(f"Using Google suggestion: {suggested}")
                    username = suggested
                else:
                    import random, string
                    suffix = "".join(random.choices(string.digits, k=4))
                    base = f"{self.credentials.get('first_name','user').lower()}.{self.credentials.get('last_name','x').lower()}"
                    username = f"{base}{suffix}"
                self.credentials["email_username"] = username
                self.credentials["full_email"] = f"{username}@gmail.com"
                logger.info(f"Username taken — trying: {username}")

            ok = await self._js_clear_and_set_input('input[name="Username"]', username)
            if not ok:
                ok = await self._js_clear_and_set_input('#Username', username)
            if not ok:
                return False
            await asyncio.sleep(0.5)
            await self._js_click_next()
            await asyncio.sleep(2.0)

            err = await self._cdp_check_username_error()
            if not err:
                return True
            logger.warning(f"Username '{username}' error: {err}")

        return False

    async def _js_get_suggested_username(self) -> str:
        """Получить предложенный Google username."""
        result = await self._js("""
(function() {
    var links = document.querySelectorAll('a');
    for (var a of links) {
        var t = a.textContent.trim();
        if (t && t.length > 3 && t.length < 30 && !t.includes(' ') &&
            !['help','privacy','terms'].includes(t.toLowerCase())) {
            return t;
        }
    }
    var all = document.querySelectorAll('span,div');
    for (var el of all) {
        var txt = el.textContent.trim();
        if (txt.toLowerCase().startsWith('available:')) {
            var parts = txt.split(':');
            if (parts[1]) return parts[1].trim().replace('@gmail.com','');
        }
    }
    return '';
})()
""")
        return result.strip()

    async def _cdp_fill_password(self) -> bool:
        """CDP: вести пароль и подтверждение."""
        vals = self._signup_values()
        ok1 = await self._js_set_input('input[name="Passwd"]', vals["password"])
        if not ok1:
            ok1 = await self._js_set_input('#Passwd', vals["password"])
        await asyncio.sleep(0.3)
        ok2 = await self._js_set_input('input[name="PasswdAgain"]', vals["password"])
        if not ok2:
            ok2 = await self._js_set_input('#PasswdAgain', vals["password"])
        await asyncio.sleep(0.3)
        if not ok1 or not ok2:
            logger.warning(f"cdp_fill_password partial: p1={ok1} p2={ok2}")
            return False
        return await self._js_click_next()

    async def _cdp_fill_phone(self) -> bool:
        """CDP: вести номер телефона."""
        phone = self._signup_values()["phone"]
        # Try standard selectors first
        for sel in ('#phoneNumberId', 'input[type="tel"]',
                     'input[name="phoneNumber"]', 'input[aria-label*="phone" i]',
                     'input[aria-label*="Phone" i]', 'input[autocomplete="tel"]'):
            ok = await self._js_set_input(sel, phone)
            if ok:
                await asyncio.sleep(0.3)
                return await self._js_click_next()

        # Broader fallback: find any visible input on the page
        result = await self._js(r"""
(function() {
    var inputs = document.querySelectorAll('input:not([type="hidden"]):not([type="submit"])');
    for (var i = 0; i < inputs.length; i++) {
        var el = inputs[i];
        var rect = el.getBoundingClientRect();
        if (rect.width > 50 && rect.height > 10 && rect.top > 0) {
            return 'found:' + el.id + '|' + el.name + '|' + el.type + '|' + el.getAttribute('aria-label');
        }
    }
    // Also check for custom elements
    var all = document.querySelectorAll('[contenteditable="true"], [data-phone-input]');
    for (var j = 0; j < all.length; j++) {
        return 'found_custom:' + all[j].tagName + '|' + all[j].id;
    }
    return 'none';
})()
""")
        logger.info(f"_cdp_fill_phone broad search: {result}")
        if result.startswith("found"):
            # Try setting value on the found input
            parts = result.split(":")[1].split("|")
            el_id = parts[0] if len(parts) > 0 else ""
            el_name = parts[1] if len(parts) > 1 else ""
            sel = f'#{el_id}' if el_id else f'input[name="{el_name}"]' if el_name else None
            if sel:
                ok = await self._js_set_input(sel, phone)
                if ok:
                    await asyncio.sleep(0.3)
                    return await self._js_click_next()

        logger.warning("_cdp_fill_phone: no input field found via CDP")
        return False

    async def _cdp_fill_sms_code(self, code: str) -> bool:
        """CDP: вести SMS-код."""
        for sel in ('#code', 'input[type="tel"]', 'input[name="code"]',
                     'input[aria-label*="code" i]', 'input[aria-label*="Code" i]',
                     'input[autocomplete="one-time-code"]', 'input[maxlength="6"]'):
            ok = await self._js_set_input(sel, code)
            if ok:
                await asyncio.sleep(0.3)
                return await self._js_click_next()

        # Broader fallback: any visible input
        result = await self._js(r"""
(function() {
    var inputs = document.querySelectorAll('input:not([type="hidden"]):not([type="submit"])');
    for (var i = 0; i < inputs.length; i++) {
        var el = inputs[i];
        var rect = el.getBoundingClientRect();
        if (rect.width > 50 && rect.height > 10 && rect.top > 0) {
            return 'found:' + el.id + '|' + el.name + '|' + el.type;
        }
    }
    return 'none';
})()
""")
        logger.info(f"_cdp_fill_sms_code broad search: {result}")
        if result.startswith("found"):
            parts = result.split(":")[1].split("|")
            el_id = parts[0] if len(parts) > 0 else ""
            el_name = parts[1] if len(parts) > 1 else ""
            sel = f'#{el_id}' if el_id else f'input[name="{el_name}"]' if el_name else None
            if sel:
                ok = await self._js_set_input(sel, code)
                if ok:
                    await asyncio.sleep(0.3)
                    return await self._js_click_next()
        return False

    async def _cdp_accept_terms(self) -> bool:
        """CDP: прокрутить и принять Terms."""
        await self._js("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(0.5)
        for text in ("i agree", "agree", "accept", "confirm", "next"):
            if await self._js_click_text(text):
                return True
        return False

    async def _cdp_reconnect(self) -> bool:
        """Переподключить CDP."""
        await self._cdp_close()
        await asyncio.sleep(1)
        if not await self._cdp_forward():
            return False
        return await self._cdp_connect()

    async def _cdp_close(self):
        if self._cdp_ws:
            try:
                await self._cdp_ws.close()
            except Exception:
                pass
            self._cdp_ws = None

    # ──────────────────────────────────────────────────────────────
    # UIAutomator-based helpers
    # ──────────────────────────────────────────────────────────────

    async def _uiautomator_tap_by_text(self, *texts: str) -> bool:
        """Найти элемент по тексту через uiautomator dump и тапнуть."""
        import re
        try:
            await self.action._run_adb("shell", "uiautomator", "dump", "/sdcard/ui.xml", timeout=15)
            xml = await self.action._run_adb("shell", "cat", "/sdcard/ui.xml", timeout=10)
        except Exception as e:
            self._log_step(f"uiautomator dump error: {e}")
            return False
        bounds_re = re.compile(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')
        for node in re.finditer(r'<node\b(?:[^>]|"[^"]*")*?/?>', xml):
            node_str = node.group(0)
            for txt in texts:
                if f'text="{txt}"' in node_str or f'content-desc="{txt}"' in node_str:
                    m = bounds_re.search(node_str)
                    if m:
                        cx = (int(m.group(1)) + int(m.group(3))) // 2
                        cy = (int(m.group(2)) + int(m.group(4))) // 2
                        self._log_step(f"uiautomator: tap '{txt}' at ({cx},{cy})")
                        await self.action.tap(cx, cy, pause=1.0)
                        return True
        self._log_step(f"uiautomator: texts not found: {texts}")
        return False

    async def _uiautomator_find_input(self) -> tuple[int, int] | None:
        """Найти первое EditText через uiautomator dump."""
        import re
        try:
            await self.action._run_adb("shell", "uiautomator", "dump", "/sdcard/ui.xml", timeout=15)
            xml = await self.action._run_adb("shell", "cat", "/sdcard/ui.xml", timeout=10)
        except Exception as e:
            self._log_step(f"uiautomator dump error: {e}")
            return None
        bounds_re = re.compile(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')
        for node in re.finditer(r'<node\b(?:[^>]|"[^"]*")*?/?>', xml):
            node_str = node.group(0)
            if 'EditText' in node_str or 'class="android.widget.EditText"' in node_str:
                m = bounds_re.search(node_str)
                if m:
                    cx = (int(m.group(1)) + int(m.group(3))) // 2
                    cy = (int(m.group(2)) + int(m.group(4))) // 2
                    self._log_step(f"uiautomator: input field at ({cx},{cy})")
                    return (cx, cy)
        return None

    # ──────────────────────────────────────────────────────────────
    # Открытие формы регистрации
    # ──────────────────────────────────────────────────────────────

    async def _open_google_signup(self):
        """Открыть браузер и через CDP-JS пройти Sign In → Create account → For my personal use."""
        self._log_step("Opening WebView browser...")
        await self.action.open_url(SIGNUP_URL)
        await asyncio.sleep(6)

        for attempt in range(5):
            if await self._cdp_forward():
                break
            logger.warning(f"CDP forward attempt {attempt+1} failed — retrying in 3s...")
            await asyncio.sleep(3)
        else:
            raise RuntimeError("Could not forward CDP port after 5 attempts")
        await asyncio.sleep(1)

        for attempt in range(3):
            if await self._cdp_connect():
                break
            await asyncio.sleep(2)
        else:
            raise RuntimeError("Could not connect to CDP")

        for _ in range(15):
            url = await self._js_get_url()
            if "accounts.google.com" in url:
                break
            await asyncio.sleep(1)

        self._log_step(f"Page loaded: {url}")

        # If already on lifecycle/signup form (cookies from previous attempts), skip button clicks
        if "lifecycle" in url or "signup/name" in url or "signup" in url and "Create account" not in await self._js("document.body ? document.body.innerText : ''"):
            self._log_step("Already at signup form (cookies/cache), skipping Create account flow")
        else:
            self._log_step("JS click 'Create account'...")
            if not await self._js_click_text("Create account"):
                raise RuntimeError("Could not click 'Create account'")
            await asyncio.sleep(1.5)

            self._log_step("JS click 'For my personal use'...")
            clicked = await self._js_click_text("For my personal use")
            if not clicked:
                clicked = await self._js_click_text("For myself")
            if not clicked:
                raise RuntimeError("Could not click 'For my personal use'")
            await asyncio.sleep(3)

        url = await self._js_get_url()
        self._log_step(f"After selection URL: {url}")
        if "lifecycle" not in url and "signup" not in url:
            raise RuntimeError(f"Did not land on signup form, URL: {url}")

        self._log_step("Signup form ready — handing off to autopilot")

    # ──────────────────────────────────────────────────────────────
    # Автопилот с CDP + UIAutomator2 fallback (БЕЗ CV)
    # ──────────────────────────────────────────────────────────────

    async def _ensure_cdp(self):
        """Убедиться что CDP подключён."""
        if self._cdp_ws is None:
            await self._cdp_reconnect()
        url = await self._js_get_url()
        if not url:
            await self._cdp_reconnect()
        return await self._js_get_url()

    async def _run_deterministic_autopilot(self, max_steps: int = 80) -> bool:
        """Автопилот: CDP для веб-форм, UIAutomator2 для нативных экранов. БЕЗ CV."""
        sms_code: str | None = None
        phone_input_count = 0
        moph_tapped = False
        recent_actions: list[str] = []
        stall_counter = 0
        last_stage = ""
        stage_attempts = 0

        for step in range(1, max_steps + 1):
            await asyncio.sleep(0.8)

            # ── CDP reconnect + URL ──
            url = await self._ensure_cdp()
            stage = self._stage_from_url(url)

            # ── Fallback на UIAutomator2 если URL не даёт стадию ──
            if not stage:
                stage = await self._detect_stage_from_page_source()
                if stage == "done":
                    self._log_step(f"Done at step {step}: page_source")
                    return True
            else:
                pass  # CDP stage known

            self._log_step(f"Step {step}/{max_steps} | stage={stage} | url={url[:80]}")

            # ── Антизависание по стадии ──
            if stage == last_stage:
                stage_attempts += 1
            else:
                stage_attempts = 0
                last_stage = stage

            if stage_attempts >= 4:
                self._log_step(f"Stall on stage={stage} → scroll + UIAutomator2 fallback")
                await self.action.swipe_up()
                await asyncio.sleep(1)
                stage_attempts = 0
                continue

            # ══════════════ CDP-first обработка стадий ══════════════

            if stage == "name":
                ok = await self._cdp_fill_name()
                recent_actions.append(f"name:{'ok' if ok else 'fail'}")
                if not ok:
                    # UIAutomator2 fallback
                    await self._do_fill_name()
                await asyncio.sleep(2)
                continue

            if stage == "birthday":
                ok = await self._cdp_fill_birthday()
                recent_actions.append(f"birthday:{'ok' if ok else 'fail'}")
                if not ok:
                    await self._do_fill_birthday()
                await asyncio.sleep(2)
                continue

            if stage == "email":
                ok = await self._cdp_fill_email()
                recent_actions.append(f"email:{'ok' if ok else 'fail'}")
                if not ok:
                    await self._do_fill_email()
                await asyncio.sleep(2)
                continue

            if stage == "password":
                ok = await self._cdp_fill_password()
                recent_actions.append(f"password:{'ok' if ok else 'fail'}")
                if not ok:
                    await self._do_fill_password()
                await asyncio.sleep(2)
                continue

            if stage == "phone_consent":
                # Google consent page requires checking checkboxes before Next is enabled
                self._log_step("phone_consent: checking checkboxes...")
                cb_result = await self._js(r"""
(function() {
    var checked = 0;
    // MD3 checkbox elements
    var mdCbs = document.querySelectorAll('md-checkbox');
    for (var i = 0; i < mdCbs.length; i++) {
        if (!mdCbs[i].hasAttribute('checked')) {
            mdCbs[i].click();
            checked++;
        }
    }
    // Native input[type=checkbox]
    var inputs = document.querySelectorAll('input[type="checkbox"]');
    for (var i = 0; i < inputs.length; i++) {
        if (!inputs[i].checked) {
            inputs[i].click();
            checked++;
        }
    }
    // role="checkbox"
    var roles = document.querySelectorAll('[role="checkbox"]');
    for (var i = 0; i < roles.length; i++) {
        var state = roles[i].getAttribute('aria-checked');
        if (state !== 'true') {
            roles[i].click();
            checked++;
        }
    }
    // Material Design mdc-checkbox
    var mdcCbs = document.querySelectorAll('.mdc-checkbox, .VfPpkd-muHVFf-bMcfAe');
    for (var i = 0; i < mdcCbs.length; i++) {
        var inp = mdcCbs[i].querySelector('input[type="checkbox"]');
        if (inp && !inp.checked) {
            mdcCbs[i].click();
            checked++;
        }
    }
    return 'checked:' + checked;
})()
""")
                self._log_step(f"phone_consent checkboxes: {cb_result}")
                await asyncio.sleep(1)

                # Now click Next (should be enabled after checkboxes)
                ok = await self._js_click_next()
                if not ok:
                    for txt in ("next", "continue", "ok", "agree"):
                        if await self._js_click_text(txt):
                            ok = True
                            break
                if not ok:
                    await self.find_and_tap(
                        "Next or Continue button on phone verification consent screen",
                        retries=3, pause_after=2.0,
                    )
                recent_actions.append("phone_consent:clicked")
                await asyncio.sleep(3)
                continue

            if stage == "phone_input" and phone_input_count < 2:
                if getattr(config, "GOOGLE_STOP_AT_PHONE_VERIFICATION", False):
                    self._log_step("Phone input screen reached; stopping before phone entry as requested")
                    raise PhoneVerificationReached(stage="phone_input")
                phone_input_count += 1
                ok = await self._cdp_fill_phone()
                if not ok:
                    ok = await self._do_enter_phone()
                if ok:
                    recent_actions.append("phone_input:ok")
                    sms_code = await self._wait_for_sms_with_retry()
                    recent_actions.append(f"sms_code:{'ok' if sms_code else 'fail'}")
                else:
                    recent_actions.append("phone_input:fail")
                await asyncio.sleep(2)
                continue

            if stage == "phone_code":
                if getattr(config, "GOOGLE_STOP_AT_PHONE_VERIFICATION", False):
                    self._log_step("Phone code screen reached; stopping before SMS verification as requested")
                    raise PhoneVerificationReached(stage="phone_code")
                if sms_code:
                    ok = await self._cdp_fill_sms_code(sms_code)
                    if not ok:
                        ok = await self._do_enter_code(sms_code)
                    recent_actions.append(f"phone_code:{'ok' if ok else 'fail'}")
                else:
                    self._log_step("Waiting for SMS code...")
                    await asyncio.sleep(5)
                    recent_actions.append("phone_code:waiting")
                continue

            if stage == "terms":
                ok = await self._cdp_accept_terms()
                if not ok:
                    await self._do_accept_terms()
                recent_actions.append(f"terms:{'ok' if ok else 'fail'}")
                await asyncio.sleep(2)
                continue

            if stage == "moph_verify":
                # ── Проверяем текущее состояние экрана ──
                try_again_tapped = await self._uiautomator_tap_by_text("Try Again", "TRY AGAIN")
                if try_again_tapped:
                    self._log_step("'Try Again' detected and tapped — waiting for phone form...")
                    moph_tapped = True
                    await asyncio.sleep(3)
                    await asyncio.sleep(1)

                if not moph_tapped:
                    skipped = await self._uiautomator_tap_by_text(
                        "Skip", "Not now", "Maybe later", "Remind me later",
                    )
                    if not skipped:
                        tapped = await self._uiautomator_tap_by_text("Verify", "Verify phone")
                        if not tapped:
                            tapped = await self._js_click_text("verify")
                        if not tapped:
                            tapped = await self._uiautomator_tap_by_text("Confirm", "Continue", "Next", "OK")
                        if not tapped:
                            for alt_text in ("confirm", "continue", "get started", "i agree", "ok"):
                                if await self._js_click_text(alt_text):
                                    tapped = True
                                    break
                        if not tapped:
                            tapped_next = await self._js_click_next()
                            if tapped_next:
                                tapped = True
                        if tapped:
                            moph_tapped = True
                            recent_actions.append("moph_verify:verify_tapped")
                            self._log_step("Verify/Confirm tapped — waiting for phone input form...")
                            await asyncio.sleep(4)
                            try_again_immediate = await self._uiautomator_tap_by_text("Try Again", "TRY AGAIN")
                            if try_again_immediate:
                                self._log_step("'Try Again' appeared right after Verify — tapped")
                                await asyncio.sleep(3)
                        else:
                            recent_actions.append("moph_verify:verify_not_found")
                    else:
                        recent_actions.append("moph_verify:skipped")
                    await asyncio.sleep(1)

                if not moph_tapped:
                    continue

                # ── Ищем поле ввода телефона ──
                phone_clean = (self.phone_data or {}).get("phone", "").lstrip("+")

                typed_cdp = await self._cdp_fill_phone()
                if typed_cdp:
                    self._log_step(f"moph phone entered via CDP: {phone_clean}")
                    phone_input_count += 1
                    recent_actions.append("moph_phone:cdp_ok")
                    sms_code = await self._wait_for_sms_with_retry()
                    recent_actions.append(f"sms_code:{'ok' if sms_code else 'fail'}")
                    moph_tapped = False
                    await asyncio.sleep(2)
                    continue

                # UIAutomator2 — ищем EditText поле
                input_coord = await self._uiautomator_find_input()
                typed = False
                if input_coord:
                    cx, cy = input_coord
                    self._log_step(f"moph phone input via uiautomator at ({cx},{cy}): {phone_clean}")
                    await self.action.tap(cx, cy, pause=0.5)
                    await self.action.clear_field()
                    await self.action.type_text(phone_clean)
                    typed = True
                else:
                    typed_cdp2 = await self._js_set_input('input[type="tel"]', phone_clean)
                    if not typed_cdp2:
                        typed_cdp2 = await self._js_set_input('#phoneNumberId', phone_clean)
                    if typed_cdp2:
                        self._log_step(f"moph phone entered via CDP DOM: {phone_clean}")
                        typed = True
                    else:
                        self._log_step("No phone input field found — checking for Try Again")
                        retry_again = await self._uiautomator_tap_by_text("Try Again", "TRY AGAIN")
                        if retry_again:
                            self._log_step("Try Again tapped again — will retry next iteration")
                            moph_tapped = False
                        recent_actions.append("moph_phone:field_not_found")
                        await asyncio.sleep(2)
                        continue

                if typed:
                    await asyncio.sleep(0.5)
                    await self.action.press_enter()
                    await asyncio.sleep(1.0)
                    next_ok = await self.find_and_tap(
                        "Next or Continue button", retries=2, pause_after=2.0,
                    )
                    if not next_ok:
                        await self._js_click_next()
                        await asyncio.sleep(2.0)
                    phone_input_count += 1
                    recent_actions.append("moph_phone:entered")
                    sms_code = await self._wait_for_sms_with_retry()
                    recent_actions.append(f"sms_code:{'ok' if sms_code else 'fail'}")
                    moph_tapped = False
                else:
                    recent_actions.append("moph_phone:field_not_found")
                await asyncio.sleep(2)
                continue

            if stage == "extras":
                for skip_text in ("skip", "not now", "later", "no thanks", "maybe later", "continue"):
                    if await self._js_click_text(skip_text):
                        break
                else:
                    await self._js_click_next()
                recent_actions.append("extras:skip")
                await asyncio.sleep(2)
                continue

            if stage == "done":
                self._log_step(f"Done stage detected at step {step}")
                return True

            # ── Неизвестная стадия — UIAutomator2 fallback ──
            uia_stage = await self._detect_stage_from_page_source()
            if uia_stage == "done":
                self._log_step(f"Done at step {step}: page_source")
                return True

            # Пробуем common actions
            await self._try_common_actions()
            await asyncio.sleep(1)

        logger.warning(f"Autopilot exhausted {max_steps} steps")
        return False

    # ──────────────────────────────────────────────────────────────
    # SMS retry (override for Chrome scenario)
    # ──────────────────────────────────────────────────────────────

    _SMS_ROTATION = [
        ("indonesia", "virtual53"),
        ("indonesia", "virtual4"),
        ("indonesia", "virtual58"),
        ("india",     "any"),
        ("indonesia", "any"),
        ("kazakhstan","any"),
    ]

    async def _wait_for_sms_with_retry(self) -> str | None:
        """Chrome-override: ждать SMS, при таймауме ротировать страну/оператор."""
        if self._is_manual_phone():
            try:
                code = await self._wait_for_manual_sms_code(timeout=600)
                logger.success("Manual SMS code received")
                return code
            except Exception as e:
                logger.error(f"Manual SMS code was not provided: {e}")
                return None

        self._log_step("Waiting for SMS verification code (up to 90s)...")
        try:
            code = await self.sms.wait_for_code(
                order_id=self.phone_data["id"],
                timeout=90,
                poll_interval=3,
            )
            logger.success(f"SMS code received: {code}")
            await self.sms.finish_order(self.phone_data["id"])
            return code
        except TimeoutError:
            pass

        failed_op = (self.phone_data or {}).get("operator", "")
        failed_country = "indonesia"
        failed_key = (failed_country, failed_op)
        self._sms_failed.add(failed_key)
        logger.warning(f"SMS timeout on {failed_key} → rotating (failed so far: {self._sms_failed})")
        try:
            await self.sms.cancel_order(self.phone_data["id"])
        except Exception:
            pass

        for country, op in self._SMS_ROTATION:
            key = (country, op)
            if key in self._sms_failed:
                continue
            logger.info(f"Trying {country}/{op}...")
            try:
                self.phone_data = await self.sms.buy_number(
                    service="google", country=country, operator=op,
                )
                logger.info(f"Bought {self.phone_data['phone']} ({country}/{op})")
                return None  # moph_verify handler заново введёт телефон
            except Exception as e:
                logger.warning(f"  buy failed {country}/{op}: {e}")
                self._sms_failed.add(key)
                continue

        logger.error("SMS: exhausted all country/operator combinations")
        return None

    @staticmethod
    def _stage_from_url(url: str) -> str | None:
        if not url:
            return None
        u = url.lower()
        if "signup/name" in u:                                    return "name"
        if "signup/birthday" in u or "birthdaygender" in u:       return "birthday"
        if "signup/username" in u:                                 return "email"
        if "signup/createpasswd" in u or "signup/password" in u:  return "password"
        if "signup/phonenumber" in u or "signup/phone" in u:       return "phone_input"
        if "signup/verifyphone" in u or "signup/verify" in u:      return "phone_code"
        if "mophoneverification" in u:                             return "moph_verify"
        if "devicephoneverification/consent" in u:                 return "phone_consent"
        if "devicephoneverification" in u:                         return "phone_input"
        if "phoneverification" in u:                               return "phone_input"
        if "termsofservice" in u or "steps/terms" in u or "signup/termsofservice" in u: return "terms"
        if "myaccount.google.com" in u or "manageaccount" in u:   return "done"
        return None
