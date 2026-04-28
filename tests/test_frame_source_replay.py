import asyncio
from io import BytesIO
import struct
import subprocess

from PIL import Image
import pytest

import config
from core.frame_source import (
    AdbScreencapSource,
    MinicapFrameSource,
    ReplayFrameSource,
    ScrcpyFrameSource,
    create_frame_source,
    png_dimensions,
    timestamp_ms,
    _read_minicap_banner,
    _recv_exact,
)


def _png(width: int, height: int, color: str = "white") -> bytes:
    image = Image.new("RGB", (width, height), color)
    buf = BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _jpeg(width: int, height: int, color: str = "white") -> bytes:
    image = Image.new("RGB", (width, height), color)
    buf = BytesIO()
    image.save(buf, format="JPEG")
    return buf.getvalue()


def test_png_dimensions_reads_png_header():
    assert png_dimensions(_png(17, 23)) == (17, 23)


def test_replay_frame_source_returns_frames_in_order_and_repeats(tmp_path):
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    first.write_bytes(_png(10, 20, "red"))
    second.write_bytes(_png(30, 40, "blue"))
    source = ReplayFrameSource([first, second], repeat=True)

    frame1 = asyncio.run(source.latest_frame())
    frame2 = asyncio.run(source.latest_frame())
    frame3 = asyncio.run(source.latest_frame())

    assert (frame1.width, frame1.height, frame1.source_name) == (10, 20, "replay")
    assert (frame2.width, frame2.height, frame2.source_name) == (30, 40, "replay")
    assert (frame3.width, frame3.height, frame3.source_name) == (10, 20, "replay")
    assert frame1.png_bytes == first.read_bytes()


def test_replay_frame_source_holds_last_frame_when_repeat_disabled(tmp_path):
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    first.write_bytes(_png(10, 20))
    second.write_bytes(_png(30, 40))
    source = ReplayFrameSource([first, second], repeat=False)

    asyncio.run(source.latest_frame())
    frame2 = asyncio.run(source.latest_frame())
    frame3 = asyncio.run(source.latest_frame())

    assert (frame2.width, frame2.height) == (30, 40)
    assert (frame3.width, frame3.height) == (30, 40)


def test_replay_frame_source_rejects_empty_or_missing_inputs(tmp_path):
    with pytest.raises(ValueError):
        ReplayFrameSource([])

    with pytest.raises(FileNotFoundError):
        ReplayFrameSource([tmp_path / "missing.png"])


def test_replay_frame_source_rejects_non_png_frame(tmp_path):
    path = tmp_path / "bad.png"
    path.write_bytes(b"not-png")
    source = ReplayFrameSource([path])

    with pytest.raises(RuntimeError, match="not a PNG"):
        asyncio.run(source.latest_frame())


def test_adb_frame_source_wraps_existing_action_screenshot():
    class FakeAction:
        async def screenshot(self):
            return _png(55, 66)

    source = AdbScreencapSource(action=FakeAction())

    frame = asyncio.run(source.latest_frame())

    assert frame.source_name == "adb"
    assert (frame.width, frame.height) == (55, 66)
    assert frame.png_bytes.startswith(b"\x89PNG\r\n\x1a\n")


def test_adb_frame_source_raw_screencap_success_and_errors(monkeypatch):
    class FakeProc:
        def __init__(self, returncode, stdout, stderr=b""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

        async def communicate(self):
            return self.stdout, self.stderr

    async def fake_exec_success(*args, **kwargs):
        assert "-s" in args
        return FakeProc(0, _png(12, 13))

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec_success)
    frame = asyncio.run(AdbScreencapSource(serial="emu").latest_frame())
    assert (frame.width, frame.height) == (12, 13)

    async def fake_exec_error(*args, **kwargs):
        return FakeProc(1, b"", b"boom")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec_error)
    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(AdbScreencapSource().latest_frame())

    async def fake_exec_bad_png(*args, **kwargs):
        return FakeProc(0, b"bad")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec_bad_png)
    with pytest.raises(RuntimeError, match="PNG"):
        asyncio.run(AdbScreencapSource().latest_frame())


def test_create_frame_source_factory_and_invalid_png(monkeypatch, tmp_path):
    path = tmp_path / "frame.png"
    path.write_bytes(_png(10, 10))

    monkeypatch.setattr(config, "FRAME_SOURCE", "adb")
    assert isinstance(create_frame_source(action=object()), AdbScreencapSource)

    monkeypatch.setattr(config, "FRAME_SOURCE", "replay")
    assert isinstance(create_frame_source(replay_paths=[path]), ReplayFrameSource)

    monkeypatch.setattr(config, "FRAME_SOURCE", "scrcpy")
    assert isinstance(create_frame_source(), ScrcpyFrameSource)

    monkeypatch.setattr(config, "FRAME_SOURCE", "minicap")
    assert isinstance(create_frame_source(), MinicapFrameSource)

    with pytest.raises(RuntimeError, match="invalid"):
        png_dimensions(b"bad")

    assert timestamp_ms() > 0


def test_scrcpy_frame_source_captures_with_scrcpy_and_ffmpeg(tmp_path):
    scrcpy = tmp_path / "scrcpy"
    ffmpeg = tmp_path / "ffmpeg"
    scrcpy.write_text("", encoding="utf-8")
    ffmpeg.write_text("", encoding="utf-8")
    calls = []

    def fake_runner(cmd, stdout=None, stderr=None, timeout=None):
        calls.append(cmd)
        if cmd[0] == str(scrcpy):
            recording = cmd[cmd.index("--record") + 1]
            open(recording, "wb").write(b"mp4")
        elif cmd[0] == str(ffmpeg):
            open(cmd[-1], "wb").write(_png(22, 33))
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    source = ScrcpyFrameSource(
        serial="emu",
        scrcpy_path=str(scrcpy),
        ffmpeg_path=str(ffmpeg),
        runner=fake_runner,
    )

    frame = asyncio.run(source.latest_frame())

    assert frame.source_name == "scrcpy"
    assert (frame.width, frame.height) == (22, 33)
    assert any("--serial" in call for call in calls)


def test_scrcpy_frame_source_reports_command_and_decode_errors(tmp_path):
    scrcpy = tmp_path / "scrcpy"
    ffmpeg = tmp_path / "ffmpeg"
    scrcpy.write_text("", encoding="utf-8")
    ffmpeg.write_text("", encoding="utf-8")

    def failing_runner(cmd, stdout=None, stderr=None, timeout=None):
        return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"boom")

    source = ScrcpyFrameSource(
        scrcpy_path=str(scrcpy),
        ffmpeg_path=str(ffmpeg),
        runner=failing_runner,
    )
    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(source.latest_frame())

    def bad_png_runner(cmd, stdout=None, stderr=None, timeout=None):
        if cmd[0] == str(scrcpy):
            open(cmd[cmd.index("--record") + 1], "wb").write(b"mp4")
        else:
            open(cmd[-1], "wb").write(b"bad")
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    source = ScrcpyFrameSource(
        scrcpy_path=str(scrcpy),
        ffmpeg_path=str(ffmpeg),
        runner=bad_png_runner,
    )
    with pytest.raises(RuntimeError, match="PNG"):
        asyncio.run(source.latest_frame())


def test_scrcpy_frame_source_reports_missing_binary(tmp_path):
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_text("", encoding="utf-8")
    source = ScrcpyFrameSource(
        scrcpy_path=str(tmp_path / "missing-scrcpy"),
        ffmpeg_path=str(ffmpeg),
    )

    with pytest.raises(RuntimeError, match="scrcpy binary not found"):
        asyncio.run(source.latest_frame())


def test_minicap_frame_source_reads_socket_protocol(monkeypatch, tmp_path):
    adb = tmp_path / "adb"
    adb.write_text("", encoding="utf-8")
    jpeg = _jpeg(24, 12)
    banner = bytes([1, 24]) + struct.pack("<IIIIIBB", 123, 24, 12, 24, 12, 0, 0)
    stream = banner + struct.pack("<I", len(jpeg)) + jpeg

    class FakeSocket:
        def __init__(self, payload):
            self.payload = bytearray(payload)

        def recv(self, size):
            chunk = self.payload[:size]
            del self.payload[:size]
            return bytes(chunk)

        def close(self):
            return None

    class FakeProcess:
        def terminate(self):
            return None

    def fake_runner(cmd, stdout=None, stderr=None, timeout=None):
        if "wm" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout=b"Physical size: 24x12\n", stderr=b"")
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    source = MinicapFrameSource(
        adb_path=str(adb),
        runner=fake_runner,
        socket_factory=lambda *args, **kwargs: FakeSocket(stream),
    )

    frame = asyncio.run(source.latest_frame())

    assert frame.source_name == "minicap"
    assert (frame.width, frame.height) == (24, 12)
    source.close()


def test_minicap_frame_source_error_paths(monkeypatch, tmp_path):
    adb = tmp_path / "adb"
    adb.write_text("", encoding="utf-8")

    def ok_runner(cmd, stdout=None, stderr=None, timeout=None):
        return subprocess.CompletedProcess(cmd, 0, stdout=b"Physical size: 24x12\n", stderr=b"")

    def failing_runner(cmd, stdout=None, stderr=None, timeout=None):
        return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"bad adb")

    class FakeProcess:
        def terminate(self):
            raise RuntimeError("ignore")

    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    source = MinicapFrameSource(
        adb_path=str(adb),
        runner=ok_runner,
        socket_factory=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("no socket")),
    )
    with pytest.raises(RuntimeError, match="Could not connect"):
        asyncio.run(source.latest_frame())
    source.close()

    source = MinicapFrameSource(adb_path=str(adb), runner=failing_runner)
    with pytest.raises(RuntimeError, match="bad adb"):
        asyncio.run(source.latest_frame())

    source = MinicapFrameSource(adb_path=str(adb), runner=ok_runner)
    source._socket = type("ExistingSocket", (), {"close": lambda self: (_ for _ in ()).throw(RuntimeError("ignore"))})()
    source._process = FakeProcess()
    source._ensure_started()
    source.close()


def test_minicap_protocol_validation(monkeypatch, tmp_path):
    adb = tmp_path / "adb"
    adb.write_text("", encoding="utf-8")

    class FakeSocket:
        def __init__(self, payload):
            self.payload = bytearray(payload)

        def recv(self, size):
            chunk = self.payload[:size]
            del self.payload[:size]
            return bytes(chunk)

    with pytest.raises(RuntimeError, match="closed"):
        _recv_exact(FakeSocket(b""), 1)

    with pytest.raises(RuntimeError, match="banner length"):
        _read_minicap_banner(FakeSocket(bytes([1, 2])))

    banner = bytes([1, 24]) + struct.pack("<IIIIIBB", 123, 24, 12, 24, 12, 0, 0)
    invalid_size_stream = banner + struct.pack("<I", 0)

    def ok_runner(cmd, stdout=None, stderr=None, timeout=None):
        return subprocess.CompletedProcess(cmd, 0, stdout=b"Physical size: 24x12\n", stderr=b"")

    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda *args, **kwargs: type("FakeProcess", (), {"terminate": lambda self: None})(),
    )
    source = MinicapFrameSource(
        adb_path=str(adb),
        runner=ok_runner,
        socket_factory=lambda *args, **kwargs: FakeSocket(invalid_size_stream),
    )
    with pytest.raises(RuntimeError, match="Invalid minicap frame size"):
        asyncio.run(source.latest_frame())

    non_jpeg_stream = banner + struct.pack("<I", 3) + b"bad"
    source = MinicapFrameSource(
        adb_path=str(adb),
        runner=ok_runner,
        socket_factory=lambda *args, **kwargs: FakeSocket(non_jpeg_stream),
    )
    with pytest.raises(RuntimeError, match="not JPEG"):
        asyncio.run(source.latest_frame())


def test_minicap_projection_and_factory_errors(tmp_path):
    adb = tmp_path / "adb"
    adb.write_text("", encoding="utf-8")

    def no_size_runner(cmd, stdout=None, stderr=None, timeout=None):
        return subprocess.CompletedProcess(cmd, 0, stdout=b"unknown\n", stderr=b"")

    with pytest.raises(RuntimeError, match="screen size"):
        MinicapFrameSource(adb_path=str(adb), runner=no_size_runner)._detect_projection()

    assert MinicapFrameSource(serial="emu", adb_path="adb")._adb_cmd("shell", "true")[:3] == ["adb", "-s", "emu"]

    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(config, "FRAME_SOURCE", "unknown")
        with pytest.raises(RuntimeError, match="Unsupported"):
            create_frame_source()
    finally:
        monkeypatch.undo()
