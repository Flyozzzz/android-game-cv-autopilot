import asyncio
from io import BytesIO
import struct
import subprocess

from PIL import Image
import pytest

import config
from core.frame_source import (
    AdbRawFrameSource,
    AdbScreencapSource,
    AdbScreenrecordFrameSource,
    Frame,
    MinicapFrameSource,
    ReplayFrameSource,
    ScrcpyFrameSource,
    ScrcpyRawStreamFrameSource,
    create_frame_source,
    find_scrcpy_server_path,
    frame_to_image,
    png_dimensions,
    raw_screencap_to_rgb,
    rgb_to_png,
    timestamp_ms,
    _detect_scrcpy_version,
    _pop_complete_jpegs,
    _read_minicap_banner,
    _recv_exact,
    _scrcpy_bit_rate_to_bps,
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


def _raw_screencap(width: int, height: int, pixels: bytes, *, header_size: int = 16) -> bytes:
    header = struct.pack("<III", width, height, 1)
    if header_size == 16:
        header += struct.pack("<I", 1)
    return header + pixels


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


def test_raw_screencap_to_rgb_supports_android_headers_and_png_conversion():
    rgba = bytes([
        255, 0, 0, 255,
        0, 255, 0, 255,
        0, 0, 255, 255,
        9, 8, 7, 255,
    ])

    width, height, rgb = raw_screencap_to_rgb(_raw_screencap(2, 2, rgba, header_size=16))

    assert (width, height) == (2, 2)
    assert rgb == bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 9, 8, 7])
    assert png_dimensions(rgb_to_png(width, height, rgb)) == (2, 2)

    width12, height12, rgb12 = raw_screencap_to_rgb(_raw_screencap(2, 2, rgba, header_size=12))
    assert (width12, height12, rgb12) == (2, 2, rgb)

    with pytest.raises(RuntimeError, match="Unsupported"):
        raw_screencap_to_rgb(struct.pack("<III", 1, 1, 99) + b"\x00" * 4)

    with pytest.raises(RuntimeError, match="truncated"):
        raw_screencap_to_rgb(struct.pack("<III", 2, 2, 1) + b"\x00" * 4)


def test_adb_raw_frame_source_returns_rgb_frame_without_device_png(monkeypatch):
    rgba = bytes([10, 20, 30, 255, 40, 50, 60, 255])
    raw = _raw_screencap(2, 1, rgba)

    class FakeProc:
        returncode = 0
        stderr = b""

        async def communicate(self):
            return raw, b""

    async def fake_exec(*args, **kwargs):
        assert args[-2:] == ("exec-out", "screencap")
        return FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    frame = asyncio.run(AdbRawFrameSource(serial="emu", include_png=False).latest_frame())

    assert frame.source_name == "adb_raw"
    assert (frame.width, frame.height) == (2, 1)
    assert frame.rgb_or_bgr_array == bytes([10, 20, 30, 40, 50, 60])
    assert frame.png_bytes is None
    assert frame_to_image(frame).getpixel((1, 0)) == (40, 50, 60)

    frame_png = Frame(1, 2, 1, frame.rgb_or_bgr_array, None, "adb_raw", 0.1)
    assert png_dimensions(rgb_to_png(frame_png.width, frame_png.height, frame_png.rgb_or_bgr_array)) == (2, 1)


def test_create_frame_source_factory_and_invalid_png(monkeypatch, tmp_path):
    path = tmp_path / "frame.png"
    path.write_bytes(_png(10, 10))

    monkeypatch.setattr(config, "FRAME_SOURCE", "adb")
    assert isinstance(create_frame_source(action=object()), AdbScreencapSource)

    monkeypatch.setattr(config, "FRAME_SOURCE", "adb_raw")
    assert isinstance(create_frame_source(), AdbRawFrameSource)

    monkeypatch.setattr(config, "FRAME_SOURCE", "screenrecord")
    assert isinstance(create_frame_source(), AdbScreenrecordFrameSource)

    monkeypatch.setattr(config, "FRAME_SOURCE", "replay")
    assert isinstance(create_frame_source(replay_paths=[path]), ReplayFrameSource)

    monkeypatch.setattr(config, "FRAME_SOURCE", "scrcpy")
    assert isinstance(create_frame_source(), ScrcpyFrameSource)

    monkeypatch.setattr(config, "FRAME_SOURCE", "scrcpy_raw")
    assert isinstance(create_frame_source(), ScrcpyRawStreamFrameSource)

    monkeypatch.setattr(config, "FRAME_SOURCE", "minicap")
    assert isinstance(create_frame_source(), MinicapFrameSource)

    with pytest.raises(RuntimeError, match="invalid"):
        png_dimensions(b"bad")

    assert timestamp_ms() > 0


def test_screenrecord_jpeg_stream_parser_keeps_latest_boundaries():
    first = _jpeg(2, 2, "red")
    second = _jpeg(3, 3, "blue")
    buffer = bytearray(b"noise" + first + b"partial")

    frames = _pop_complete_jpegs(buffer)
    assert frames == [first]
    assert bytes(buffer) == b""

    buffer.extend(b"partial" + second[:5])
    assert _pop_complete_jpegs(buffer) == []
    buffer.extend(second[5:])
    assert _pop_complete_jpegs(buffer) == [second]


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


def test_scrcpy_raw_stream_builds_server_command_and_helpers(tmp_path):
    server = tmp_path / "scrcpy-server"
    server.write_text("server", encoding="utf-8")

    def version_runner(cmd, stdout=None, stderr=None, timeout=None):
        return subprocess.CompletedProcess(cmd, 0, stdout=b"scrcpy 3.3.4\n", stderr=b"")

    assert find_scrcpy_server_path(explicit_path=str(server), runner=version_runner) == str(server)
    assert _detect_scrcpy_version("scrcpy", runner=version_runner) == "3.3.4"
    assert _scrcpy_bit_rate_to_bps("2M") == "2000000"
    assert _scrcpy_bit_rate_to_bps("750k") == "750000"

    source = ScrcpyRawStreamFrameSource(
        serial="emu",
        adb_path="adb-test",
        ffmpeg_path="ffmpeg-test",
        server_path=str(server),
        server_version="3.3.4",
        max_size=720,
        max_fps=30,
        bit_rate="2M",
        port=12345,
    )
    cmd = source._server_cmd("3.3.4")

    assert cmd[:3] == ["adb-test", "-s", "emu"]
    assert "app_process" in cmd
    assert "raw_stream=true" in cmd
    assert "video_bit_rate=2000000" in cmd
    assert "max_size=720" in cmd
    assert "max_fps=30" in cmd


def test_scrcpy_raw_stream_uses_latest_decoded_jpeg_without_waiting(tmp_path):
    server = tmp_path / "scrcpy-server"
    server.write_text("server", encoding="utf-8")
    source = ScrcpyRawStreamFrameSource(
        server_path=str(server),
        include_png=False,
        frame_wait_timeout=0.1,
    )
    source._latest_jpeg = _jpeg(7, 9, "green")
    source._latest_timestamp_ms = 123
    source._ensure_started = lambda: None

    frame = asyncio.run(source.latest_frame())

    assert frame.source_name == "scrcpy_raw"
    assert (frame.timestamp_ms, frame.width, frame.height) == (123, 7, 9)
    assert frame.png_bytes is None
    assert frame.rgb_or_bgr_array is not None


def test_scrcpy_raw_stream_falls_back_to_adb_when_static(monkeypatch, tmp_path):
    server = tmp_path / "scrcpy-server"
    server.write_text("server", encoding="utf-8")
    source = ScrcpyRawStreamFrameSource(
        server_path=str(server),
        fallback_to_adb=True,
        frame_wait_timeout=0.1,
    )
    source._ensure_started = lambda: None
    source._frame_event.clear()

    async def fake_latest_frame(self):
        return Frame(77, 5, 6, None, _png(5, 6), "adb", 3.0)

    monkeypatch.setattr(AdbScreencapSource, "latest_frame", fake_latest_frame)

    frame = asyncio.run(source.latest_frame())

    assert frame.source_name == "scrcpy_raw_adb_fallback"
    assert (frame.width, frame.height) == (5, 6)


def test_scrcpy_raw_stream_missing_server_path_errors(tmp_path):
    with pytest.raises(RuntimeError, match="scrcpy-server not found"):
        find_scrcpy_server_path(explicit_path=str(tmp_path / "missing-server"))


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
