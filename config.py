"""
Конфиг проекта.
GOOGLE_EMAIL и GOOGLE_PASSWORD могут заполняться автоматически
после регистрации нового аккаунта.
"""
import os

from core.game_profiles import resolve_game_profile


def _env_bool(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _env_choice(name: str, default: str, choices: tuple[str, ...]) -> str:
    value = os.getenv(name, default).strip().lower()
    return value if value in choices else default


# ══════════════════════════════════════════════════
# Dashboard auth
# ══════════════════════════════════════════════════
DASHBOARD_AUTH_ENABLED = _env_bool("DASHBOARD_AUTH_ENABLED", "1")
DASHBOARD_USERNAME = os.getenv("DASHBOARD_USERNAME", "admin").strip() or "admin"
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "change-me").strip() or "change-me"
DASHBOARD_SESSION_TTL_SECONDS = int(os.getenv("DASHBOARD_SESSION_TTL_SECONDS", "86400"))
DASHBOARD_MCP_API_KEY = os.getenv("DASHBOARD_MCP_API_KEY", "change-me").strip() or "change-me"


# ══════════════════════════════════════════════════
# OpenRouter — может использоваться для других задач
# ══════════════════════════════════════════════════
OPENROUTER_API_KEY = os.getenv(
    "OPENROUTER_API_KEY",
    ""
)
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# ══════════════════════════════════════════════════
# Vision LLM (CVEngine)
# ══════════════════════════════════════════════════
CV_MODELS = [
    model.strip()
    for model in os.getenv("CV_MODELS", "xiaomi/mimo-v2.5").split(",")
    if model.strip()
]
CV_REQUEST_TIMEOUT = int(os.getenv("CV_REQUEST_TIMEOUT", "60"))
CV_MODEL_ATTEMPTS = int(os.getenv("CV_MODEL_ATTEMPTS", "3"))
CV_MAX_TOKENS = int(os.getenv("CV_MAX_TOKENS", "4096"))
CV_JSON_REPAIR_ATTEMPTS = int(os.getenv("CV_JSON_REPAIR_ATTEMPTS", "1"))
CV_AUTOPILOT_MAX_STEPS = int(os.getenv("CV_AUTOPILOT_MAX_STEPS", "45"))
CV_GAME_TUTORIAL_MAX_STEPS = int(os.getenv("CV_GAME_TUTORIAL_MAX_STEPS", "120"))
CV_PURCHASE_PREVIEW_MAX_STEPS = int(os.getenv("CV_PURCHASE_PREVIEW_MAX_STEPS", "45"))
CV_COORDINATE_SCALE = os.getenv("CV_COORDINATE_SCALE", "").strip()
CV_FAILURE_FALLBACK_TO_MANUAL = _env_bool("CV_FAILURE_FALLBACK_TO_MANUAL", "0")
CV_INSTALL_GOAL_TEMPLATE = os.getenv("CV_INSTALL_GOAL_TEMPLATE", "").strip()
CV_TUTORIAL_GOAL_TEMPLATE = os.getenv("CV_TUTORIAL_GOAL_TEMPLATE", "").strip()
CV_PURCHASE_GOAL_TEMPLATE = os.getenv("CV_PURCHASE_GOAL_TEMPLATE", "").strip()
CV_INSTALL_GOAL_EXTRA = os.getenv("CV_INSTALL_GOAL_EXTRA", "").strip()
CV_TUTORIAL_GOAL_EXTRA = os.getenv("CV_TUTORIAL_GOAL_EXTRA", "").strip()
CV_PURCHASE_GOAL_EXTRA = os.getenv("CV_PURCHASE_GOAL_EXTRA", "").strip()
CV_EXTRA_BLOCKER_WORDS = tuple(
    word.strip()
    for word in os.getenv("CV_EXTRA_BLOCKER_WORDS", "").split(",")
    if word.strip()
)
CV_COORDINATE_GRID = _env_bool("CV_COORDINATE_GRID", "1")
CV_COORDINATE_GRID_STEP = int(os.getenv("CV_COORDINATE_GRID_STEP", "240"))

# ══════════════════════════════════════════════════
# Local-first perception rollout
# ══════════════════════════════════════════════════
PERCEPTION_MODE = _env_choice(
    "PERCEPTION_MODE",
    "local_first",
    ("llm_first", "local_first", "local_only", "shadow"),
)
FRAME_SOURCE = _env_choice(
    "FRAME_SOURCE",
    "adb",
    ("adb", "adb_raw", "screenrecord", "replay", "scrcpy", "minicap"),
)
FRAME_SOURCE_INCLUDE_PNG = _env_bool("FRAME_SOURCE_INCLUDE_PNG", "1")
ACTION_MODE = _env_choice(
    "ACTION_MODE",
    "menu",
    ("menu", "fast"),
)
ENABLE_TEMPLATE_PROVIDER = _env_bool("ENABLE_TEMPLATE_PROVIDER", "1")
ENABLE_UIAUTOMATOR_PROVIDER = _env_bool("ENABLE_UIAUTOMATOR_PROVIDER", "1")
ENABLE_LLM_FALLBACK = _env_bool("ENABLE_LLM_FALLBACK", "1")
ENABLE_DETECTOR_PROVIDER = _env_bool("ENABLE_DETECTOR_PROVIDER", "0")
DETECTOR_MODEL_PATH = os.getenv("DETECTOR_MODEL_PATH", "").strip()
DETECTOR_CONFIDENCE_THRESHOLD = float(os.getenv("DETECTOR_CONFIDENCE_THRESHOLD", "0.50"))

# ══════════════════════════════════════════════════
# Ферма устройств: local | genymotion | browserstack | lambdatest
# ══════════════════════════════════════════════════
DEVICE_FARM = os.getenv("DEVICE_FARM", "local").strip().lower()

# ══════════════════════════════════════════════════
# Local emulator (Appium + AVD)
# ══════════════════════════════════════════════════
APPIUM_PORT = int(os.getenv("APPIUM_PORT", "4723"))
LOCAL_DEVICE = os.getenv("LOCAL_DEVICE", "emulator-5554")

# ══════════════════════════════════════════════════
# BrowserStack App Automate (реальные устройства с Play Market)
# ══════════════════════════════════════════════════
BROWSERSTACK_USERNAME = os.getenv("BROWSERSTACK_USERNAME", "").strip()
BROWSERSTACK_ACCESS_KEY = os.getenv("BROWSERSTACK_ACCESS_KEY", "").strip()
BROWSERSTACK_DEVICE = os.getenv("BROWSERSTACK_DEVICE", "Google Pixel 7").strip()
BROWSERSTACK_OS_VERSION = os.getenv("BROWSERSTACK_OS_VERSION", "13.0").strip()

# ══════════════════════════════════════════════════
# LambdaTest Real Devices (реальные устройства с Play Market)
# ══════════════════════════════════════════════════
LT_USERNAME = os.getenv("LT_USERNAME", "").strip()
LT_ACCESS_KEY = os.getenv("LT_ACCESS_KEY", "").strip()
LT_DEVICE = os.getenv("LT_DEVICE", "Pixel 7").strip()
LT_OS_VERSION = os.getenv("LT_OS_VERSION", "14").strip()

# ══════════════════════════════════════════════════
# Genymotion Cloud — ферма Android-устройств
# ══════════════════════════════════════════════════
GENYMOTION_API_TOKEN = os.getenv(
    "GENYMOTION_API_TOKEN",
    ""
)
# Публичный SaaS API
GENYMOTION_API_URL = os.getenv(
    "GENYMOTION_API_URL",
    "https://api.geny.io/cloud",
)

# ══════════════════════════════════════════════════
# 5sim.net — SMS-аренда номеров
# ══════════════════════════════════════════════════
FIVESIM_API_KEY = os.getenv(
    "FIVESIM_API_KEY",
    ""
)
FIVESIM_BASE_URL = "https://5sim.net/v1"
FIVESIM_PROXY = os.getenv(
    "FIVESIM_PROXY",
    "",
).strip()
GOOGLE_WEB_PROXY = os.getenv("GOOGLE_WEB_PROXY", "").strip()

# ══════════════════════════════════════════════════
# Google Account
# ══════════════════════════════════════════════════
GOOGLE_EMAIL = os.getenv("GOOGLE_EMAIL", "")
GOOGLE_PASSWORD = os.getenv("GOOGLE_PASSWORD", "")

# Регистрация нового аккаунта:
#   web    — accounts.google.com в Chromium (Playwright), без Android
#   chrome — Chrome WebView на устройстве (CDP)
#   cv     — Chrome на устройстве + screenshot/Vision autopilot
#   android — Settings → Add Account (UIAutomator2)
_GOOGLE_REG_VIA = os.getenv("GOOGLE_REGISTER_VIA", "chrome").strip().lower()
_google_reg_via_resolved = (
    _GOOGLE_REG_VIA if _GOOGLE_REG_VIA in ("web", "android", "chrome", "cv") else "chrome"
)
GOOGLE_REGISTER_VIA = (
    "android"
    if DEVICE_FARM in ("browserstack", "lambdatest") and _google_reg_via_resolved in ("chrome", "cv")
    else _google_reg_via_resolved
)
GOOGLE_REGISTER_SKIP_PLAY_STORE = (
    os.getenv("GOOGLE_REGISTER_SKIP_PLAY_STORE", "").strip().lower() in ("1", "true", "yes", "on")
    or DEVICE_FARM in ("browserstack", "lambdatest")
)

# Phone verification mode for Google signup:
#   manual — legal/user-controlled: use GOOGLE_PHONE_NUMBER and GOOGLE_SMS_CODE
#            or GOOGLE_SMS_CODE_FILE; no disposable number auto-buy/rotation.
#   fivesim — legacy 5sim automation for services where this is permitted.
GOOGLE_PHONE_MODE = os.getenv("GOOGLE_PHONE_MODE", "manual").strip().lower()
GOOGLE_PHONE_NUMBER = os.getenv("GOOGLE_PHONE_NUMBER", "").strip()
GOOGLE_SMS_CODE = os.getenv("GOOGLE_SMS_CODE", "").strip()
GOOGLE_SMS_CODE_FILE = os.getenv("GOOGLE_SMS_CODE_FILE", "").strip()
GOOGLE_STOP_AT_PHONE_VERIFICATION = _env_bool("GOOGLE_STOP_AT_PHONE_VERIFICATION", "0")
GOOGLE_WEB_HEADLESS = _env_bool("GOOGLE_WEB_HEADLESS", "0")
try:
    GOOGLE_WEB_SLOW_MO_MS = int(os.getenv("GOOGLE_WEB_SLOW_MO_MS", "0") or "0")
except ValueError:
    GOOGLE_WEB_SLOW_MO_MS = 0

# ══════════════════════════════════════════════════
# Платёжная карта
# ══════════════════════════════════════════════════
CARD_NUMBER = os.getenv("CARD_NUMBER", "")
CARD_EXPIRY = os.getenv("CARD_EXPIRY", "")
CARD_CVV = os.getenv("CARD_CVV", "")
ALLOW_PURCHASE_WITHOUT_CARD = _env_bool("ALLOW_PURCHASE_WITHOUT_CARD", "0")
INSTALL_AUTOPILOT_VIA = os.getenv("INSTALL_AUTOPILOT_VIA", "cv").strip().lower()
GAME_AUTOPILOT_VIA = os.getenv("GAME_AUTOPILOT_VIA", "cv").strip().lower()
PURCHASE_AUTOPILOT_VIA = os.getenv("PURCHASE_AUTOPILOT_VIA", "cv").strip().lower()
PURCHASE_MODE = os.getenv("PURCHASE_MODE", "preview").strip().lower()
PURCHASE_PREVIEW_LEAVE_OPEN = _env_bool("PURCHASE_PREVIEW_LEAVE_OPEN", "0")
GAME_PROFILE = os.getenv("GAME_PROFILE", "").strip()
_GAME_NAME_RAW = os.getenv("GAME_NAME", "").strip()
_GAME_PACKAGE_RAW = os.getenv("GAME_PACKAGE", "").strip()
SELECTED_GAME_PROFILE = resolve_game_profile(
    GAME_PROFILE or _GAME_NAME_RAW or _GAME_PACKAGE_RAW,
    game_name=_GAME_NAME_RAW,
    package=_GAME_PACKAGE_RAW,
)
GAME_PROFILE_ID = SELECTED_GAME_PROFILE.id
GAME_NAME = _GAME_NAME_RAW or SELECTED_GAME_PROFILE.name
GAME_PACKAGE = _GAME_PACKAGE_RAW or SELECTED_GAME_PROFILE.package
GAME_PLAYER_NAME_PREFIX = os.getenv(
    "GAME_PLAYER_NAME_PREFIX",
    SELECTED_GAME_PROFILE.player_name_prefix,
).strip()
GAME_APK_PATH = os.getenv("GAME_APK_PATH", "").strip()
GAMEPLAY_AUTOPILOT_VIA = os.getenv("GAMEPLAY_AUTOPILOT_VIA", "fast").strip().lower()
FAST_RUNNER_PACKAGES = tuple(
    p.strip()
    for p in os.getenv(
        "FAST_RUNNER_PACKAGES",
        "com.kiloo.subwaysurf,com.imangi.templerun2",
    ).split(",")
    if p.strip()
)
FAST_GAMEPLAY_SECONDS = float(os.getenv("FAST_GAMEPLAY_SECONDS", "35"))
FAST_GAMEPLAY_FRAME_DELAY = float(os.getenv("FAST_GAMEPLAY_FRAME_DELAY", "0.05"))
GAMEPLAY_REQUIRED = _env_bool("GAMEPLAY_REQUIRED", "0")
MATCH3_GRID_ROWS = int(os.getenv("MATCH3_GRID_ROWS", "9"))
MATCH3_GRID_COLS = int(os.getenv("MATCH3_GRID_COLS", "9"))
MATCH3_GRID_BOUNDS = os.getenv("MATCH3_GRID_BOUNDS", "").strip()
MATCH3_MAX_MOVES = int(os.getenv("MATCH3_MAX_MOVES", "12"))
MANUAL_CONTROL_SIGNAL_FILE = os.getenv(
    "MANUAL_CONTROL_SIGNAL_FILE",
    "dashboard/manual_continue.flag",
).strip()
MANUAL_CONTROL_TIMEOUT_SECONDS = int(os.getenv("MANUAL_CONTROL_TIMEOUT_SECONDS", "600"))
RECORDED_INSTALL_PATH = os.getenv("RECORDED_INSTALL_PATH", "").strip()
RECORDED_TUTORIAL_PATH = os.getenv("RECORDED_TUTORIAL_PATH", "").strip()
RECORDED_GAMEPLAY_PATH = os.getenv("RECORDED_GAMEPLAY_PATH", "").strip()

# ══════════════════════════════════════════════════
# Настройки устройства (Genymotion Cloud)
# ══════════════════════════════════════════════════
TARGET_ANDROID_VERSION = os.getenv("TARGET_ANDROID_VERSION", "12.0").strip()
TARGET_DEVICE_KEYWORD = os.getenv("TARGET_DEVICE_KEYWORD", "pixel").strip()
GENYMOTION_RECIPE_UUID = os.getenv(
    "GENYMOTION_RECIPE_UUID",
    "3012be8a-1901-42d8-9779-5687817dfaf2",
).strip()
GENYMOTION_RECIPE_NAME_CONTAINS = os.getenv(
    "GENYMOTION_RECIPE_NAME_CONTAINS", ""
).strip()
GENYMOTION_RECIPE_ALLOW_FALLBACK = _env_bool("GENYMOTION_RECIPE_ALLOW_FALLBACK", "1")
SCREEN_WIDTH = 1080
SCREEN_HEIGHT = 2400

# ══════════════════════════════════════════════════
# Тайминги
# ══════════════════════════════════════════════════
TOTAL_TIMEOUT_SECONDS = 180       # 3 минуты на весь сценарий
ADB_COMMAND_TIMEOUT = 30          # макс время на ADB команду
POLL_INTERVAL = 0.5               # пауза между шагами
SCREENSHOT_DIR = "screenshots"    # папка для debug-скриншотов

# ══════════════════════════════════════════════════
# Трассировка и диагностика
# ══════════════════════════════════════════════════
TRACE_ENABLED = os.getenv("TRACE_ENABLED", "1").strip() not in ("0", "false", "False")
TRACE_DIR = os.getenv("TRACE_DIR", "trace").strip()

# Какие этапы запускать в main
RUN_STAGES = os.getenv("RUN_STAGES", "").strip()

# TEST_RUN: если GOOGLE_EMAIL/PASSWORD не заданы — взять последний
# аккаунт из credentials.json и войти (без новой регистрации).
_TEST_RUN_RAW = os.getenv("TEST_RUN", "0").strip().lower()
TEST_RUN = _TEST_RUN_RAW in ("1", "true", "yes", "on")
CREDENTIALS_JSON_PATH = os.getenv("CREDENTIALS_JSON_PATH", "credentials.json").strip()

# Эксперимент: прошить zip через /system/bin/flash-archive.sh
_GAPPS_TRY_RAW = os.getenv("GENYMOTION_TRY_ADB_GAPPS", "0").strip().lower()
GENYMOTION_TRY_ADB_GAPPS = _GAPPS_TRY_RAW in ("1", "true", "yes", "on")
GENYMOTION_ADB_GAPPS_ZIP = os.getenv("GENYMOTION_ADB_GAPPS_ZIP", "").strip()

# Перед стартом нового device останавливать уже запущенные Genymotion инстансы.
STOP_RUNNING_INSTANCES_ON_START = (
    os.getenv("STOP_RUNNING_INSTANCES_ON_START", "1").strip()
    not in ("0", "false", "False")
)
