import unittest

import lightstick
import rgb_cycle


class RgbCycleTests(unittest.TestCase):
    def test_sequence_is_bright_red_green_blue(self):
        self.assertEqual(
            rgb_cycle.RGB_SEQUENCE,
            (
                ("红", (255, 0, 0)),
                ("绿", (0, 255, 0)),
                ("蓝", (0, 0, 255)),
            ),
        )

    def test_frames_use_verified_timing(self):
        frames = rgb_cycle.build_color_frames()
        self.assertEqual(set(frames), {"红", "绿", "蓝"})
        for frame in frames.values():
            self.assertEqual(sum(run.duration_us for run in frame), 53_000)

    def test_green_packet(self):
        green = lightstick.build_packet([(0, 255, 0)] * lightstick.NUM_ZONES)
        self.assertEqual(green[:7], bytes([0x33] * 7))


if __name__ == "__main__":
    unittest.main()
