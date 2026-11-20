import json
import threading
import unittest
from http.client import HTTPConnection
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

    @patch("social_agent.web_server.save_credentials")
    def test_credentials_endpoint_rejects_non_json_and_foreign_origin(self, save):
        for headers, status in [
            ({"Content-Type": "text/plain"}, 400),
            ({"Content-Type": "application/json", "Origin": "https://foreign.example"}, 403),
        ]:
            request = Request(f"{self.base}/api/accounts/wechat-mp", data=b"{}", headers=headers)
            with self.assertRaises(HTTPError) as caught:
                urlopen(request)
            self.assertEqual(caught.exception.code, status)
        save.assert_not_called()

    @patch("social_agent.web_server.CredentialStore.get", return_value="https://mp.weixin.qq.com/cgi-bin/filepage?token=example")
    def test_materials_shortcut_redirects_without_exposing_session_in_html(self, get_secret):
        with urlopen(self.base + "/") as response:
            html = response.read().decode()
        self.assertIn('/go/wechat-materials', html)
        self.assertNotIn("token=example", html)
        conn = HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=3)
        try:
            conn.request("GET", "/go/wechat-materials")
            response = conn.getresponse()
            self.assertEqual(response.status, 302)
            self.assertEqual(response.getheader("Location"), get_secret.return_value)
            self.assertEqual(response.getheader("Cache-Control"), "no-store")
        finally:
            conn.close()

    @patch("social_agent.web_server.sau.start_login", return_value={"alias": "demo", "running": True})
    def test_sau_login_requires_user_action_from_workbench_origin(self, start_login):
        data = b'{"platform":"xiaohongshu","account":"demo"}'
        no_origin = Request(self.base + "/api/sau/login", data=data, headers={"Content-Type": "application/json"})
        with self.assertRaises(HTTPError) as caught:
            urlopen(no_origin)
        self.assertEqual(caught.exception.code, 400)
        start_login.assert_not_called()
        local = Request(self.base + "/api/sau/login", data=data,
                        headers={"Content-Type": "application/json", "Origin": self.base})
        with urlopen(local) as response:
            self.assertEqual(response.status, 202)
        start_login.assert_called_once_with("xiaohongshu", "demo")

    @patch("social_agent.web_server.submit_sau")
    def test_sau_requires_explicit_same_origin_confirmation(self, submit):
        request = Request(f"{self.base}/api/sau/video", data=b'{"confirmed":true}',
                          headers={"Content-Type": "application/json"})
        with self.assertRaises(HTTPError) as caught:
            urlopen(request)
        self.assertEqual(caught.exception.code, 400)
        self.assertEqual(json.load(caught.exception)["error"]["code"], "confirmation_required")
        submit.assert_not_called()

    @patch("social_agent.web_server._cli", return_value={"ok": True, "data": {"status": {"logged_in": True}}})
    @patch("social_agent.web_server.shutil.which", return_value="/usr/local/bin/bili")
    def test_platform_catalog_marks_only_verified_bilibili_connected(self, _which, _cli):
        with urlopen(f"{self.base}/api/platforms") as response:
            payload = json.load(response)
        platforms = payload["data"]
        self.assertEqual({item["id"] for item in platforms}, {"xiaohongshu", "wechat_mp", "wechat_channels", "douyin", "zhihu", "youtube", "bilibili"})
        self.assertEqual([item["id"] for item in platforms if item["connected"]], ["bilibili"])


if __name__ == "__main__":
    unittest.main()
