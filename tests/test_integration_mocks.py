import asyncio

import httpx
import pytest

import bootstrap
import config
from core.appium_action_engine import AppiumActionEngine
from services.browserstack_farm import BrowserStackFarm
from services.lambdatest_farm import LambdaTestFarm
from services.local_farm import LocalEmulatorFarm
from services.sms_service import SMSService


pytestmark = pytest.mark.integration


PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00"
)


class FakeHTTPResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text or jsonish(self._payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("bad", request=None, response=None)


def jsonish(value):
    return str(value).replace("'", '"')


class FakeAsyncClient:
    def __init__(self, *args, responses=None, **kwargs):
        self.responses = list(responses or [FakeHTTPResponse()])
        self.kwargs = kwargs
        self.calls = []
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.closed = True

    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if len(self.responses) > 1:
            return self.responses.pop(0)
        return self.responses[0]

    async def aclose(self):
        self.closed = True


class FakeProc:
    def __init__(self, stdout=b"", stderr=b"", returncode=0):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode

    async def communicate(self):
        return self._stdout, self._stderr


def test_local_farm_connected_devices_and_check_api(monkeypatch):
    monkeypatch.setattr(config, "LOCAL_DEVICE", "auto")
    monkeypatch.setattr(config, "APPIUM_PORT", 4723)

    async def fake_subprocess(*args, **kwargs):
        assert args[:2] == ("adb", "devices")
        return FakeProc(b"List of devices attached\nemulator-5554\tdevice product:sdk\n")

    monkeypatch.setattr(LocalEmulatorFarm, "_adb_path", staticmethod(lambda: "adb"))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *a, **k: FakeAsyncClient(responses=[
            FakeHTTPResponse(200, {"value": {"ready": True}})
        ]),
    )

    farm = LocalEmulatorFarm()

    assert asyncio.run(farm._connected_devices()) == ["emulator-5554"]
    assert farm._select_device(["emulator-5554"]) == "emulator-5554"
    assert asyncio.run(farm.check_api()) is True
    assert farm.device_serial == "emulator-5554"


def test_local_farm_rejects_multiple_or_missing_requested_device(monkeypatch):
    farm = LocalEmulatorFarm()

    monkeypatch.setattr(config, "LOCAL_DEVICE", "missing")
    with pytest.raises(RuntimeError, match="not connected"):
        farm._select_device(["emulator-5554"])

    monkeypatch.setattr(config, "LOCAL_DEVICE", "auto")
    with pytest.raises(RuntimeError, match="Multiple Android devices"):
        farm._select_device(["emu1", "emu2"])


def test_remote_provider_api_checks_are_mocked(monkeypatch):
    monkeypatch.setattr(config, "BROWSERSTACK_USERNAME", "user")
    monkeypatch.setattr(config, "BROWSERSTACK_ACCESS_KEY", "key")
    monkeypatch.setattr(config, "LT_USERNAME", "lt-user")
    monkeypatch.setattr(config, "LT_ACCESS_KEY", "lt-key")

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *a, **k: FakeAsyncClient(responses=[
            FakeHTTPResponse(200, {"parallel_sessions_max_allowed": 1, "automate_plan": "test"})
        ]),
    )
    assert asyncio.run(BrowserStackFarm().check_api()) is True

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *a, **k: FakeAsyncClient(responses=[FakeHTTPResponse(200, {"data": []})]),
    )
    assert asyncio.run(LambdaTestFarm().check_api()) is True

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *a, **k: FakeAsyncClient(responses=[FakeHTTPResponse(401, {}, "unauthorized")]),
    )
    assert asyncio.run(BrowserStackFarm().check_api()) is False
    assert asyncio.run(LambdaTestFarm().check_api()) is False


def test_remote_provider_api_checks_fail_without_credentials(monkeypatch):
    monkeypatch.setattr(config, "BROWSERSTACK_USERNAME", "")
    monkeypatch.setattr(config, "BROWSERSTACK_ACCESS_KEY", "")
    monkeypatch.setattr(config, "LT_USERNAME", "")
    monkeypatch.setattr(config, "LT_ACCESS_KEY", "")

    assert asyncio.run(BrowserStackFarm().check_api()) is False
    assert asyncio.run(LambdaTestFarm().check_api()) is False


def test_sms_service_http_paths_are_mocked(monkeypatch):
    service = SMSService(api_key="token")
    service.client = FakeAsyncClient(responses=[
        FakeHTTPResponse(200, {"balance": "12.5"}),
        FakeHTTPResponse(200, {"id": 123, "phone": "+15550001111", "operator": "any", "price": 1}),
        FakeHTTPResponse(200, {"status": "RECEIVED", "sms": [{"text": "Your code is G-123456"}]}),
        FakeHTTPResponse(200, {"ok": True}),
        FakeHTTPResponse(200, {"ok": True}),
        FakeHTTPResponse(200, {"ok": True}),
    ])

    assert asyncio.run(service.check_balance()) == 12.5
    number = asyncio.run(service.buy_number(service="telegram", country="usa"))
    assert number["id"] == "123"
    assert number["phone"] == "+15550001111"
    assert asyncio.run(service.wait_for_code(timeout=1, poll_interval=1)) == "123456"
    asyncio.run(service.finish_order())
    asyncio.run(service.cancel_order())
    asyncio.run(service.ban_number())


def test_sms_service_error_and_retry_paths(monkeypatch):
    service = SMSService(api_key="")
    service.client = FakeAsyncClient(responses=[FakeHTTPResponse(401, {}, "bad token")])
    assert asyncio.run(service.check_api()) is False

    service.client = FakeAsyncClient(responses=[FakeHTTPResponse(400, {"error": "no"}, "no numbers")])
    with pytest.raises(RuntimeError, match="Cannot buy number"):
        asyncio.run(service.buy_number())

    attempts = []

    async def fail_buy_number(*args, **kwargs):
        attempts.append((args, kwargs))
        raise RuntimeError("sold out")

    monkeypatch.setattr(service, "buy_number", fail_buy_number)
    with pytest.raises(RuntimeError, match="Failed to buy number"):
        asyncio.run(service.buy_number_with_retry(countries=["usa"], operators=["any", "tmobile"], max_retries=1))
    assert len(attempts) == 2


def test_appium_action_engine_local_adb_boundaries(monkeypatch):
    monkeypatch.setattr(config, "DEVICE_FARM", "local")
    monkeypatch.setattr(config, "LOCAL_DEVICE", "emulator-5554")

    calls = []

    async def fake_run_adb(*args, timeout=None):
        calls.append((args, timeout))
        return "ok"

    engine = AppiumActionEngine(driver=object())
    monkeypatch.setattr(engine, "_run_adb", fake_run_adb)

    asyncio.run(engine.tap(10, 20, pause=0))
    asyncio.run(engine.type_text("hello world", pause=0))
    asyncio.run(engine.press_key("KEYCODE_BACK"))
    asyncio.run(engine.clear_field())

    assert ("shell", "input", "tap", "10", "20") in [call[0] for call in calls]
    assert any(call[0][:4] == ("shell", "input", "text", "hello%sworld") for call in calls)
    assert any(call[0] == ("shell", "input", "keyevent", "4") for call in calls)
    assert AppiumActionEngine._adb_input_text_arg("a b&$") == r"a%sb\&\$"


def test_appium_action_engine_screenshot_and_raw_screencap(monkeypatch):
    monkeypatch.setattr(config, "DEVICE_FARM", "local")
    monkeypatch.setattr(config, "LOCAL_DEVICE", "emulator-5554")

    async def fake_subprocess(*args, **kwargs):
        assert "screencap" in args
        return FakeProc(PNG_1X1)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)
    engine = AppiumActionEngine(driver=object())

    data = asyncio.run(engine.screenshot())
    raw = asyncio.run(engine._run_adb_raw("exec-out", "screencap", "-p"))

    assert data.startswith(b"\x89PNG")
    assert raw.startswith(b"\x89PNG")


def test_bootstrap_check_all_apis_with_mocked_local_farm(monkeypatch):
    class FakeFarm:
        async def check_api(self):
            return True

        async def close(self):
            self.closed = True

    class FakeSMS:
        async def check_api(self):
            return True

        async def close(self):
            self.closed = True

    monkeypatch.setattr(config, "DEVICE_FARM", "local")
    monkeypatch.setattr("services.local_farm.LocalEmulatorFarm", lambda: FakeFarm())
    monkeypatch.setattr(bootstrap, "SMSService", lambda: FakeSMS())

    assert asyncio.run(bootstrap.check_all_apis()) == {"local": True, "5sim": True}
    assert asyncio.run(bootstrap.check_all_apis(skip_fivesim=True)) == {"local": True, "5sim": True}
