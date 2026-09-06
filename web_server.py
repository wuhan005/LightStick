#!/usr/bin/env python3
"""Local web controller for the Encore-compatible 433 MHz light stick."""

from __future__ import annotations

import argparse
import json
import threading
import time
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Dict, Optional, Sequence, Tuple
from urllib.parse import urlsplit

from lightstick import (
    DEFAULT_GPIO,
    NUM_ZONES,
    LevelRun,
    PigpioTransmitter,
    RGB,
    build_frame_runs,
    build_packet,
)


DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8080
DEFAULT_REFRESH_HZ = 20.0
MAX_REQUEST_BYTES = 1_024
WEB_ROOT = Path(__file__).resolve().parent / "web"


def validate_color(payload: object) -> RGB:
    if not isinstance(payload, dict):
        raise ValueError("请求内容必须是 RGB 对象")
    values = []
    for channel in ("r", "g", "b"):
        value = payload.get(channel)
        if type(value) is not int or not 0 <= value <= 255:
            raise ValueError(f"{channel.upper()} 必须是 0 到 255 的整数")
        values.append(value)
    return values[0], values[1], values[2]


def quantized_levels(color: RGB) -> Tuple[int, int, int]:
    return tuple(channel // 64 for channel in color)  # type: ignore[return-value]


class DryRunTransmitter:
    """No-GPIO transmitter used only for API checks and local previews."""

    def __init__(self, gpio: int) -> None:
        self.gpio = gpio

    def __enter__(self) -> "DryRunTransmitter":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def send(self, runs: Sequence[LevelRun]) -> int:
        return sum(run.duration_us for run in runs)


TransmitterFactory = Callable[[int], object]


class LightstickService:
    """Own exactly one background RF loop and update its current color safely."""

    def __init__(
        self,
        gpio: int = DEFAULT_GPIO,
        refresh_hz: float = DEFAULT_REFRESH_HZ,
        transmitter_factory: TransmitterFactory = PigpioTransmitter,
        dry_run: bool = False,
    ) -> None:
        self.gpio = gpio
        self.frame_gap = 1.0 / refresh_hz
        self.transmitter_factory = transmitter_factory
        self.dry_run = dry_run
        self._command_lock = threading.RLock()
        self._condition = threading.Condition()
        self._thread: Optional[threading.Thread] = None
        self._transmitting = False
        self._connected = False
        self._color: RGB = (0, 255, 0)
        self._version = 0
        self._error: Optional[str] = None

    def status(self) -> Dict[str, object]:
        with self._condition:
            return {
                "ok": self._error is None,
                "connected": self._connected,
                "transmitting": self._transmitting and self._connected,
                "color": list(self._color),
                "levels": list(quantized_levels(self._color)),
                "gpio": self.gpio,
                "dry_run": self.dry_run,
                "error": self._error,
            }

    def start(self, color: RGB) -> Dict[str, object]:
        with self._command_lock:
            return self._start_locked(color)

    def _start_locked(self, color: RGB) -> Dict[str, object]:
        ready: Optional[threading.Event] = None
        with self._condition:
            self._color = color
            self._version += 1
            self._error = None
            if self._thread is not None and self._thread.is_alive():
                self._transmitting = True
                self._condition.notify_all()
                return self.status()

            self._transmitting = True
            ready = threading.Event()
            self._thread = threading.Thread(
                target=self._worker,
                args=(ready,),
                name="lightstick-rf",
                daemon=True,
            )
            self._thread.start()

        if not ready.wait(timeout=3.0):
            self.stop()
            raise RuntimeError("启动发射线程超时")

        status = self.status()
        if status["error"]:
            raise RuntimeError(str(status["error"]))
        return status

    def stop(self) -> Dict[str, object]:
        with self._command_lock:
            with self._condition:
                self._transmitting = False
                self._condition.notify_all()
                thread = self._thread
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=2.0)
            return self.status()

    def _worker(self, ready: threading.Event) -> None:
        try:
            transmitter_context = self.transmitter_factory(self.gpio)
            with transmitter_context as transmitter:  # type: ignore[attr-defined]
                with self._condition:
                    self._connected = True
                    ready.set()

                while True:
                    with self._condition:
                        if not self._transmitting:
                            break
                        color = self._color
                        version = self._version

                    frame = build_frame_runs(build_packet([color] * NUM_ZONES))
                    transmitter.send(frame)

                    with self._condition:
                        if self._transmitting and version == self._version:
                            self._condition.wait(timeout=self.frame_gap)
        except Exception as exc:  # The status endpoint exposes a safe summary.
            with self._condition:
                self._error = str(exc)
                self._transmitting = False
                ready.set()
        finally:
            with self._condition:
                self._connected = False
                self._transmitting = False
                self._thread = None
                self._condition.notify_all()
                ready.set()


class LightstickHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, handler_class, service: LightstickService):
        super().__init__(server_address, handler_class)
        self.service = service


class ControllerHandler(SimpleHTTPRequestHandler):
    server: LightstickHTTPServer

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'self'",
        )
        if urlsplit(self.path).path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/api/status":
            self._send_json(HTTPStatus.OK, self.server.service.status())
            return
        if path == "/healthz":
            self._send_json(HTTPStatus.OK, {"ok": True})
            return
        super().do_GET()

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path not in ("/api/color", "/api/stop"):
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "接口不存在"})
            return
        try:
            payload = self._read_json()
            if path == "/api/color":
                color = validate_color(payload)
                status = self.server.service.start(color)
                self._send_json(HTTPStatus.OK, status)
            else:
                status = self.server.service.stop()
                status["message"] = "已停止发射，没有发送黑色包。"
                self._send_json(HTTPStatus.OK, status)
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except RuntimeError as exc:
            self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})

    def do_OPTIONS(self) -> None:
        self._send_json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "不允许跨域控制"})

    def _read_json(self) -> object:
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip()
        if content_type != "application/json":
            raise ValueError("Content-Type 必须是 application/json")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Content-Length 无效") from exc
        if not 0 < length <= MAX_REQUEST_BYTES:
            raise ValueError("请求内容为空或过大")
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("JSON 内容无效") from exc

    def _send_json(self, status: HTTPStatus, payload: Dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format_string: str, *args: object) -> None:
        if urlsplit(self.path).path != "/api/status":
            super().log_message(format_string, *args)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Encore 荧光棒 Web RGB 控制器")
    parser.add_argument("--host", default=DEFAULT_HOST, help="监听地址（默认 0.0.0.0）")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="网页端口（默认 8080）")
    parser.add_argument("--gpio", type=int, default=DEFAULT_GPIO, help="BCM GPIO 编号（默认 17）")
    parser.add_argument("--hz", type=float, default=DEFAULT_REFRESH_HZ, help="帧后等待频率值（默认 20）")
    parser.add_argument("--dry-run", action="store_true", help="运行网页但不访问 GPIO")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port 必须在 1 到 65535 之间")
    if not 0 <= args.gpio <= 31:
        parser.error("--gpio 必须是 0 到 31 之间的 BCM GPIO 编号")
    if args.hz <= 0:
        parser.error("--hz 必须大于 0")
    if not WEB_ROOT.is_dir():
        parser.error(f"网页目录不存在: {WEB_ROOT}")

    factory: TransmitterFactory = DryRunTransmitter if args.dry_run else PigpioTransmitter
    service = LightstickService(args.gpio, args.hz, factory, args.dry_run)
    handler = partial(ControllerHandler, directory=str(WEB_ROOT))
    server = LightstickHTTPServer((args.host, args.port), handler, service)

    shown_host = "127.0.0.1" if args.host == "0.0.0.0" else args.host
    mode = "预览（不发射）" if args.dry_run else "真实 RF 发射"
    print(f"Encore Light Control 已启动：{mode}")
    print(f"打开 http://{shown_host}:{args.port}")
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\n正在停止网页和 RF 发射……")
    finally:
        service.stop()
        server.server_close()
    print("已停止。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
