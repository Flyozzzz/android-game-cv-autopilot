import os
import asyncio
from io import BytesIO
import json
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

from PIL import Image, ImageStat
import pytest

from core.frame_source import AdbScreencapSource
from core.perception.element import ElementCandidate
from core.perception.finder import ElementFinder
from core.perception.providers.base import ElementProvider, ProviderContext
from core.perception.providers.template_provider import TemplateProvider
from core.perception.providers.uiautomator_provider import UIAutomatorProvider
from core.perception.template_registry import TemplateRegistry


pytestmark = [pytest.mark.integration, pytest.mark.live_adb]


def _adb_path() -> str:
    configured = os.getenv("ADB_PATH", "").strip()
    if configured:
        if shutil.which(configured) or os.path.exists(configured):
            return configured
        pytest.skip(f"ADB_PATH={configured} is not available")
    adb = shutil.which("adb")
    if not adb:
        pytest.skip("ADB executable is not available")
    return adb


def _connected_devices() -> list[str]:
    proc = subprocess.run(
        [_adb_path(), "devices", "-l"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=10,
    )
    if proc.returncode != 0:
        return []
    serials = []
    for line in proc.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            serials.append(parts[0])
    return serials


def _target_serial() -> str:
    devices = _connected_devices()
    if not devices:
        pytest.skip("No live ADB device connected")
    requested = (os.getenv("LOCAL_DEVICE") or "").strip()
    if requested and requested.lower() not in {"auto", "first"}:
        if requested not in devices:
            pytest.skip(f"LOCAL_DEVICE={requested} not connected; connected={devices}")
        return requested
    return devices[0]


def test_live_adb_screenshot_and_ui_dump_are_available():
    """Read-only smoke test for a real phone or emulator connected over ADB."""

    serial = _target_serial()
    shot = subprocess.run(
        [_adb_path(), "-s", serial, "exec-out", "screencap", "-p"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
    )
    assert shot.returncode == 0, shot.stderr.decode(errors="ignore")
    assert shot.stdout.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(shot.stdout) > 1000

    ui = subprocess.run(
        [_adb_path(), "-s", serial, "exec-out", "uiautomator", "dump", "/dev/tty"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=25,
    )
    assert ui.returncode == 0, ui.stderr
    assert "<hierarchy" in ui.stdout
    assert "package=" in ui.stdout


def test_live_adb_local_first_template_provider_matches_real_frame(tmp_path):
    """Capture a real frame and match a real crop locally with OpenCV/Pillow."""

    serial = _target_serial()
    frame = asyncio.run(AdbScreencapSource(serial=serial, adb_path=_adb_path()).latest_frame())
    assert frame.source_name == "adb"
    assert frame.png_bytes and frame.png_bytes.startswith(b"\x89PNG\r\n\x1a\n")

    image = Image.open(BytesIO(frame.png_bytes)).convert("RGB")
    crop_box = _high_variance_crop(image, size=48)
    if float(ImageStat.Stat(image.crop(crop_box).convert("L")).stddev[0]) < 1.0:
        pytest.skip("Live ADB screen is too flat for a meaningful template smoke; wake/unlock the device")
    template_path = tmp_path / "live_crop.png"
    image.crop(crop_box).save(template_path)
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps({
            "templates": [{
                "id": "live_crop",
                "paths": [str(template_path)],
                "threshold": 0.99,
                "scales": [1.0],
            }]
        }),
        encoding="utf-8",
    )

    provider = TemplateProvider(TemplateRegistry.from_file(registry_path))
    candidates = asyncio.run(provider.find(ProviderContext(frame=frame, goal="live crop")))

    assert candidates
    assert candidates[0].source == "template"
    assert candidates[0].confidence >= 0.99


def test_live_adb_element_finder_local_only_does_not_call_llm(tmp_path):
    """Run the local-only finder chain on a real ADB frame without Vision calls."""

    serial = _target_serial()
    frame = asyncio.run(AdbScreencapSource(serial=serial, adb_path=_adb_path()).latest_frame())
    image = Image.open(BytesIO(frame.png_bytes or b"")).convert("RGB")
    crop_box = _high_variance_crop(image, size=40)
    if float(ImageStat.Stat(image.crop(crop_box).convert("L")).stddev[0]) < 1.0:
        pytest.skip("Live ADB screen is too flat for a meaningful local-only finder smoke; wake/unlock the device")
    template_path = tmp_path / "target.png"
    image.crop(crop_box).save(template_path)
    registry = TemplateRegistry.from_mappings([{
        "id": "live_target",
        "paths": [str(template_path)],
        "threshold": 0.99,
        "scales": [1.0],
    }])
    action = _LiveTextAction(serial)
    finder = ElementFinder(
        [UIAutomatorProvider(action), TemplateProvider(registry)],
        llm_provider=_FailingLLMProvider(),
        mode="local_only",
        enable_llm_fallback=False,
    )

    result = asyncio.run(finder.find(frame, goal="live target"))

    assert result.found
    assert result.llm_called is False
    assert "template" in result.providers_called


def _high_variance_crop(image: Image.Image, *, size: int) -> tuple[int, int, int, int]:
    width, height = image.size
    step_x = max(size, width // 8)
    step_y = max(size, height // 8)
    best_box = (max(0, width // 2 - size // 2), max(0, height // 2 - size // 2), min(width, width // 2 + size // 2), min(height, height // 2 + size // 2))
    best_score = -1.0
    for y in range(0, max(1, height - size), step_y):
        for x in range(0, max(1, width - size), step_x):
            box = (x, y, min(width, x + size), min(height, y + size))
            crop = image.crop(box).convert("L")
            score = float(ImageStat.Stat(crop).stddev[0])
            if score > best_score:
                best_box = box
                best_score = score
    return best_box


class _LiveTextAction:
    def __init__(self, serial: str):
        self.serial = serial

    async def get_visible_texts(self):
        proc = subprocess.run(
            [_adb_path(), "-s", self.serial, "exec-out", "uiautomator", "dump", "/dev/tty"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=25,
        )
        if proc.returncode != 0 or "<hierarchy" not in proc.stdout:
            return []
        return _visible_text_centers(proc.stdout)


def _visible_text_centers(xml_text: str) -> list[tuple[str, int, int]]:
    xml_start = xml_text.find("<hierarchy")
    if xml_start > 0:
        xml_text = xml_text[xml_start:]
    xml_end = xml_text.rfind("</hierarchy>")
    if xml_end >= 0:
        xml_text = xml_text[:xml_end + len("</hierarchy>")]
    root = ET.fromstring(xml_text)
    items: list[tuple[str, int, int]] = []
    for node in root.iter("node"):
        text = (node.attrib.get("text") or node.attrib.get("content-desc") or "").strip()
        bounds = node.attrib.get("bounds") or ""
        if not text or not bounds:
            continue
        nums = [int(part) for part in re.findall(r"\d+", bounds)]
        if len(nums) != 4:
            continue
        x1, y1, x2, y2 = nums
        items.append((text, (x1 + x2) // 2, (y1 + y2) // 2))
    return items


class _FailingLLMProvider(ElementProvider):
    name = "llm"

    async def find(self, context: ProviderContext) -> list[ElementCandidate]:
        raise AssertionError("local_only live smoke must not call LLM")
