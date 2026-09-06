#!/usr/bin/env python3
"""Cycle an Encore-compatible light stick through bright red, green and blue."""

from __future__ import annotations

import argparse
import sys
import time
from typing import Dict, List, Optional, Sequence, Tuple

from lightstick import (
    DEFAULT_GPIO,
    NUM_ZONES,
    LevelRun,
    PigpioTransmitter,
    RGB,
    build_frame_runs,
    build_packet,
    packet_hex,
)


RGB_SEQUENCE: Tuple[Tuple[str, RGB], ...] = (
    ("红", (255, 0, 0)),
    ("绿", (0, 255, 0)),
    ("蓝", (0, 0, 255)),
)


def build_color_frames() -> Dict[str, List[LevelRun]]:
    frames: Dict[str, List[LevelRun]] = {}
    for name, color in RGB_SEQUENCE:
        frames[name] = build_frame_runs(build_packet([color] * NUM_ZONES))
    return frames


def transmit_for(
    transmitter: PigpioTransmitter,
    frame: Sequence[LevelRun],
    duration: float,
    frame_gap: float,
) -> None:
    """Refresh one color for approximately duration seconds."""
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        transmitter.send(frame)
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(frame_gap, remaining))


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="让 433MHz 场控荧光棒按红、绿、蓝循环闪烁"
    )
    parser.add_argument(
        "--hold",
        type=float,
        default=1.0,
        help="每种颜色保持秒数（默认 1.0）",
    )
    parser.add_argument(
        "--hz",
        type=float,
        default=20.0,
        help="同一状态每帧发送完成后的等待频率值（默认 20，即等待 50ms）",
    )
    parser.add_argument(
        "--cycles",
        type=int,
        default=0,
        help="RGB 循环次数；0 表示一直循环（默认 0）",
    )
    parser.add_argument(
        "--gpio",
        type=int,
        default=DEFAULT_GPIO,
        help="BCM GPIO 编号（默认 17，即物理针脚 11）",
    )
    parser.add_argument(
        "--host",
        help="可选：远程 pigpiod 主机名或 IP；默认连接本机",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只显示 RGB 数据包，不访问 GPIO",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)

    if args.hold <= 0:
        parser.error("--hold 必须大于 0")
    if args.hz <= 0:
        parser.error("--hz 必须大于 0")
    if args.cycles < 0:
        parser.error("--cycles 不能小于 0")
    if not 0 <= args.gpio <= 31:
        parser.error("--gpio 必须是 0 到 31 之间的 BCM GPIO 编号")

    frames = build_color_frames()
    packets = {
        name: build_packet([color] * NUM_ZONES)
        for name, color in RGB_SEQUENCE
    }

    print(f"GPIO: BCM {args.gpio}")
    for name in ("红", "绿", "蓝"):
        print(f"{name}: {packet_hex(packets[name])}")
    if args.cycles == 0:
        print("模式: 持续循环；按 Ctrl+C 停止发射")
    else:
        print(f"模式: 循环 {args.cycles} 次后停止发射")

    if args.dry_run:
        print("预览完成，未访问 GPIO。")
        return 0

    frame_gap = 1.0 / args.hz
    try:
        with PigpioTransmitter(args.gpio, args.host) as transmitter:
            try:
                completed = 0
                while args.cycles == 0 or completed < args.cycles:
                    for name, _color in RGB_SEQUENCE:
                        print(f"\r当前颜色: {name}", end="", flush=True)
                        transmit_for(transmitter, frames[name], args.hold, frame_gap)
                    completed += 1
            except KeyboardInterrupt:
                print("\n收到停止指令，停止发射。")
    except (RuntimeError, OSError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    print("\n已停止。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
