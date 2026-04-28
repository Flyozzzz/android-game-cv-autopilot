"""Frame source abstraction for local perception loops."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import socket
import struct
import subprocess
import tempfile
import threading
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


class AdbRawFrameSource(FrameSource):
    """ADB raw framebuffer source.

    `adb exec-out screencap -p` asks Android to PNG-encode every frame on the
    device. On some phones that dominates latency. Raw screencap avoids device
    PNG encoding and transfers RGBA_8888 pixels; local providers can consume the
    RGB bytes directly, and PNG bytes are generated locally only when requested.
    """

    def __init__(
        self,
        *,
        serial: str = "",
        adb_path: str | None = None,
        include_png: bool = True,
    ):
        self.serial = serial
        self.adb_path = adb_path or shutil.which("adb") or "adb"
        self.include_png = bool(include_png)

    async def latest_frame(self) -> Frame:
        started = time.perf_counter()
        raw = await self._screencap_raw()
        width, height, rgb = raw_screencap_to_rgb(raw)
        png = rgb_to_png(width, height, rgb) if self.include_png else None
        latency_ms = (time.perf_counter() - started) * 1000.0
        return Frame(
            timestamp_ms=timestamp_ms(),
            width=width,
            height=height,
            rgb_or_bgr_array=rgb,
            png_bytes=png,
            source_name="adb_raw",
            latency_ms=round(latency_ms, 3),
        )

    async def _screencap_raw(self) -> bytes:
        cmd = [self.adb_path]
        if self.serial:
            cmd += ["-s", self.serial]
        cmd += ["exec-out", "screencap"]
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
            raise RuntimeError(stderr.decode(errors="ignore").strip() or "ADB raw screencap failed")
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
            time_limit = max(1, int(round(self.capture_seconds)))
            scrcpy_cmd = [
                self.scrcpy_path,
                "--no-audio",
                "--no-control",
                "--no-playback",
                "--time-limit",
                str(time_limit),
                "--record",
                str(recording),
            ]
            if self.serial:
                scrcpy_cmd += ["--serial", self.serial]
            self._run_checked(scrcpy_cmd, timeout=max(3, time_limit + 5))
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


class AdbScreenrecordFrameSource(FrameSource):
    """Persistent H.264 screen stream decoded locally with ffmpeg.

    This backend avoids per-frame ADB screenshot process startup and Android-side
    PNG encoding. The first frame pays stream startup cost; later calls return
    the latest decoded frame already buffered by the reader thread.
    """

    def __init__(
        self,
        *,
        serial: str = "",
        adb_path: str | None = None,
        ffmpeg_path: str | None = None,
        bit_rate: str = "8M",
        size: str = "",
        include_png: bool = True,
        frame_wait_timeout: float = 3.0,
    ):
        self.serial = serial
        self.adb_path = adb_path or shutil.which("adb") or "adb"
        self.ffmpeg_path = ffmpeg_path or shutil.which("ffmpeg") or "ffmpeg"
        self.bit_rate = str(bit_rate or "8M")
        self.size = str(size or "")
        self.include_png = bool(include_png)
        self.frame_wait_timeout = max(0.1, float(frame_wait_timeout or 3.0))
        self._adb_proc: subprocess.Popen | None = None
        self._ffmpeg_proc: subprocess.Popen | None = None
        self._pump_thread: threading.Thread | None = None
        self._reader_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._frame_event = threading.Event()
        self._latest_jpeg: bytes | None = None
        self._latest_timestamp_ms = 0

    async def latest_frame(self) -> Frame:
        started = time.perf_counter()
        await asyncio.to_thread(self._ensure_started)
        if self._latest_jpeg is None and not await asyncio.to_thread(self._frame_event.wait, self.frame_wait_timeout):
            raise RuntimeError("screenrecord stream did not produce a frame")
        with self._lock:
            jpeg = self._latest_jpeg
            ts = self._latest_timestamp_ms or timestamp_ms()
        if not jpeg:
            raise RuntimeError("screenrecord stream frame is empty")
        width, height, rgb = _jpeg_to_rgb(jpeg)
        png = rgb_to_png(width, height, rgb) if self.include_png else None
        latency_ms = (time.perf_counter() - started) * 1000.0
        return Frame(
            timestamp_ms=ts,
            width=width,
            height=height,
            rgb_or_bgr_array=rgb,
            png_bytes=png,
            source_name="screenrecord",
            latency_ms=round(latency_ms, 3),
        )

    def close(self) -> None:
        for proc in (self._ffmpeg_proc, self._adb_proc):
            if proc is None:
                continue
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                proc.wait(timeout=1)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self._ffmpeg_proc = None
        self._adb_proc = None

    def _ensure_started(self) -> None:
        if self._is_running():
            return
        self.close()
        _require_binary(self.adb_path, "adb")
        _require_binary(self.ffmpeg_path, "ffmpeg")
        adb_cmd = [self.adb_path]
        if self.serial:
            adb_cmd += ["-s", self.serial]
        adb_cmd += ["shell", "screenrecord", "--output-format=h264", "--bit-rate", self.bit_rate]
        if self.size:
            adb_cmd += ["--size", self.size]
        adb_cmd += ["-"]
        ffmpeg_cmd = [
            self.ffmpeg_path,
            "-loglevel",
            "error",
            "-fflags",
            "nobuffer",
            "-flags",
            "low_delay",
            "-f",
            "h264",
            "-i",
            "pipe:0",
            "-f",
            "image2pipe",
            "-vcodec",
            "mjpeg",
            "-q:v",
            "5",
            "pipe:1",
        ]
        self._adb_proc = subprocess.Popen(adb_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self._ffmpeg_proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self._pump_thread = threading.Thread(target=self._pump_adb_to_ffmpeg, daemon=True)
        self._reader_thread = threading.Thread(target=self._read_ffmpeg_jpegs, daemon=True)
        self._pump_thread.start()
        self._reader_thread.start()

    def _is_running(self) -> bool:
        return (
            self._adb_proc is not None
            and self._ffmpeg_proc is not None
            and self._adb_proc.poll() is None
            and self._ffmpeg_proc.poll() is None
        )

    def _pump_adb_to_ffmpeg(self) -> None:
        adb_stdout = self._adb_proc.stdout if self._adb_proc else None
        ffmpeg_stdin = self._ffmpeg_proc.stdin if self._ffmpeg_proc else None
        if adb_stdout is None or ffmpeg_stdin is None:
            return
        try:
            while True:
                chunk = os.read(adb_stdout.fileno(), 65536)
                if not chunk:
                    break
                os.write(ffmpeg_stdin.fileno(), chunk)
        except Exception:
            pass
        try:
            ffmpeg_stdin.close()
        except Exception:
            pass

    def _read_ffmpeg_jpegs(self) -> None:
        stdout = self._ffmpeg_proc.stdout if self._ffmpeg_proc else None
        if stdout is None:
            return
        buffer = bytearray()
        try:
            while True:
                chunk = os.read(stdout.fileno(), 32768)
                if not chunk:
                    break
                buffer.extend(chunk)
                for jpeg in _pop_complete_jpegs(buffer):
                    with self._lock:
                        self._latest_jpeg = jpeg
                        self._latest_timestamp_ms = timestamp_ms()
                    self._frame_event.set()
        except Exception:
            pass


class ScrcpyRawStreamFrameSource(FrameSource):
    """Persistent scrcpy-server raw H.264 stream decoded locally with ffmpeg.

    Unlike :class:`ScrcpyFrameSource`, this source does not record a short mp4
    for every frame. It starts scrcpy-server once, forwards its raw H.264 socket
    to the host, decodes the stream through a persistent ffmpeg process, and
    returns the latest decoded frame from memory.
    """

    def __init__(
        self,
        *,
        serial: str = "",
        adb_path: str | None = None,
        scrcpy_path: str | None = None,
        ffmpeg_path: str | None = None,
        server_path: str | None = None,
        server_version: str | None = None,
        max_size: int = 720,
        max_fps: int = 30,
        bit_rate: str = "2M",
        port: int = 0,
        include_png: bool = True,
        frame_wait_timeout: float = 3.0,
        fallback_to_adb: bool = True,
        popen_factory: Any | None = None,
        runner: Any | None = None,
        socket_factory: Any | None = None,
    ):
        self.serial = serial
        self.adb_path = adb_path or shutil.which("adb") or "adb"
        self.scrcpy_path = scrcpy_path or shutil.which("scrcpy") or "scrcpy"
        self.ffmpeg_path = ffmpeg_path or shutil.which("ffmpeg") or "ffmpeg"
        self.server_path = str(server_path or "").strip()
        self.server_version = str(server_version or "").strip()
        self.max_size = max(0, int(max_size or 0))
        self.max_fps = max(0, int(max_fps or 0))
        self.bit_rate = str(bit_rate or "2M")
        self.port = max(0, int(port or 0))
        self.include_png = bool(include_png)
        self.frame_wait_timeout = max(0.1, float(frame_wait_timeout or 3.0))
        self.fallback_to_adb = bool(fallback_to_adb)
        self.popen_factory = popen_factory or subprocess.Popen
        self.runner = runner or subprocess.run
        self.socket_factory = socket_factory or socket.create_connection
        self._device_server_path = "/data/local/tmp/scrcpy-server-autopilot.jar"
        self._server_proc: subprocess.Popen | None = None
        self._ffmpeg_proc: subprocess.Popen | None = None
        self._socket: socket.socket | None = None
        self._pump_thread: threading.Thread | None = None
        self._reader_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._frame_event = threading.Event()
        self._latest_jpeg: bytes | None = None
        self._latest_timestamp_ms = 0

    async def latest_frame(self) -> Frame:
        started = time.perf_counter()
        await asyncio.to_thread(self._ensure_started)
        if self._latest_jpeg is None and not await asyncio.to_thread(self._frame_event.wait, self.frame_wait_timeout):
            if self.fallback_to_adb:
                return await self._adb_fallback_frame(started)
            raise RuntimeError(self._no_frame_error())
        with self._lock:
            jpeg = self._latest_jpeg
            ts = self._latest_timestamp_ms or timestamp_ms()
        if not jpeg:
            raise RuntimeError("scrcpy raw stream frame is empty")
        width, height, rgb = _jpeg_to_rgb(jpeg)
        png = rgb_to_png(width, height, rgb) if self.include_png else None
        latency_ms = (time.perf_counter() - started) * 1000.0
        return Frame(
            timestamp_ms=ts,
            width=width,
            height=height,
            rgb_or_bgr_array=rgb,
            png_bytes=png,
            source_name="scrcpy_raw",
            latency_ms=round(latency_ms, 3),
        )

    async def _adb_fallback_frame(self, started: float) -> Frame:
        frame = await AdbScreencapSource(serial=self.serial, adb_path=self.adb_path).latest_frame()
        return Frame(
            timestamp_ms=frame.timestamp_ms,
            width=frame.width,
            height=frame.height,
            rgb_or_bgr_array=frame.rgb_or_bgr_array,
            png_bytes=frame.png_bytes,
            source_name="scrcpy_raw_adb_fallback",
            latency_ms=round((time.perf_counter() - started) * 1000.0, 3),
        )

    def close(self) -> None:
        if self._socket is not None:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None
        for proc in (self._ffmpeg_proc, self._server_proc):
            if proc is None:
                continue
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                proc.wait(timeout=1)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self._ffmpeg_proc = None
        self._server_proc = None
        if self.port:
            try:
                self._run_checked(self._adb_cmd("forward", "--remove", f"tcp:{self.port}"), timeout=3)
            except Exception:
                pass

    def _ensure_started(self) -> None:
        if self._is_running():
            return
        self.close()
        _require_binary(self.adb_path, "adb")
        _require_binary(self.ffmpeg_path, "ffmpeg")
        server_path = find_scrcpy_server_path(
            explicit_path=self.server_path,
            scrcpy_path=self.scrcpy_path,
            runner=self.runner,
        )
        version = self.server_version or _detect_scrcpy_version(self.scrcpy_path, runner=self.runner) or "3.3.4"
        self._run_checked(self._adb_cmd("push", server_path, self._device_server_path), timeout=15)
        if not self.port:
            self.port = _find_free_tcp_port()
        self._run_checked(self._adb_cmd("forward", f"tcp:{self.port}", "localabstract:scrcpy"), timeout=5)
        self._server_proc = self.popen_factory(
            self._server_cmd(version),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        time.sleep(0.5)
        self._socket = self._connect_stream_socket()
        self._ffmpeg_proc = self.popen_factory(
            self._ffmpeg_cmd(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._frame_event.clear()
        self._pump_thread = threading.Thread(target=self._pump_socket_to_ffmpeg, daemon=True)
        self._reader_thread = threading.Thread(target=self._read_ffmpeg_jpegs, daemon=True)
        self._pump_thread.start()
        self._reader_thread.start()

    def _is_running(self) -> bool:
        return (
            self._server_proc is not None
            and self._ffmpeg_proc is not None
            and self._server_proc.poll() is None
            and self._ffmpeg_proc.poll() is None
            and self._socket is not None
        )

    def _connect_stream_socket(self) -> socket.socket:
        deadline = time.monotonic() + 3.0
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            if self._server_proc is not None and self._server_proc.poll() is not None:
                raise RuntimeError(self._process_error(self._server_proc, "scrcpy-server exited before socket connection"))
            try:
                sock = self.socket_factory(("127.0.0.1", self.port), timeout=1.0)
                try:
                    sock.settimeout(None)
                except Exception:
                    pass
                return sock
            except Exception as exc:
                last_error = exc
                time.sleep(0.05)
        raise RuntimeError(f"Could not connect to scrcpy raw socket: {last_error}")

    def _pump_socket_to_ffmpeg(self) -> None:
        ffmpeg_stdin = self._ffmpeg_proc.stdin if self._ffmpeg_proc else None
        if ffmpeg_stdin is None:
            return
        saw_bytes = False
        # Some devices close a newly connected scrcpy raw socket if the host
        # reads before the video encoder has emitted its first packet.
        time.sleep(1.0)
        first_byte_deadline = time.monotonic() + self.frame_wait_timeout
        try:
            while True:
                sock = self._socket
                if sock is None:
                    if not saw_bytes and time.monotonic() < first_byte_deadline:
                        time.sleep(0.25)
                        self._socket = self._connect_stream_socket()
                        continue
                    break
                try:
                    chunk = sock.recv(65536)
                except Exception:
                    if not saw_bytes and time.monotonic() < first_byte_deadline:
                        try:
                            sock.close()
                        except Exception:
                            pass
                        self._socket = None
                        time.sleep(0.25)
                        continue
                    break
                if not chunk:
                    if not saw_bytes and time.monotonic() < first_byte_deadline and self._server_proc is not None and self._server_proc.poll() is None:
                        try:
                            sock.close()
                        except Exception:
                            pass
                        self._socket = None
                        time.sleep(0.25)
                        continue
                    break
                saw_bytes = True
                os.write(ffmpeg_stdin.fileno(), chunk)
        except Exception:
            pass
        try:
            ffmpeg_stdin.close()
        except Exception:
            pass

    def _read_ffmpeg_jpegs(self) -> None:
        stdout = self._ffmpeg_proc.stdout if self._ffmpeg_proc else None
        if stdout is None:
            return
        buffer = bytearray()
        try:
            while True:
                chunk = os.read(stdout.fileno(), 32768)
                if not chunk:
                    break
                buffer.extend(chunk)
                for jpeg in _pop_complete_jpegs(buffer):
                    with self._lock:
                        self._latest_jpeg = jpeg
                        self._latest_timestamp_ms = timestamp_ms()
                    self._frame_event.set()
        except Exception:
            pass

    def _server_cmd(self, version: str) -> list[str]:
        args = [
            f"CLASSPATH={self._device_server_path}",
            "app_process",
            "/",
            "com.genymobile.scrcpy.Server",
            version,
            "tunnel_forward=true",
            "audio=false",
            "control=false",
            "cleanup=false",
            "raw_stream=true",
            f"video_bit_rate={_scrcpy_bit_rate_to_bps(self.bit_rate)}",
            "log_level=info",
        ]
        if self.max_size:
            args.append(f"max_size={self.max_size}")
        if self.max_fps:
            args.append(f"max_fps={self.max_fps}")
        return self._adb_cmd("shell", *args)

    def _ffmpeg_cmd(self) -> list[str]:
        return [
            self.ffmpeg_path,
            "-loglevel",
            "error",
            "-probesize",
            "32",
            "-analyzeduration",
            "0",
            "-f",
            "h264",
            "-i",
            "pipe:0",
            "-f",
            "image2pipe",
            "-vcodec",
            "mjpeg",
            "-q:v",
            "5",
            "pipe:1",
        ]

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

    def _no_frame_error(self) -> str:
        for proc, label in ((self._server_proc, "scrcpy-server"), (self._ffmpeg_proc, "ffmpeg")):
            if proc is not None and proc.poll() is not None:
                return self._process_error(proc, f"{label} exited before producing a frame")
        return (
            "scrcpy raw stream did not produce a frame. "
            "On a static Android screen, force a small screen change or benchmark with --nudge-key."
        )

    def _process_error(self, proc: subprocess.Popen, fallback: str) -> str:
        stderr = b""
        try:
            if proc.stderr is not None:
                stderr = proc.stderr.read() or b""
        except Exception:
            stderr = b""
        message = stderr.decode(errors="ignore").strip()
        return f"{fallback}: {message}" if message else fallback


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
    if source == "adb_raw":
        return AdbRawFrameSource(
            serial=serial,
            include_png=bool(getattr(config, "FRAME_SOURCE_INCLUDE_PNG", True)),
        )
    if source == "screenrecord":
        return AdbScreenrecordFrameSource(
            serial=serial,
            include_png=bool(getattr(config, "FRAME_SOURCE_INCLUDE_PNG", True)),
        )
    if source == "replay":
        return ReplayFrameSource(replay_paths or ())
    if source == "scrcpy":
        return ScrcpyFrameSource(serial=serial)
    if source == "scrcpy_raw":
        return ScrcpyRawStreamFrameSource(
            serial=serial,
            include_png=bool(getattr(config, "FRAME_SOURCE_INCLUDE_PNG", True)),
            server_path=getattr(config, "SCRCPY_SERVER_PATH", ""),
            server_version=getattr(config, "SCRCPY_SERVER_VERSION", ""),
            max_size=int(getattr(config, "SCRCPY_RAW_MAX_SIZE", 720)),
            max_fps=int(getattr(config, "SCRCPY_RAW_MAX_FPS", 30)),
            bit_rate=getattr(config, "SCRCPY_RAW_BIT_RATE", "2M"),
            port=int(getattr(config, "SCRCPY_RAW_PORT", 0)),
            frame_wait_timeout=float(getattr(config, "SCRCPY_RAW_FRAME_WAIT_TIMEOUT", 3.0)),
            fallback_to_adb=bool(getattr(config, "SCRCPY_RAW_FALLBACK_TO_ADB", True)),
        )
    if source == "minicap":
        return MinicapFrameSource(serial=serial)
    raise RuntimeError(f"Unsupported FRAME_SOURCE={source!r}")


def png_dimensions(png: bytes) -> tuple[int, int]:
    if not png or len(png) < 24 or not png.startswith(PNG_SIGNATURE):
        raise RuntimeError("PNG frame data is missing or invalid")
    return struct.unpack(">I", png[16:20])[0], struct.unpack(">I", png[20:24])[0]


def timestamp_ms() -> int:
    return int(time.time() * 1000)


def raw_screencap_to_rgb(raw: bytes) -> tuple[int, int, bytes]:
    if not raw or len(raw) < 12:
        raise RuntimeError("ADB raw screencap data is missing")
    width, height, pixel_format = struct.unpack("<III", raw[:12])
    if width <= 0 or height <= 0:
        raise RuntimeError(f"Invalid raw screencap dimensions: {width}x{height}")
    expected_rgba = width * height * 4
    if pixel_format not in {1, 2}:
        raise RuntimeError(f"Unsupported raw screencap pixel format: {pixel_format}")
    payload_offset = 16 if len(raw) >= expected_rgba + 16 else 12
    payload = raw[payload_offset:]
    if len(payload) < expected_rgba:
        raise RuntimeError("ADB raw screencap payload is truncated")
    rgba = payload[:expected_rgba]
    try:
        import numpy as np  # type: ignore

        array = np.frombuffer(rgba, dtype=np.uint8).reshape((height * width, 4))
        return width, height, array[:, :3].copy().tobytes()
    except Exception:
        return width, height, b"".join(rgba[index:index + 3] for index in range(0, expected_rgba, 4))


def rgb_to_png(width: int, height: int, rgb: bytes) -> bytes:
    from io import BytesIO

    from PIL import Image

    image = Image.frombytes("RGB", (int(width), int(height)), rgb)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def frame_to_image(frame: Frame):
    from io import BytesIO

    from PIL import Image

    data = frame.rgb_or_bgr_array
    if isinstance(data, Image.Image):
        return data.convert("RGB")
    if isinstance(data, (bytes, bytearray)):
        return Image.frombytes("RGB", (int(frame.width), int(frame.height)), bytes(data))
    if data is not None:
        try:
            return Image.fromarray(data).convert("RGB")
        except Exception:
            pass
    if frame.png_bytes:
        return Image.open(BytesIO(frame.png_bytes)).convert("RGB")
    raise RuntimeError("Frame has neither RGB data nor PNG bytes")


def frame_to_png_bytes(frame: Frame) -> bytes:
    if frame.png_bytes:
        return frame.png_bytes
    data = frame.rgb_or_bgr_array
    if isinstance(data, (bytes, bytearray)):
        return rgb_to_png(frame.width, frame.height, bytes(data))
    from io import BytesIO

    image = frame_to_image(frame)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def infer_frame_source_serial(action: Any | None = None, default: str = "") -> str:
    for attr in ("serial", "adb_serial", "device_serial"):
        value = getattr(action, attr, "") if action is not None else ""
        if value:
            return str(value)
    configured = str(getattr(config, "LOCAL_DEVICE", "") or os.getenv("LOCAL_DEVICE", "") or "").strip()
    if configured and configured.lower() != "auto":
        return configured
    return str(default or "")


def close_frame_source(source: FrameSource) -> None:
    close = getattr(source, "close", None)
    if callable(close):
        close()


def _require_binary(path: str, label: str) -> None:
    if Path(path).is_file() or shutil.which(path):
        return
    raise RuntimeError(f"{label} binary not found: {path}")


def _scrcpy_bit_rate_to_bps(value: str) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return "2000000"
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([kmg]?)", raw)
    if not match:
        return raw
    amount = float(match.group(1))
    suffix = match.group(2)
    multiplier = {"": 1, "k": 1_000, "m": 1_000_000, "g": 1_000_000_000}[suffix]
    return str(int(amount * multiplier))


def find_scrcpy_server_path(
    *,
    explicit_path: str = "",
    scrcpy_path: str = "scrcpy",
    runner: Any | None = None,
) -> str:
    explicit = str(explicit_path or os.getenv("SCRCPY_SERVER_PATH", "")).strip()
    if explicit:
        path = Path(explicit).expanduser()
        if path.is_file():
            return str(path)
        raise RuntimeError(f"scrcpy-server not found: {path}")
    version = _detect_scrcpy_version(scrcpy_path, runner=runner)
    candidates = [
        Path("/opt/homebrew/share/scrcpy/scrcpy-server"),
        Path("/usr/local/share/scrcpy/scrcpy-server"),
        Path("/usr/share/scrcpy/scrcpy-server"),
    ]
    if version:
        candidates[:0] = [
            Path(f"/opt/homebrew/Cellar/scrcpy/{version}/share/scrcpy/scrcpy-server"),
            Path(f"/usr/local/Cellar/scrcpy/{version}/share/scrcpy/scrcpy-server"),
        ]
    for path in candidates:
        if path.is_file():
            return str(path)
    raise RuntimeError(
        "scrcpy-server not found. Set SCRCPY_SERVER_PATH to the host scrcpy-server file."
    )


def _detect_scrcpy_version(scrcpy_path: str, *, runner: Any | None = None) -> str:
    runner = runner or subprocess.run
    try:
        proc = runner(
            [scrcpy_path, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
        )
    except Exception:
        return ""
    output = _bytes_for_regex(proc.stdout) + b"\n" + _bytes_for_regex(proc.stderr)
    match = re.search(rb"scrcpy\s+([0-9]+(?:\.[0-9]+){1,3})", output)
    return match.group(1).decode() if match else ""


def _bytes_for_regex(value: bytes | str | None) -> bytes:
    if value is None:
        return b""
    return value if isinstance(value, bytes) else str(value).encode()


def _find_free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _jpeg_to_png(jpeg: bytes) -> bytes:
    from io import BytesIO

    from PIL import Image

    image = Image.open(BytesIO(jpeg)).convert("RGB")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _jpeg_to_rgb(jpeg: bytes) -> tuple[int, int, bytes]:
    from io import BytesIO

    from PIL import Image

    image = Image.open(BytesIO(jpeg)).convert("RGB")
    return image.width, image.height, image.tobytes()


def _pop_complete_jpegs(buffer: bytearray) -> list[bytes]:
    frames: list[bytes] = []
    while True:
        start = buffer.find(b"\xff\xd8")
        if start < 0:
            buffer.clear()
            return frames
        if start > 0:
            del buffer[:start]
        end = buffer.find(b"\xff\xd9", 2)
        if end < 0:
            return frames
        frames.append(bytes(buffer[:end + 2]))
        del buffer[:end + 2]


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
