#!/usr/bin/env python3
"""Control Encore-compatible 433 MHz light sticks with a Raspberry Pi.

The protocol implemented here follows the Soul Power II 2024 (7-zone)
implementation documented by EncoreLightSticks:
https://github.com/HansZ8/EncoreLightSticks

GPIO numbering is BCM numbering. Physical pin 11 is BCM GPIO17.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple


NUM_ZONES = 7
PACKET_DATA_BYTES = 11
PACKET_TOTAL_BYTES = 13
DEFAULT_GPIO = 17
HALF_BIT_US = 250
# Hardware testing with the target 2024 light stick requires a 500 us LOW sync
# period. This differs from the 1000 us written in the upstream protocol notes.
SYNC_LOW_US = 500

RGB = Tuple[int, int, int]

NAMED_COLORS = {
    "off": (0, 0, 0),
    "black": (0, 0, 0),
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "white": (255, 255, 255),
    "yellow": (255, 255, 0),
    "cyan": (0, 255, 255),
    "magenta": (255, 0, 255),
    "purple": (128, 0, 255),
    "orange": (255, 128, 0),
}


@dataclass(frozen=True)
class LevelRun:
    """A GPIO level held for a precise number of microseconds."""

    level: int
    duration_us: int


def parse_color(value: str) -> RGB:
    """Parse a named color, #RRGGBB, or R,G,B value."""
    normalized = value.strip().lower()
    if normalized in NAMED_COLORS:
        return NAMED_COLORS[normalized]

    if re.fullmatch(r"#[0-9a-f]{6}", normalized):
        return tuple(
            int(normalized[index : index + 2], 16) for index in (1, 3, 5)
        )  # type: ignore[return-value]

    parts = [part.strip() for part in normalized.split(",")]
    if len(parts) == 3:
        try:
            rgb = tuple(int(part, 10) for part in parts)
        except ValueError:
            pass
        else:
            if all(0 <= channel <= 255 for channel in rgb):
                return rgb  # type: ignore[return-value]

    raise argparse.ArgumentTypeError(
        f"无效颜色 {value!r}；请使用颜色名、#RRGGBB 或 R,G,B"
    )


def parse_zone(value: str) -> Tuple[int, RGB]:
    """Parse ZONE=COLOR, with zones numbered 1 through 7."""
    if "=" not in value:
        raise argparse.ArgumentTypeError("分区格式应为 ZONE=COLOR，例如 1=red")
    zone_text, color_text = value.split("=", 1)
    try:
        zone = int(zone_text, 10)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("分区编号必须是 1 到 7") from exc
    if not 1 <= zone <= NUM_ZONES:
        raise argparse.ArgumentTypeError("分区编号必须是 1 到 7")
    return zone, parse_color(color_text)


def parse_channel(value: str) -> int:
    try:
        channel = int(value, 10)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("RGB 通道必须是 0 到 255 的整数") from exc
    if not 0 <= channel <= 255:
        raise argparse.ArgumentTypeError("RGB 通道必须是 0 到 255 的整数")
    return channel


def select_base_color(
    color: Optional[RGB],
    red: Optional[int],
    green: Optional[int],
    blue: Optional[int],
) -> RGB:
    """Resolve --color or the compatible --r/--g/--b form."""
    channels = (red, green, blue)
    if color is not None and any(channel is not None for channel in channels):
        raise ValueError("--color 不能和 --r/--g/--b 同时使用")
    if any(channel is not None for channel in channels):
        # Match encore_lightstick_pi.py defaults for omitted component options.
        return (
            255 if red is None else red,
            0 if green is None else green,
            0 if blue is None else blue,
        )
    return NAMED_COLORS["red"] if color is None else color


def encode_zone_color(color: RGB) -> int:
    """Quantize 24-bit RGB to the protocol's two bits per channel."""
    red, green, blue = (channel // 64 for channel in color)
    control = 0b11
    return (blue << 6) | (green << 4) | (red << 2) | control


def calculate_checksum(data: Sequence[int]) -> int:
    """Return the four-bit XOR checksum used by the protocol."""
    if len(data) != 10:
        raise ValueError("校验必须覆盖前 10 个数据字节")
    checksum = 0
    for byte in data:
        checksum ^= (byte >> 4) & 0x0F
        checksum ^= byte & 0x0F
    return (checksum ^ 0x0D) & 0x0F


def build_packet(colors: Sequence[RGB]) -> bytes:
    """Build the 13-byte packet expected by the reference transmitter."""
    if len(colors) != NUM_ZONES:
        raise ValueError(f"必须提供 {NUM_ZONES} 个分区的颜色")
    if any(len(color) != 3 for color in colors):
        raise ValueError("每个颜色都必须包含 R、G、B 三个通道")
    if any(not 0 <= channel <= 255 for color in colors for channel in color):
        raise ValueError("RGB 通道值必须在 0 到 255 之间")

    # Bytes 7..9 are the reference protocol's BB/GG/RR extension fields.
    # The working EncoreLightSticks sender leaves these fields at zero.
    data = [encode_zone_color(color) for color in colors] + [0x00, 0x00, 0x00]
    checksum = calculate_checksum(data)
    return bytes(data + [0x80 | checksum, 0x00, 0x00])


def append_run(runs: List[LevelRun], level: int, duration_us: int) -> None:
    """Append a run, merging adjacent periods at the same level."""
    if duration_us <= 0:
        raise ValueError("脉冲持续时间必须为正数")
    if runs and runs[-1].level == level:
        previous = runs[-1]
        runs[-1] = LevelRun(level, previous.duration_us + duration_us)
    else:
        runs.append(LevelRun(level, duration_us))


def append_manchester_bit(runs: List[LevelRun], bit: int) -> None:
    """Encode 0 as high-low and 1 as low-high."""
    first, second = ((1, 0) if bit == 0 else (0, 1))
    append_run(runs, first, HALF_BIT_US)
    append_run(runs, second, HALF_BIT_US)


def append_manchester_bytes(runs: List[LevelRun], data: bytes) -> None:
    for byte in data:
        for bit_index in range(7, -1, -1):
            append_manchester_bit(runs, (byte >> bit_index) & 1)


def build_frame_runs(packet: bytes) -> List[LevelRun]:
    """Build one RF frame in the same wire order as DigitalSender2.ino."""
    if len(packet) != PACKET_TOTAL_BYTES:
        raise ValueError(f"数据包必须正好是 {PACKET_TOTAL_BYTES} 字节")

    runs: List[LevelRun] = []
    append_manchester_bytes(runs, packet[-2:])
    append_run(runs, 0, SYNC_LOW_US)
    append_manchester_bit(runs, 0)
    append_manchester_bytes(runs, packet[:PACKET_DATA_BYTES])
    return runs


def repeat_runs(frame: Sequence[LevelRun], repeats: int) -> List[LevelRun]:
    if repeats < 1:
        raise ValueError("重复次数至少为 1")
    runs: List[LevelRun] = []
    for _ in range(repeats):
        for run in frame:
            append_run(runs, run.level, run.duration_us)
    return runs


class PigpioTransmitter:
    """Turn logical level runs into a pigpio DMA waveform."""

    def __init__(self, gpio: int, host: Optional[str] = None) -> None:
        try:
            import pigpio  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "未安装 Python pigpio；请执行 sudo apt install pigpio python3-pigpio"
            ) from exc

        self.pigpio = pigpio
        self.gpio = gpio
        self.pi = pigpio.pi(host) if host else pigpio.pi()
        if not self.pi.connected:
            self.pi.stop()
            raise RuntimeError(
                "无法连接 pigpio 服务；请执行 sudo systemctl enable --now pigpiod"
            )

        self.pi.set_mode(gpio, pigpio.OUTPUT)
        self.pi.set_pull_up_down(gpio, pigpio.PUD_OFF)
        self.pi.write(gpio, pigpio.LOW)

    def close(self) -> None:
        self.pi.wave_tx_stop()
        self.pi.write(self.gpio, self.pigpio.LOW)
        self.pi.stop()

    def __enter__(self) -> "PigpioTransmitter":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def send(self, runs: Sequence[LevelRun]) -> int:
        gpio_mask = 1 << self.gpio
        pulses = [
            self.pigpio.pulse(
                gpio_mask if run.level else 0,
                0 if run.level else gpio_mask,
                run.duration_us,
            )
            for run in runs
        ]

        self.pi.wave_add_new()
        added = self.pi.wave_add_generic(pulses)
        if added < 0:
            raise RuntimeError(f"pigpio 无法建立波形（错误 {added}）")
        wave_id = self.pi.wave_create()
        if wave_id < 0:
            raise RuntimeError(f"pigpio 无法创建波形（错误 {wave_id}）")

        try:
            result = self.pi.wave_send_once(wave_id)
            if result < 0:
                raise RuntimeError(f"pigpio 无法发送波形（错误 {result}）")
            while self.pi.wave_tx_busy():
                time.sleep(0.001)
        finally:
            self.pi.wave_delete(wave_id)

        return sum(run.duration_us for run in runs)


def packet_hex(packet: bytes) -> str:
    return " ".join(f"{byte:02X}" for byte in packet)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="使用树莓派 GPIO 和 433MHz 发射模块控制 7 分区场控荧光棒"
    )
    parser.add_argument(
        "--color",
        type=parse_color,
        default=None,
        metavar="COLOR",
        help="全部分区的底色：颜色名、#RRGGBB 或 R,G,B（默认 red）",
    )
    parser.add_argument("--r", type=parse_channel, help="红色通道 0..255")
    parser.add_argument("--g", type=parse_channel, help="绿色通道 0..255")
    parser.add_argument("--b", type=parse_channel, help="蓝色通道 0..255")
    parser.add_argument(
        "--zone",
        action="append",
        type=parse_zone,
        default=[],
        metavar="N=COLOR",
        help="覆盖指定分区，可重复使用，例如 --zone 1=red --zone 2=#00FF00",
    )
    parser.add_argument(
        "--gpio",
        type=int,
        default=DEFAULT_GPIO,
        help="BCM GPIO 编号（默认 17，即物理针脚 11）",
    )
    parser.add_argument(
        "--count",
        "--repeats",
        dest="count",
        type=int,
        default=None,
        help="发送指定帧数后退出；省略则持续发送，--repeats 是兼容别名",
    )
    parser.add_argument(
        "--hz",
        type=float,
        default=20.0,
        help="每帧发送完成后的等待间隔为 1/HZ 秒（默认 20）",
    )
    parser.add_argument(
        "--host",
        help="可选：远程 pigpiod 主机名或 IP；默认连接本机",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印数据包和波形信息，不访问 GPIO",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)

    if not 0 <= args.gpio <= 31:
        parser.error("--gpio 必须是 0 到 31 之间的 BCM GPIO 编号")
    if args.count is not None and not 1 <= args.count <= 10_000:
        parser.error("--count/--repeats 必须在 1 到 10000 之间")
    if args.hz <= 0:
        parser.error("--hz 必须大于 0")

    try:
        base_color = select_base_color(args.color, args.r, args.g, args.b)
    except ValueError as exc:
        parser.error(str(exc))

    colors = [base_color] * NUM_ZONES
    for zone, color in args.zone:
        colors[zone - 1] = color

    packet = build_packet(colors)
    frame = build_frame_runs(packet)
    duration_us = sum(run.duration_us for run in frame)

    print(f"GPIO: BCM {args.gpio}（物理针脚 11 是 BCM 17）")
    print(f"分区颜色: {', '.join(f'{r},{g},{b}' for r, g, b in colors)}")
    print(f"数据包: {packet_hex(packet)}")
    if args.count is None:
        print(
            f"发送: 持续发送（每帧 {duration_us / 1000:.1f} ms，"
            f"帧后等待 {1000 / args.hz:.1f} ms）"
        )
    else:
        print(f"发送: {args.count} 帧（每帧约 {duration_us / 1000:.1f} ms）")

    if args.dry_run:
        print("预览完成，未访问 GPIO。")
        return 0

    try:
        with PigpioTransmitter(args.gpio, args.host) as transmitter:
            sent = 0
            while args.count is None or sent < args.count:
                transmitter.send(frame)
                sent += 1
                if args.count is None or sent < args.count:
                    time.sleep(1.0 / args.hz)
    except (RuntimeError, OSError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n发送已中止。", file=sys.stderr)
        return 130

    if args.count is not None:
        print("发送完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
