from __future__ import annotations

from http import HTTPStatus
from http.client import HTTPConnection
import io
import json
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from case_rest_api_v2 import (CaseRESTApplication, CaseRESTServer, CaseRESTUnavailable,
                              DEFAULT_ENDPOINT, validate_error_payload)

REQUEST = (ROOT / "specs/application/examples/case-rest-v2/request.json").read_bytes()


class RestTransportConcurrencyTests(unittest.TestCase):
    """Keep-alive transport never blocks other clients or multiplies research."""

    def setUp(self):
        self.running = []

    def tearDown(self):
        for server, thread in reversed(self.running):
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())

    def start_server(self, researcher):
        server = CaseRESTServer(("127.0.0.1", 0), CaseRESTApplication(researcher))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.running.append((server, thread))
        return server.server_address

    def connect(self, address):
        return HTTPConnection(address[0], address[1], timeout=1.25)

    def request(self, conn, method="GET", body=None):
        if method == "POST":
            conn.request("POST", DEFAULT_ENDPOINT, body=REQUEST,
                         headers={"Content-Type": "application/json"})
        else:
            conn.request(method, DEFAULT_ENDPOINT)
        response = conn.getresponse()
        payload = json.loads(response.read())
        validate_error_payload(payload)
        return response.status, payload

    def test_idle_http11_keepalive_cannot_starve_second_client(self):
        address = self.start_server(lambda _: None)
        idle = self.connect(address)
        other = self.connect(address)
        try:
            with mock.patch("case_rest_api_v2.sys.stderr", io.StringIO()):
                self.assertEqual(self.request(idle)[0], HTTPStatus.METHOD_NOT_ALLOWED)
                # Keep the first connection alive after fully reading the response.
                self.assertIsNotNone(idle.sock)
                started = time.monotonic()
                self.assertEqual(self.request(other)[0], HTTPStatus.METHOD_NOT_ALLOWED)
                self.assertLess(time.monotonic() - started, 1.0)
        finally:
            idle.close()
            other.close()

    def test_research_serialized_while_cheap_client_remains_responsive(self):
        first_entered = threading.Event()
        release_first = threading.Event()
        guard = threading.Lock()
        current = 0
        max_current = 0
        count = 0

        def researcher(_case_input):
            nonlocal current, max_current, count
            with guard:
                count += 1
                current += 1
                max_current = max(max_current, current)
                my_count = count
            try:
                if my_count == 1:
                    first_entered.set()
                    if not release_first.wait(timeout=3):
                        raise AssertionError("test timed out waiting to release first")
                raise CaseRESTUnavailable("synthetic backend unavailable")
            finally:
                with guard:
                    current -= 1

        address = self.start_server(researcher)
        results = []
        failures = []

        def post():
            conn = self.connect(address)
            try:
                results.append(self.request(conn, "POST"))
            except Exception as exc:
                failures.append(repr(exc))
            finally:
                conn.close()

        t1 = threading.Thread(target=post, daemon=True)
        t2 = threading.Thread(target=post, daemon=True)
        with mock.patch("case_rest_api_v2.sys.stderr", io.StringIO()):
            try:
                t1.start()
                self.assertTrue(first_entered.wait(timeout=1.5))
                t2.start()
                cheap = self.connect(address)
                try:
                    self.assertEqual(self.request(cheap)[0], HTTPStatus.METHOD_NOT_ALLOWED)
                finally:
                    cheap.close()
                with guard:
                    self.assertEqual(max_current, 1)
                    self.assertEqual(count, 1)
            finally:
                release_first.set()
                t1.join(timeout=3)
                t2.join(timeout=3)
        self.assertFalse(t1.is_alive())
        self.assertFalse(t2.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(len(results), 2)
        self.assertTrue(all(status == 503 for status, _ in results))
        self.assertEqual(max_current, 1)

    def test_shutdown_does_not_wait_for_idle_keepalive_thread(self):
        address = self.start_server(lambda _: None)
        idle = self.connect(address)
        try:
            with mock.patch("case_rest_api_v2.sys.stderr", io.StringIO()):
                self.assertEqual(self.request(idle)[0], HTTPStatus.METHOD_NOT_ALLOWED)
            server, thread = self.running.pop()
            started = time.monotonic()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
            self.assertLess(time.monotonic() - started, 2.0)
        finally:
            idle.close()


if __name__ == "__main__":
    unittest.main()
