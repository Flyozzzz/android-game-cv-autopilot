# Требования к Android Automation Pipeline

## Device Farm: LambdaTest (ОБЯЗАТЕЛЬНО)
- **НЕ BrowserStack** — BrowserStack НЕ использовать
- Hub URL: `https://mobile-hub.lambdatest.com/wd/hub`
- Username: `dobroeprosto`
- Access Key: `LT_VQ0C1s1vhqmZe7ah5Jpf9r3gYYKfVtdZkYdF1yGugUS3uQS`
- Device: Pixel 7, Android 14
- Capabilities: `lt:options` (не `bstack:options`)

## Что работает на LambdaTest (подтверждено)
1. **`mobile: shell`** — ADB shell команды работают!
   - `am start -a android.settings.ADD_ACCOUNT_SETTINGS` — открывает Add Account
   - `screencap -p | base64 | tr -d '\\n'` — скриншоты через ADB
   - `dumpsys activity top` — текущая активность
   - `echo`, `cat`, `ls` — базовые команды
2. **`activate_app(pkg)`** — открывает приложения по package name
3. **`get_screenshot_as_png()`** — Appium скриншоты (бывают таймауты!)
4. **`page_source`** — XML дерево UI (бывает зависает на 20+ сек)
5. **`find_element()` / `find_elements()`** — UiAutomator2 поиск элементов
6. **`driver.swipe()`** — свайпы для скроллинга
7. **`driver.tap()`** — тап по координатам
8. **`driver.press_keycode()`** — нажатие кнопок (Back, Enter и т.д.)

## Что НЕ работает на LambdaTest
1. **UiScrollable.scrollIntoView()** — сломан, находит не те элементы или NoSuchElement
2. **`mobile: deepLink`** с action names — конвертирует в VIEW intent с пустым data (не работает)
   - deepLink с URL (`market://`) — может работать
3. **`start_activity()`** — НЕТ такого метода в Appium Python

## Проблемы с зависанием
- **`page_source`** висит 20+ сек на LambdaTest real devices — нужен threading timeout (20с)
- **`get_screenshot_as_png()`** может зависнуть — нужен threading timeout (20с)
- **Session creation** занимает 60+ сек когда нет свободных устройств
- Решение: `_run_with_timeout(fn, timeout=20)` — threading-based timeout для всех блокирующих вызовов

## Альтернативные скриншоты (если Appium зависает)
```python
# ADB screencap | base64 (всегда работает)
b64 = adb(driver, "screencap -p | base64 | tr -d '\\n'")
png = base64.b64decode(b64)
```

## Pipeline Flow
1. **Session creation** — LambdaTest Appium, Pixel 7, Android 14
2. **Warmup** — activate_app(Settings) + page_source check (с таймаутом)
3. **Open Add Account** — ADB `am start -a android.settings.ADD_ACCOUNT_SETTINGS`
4. **Select Google** — click_text("Google") + dismiss_popups()
5. **Sign-In** — WebView или Native (email → password → accept loop)
6. **Play Store** — activate_app("com.android.vending")
7. **Install Clash Royale** — search + click Install

## Аккаунт для тестирования
- Тестовые аккаунты и пароли не храним в документации. Используй dashboard
  credentials fields или env-переменные для локального запуска.

## Credentials (14 аккаунтов в credentials.json)
- Используются по кругу для pipeline запусков
- После входа аккаунт может заблокироваться Google

## Файлы
- `legacy/scripts/step_x10.py` — старый pipeline (LambdaTest)
- `legacy/scripts/lt_test_ss.py` — старый тест скриншотов LambdaTest
- `legacy/scripts/lt_diag.py` — старая диагностика LambdaTest
- `config.py` — все креды и настройки
- `credentials.json` — Google аккаунты
- `services/lambdatest_farm.py` — LambdaTest farm client (async)
- `scenarios/google_register_web.py` — регистрация Google через Playwright

## Текущая проблема
- Сессия LambdaTest создается но `page_source` зависает
- Нужно: threading timeout на page_source и screenshot
- Старый `step_x10.py` зависал на `driver.page_source` без таймаута
- Фикс: уже добавлен `_run_with_timeout()` с 20с таймаутом
- НЕ ТЕСТИРОВАНО с новыми кредитами — нужно запустить
