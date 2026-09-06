import argparse
import unittest

import lightstick


class ColorParsingTests(unittest.TestCase):
    def test_named_hex_and_decimal_colors(self):
        self.assertEqual(lightstick.parse_color("red"), (255, 0, 0))
        self.assertEqual(lightstick.parse_color("#12aBcD"), (0x12, 0xAB, 0xCD))
        self.assertEqual(lightstick.parse_color("1, 2, 255"), (1, 2, 255))

    def test_invalid_color_is_rejected(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            lightstick.parse_color("256,0,0")

    def test_zone_parser(self):
        self.assertEqual(lightstick.parse_zone("7=blue"), (7, (0, 0, 255)))
        with self.assertRaises(argparse.ArgumentTypeError):
            lightstick.parse_zone("8=blue")

    def test_component_arguments_match_verified_script(self):
        color = lightstick.select_base_color(None, 0, 255, 0)
        self.assertEqual(color, (0, 255, 0))

    def test_component_defaults_match_verified_script(self):
        self.assertEqual(
            lightstick.select_base_color(None, None, None, None), (255, 0, 0)
        )
        self.assertEqual(lightstick.select_base_color(None, 0, None, None), (0, 0, 0))

    def test_color_and_components_are_mutually_exclusive(self):
        with self.assertRaises(ValueError):
            lightstick.select_base_color((0, 255, 0), 0, None, None)


class PacketTests(unittest.TestCase):
    def test_documented_quantization_example(self):
        self.assertEqual(lightstick.encode_zone_color((128, 64, 0)), 0x1B)

    def test_all_red_packet(self):
        packet = lightstick.build_packet([(255, 0, 0)] * 7)
        self.assertEqual(packet, bytes([0x0F] * 7 + [0, 0, 0, 0x82, 0, 0]))

    def test_all_white_packet(self):
        packet = lightstick.build_packet([(255, 255, 255)] * 7)
        self.assertEqual(packet, bytes([0xFF] * 7 + [0, 0, 0, 0x8D, 0, 0]))

    def test_verified_green_and_off_packets(self):
        green = lightstick.build_packet([(0, 255, 0)] * 7)
        off = lightstick.build_packet([(0, 0, 0)] * 7)
        self.assertEqual(green, bytes([0x33] * 7 + [0, 0, 0, 0x8D, 0, 0]))
        self.assertEqual(off, bytes([0x03] * 7 + [0, 0, 0, 0x8E, 0, 0]))

    def test_bad_zone_count_is_rejected(self):
        with self.assertRaises(ValueError):
            lightstick.build_packet([(255, 0, 0)] * 6)


class WaveformTests(unittest.TestCase):
    def test_manchester_polarity(self):
        runs = []
        lightstick.append_manchester_bit(runs, 0)
        lightstick.append_manchester_bit(runs, 1)
        self.assertEqual(
            runs,
            [
                lightstick.LevelRun(1, 250),
                lightstick.LevelRun(0, 500),
                lightstick.LevelRun(1, 250),
            ],
        )

    def test_frame_has_reference_duration_and_sync_gap(self):
        packet = lightstick.build_packet([(255, 0, 0)] * 7)
        runs = lightstick.build_frame_runs(packet)
        self.assertEqual(sum(run.duration_us for run in runs), 53_000)
        self.assertTrue(any(run.level == 0 and run.duration_us >= 750 for run in runs))

    def test_repeated_frames_keep_exact_duration(self):
        packet = lightstick.build_packet([(0, 0, 0)] * 7)
        frame = lightstick.build_frame_runs(packet)
        repeated = lightstick.repeat_runs(frame, 5)
        self.assertEqual(sum(run.duration_us for run in repeated), 265_000)


if __name__ == "__main__":
    unittest.main()
