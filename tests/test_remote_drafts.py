import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit

import pytest

from social_agent import remote_drafts
from social_agent.content import create_draft
from social_agent.errors import SocialAgentError
from social_agent.platforms.wechat_mp import WechatMPSession
from social_agent.storage import StateStore


APP_ID = "wx0123456789abcdef"
SECRET = "a" * 32
TOKEN = "fake-token"


class FakeWechat:
    def __init__(self):
        self.calls = []
        self.article = None
        self.fail_save = False
        self.fail_read = False

    def open(self, request, timeout):
        url = urlsplit(request.full_url)
        assert url.netloc == "api.weixin.qq.com"
        path = url.path.removeprefix("/cgi-bin/")
        self.calls.append(path)
        if path != "stable_token":
            assert parse_qs(url.query)["access_token"] == [TOKEN]
        if path == "stable_token":
            assert json.loads(request.data) == {
                "grant_type": "client_credential", "appid": APP_ID, "secret": SECRET, "force_refresh": False,
            }
            response = {"access_token": TOKEN}
        elif path == "draft/count":
            response = {"total_count": int(self.article is not None)}
        elif path == "material/add_material":
            assert parse_qs(url.query)["type"] == ["thumb"]
            assert b'filename="cover.jpg"' in request.data
            response = {"media_id": "cover-1"}
        elif path == "draft/add":
            self.article = json.loads(request.data)["articles"][0]
            if self.fail_save:
                raise URLError("sensitive upstream text")
            response = {"media_id": "draft-1"}
        elif path == "draft/get":
            assert json.loads(request.data)["media_id"] == "draft-1"
            if self.fail_read:
                raise URLError("sensitive upstream text")
            response = {"news_item": [self.article]}
        else:
            pytest.fail("unexpected endpoint: " + path)
        return io.BytesIO(json.dumps(response).encode())


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("SOCIAL_AGENT_HOME", str(tmp_path))
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"\xff\xd8\xff\xff\xd9")
    video = tmp_path / "video.mp4"
    video.write_bytes(b"local video sample")
    draft = create_draft("标题", "第一段 <文本>\n\n第二段", ["wechat_mp", "xiaohongshu"],
                         media=[str(video)], cover=str(cover), ai_generated=True)
    api = FakeWechat()

    class Adapter:
        def connect(self, alias):
            assert alias in {"sample", "another"}
            return WechatMPSession(APP_ID, SECRET, api)

    monkeypatch.setattr(remote_drafts, "get_adapter", lambda platform: Adapter())
    monkeypatch.setattr("social_agent.platforms.wechat_mp.time.sleep", lambda _: None)
    return draft, api, StateStore()


def test_draft_save_and_read_deduplicate_across_aliases(data):
    draft, api, store = data
    row = remote_drafts.save_draft(draft, "wechat_mp", "sample", store)
    assert row["status"] == "verified"
    assert row["result"]["reference"] == "draft-1"
    assert "AI 辅助" in api.article["content"]
    assert "&lt;文本&gt;" in api.article["content"]
    assert api.calls == ["stable_token", "draft/count", "material/add_material", "draft/add", "draft/get"]
    duplicate = remote_drafts.save_draft(draft, "wechat_mp", "another", StateStore())
    assert duplicate["id"] == row["id"]
    assert api.calls.count("draft/add") == 1
    assert remote_drafts.verify_draft(StateStore(), row["id"])["status"] == "verified"


def test_interrupted_write_is_reconciled_without_resubmitting(data):
    draft, api, store = data
    api.fail_save = True
    row = remote_drafts.save_draft(draft, "wechat_mp", "sample", store)
    assert row["status"] == "needs_verification"
    assert row["result"]["cover_id"] == "cover-1"
    assert row["error_code"] == "write_unconfirmed"
    assert "sensitive" not in json.dumps(row)
    assert remote_drafts.save_draft(draft, "wechat_mp", "sample", StateStore())["id"] == row["id"]
    assert remote_drafts.verify_draft(StateStore(), row["id"], "draft-1")["status"] == "verified"
    assert api.calls.count("draft/add") == 1


def test_readback_failure_preserves_remote_receipt(data):
    draft, api, store = data
    api.fail_read = True
    row = remote_drafts.save_draft(draft, "wechat_mp", "sample", store)
    assert row["status"] == "needs_verification"
    assert row["result"]["reference"] == "draft-1"
    api.fail_read = False
    assert remote_drafts.verify_draft(StateStore(), row["id"])["status"] == "verified"


def test_double_submit_executes_one_write(data):
    draft, api, store = data
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(remote_drafts.save_draft, draft, "wechat_mp", "sample", store) for _ in range(3)]
        ids = {f.result()["id"] for f in futures}
    assert len(ids) == 1
    assert api.calls.count("draft/add") == 1


def test_interrupted_running_operation_is_never_retried(data):
    _, _, store = data
    row, _ = store.reserve_draft("key", "wechat_mp", {})
    store.advance_draft(row["id"], "queued", "running")
    old = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    with store._connect() as conn:
        conn.execute("UPDATE operations SET finished_at=? WHERE id=?", (old, row["id"]))
    assert remote_drafts.operation(store, row["id"])["status"] == "needs_verification"
    _, start = store.reserve_draft("key", "wechat_mp", {})
    assert not start


def test_handoff_receipt_distinguishes_browser_storage(data):
    draft, api, store = data
    row = remote_drafts.prepare_handoff(draft, "xiaohongshu", "sample", store)
    assert row["status"] == "handoff_ready"
    assert not api.calls
    with pytest.raises(SocialAgentError, match="账号"):
        remote_drafts.record_handoff(store, row["id"], "another", "browser")
    result = remote_drafts.record_handoff(store, row["id"], "sample", "browser")
    assert result["status"] == "verified_manually"
    assert result["result"]["scope"] == "browser"
    assert remote_drafts.prepare_handoff(draft, "xiaohongshu", "sample", store)["id"] == row["id"]


def test_sau_draft_and_schedule_routes_have_distinct_parameters(data, monkeypatch):
    draft, _, store = data
    from social_agent.platforms import sau

    def accounts(platform):
        return {"mode": "draft" if platform == "wechat_channels" else "schedule", "installed": True, "accounts": ["sample"]}

    calls = []
    scheduled = sau.default_schedule()
    monkeypatch.setattr(sau, "accounts", accounts)
    monkeypatch.setattr(sau, "run_video", lambda args: calls.append(args) or {"exit_code": 0})
    with ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(SocialAgentError, match="时间"):
            remote_drafts.submit_sau(draft, "xiaohongshu", "sample", "schedule", store, pool)
        with pytest.raises(SocialAgentError, match="未接入"):
            remote_drafts.submit_sau(draft, "xiaohongshu", "sample", "publish", store, pool)
        row = remote_drafts.submit_sau(draft, "xiaohongshu", "sample", "schedule", store, pool, scheduled, "Sample account")
        duplicate = remote_drafts.submit_sau(draft, "xiaohongshu", "sample", "schedule", store, pool, scheduled, "Sample account")
        assert duplicate["id"] == row["id"]
    assert len(calls) == 1
    assert calls[0][:2] == ["xiaohongshu", "upload-video"]
    assert "--draft" not in calls[0]
    assert calls[0][calls[0].index("--schedule") + 1] == scheduled.replace("T", " ")
    assert remote_drafts.operation(store, row["id"])["status"] == "needs_verification"
    with pytest.raises(SocialAgentError):
        remote_drafts.record_handoff(store, row["id"], "sample", "account")
    assert remote_drafts.record_handoff(store, row["id"], "sample", "account", "sample-note")["status"] == "verified_manually"
    assert "--draft" in sau.video_args("wechat_channels", "sample", {
        "video": "sample.mp4", "title": "sample", "body": "sample", "tags": [], "cover": None,
    })
