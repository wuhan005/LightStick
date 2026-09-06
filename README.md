# LightStick for Raspberry Pi

使用树莓派和 433MHz ASK/OOK 发射模块控制兼容的演唱会场控荧光棒。项目提供命令行单色/分区控制、RGB 循环效果，以及适合手机使用的本地 Web 色盘。

> [!NOTE]
> 本项目的协议分析、编码格式与原始发送实现来自 [HansZ8/EncoreLightSticks](https://github.com/HansZ8/EncoreLightSticks)。感谢原项目作者 [HansZ8](https://github.com/HansZ8)（原 GitHub 用户名 `GDDG08`）以及所有参与协议研究和资料整理的贡献者；本项目是在其成果基础上完成的 Raspberry Pi + `pigpio` 实现。

> [!IMPORTANT]
> 当前编码实现源自陶喆 Soul Power II 2024 版 7 分区协议。不同演唱会、场次、年份和硬件批次可能使用不同协议，请勿仅凭频率相同判断兼容性。

## 已验证兼容性

本项目已使用**许嵩 2026「安泊猜想」中国巡回演唱会**荧光棒进行实机测试，单色控制、RGB 颜色切换及关闭指令均可正常使用。

该结果仅代表测试所用荧光棒；后续场次或不同硬件批次仍可能调整协议。如果你测试了其他场次，欢迎在 Issue 或 Pull Request 中补充型号、场次与测试结果。

## 功能

- 使用 `pigpio` 稳定发送 433MHz 信号
- 支持颜色名、RGB、HEX 和 7 分区颜色
- 支持红、绿、蓝循环效果
- 提供适合手机使用的 Web RGB 色盘和快捷颜色

## 硬件与接线

需要一个**不带编码芯片**的 433MHz ASK/OOK 发射模块。

| 发射模块 | 树莓派 |
| --- | --- |
| DATA | 物理针脚 11 / BCM GPIO17 |
| VCC | 物理针脚 2 或 4 / 5V |
| GND | 物理针脚 6 / GND |
| ANT | 约 17cm 直导线 |

GPIO17 是 3.3V 逻辑。不要把任何 5V 信号接回树莓派 GPIO；如果模块 DATA 明确要求 5V 高电平，请使用三极管或电平转换器。

## 安装

```bash
git clone https://github.com/wuhan005/LightStick.git
cd LightStick

sudo apt update
sudo apt install pigpio python3-pigpio
sudo systemctl enable --now pigpiod
```

## 命令行控制

持续发送绿色，按 `Ctrl+C` 停止：

```bash
python3 lightstick.py --color green
```

也可以直接指定 RGB：

```bash
python3 lightstick.py --r 0 --g 255 --b 0
```

发送黑色以关闭荧光棒：

```bash
python3 lightstick.py --color off
```

也支持 HEX、逗号分隔 RGB 和分区控制：

```bash
python3 lightstick.py --color '#8000FF'
python3 lightstick.py --color 255,128,0
python3 lightstick.py --color off \
  --zone 1=red \
  --zone 2=green \
  --zone 3=blue
```

协议中每个颜色通道只有 2 bit，因此 RGB 会量化为 0、1、2、3 四档。

## RGB 循环效果

按“红 → 绿 → 蓝”持续循环，不插入黑色帧：

```bash
python3 rgb_cycle.py
```

可以调整每种颜色的保持时间：

```bash
python3 rgb_cycle.py --hold 2.0
```

## Web RGB 控制台

请先停止 `lightstick.py` 或 `rgb_cycle.py`，同一时间只运行一个控制程序：

```bash
python3 web_server.py
```

查询树莓派的局域网 IP：

```bash
hostname -I
```

随后用同一局域网中的手机或电脑打开：

```text
http://<树莓派IP>:8080
```

网页支持色盘、亮度、RGB/HEX 输入和快捷颜色。快捷颜色点击后会立即发送；黑色按钮会发送 `RGB(0,0,0)` 关闭荧光棒。“停止发射”只停止信号刷新，不会发送黑色帧。

仅预览页面与接口、不访问 GPIO：

```bash
python3 web_server.py --dry-run
```

指定其他端口：

```bash
python3 web_server.py --port 8081
```

Web 控制台没有用户认证，请只在可信局域网中使用，不要将端口暴露到互联网。

## 协议来源

本项目不是原协议研究的替代品。编码方式、数据包结构、校验算法与发送顺序均参考原版仓库 **[HansZ8/EncoreLightSticks](https://github.com/HansZ8/EncoreLightSticks)**：

- [协议说明](https://github.com/HansZ8/EncoreLightSticks/blob/main/docs/protocols/basic.md)
- [DigitalSender2 发送实现](https://github.com/HansZ8/EncoreLightSticks/blob/main/hardware/DigitalSender2/DigitalSender2.ino)

在树莓派实现中，本项目使用 250µs 半位宽和实机验证可用的 500µs 同步低电平。其他型号可能需要重新抓取和分析协议，不能仅修改频率或颜色字段。

## 安全与合规

- 请确认当地对 433MHz 频段、发射功率和使用场景的规定。
- 建议先在近距离、低功率环境测试。
- 不要在演出现场或其他可能干扰合法设备的环境中使用。
- Raspberry Pi 5 与部分新内核可能不兼容传统 `pigpio`，请先确认 `pigpiod` 能启动。

## 许可证与致谢

本项目依据 [CC BY-NC 4.0](LICENSE) 发布，仅限非商业用途。

再次感谢 **[EncoreLightSticks 原版仓库](https://github.com/HansZ8/EncoreLightSticks)** 对 433MHz 荧光棒协议的分析、整理与开放分享。没有原项目的工作，就不会有这个树莓派版本。完整署名信息见 [NOTICE.md](NOTICE.md)。
