"""Local-only web dashboard for the Social Agent CLI."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import tempfile
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
import sys
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse, urlsplit

from .content import create_draft
from .credentials import CredentialStore
from .errors import SocialAgentError
from .paths import app_home, drafts_path, secure_mkdir
from .platforms.xiaohongshu import (
    MAX_REPORT_BYTES,
    REPORT_CONTENT_TYPE,
    XiaohongshuAdapter,
)
from .platforms import get_adapter, list_platforms, sau
from .platforms.opencli import research_sources
from .platforms.wechat_mp import save_credentials
from .publishing import dry_run_publish
from .remote_drafts import capabilities, operation, prepare_handoff, probe_wechat_account, record_handoff, save_draft, submit_sau, validate_alias, verify_draft
from .storage import StateStore

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = PROJECT_ROOT / "web"

DRAFT_WORKERS = ThreadPoolExecutor(max_workers=2, thread_name_prefix="remote-draft")
SAU_WORKER = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sau")

CREATOR_LINKS = {
    "wechat_mp": "https://mp.weixin.qq.com/",
    "xiaohongshu": "https://creator.xiaohongshu.com/new/home",
    "wechat_channels": "https://channels.weixin.qq.com/platform/post/list",
    "bilibili": "https://member.bilibili.com/platform/upload-manager/article?spm_id_from=333.1007.0.0",
}


def wechat_materials_link() -> str:
    try:
        shortcut = CredentialStore().get("wechat_mp", "local-shortcuts", "materials-url")
        if shortcut and "\r" not in shortcut and "\n" not in shortcut:
            parts = urlsplit(shortcut)
            if parts.scheme == "https" and parts.netloc == "mp.weixin.qq.com" and parts.path == "/cgi-bin/filepage":
                return shortcut
    except (SocialAgentError, ValueError):
        pass
    return CREATOR_LINKS["wechat_mp"]



def _registered_account(alias: str, store: StateStore) -> str:
    alias = validate_alias(alias)
    if not any(row["alias"] == alias and row["platform"] == "wechat_mp" for row in store.list_accounts()):
        raise SocialAgentError("credential_required", "请先在平台接入设置这个公众号账号。")
    return alias


def _local_draft(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    if path.parent != drafts_path().resolve() or path.suffix != ".json":
        raise SocialAgentError("invalid_draft", "请从工作台的草稿列表选择文件。")
    return path


def _json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n").encode("utf-8")


def _cli(args: list[str], timeout: int = 90) -> dict[str, Any]:
    command = [sys.executable, "-m", "social_agent.cli", *args, "--json"]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        return {"ok": False, "error": {"code": "timeout", "message": "操作超时，请稍后重试。"}}
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        detail = (result.stderr or result.stdout)[-500:]
        return {"ok": False, "error": {"code": "invalid_response", "message": detail or "CLI 未返回 JSON。"}}
    return payload


def _error_payload(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, SocialAgentError):
        return {"ok": False, "error": {"code": exc.code, "message": exc.message, "hint": exc.hint}}
    return {"ok": False, "error": {"code": "server_error", "message": str(exc)}}


def _draft_list() -> list[dict[str, Any]]:
    secure_mkdir(drafts_path())
    drafts: list[dict[str, Any]] = []
    for path in sorted(drafts_path().glob("*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            targets = data.get("targets", {})
            source = data.get("source", {})
            drafts.append(
                {
                    "path": str(path),
                    "id": data.get("id", path.stem),
                    "title": source.get("title") or next(iter(targets.values()), {}).get("title", path.stem),
                    "platforms": list(targets),
                    "created_at": data.get("created_at"),
                }
            )
        except (OSError, json.JSONDecodeError, AttributeError):
            continue
    return drafts


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "SocialAgentWeb/0.1"

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("[social-agent-web] " + (fmt % args) + "\n")

    def _send(self, status: int, payload: Any, content_type: str = "application/json; charset=utf-8") -> None:
        body = payload if isinstance(payload, bytes) else _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
        )
        self.end_headers()
        self.wfile.write(body)

    def _same_local_origin(self) -> bool:
        port = self.server.server_address[1]
        allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        host = self.headers.get("Host", "")
        if host not in allowed_hosts:
            return False
        origin = self.headers.get("Origin")
        if origin:
            parsed = urlparse(origin)
            if parsed.scheme != "http" or parsed.netloc != host:
                return False
        return True

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("无效的请求长度") from exc
        if not 0 <= length <= 1_000_000:
            raise ValueError("请求内容超过 1 MB 限制")
        raw = self.rfile.read(length)
        data = json.loads(raw.decode("utf-8")) if raw else {}
        if not isinstance(data, dict):
            raise ValueError("请求体必须是 JSON 对象")
        return data

    def do_GET(self) -> None:  # noqa: N802
        if not self._same_local_origin():
            self._send(HTTPStatus.FORBIDDEN, {"ok": False, "error": {"code": "invalid_origin", "message": "只允许本机工作台访问。"}})
            return
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/go/wechat-materials":
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Location", wechat_materials_link())
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                return
            if parsed.path == "/api/health":
                self._send(
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "data": {
                            "service": "social-agent-web",
                            "now": datetime.now(UTC).isoformat(timespec="seconds"),
                            "state_directory": str(app_home()),
                            "live_publish": False,
                        },
                    },
                )
                return
            if parsed.path == "/api/doctor":
                self._send(HTTPStatus.OK, _cli(["doctor"]))
                return
            if parsed.path == "/api/platforms":
                platforms = [
                    dict(item, connector_installed=False, connected=False, state="not_connected",
                         available=["跨平台草稿", "发布预览"] + [cap["label"] for cap in item.get("capabilities", [])],
                         planned=[], next_step=item["notes"])
                    for item in list_platforms() if item.get("url")
                ]
                for item in platforms:
                    item["creator_url"] = CREATOR_LINKS.get(item["id"], item["url"])
                next(item for item in platforms if item["id"] == "wechat_mp").update(
                    connector_installed=True, state="api_setup")
                next(item for item in platforms if item["id"] == "wechat_channels")["state"] = "handoff"
                xhs = next(item for item in platforms if item["id"] == "xiaohongshu")
                snapshot_available = XiaohongshuAdapter().probe()["status"]["snapshot_available"]
                xhs.update(connector_installed=True, state="snapshot_ready" if snapshot_available else "import_required")
                bili = next(item for item in platforms if item["id"] == "bilibili")
                bili["connector_installed"] = bool(shutil.which("bili"))
                probe = _cli(["accounts", "probe", "--platform", "bilibili"], timeout=90)
                bili["connected"] = bool(probe.get("data", {}).get("status", {}).get("logged_in"))
                bili["state"] = "connected" if bili["connected"] else "login_required"
                self._send(HTTPStatus.OK, {"ok": True, "data": platforms})
                return
            if parsed.path == "/api/accounts":
                self._send(HTTPStatus.OK, {"ok": True, "data": StateStore().list_accounts()})
                return
            if parsed.path == "/api/capabilities":
                query = parse_qs(parsed.query)
                result = capabilities(query.get("platform", [""])[0], query.get("account", [None])[0], StateStore())
                self._send(HTTPStatus.OK, {"ok": True, "data": result})
                return
            if parsed.path == "/api/accounts/probe":
                query = parse_qs(parsed.query)
                platform = query.get("platform", ["bilibili"])[0]
                if platform == "wechat_mp":
                    store = StateStore()
                    alias = _registered_account(query.get("account", [""])[0], store)
                    self._send(HTTPStatus.OK, {"ok": True, "data": probe_wechat_account(alias, store)})
                    return
                self._send(HTTPStatus.OK, _cli(["accounts", "probe", "--platform", platform], timeout=90))
                return
            if parsed.path == "/api/remote-drafts":
                operation_id = parse_qs(parsed.query).get("operation", [""])[0]
                self._send(HTTPStatus.OK, {"ok": True, "data": operation(StateStore(), operation_id)})
                return
            if parsed.path == "/api/bilibili/works":
                self._send(HTTPStatus.OK, {"ok": True, "data": get_adapter("bilibili").works()})
                return
            if parsed.path == "/api/sau/accounts":
                platform = parse_qs(parsed.query).get("platform", [""])[0]
                self._send(HTTPStatus.OK, {"ok": True, "data": sau.accounts(platform)})
                return
            if parsed.path == "/api/research/sources":
                self._send(HTTPStatus.OK, {"ok": True, "data": research_sources()})
                return
            if parsed.path == "/api/research":
                query = parse_qs(parsed.query)
                platform = query.get("platform", ["bilibili"])[0]
                limit = query.get("limit", ["10"])[0]
                self._send(HTTPStatus.OK, _cli(["research", "--platform", platform, "--limit", limit], timeout=90))
                return
            if parsed.path == "/api/metrics":
                query = parse_qs(parsed.query)
                platform = query.get("platform", ["bilibili"])[0]
                account = query.get("account", [None])[0]
                if platform == "xiaohongshu":
                    self._send(HTTPStatus.OK, {"ok": True, "data": XiaohongshuAdapter().metrics(account)})
                    return
                self._send(HTTPStatus.OK, _cli(["metrics", "--platform", platform], timeout=120))
                return
            if parsed.path == "/api/report":
                self._send(HTTPStatus.OK, _cli(["report", "--limit", "30"]))
                return
            if parsed.path == "/api/drafts":
                self._send(HTTPStatus.OK, {"ok": True, "data": _draft_list()})
                return
            self._serve_static(parsed.path)
        except (SocialAgentError, ValueError) as exc:
            self._send(HTTPStatus.BAD_REQUEST, _error_payload(exc))
        except Exception as exc:
            self._send(HTTPStatus.INTERNAL_SERVER_ERROR, _error_payload(exc))

    def do_POST(self) -> None:  # noqa: N802
        if not self._same_local_origin():
            self._send(HTTPStatus.FORBIDDEN, {"ok": False, "error": {"code": "invalid_origin", "message": "只允许本机工作台访问。"}})
            return
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/draft-media":
                self._save_local_media(parse_qs(parsed.query).get("kind", [""])[0])
                return
            if parsed.path == "/api/xiaohongshu/import-notes":
                self._import_xiaohongshu_notes()
                return
            if self.headers.get_content_type() != "application/json":
                raise SocialAgentError("invalid_content_type", "请求需使用 JSON。")
            body = self._read_json()
            if parsed.path == "/api/accounts/wechat-mp":
                store = StateStore()
                alias = validate_alias(str(body.get("account") or ""))
                save_credentials(alias, str(body.get("app_id") or "").strip(), str(body.get("secret") or "").strip())
                store.add_account("wechat_mp", alias)
                store.save_account_verification("wechat_mp", alias, None)
                self._send(HTTPStatus.OK, {"ok": True, "data": {"alias": alias}})
                return
            if parsed.path == "/api/remote-drafts":
                result = save_draft(_local_draft(str(body.get("draft_path", ""))),
                                    str(body.get("platform", "")), str(body.get("account", "")),
                                    StateStore(), DRAFT_WORKERS)
                self._send(HTTPStatus.ACCEPTED, {"ok": True, "data": result})
                return
            if parsed.path == "/api/sau/login":
                if self.headers.get("Origin") != f"http://{self.headers.get('Host')}":
                    raise SocialAgentError("invalid_origin", "请从工作台打开 SAU 扫码窗口。")
                result = sau.start_login(str(body.get("platform", "")), str(body.get("account", "")).strip())
                self._send(HTTPStatus.ACCEPTED, {"ok": True, "data": result})
                return
            if parsed.path == "/api/sau/video":
                if self.headers.get("Origin") != f"http://{self.headers.get('Host')}" or body.get("confirmed") is not True:
                    raise SocialAgentError("confirmation_required", "请从工作台确认这个平台操作。")
                result = submit_sau(_local_draft(str(body.get("draft_path", ""))),
                                    str(body.get("platform", "")), str(body.get("account", "")),
                                    str(body.get("mode", "")), StateStore(), SAU_WORKER,
                                    str(body.get("scheduled") or ""), str(body.get("expected_account") or "").strip())
                self._send(HTTPStatus.ACCEPTED, {"ok": True, "data": result})
                return
            if parsed.path == "/api/remote-drafts/verify":
                result = verify_draft(StateStore(), str(body.get("operation", "")), body.get("reference") or None)
                self._send(HTTPStatus.OK, {"ok": True, "data": result})
                return
            if parsed.path == "/api/remote-drafts/handoff":
                result = prepare_handoff(_local_draft(str(body.get("draft_path", ""))),
                                         str(body.get("platform", "")), str(body.get("account", "")), StateStore())
                self._send(HTTPStatus.OK, {"ok": True, "data": result})
                return
            if parsed.path == "/api/remote-drafts/receipt":
                result = record_handoff(StateStore(), str(body.get("operation", "")),
                                        str(body.get("account", "")), str(body.get("scope", "")),
                                        str(body.get("reference") or ""))
                self._send(HTTPStatus.OK, {"ok": True, "data": result})
                return
            if parsed.path == "/api/drafts":
                platforms = body.get("platforms")
                if not isinstance(platforms, list):
                    raise ValueError("platforms 必须是数组")
                path = create_draft(
                    str(body.get("title", "")),
                    str(body.get("body", "")),
                    [str(item) for item in platforms],
                    [str(item) for item in body.get("tags", [])],
                    [str(item) for item in body.get("media", [])],
                    cover=body.get("cover") or None,
                    ai_generated=body.get("ai_generated") is True,
                )
                self._send(HTTPStatus.OK, {"ok": True, "data": {"path": str(path), "drafts": _draft_list()}})
                return
            if parsed.path == "/api/publish-preview":
                draft_path = Path(str(body.get("draft_path", ""))).expanduser()
                platforms = body.get("platforms")
                selected = [str(item) for item in platforms] if isinstance(platforms, list) else None
                result = dry_run_publish(draft_path, selected, StateStore())
                self._send(HTTPStatus.OK, {"ok": True, "data": result})
                return
            self._send(HTTPStatus.NOT_FOUND, {"ok": False, "error": {"code": "not_found", "message": "接口不存在"}})
        except (ValueError, SocialAgentError) as exc:
            self._send(HTTPStatus.BAD_REQUEST, _error_payload(exc))
        except Exception as exc:
            self._send(HTTPStatus.INTERNAL_SERVER_ERROR, _error_payload(exc))

    def _save_local_media(self, kind: str) -> None:
        formats = {
            "video": ({"video/mp4": ".mp4", "video/quicktime": ".mov", "video/x-m4v": ".m4v"}, 512 * 1024 ** 2),
            "cover": ({"image/jpeg": ".jpg"}, 64 * 1024),
        }
        if kind not in formats:
            raise SocialAgentError("invalid_media", "请选择视频或 JPEG 封面。")
        extensions, limit = formats[kind]
        extension = extensions.get(self.headers.get_content_type())
        length = int(self.headers.get("Content-Length", "0"))
        if not extension or not 0 < length <= limit:
            raise SocialAgentError("invalid_media", "视频支持 MP4、MOV（最大 512 MiB），封面支持 JPEG（最大 64 KiB）。")
        directory = app_home() / "media"
        secure_mkdir(directory)
        fd, name = tempfile.mkstemp(suffix=extension, dir=directory)
        try:
            with os.fdopen(fd, "wb") as stream:
                remaining = length
                while remaining:
                    chunk = self.rfile.read(min(remaining, 1024 * 1024))
                    if not chunk:
                        raise SocialAgentError("incomplete_upload", "本地文件传输中断。")
                    stream.write(chunk)
                    remaining -= len(chunk)
        except BaseException:
            Path(name).unlink(missing_ok=True)
            raise
        self._send(HTTPStatus.CREATED, {"ok": True, "data": {"path": name}})

    def _import_xiaohongshu_notes(self) -> None:
        if self.headers.get_content_type() != REPORT_CONTENT_TYPE:
            raise SocialAgentError("invalid_content_type", "请选择 XLSX 笔记明细文件。")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise SocialAgentError("invalid_content_length", "无效的笔记明细文件长度。") from exc
        if not 0 < length <= MAX_REPORT_BYTES:
            raise SocialAgentError("invalid_content_length", "请选择 2 MB 以内的 XLSX 笔记明细文件。")
        account = parse_qs(self.headers.get("X-Social-Agent-Account", "")).get("account", [""])[0]
        snapshot = XiaohongshuAdapter().import_report(account, self.rfile.read(length))
        self._send(HTTPStatus.OK, {"ok": True, "data": snapshot})

    def _serve_static(self, request_path: str) -> None:
        relative = "index.html" if request_path in ("", "/") else request_path.lstrip("/")
        candidate = (WEB_ROOT / relative).resolve()
        if WEB_ROOT.resolve() not in candidate.parents and candidate != WEB_ROOT.resolve():
            self._send(HTTPStatus.FORBIDDEN, b"forbidden\n", "text/plain; charset=utf-8")
            return
        if not candidate.is_file():
            self._send(HTTPStatus.NOT_FOUND, b"not found\n", "text/plain; charset=utf-8")
            return
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self._send(HTTPStatus.OK, candidate.read_bytes(), f"{content_type}; charset=utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="启动 Social Agent 本地 Web 工作台")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8798)
    args = parser.parse_args(argv)
    if args.host not in {"127.0.0.1", "localhost"}:
        parser.error("为保护账号安全，Web 工作台只允许监听本机回环地址")
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"Social Agent Web: http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
