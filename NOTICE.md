# Attribution Notice

This project implements a Raspberry Pi transmitter for the 433MHz light-stick protocol documented by **EncoreLightSticks**.

- Original project: [HansZ8/EncoreLightSticks](https://github.com/HansZ8/EncoreLightSticks)
- Original author: [HansZ8](https://github.com/HansZ8) (formerly `@GDDG08`)
- Original protocol documentation: [docs/protocols/basic.md](https://github.com/HansZ8/EncoreLightSticks/blob/main/docs/protocols/basic.md)
- Original transmitter reference: [DigitalSender2.ino](https://github.com/HansZ8/EncoreLightSticks/blob/main/hardware/DigitalSender2/DigitalSender2.ino)
- Original project license: Creative Commons Attribution-NonCommercial 4.0 International

The Python implementation, Web controller, tests, and Raspberry Pi integration in this repository were independently written from the published protocol description and reference behavior. Please preserve this attribution when redistributing the project.

## Hardware compatibility test

The implementation was tested with a light stick from **Vae Xu Song's 2026 China Tour, titled 「安泊猜想」**. On the tested unit, solid-color control, RGB color changes, and the black/off command worked successfully. Compatibility may vary between venues and hardware batches.
