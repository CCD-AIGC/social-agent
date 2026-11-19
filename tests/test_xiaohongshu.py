import json
import threading
from http.server import ThreadingHTTPServer
from io import BytesIO
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest
from openpyxl import Workbook

from social_agent.cli import main
from social_agent.errors import SocialAgentError
from social_agent.platforms.xiaohongshu import REPORT_CONTENT_TYPE, XiaohongshuAdapter
from social_agent.storage import StateStore
from social_agent.web_server import DashboardHandler


def official_notes_report() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["最多导出排序后前1000条笔记"])
    sheet.append([
        "笔记标题", "首次发布时间", "体裁", "曝光", "观看量", "封面点击率", "点赞",
        "评论", "收藏", "涨粉", "分享", "人均观看时长", "弹幕",
    ])
    sheet.append(["示例笔记", "2026年10月27日08时56分22秒", "视频", 100, 21, 0.22, 3, 2, 4, 1, 0, 5, 0])
    raw = BytesIO()
    workbook.save(raw)
    return raw.getvalue()


def test_official_report_import_and_cli_round_trip(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SOCIAL_AGENT_HOME", str(tmp_path))
    report = tmp_path / "笔记列表明细表.xlsx"
    report.write_bytes(official_notes_report())
    assert main(["xiaohongshu", "import-notes", str(report), "--account", "测试账号", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["note_count"] == 1
    assert main(["accounts", "probe", "--platform", "xiaohongshu", "--json"]) == 0
    probe = json.loads(capsys.readouterr().out)["data"]
    assert probe["status"]["snapshot_available"]
    assert probe["status"]["logged_in"] is None
    assert main(["metrics", "--platform", "xiaohongshu", "--account", "测试账号", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["result"]["notes"][0]["published_at"] == "2026-10-27T08:56:22"
    assert data["result"]["notes"][0]["cover_click_rate"] == 0.22
    assert data["result"]["totals"]["views"] == 21
    assert main(["research", "--platform", "xiaohongshu", "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "research_unavailable"


def test_malformed_report_never_replaces_a_snapshot():
    store = Mock(spec=StateStore)
    with pytest.raises(SocialAgentError, match="无法读取小红书笔记明细"):
        XiaohongshuAdapter(store).import_report("测试账号", b"not a workbook")
    store.save_note_snapshot.assert_not_called()



def test_dashboard_import_accepts_a_local_report_and_rejects_other_origins(tmp_path, monkeypatch):
    monkeypatch.setenv("SOCIAL_AGENT_HOME", str(tmp_path))
    with ThreadingHTTPServer(("127.0.0.1", 0), DashboardHandler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        headers = {
            "Content-Type": REPORT_CONTENT_TYPE,
            "X-Social-Agent-Account": urlencode({"account": "网页测试账号"}),
        }
        endpoint = base + "/api/xiaohongshu/import-notes"
        try:
            req = Request(endpoint, official_notes_report(), headers={**headers, "Origin": "https://example.com"})
            with pytest.raises(HTTPError) as caught:
                urlopen(req)
            assert caught.value.code == 403
            assert not XiaohongshuAdapter().probe()["status"]["snapshot_available"]

            req = Request(endpoint, official_notes_report(), headers={**headers, "Origin": base})
            with urlopen(req) as response:
                assert json.load(response)["data"]["note_count"] == 1
            with urlopen(base + "/api/metrics?platform=xiaohongshu") as response:
                result = json.load(response)["data"]["result"]
                assert result["account"] == "网页测试账号"
                assert result["totals"]["views"] == 21
        finally:
            server.shutdown()
            thread.join(timeout=2)
