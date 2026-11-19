import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from social_agent.web_server import DashboardHandler


class WebServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), DashboardHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def test_health_api_returns_local_only_status(self):
        with urlopen(f"{self.base}/api/health") as response:
            payload = json.load(response)
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers["Content-Security-Policy"], "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.assertFalse(payload["data"]["live_publish"])

    def test_rejects_foreign_host_header(self):
        req = Request(f"{self.base}/api/health", headers={"Host": "attacker.example"})
        with self.assertRaises(HTTPError) as caught:
            urlopen(req)
        self.assertEqual(caught.exception.code, 403)

    def test_rejects_cross_origin_browser_request(self):
        req = Request(
            f"{self.base}/api/health",
            headers={"Origin": "http://attacker.example"},
        )
        with self.assertRaises(HTTPError) as caught:
            urlopen(req)
        self.assertEqual(caught.exception.code, 403)

    @patch("social_agent.web_server._cli", return_value={"ok": True, "data": {"status": {"logged_in": True}}})
    @patch("social_agent.web_server.shutil.which", return_value="/usr/local/bin/bili")
    def test_platform_catalog_marks_only_verified_bilibili_connected(self, _which, _cli):
        with urlopen(f"{self.base}/api/platforms") as response:
            payload = json.load(response)
        platforms = payload["data"]
        self.assertEqual({item["id"] for item in platforms}, {"xiaohongshu", "douyin", "zhihu", "youtube", "bilibili"})
        self.assertEqual([item["id"] for item in platforms if item["connected"]], ["bilibili"])


if __name__ == "__main__":
    unittest.main()
