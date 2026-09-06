import http.client
import json
import tempfile
import threading
import time
import unittest
from functools import partial
from pathlib import Path

import web_server


class FakeTransmitter:
    sent = []

    def __init__(self, gpio):
        self.gpio = gpio

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def send(self, runs):
        self.__class__.sent.append(tuple(runs))
        return sum(run.duration_us for run in runs)


class ValidationTests(unittest.TestCase):
    def test_valid_color(self):
        self.assertEqual(web_server.validate_color({"r": 1, "g": 2, "b": 255}), (1, 2, 255))

    def test_invalid_color(self):
        for payload in ({"r": 0, "g": 0}, {"r": -1, "g": 0, "b": 0}, {"r": True, "g": 0, "b": 0}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                web_server.validate_color(payload)

    def test_quantization(self):
        self.assertEqual(web_server.quantized_levels((0, 128, 255)), (0, 2, 3))


class ServiceTests(unittest.TestCase):
    def setUp(self):
        FakeTransmitter.sent = []
        self.service = web_server.LightstickService(
            refresh_hz=1000,
            transmitter_factory=FakeTransmitter,
            dry_run=True,
        )

    def tearDown(self):
        self.service.stop()

    def test_start_update_and_stop_single_worker(self):
        first = self.service.start((0, 255, 0))
        thread = self.service._thread
        second = self.service.start((255, 0, 0))
        self.assertTrue(first["transmitting"])
        self.assertTrue(second["transmitting"])
        self.assertIs(thread, self.service._thread)
        time.sleep(0.01)
        stopped = self.service.stop()
        self.assertFalse(stopped["transmitting"])
        self.assertGreater(len(FakeTransmitter.sent), 0)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        Path(self.temp_directory.name, "index.html").write_text("ok", encoding="utf-8")
        self.service = web_server.LightstickService(
            refresh_hz=1000,
            transmitter_factory=FakeTransmitter,
            dry_run=True,
        )
        handler = partial(web_server.ControllerHandler, directory=self.temp_directory.name)
        self.server = web_server.LightstickHTTPServer(("127.0.0.1", 0), handler, self.service)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.service.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp_directory.cleanup()

    def request(self, method, path, payload=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        body = None if payload is None else json.dumps(payload)
        headers = {} if body is None else {"Content-Type": "application/json"}
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        data = json.loads(response.read().decode("utf-8"))
        connection.close()
        return response.status, data

    def test_status_color_and_stop_endpoints(self):
        status_code, status = self.request("GET", "/api/status")
        self.assertEqual(status_code, 200)
        self.assertFalse(status["transmitting"])

        status_code, started = self.request("POST", "/api/color", {"r": 0, "g": 255, "b": 0})
        self.assertEqual(status_code, 200)
        self.assertTrue(started["transmitting"])
        self.assertEqual(started["color"], [0, 255, 0])

        status_code, off = self.request("POST", "/api/color", {"r": 0, "g": 0, "b": 0})
        self.assertEqual(status_code, 200)
        self.assertEqual(off["color"], [0, 0, 0])
        self.assertEqual(off["levels"], [0, 0, 0])

        status_code, stopped = self.request("POST", "/api/stop", {})
        self.assertEqual(status_code, 200)
        self.assertFalse(stopped["transmitting"])
        self.assertIn("没有发送黑色包", stopped["message"])

    def test_rejects_bad_payload_and_cross_origin_preflight(self):
        status_code, _ = self.request("POST", "/api/color", {"r": 999, "g": 0, "b": 0})
        self.assertEqual(status_code, 400)
        status_code, _ = self.request("OPTIONS", "/api/color")
        self.assertEqual(status_code, 405)


if __name__ == "__main__":
    unittest.main()
