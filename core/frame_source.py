"""Frame source abstraction for local perception loops."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import tempfile
import time
from typing import Any, Sequence

import config


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True)
class Frame:
    timestamp_ms: int
    width: int
    height: int
    rgb_or_bgr_array: Any | None
    png_bytes: bytes | None
    source_name: str
    latency_ms: float


class FrameSource:
    async def latest_frame(self) -> Frame:
        raise NotImplementedError


class AdbScreencapSource(FrameSource):
    """ADB screencap frame source using an existing action object or raw adb."""

    def __init__(
        self,
        *,
        action: Any | None = None,
        serial: str = "",
        adb_path: str | None = None,
    ):
        self.action = action
        self.serial = serial
        self.adb_path = adb_path or shutil.which("adb") or "adb"

    async def latest_frame(self) -> Frame:
        started = time.perf_counter()
        if self.action is not None:
            png = await self.action.screenshot()
        else:
            png = await self._screencap()
        latency_ms = (time.perf_counter() - started) * 1000.0
        width, height = png_dimensions(png)
        return Frame(
            timestamp_ms=timestamp_ms(),
            width=width,
            height=height,
            rgb_or_bgr_array=None,
            png_bytes=png,
            source_name="adb",
            latency_ms=round(latency_ms, 3),
        )

    async def _screencap(self) -> bytes:
        cmd = [self.adb_path]
        if self.serial:
            cmd += ["-s", self.serial]
        cmd += ["exec-out", "screencap", "-p"]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=getattr(config, "ADB_COMMAND_TIMEOUT", 30),
        )
        if proc.returncode != 0:
            raise RuntimeError(stderr.decode(errors="ignore").strip() or "ADB screencap failed")
        if not stdout.startswith(PNG_SIGNATURE):
            raise RuntimeError("ADB screencap did not return PNG data")
        return stdout


class ReplayFrameSource(FrameSource):
    """Replay PNG frames from disk for deterministic perception tests."""

    def __init__(self, paths: Sequence[str | Path], *, repeat: bool = True):
        self.paths = [Path(path) for path in paths]
        if not self.paths:
            raise ValueError("ReplayFrameSource requires at least one frame path")
        missing = [str(path) for path in self.paths if not path.exists()]
        if missing:
            raise FileNotFoundError(f"Replay frame not found: {missing[0]}")
        self.repeat = repeat
        self._index = 0

    async def latest_frame(self) -> Frame:
        started = time.perf_counter()
        path = self.paths[self._index]
        png = path.read_bytes()
        if not png.startswith(PNG_SIGNATURE):
            raise RuntimeError(f"Replay frame is not a PNG: {path}")
        width, height = png_dimensions(png)
        self._advance()
        latency_ms = (time.perf_counter() - started) * 1000.0
        return Frame(
            timestamp_ms=timestamp_ms(),
            width=width,
            height=height,
            rgb_or_bgr_array=None,
            png_bytes=png,
            source_name="replay",
            latency_ms=round(latency_ms, 3),
        )

    def _advance(self) -> None:
        if self._index + 1 < len(self.paths):
            self._index += 1
        elif self.repeat:
            self._index = 0


class ScrcpyFrameSource(FrameSource):
    """Capture a fresh frame through scrcpy recording and ffmpeg extraction.

    This backend is fully functional when the host has `scrcpy` and `ffmpeg`
    installed and the target device is reachable by scrcpy. It is slower than a
    persistent decoded video stream, but it exercises the real scrcpy capture
    path and keeps the dependency optional.
    """

    def __init__(
        self,
        *,
        serial: str = "",
        scrcpy_path: str | None = None,
        ffmpeg_path: str | None = None,
        capture_seconds: float = 1.0,
        runner: Any | None = None,
    ):
        self.serial = serial
        self.scrcpy_path = scrcpy_path or shutil.which("scrcpy") or "scrcpy"
        self.ffmpeg_path = ffmpeg_path or shutil.which("ffmpeg") or "ffmpeg"
        self.capture_seconds = max(0.2, float(capture_seconds or 1.0))
        self.runner = runner or subprocess.run

    async def latest_frame(self) -> Frame:
        started = time.perf_counter()
        png = await asyncio.to_thread(self._capture_png)
        latency_ms = (time.perf_counter() - started) * 1000.0
        width, height = png_dimensions(png)
        return Frame(
            timestamp_ms=timestamp_ms(),
            width=width,
            height=height,
            rgb_or_bgr_array=None,
            png_bytes=png,
            source_name="scrcpy",
            latency_ms=round(latency_ms, 3),
        )

    def _capture_png(self) -> bytes:
        _require_binary(self.scrcpy_path, "scrcpy")
        _require_binary(self.ffmpeg_path, "ffmpeg")
        with tempfile.TemporaryDirectory(prefix="scrcpy-frame-") as tmp:
            recording = Path(tmp) / "capture.mp4"
            frame = Path(tmp) / "frame.png"
            scrcpy_cmd = [
                self.scrcpy_path,
                "--no-audio",
                "--no-control",
                "--no-display",
                "--time-limit",
                str(self.capture_seconds),
                "--record",
                str(recording),
            ]
            if self.serial:
                scrcpy_cmd += ["--serial", self.serial]
            self._run_checked(scrcpy_cmd, timeout=max(3, int(self.capture_seconds) + 5))
            ffmpeg_cmd = [
                self.ffmpeg_path,
                "-y",
                "-loglevel",
                "error",
                "-sseof",
                "-0.1",
                "-i",
                str(recording),
                "-frames:v",
                "1",
                str(frame),
            ]
            self._run_checked(ffmpeg_cmd, timeout=10)
            png = frame.read_bytes()
            if not png.startswith(PNG_SIGNATURE):
                raise RuntimeError("scrcpy/ffmpeg did not produce a PNG frame")
            return png

    def _run_checked(self, cmd: list[str], *, timeout: int) -> subprocess.CompletedProcess:
        proc = self.runner(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
        if proc.returncode != 0:
            stderr = proc.stderr.decode(errors="ignore").strip()
            raise RuntimeError(stderr or f"Command failed: {' '.join(cmd)}")
        return proc


class MinicapFrameSource(FrameSource):
    """Read JPEG frames from an Android minicap localabstract socket.

    Requires `minicap` and its matching shared library to be installed on the
    device under `/data/local/tmp`. The socket protocol is the public minicap
    banner + frame-size stream: banner first, then little-endian JPEG lengths.
    """

    def __init__(
        self,
        *,
        serial: str = "",
        adb_path: str | None = None,
        port: int = 1717,
        projection: str = "",
        runner: Any | None = None,
        socket_factory: Any | None = None,
    ):
        self.serial = serial
        self.adb_path = adb_path or shutil.which("adb") or "adb"
        self.port = int(port)
        self.projection = projection
        self.runner = runner or subprocess.run
        self.socket_factory = socket_factory or socket.create_connection
        self._process: subprocess.Popen | None = None
        self._socket: socket.socket | None = None
        self._banner: dict[str, int] | None = None

    async def latest_frame(self) -> Frame:
        started = time.perf_counter()
        jpeg = await asyncio.to_thread(self._read_latest_jpeg)
        png = _jpeg_to_png(jpeg)
        latency_ms = (time.perf_counter() - started) * 1000.0
        width, height = png_dimensions(png)
        return Frame(
            timestamp_ms=timestamp_ms(),
            width=width,
            height=height,
            rgb_or_bgr_array=None,
            png_bytes=png,
            source_name="minicap",
            latency_ms=round(latency_ms, 3),
        )

    def close(self) -> None:
        if self._socket is not None:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None
        if self._process is not None:
            try:
                self._process.terminate()
            except Exception:
                pass
            self._process = None

    def _read_latest_jpeg(self) -> bytes:
        self._ensure_started()
        assert self._socket is not None
        if self._banner is None:
            self._banner = _read_minicap_banner(self._socket)
        frame_size = struct.unpack("<I", _recv_exact(self._socket, 4))[0]
        if frame_size <= 0 or frame_size > 50_000_000:
            raise RuntimeError(f"Invalid minicap frame size: {frame_size}")
        data = _recv_exact(self._socket, frame_size)
        if not data.startswith(b"\xff\xd8"):
            raise RuntimeError("Minicap frame is not JPEG data")
        return data

    def _ensure_started(self) -> None:
        if self._socket is not None:
            return
        _require_binary(self.adb_path, "adb")
        self._run_checked([*self._adb_cmd("forward", f"tcp:{self.port}", "localabstract:minicap")], timeout=5)
        projection = self.projection or self._detect_projection()
        shell_cmd = (
            "LD_LIBRARY_PATH=/data/local/tmp "
            f"/data/local/tmp/minicap -P {projection}"
        )
        self._process = subprocess.Popen(
            self._adb_cmd("shell", shell_cmd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + 3.0
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                self._socket = self.socket_factory(("127.0.0.1", self.port), timeout=1.0)
                return
            except Exception as exc:
                last_error = exc
                time.sleep(0.05)
        raise RuntimeError(f"Could not connect to minicap socket: {last_error}")

    def _detect_projection(self) -> str:
        proc = self._run_checked(self._adb_cmd("shell", "wm", "size"), timeout=5)
        output = proc.stdout.decode(errors="ignore")
        match = __import__("re").search(r"(\d+)x(\d+)", output)
        if not match:
            raise RuntimeError(f"Could not detect Android screen size from: {output.strip()}")
        width, height = match.group(1), match.group(2)
        return f"{width}x{height}@{width}x{height}/0"

    def _adb_cmd(self, *args: object) -> list[str]:
        cmd = [self.adb_path]
        if self.serial:
            cmd += ["-s", self.serial]
        cmd += [str(arg) for arg in args]
        return cmd

    def _run_checked(self, cmd: list[str], *, timeout: int) -> subprocess.CompletedProcess:
        proc = self.runner(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
        if proc.returncode != 0:
            stderr = proc.stderr.decode(errors="ignore").strip()
            raise RuntimeError(stderr or f"Command failed: {' '.join(cmd)}")
        return proc


def create_frame_source(
    *,
    action: Any | None = None,
    serial: str = "",
    replay_paths: Sequence[str | Path] | None = None,
) -> FrameSource:
    source = getattr(config, "FRAME_SOURCE", "adb")
    if source == "adb":
        return AdbScreencapSource(action=action, serial=serial)
    if source == "replay":
        return ReplayFrameSource(replay_paths or ())
    if source == "scrcpy":
        return ScrcpyFrameSource(serial=serial)
    if source == "minicap":
        return MinicapFrameSource(serial=serial)
    raise RuntimeError(f"Unsupported FRAME_SOURCE={source!r}")


def png_dimensions(png: bytes) -> tuple[int, int]:
    if not png or len(png) < 24 or not png.startswith(PNG_SIGNATURE):
        raise RuntimeError("PNG frame data is missing or invalid")
    return struct.unpack(">I", png[16:20])[0], struct.unpack(">I", png[20:24])[0]


def timestamp_ms() -> int:
    return int(time.time() * 1000)


def _require_binary(path: str, label: str) -> None:
    if Path(path).is_file() or shutil.which(path):
        return
    raise RuntimeError(f"{label} binary not found: {path}")


def _jpeg_to_png(jpeg: bytes) -> bytes:
    from io import BytesIO

    from PIL import Image

    image = Image.open(BytesIO(jpeg)).convert("RGB")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = int(size)
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise RuntimeError("Minicap socket closed while reading frame")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _read_minicap_banner(sock: socket.socket) -> dict[str, int]:
    header = _recv_exact(sock, 2)
    version = header[0]
    banner_length = header[1]
    if banner_length < 24:
        raise RuntimeError(f"Invalid minicap banner length: {banner_length}")
    rest = _recv_exact(sock, banner_length - 2)
    values = struct.unpack("<IIIIIBB", rest[:22])
    return {
        "version": version,
        "length": banner_length,
        "pid": values[0],
        "real_width": values[1],
        "real_height": values[2],
        "virtual_width": values[3],
        "virtual_height": values[4],
        "orientation": values[5],
        "quirks": values[6],
    }
