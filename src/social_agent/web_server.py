"""Local-only web dashboard for the Social Agent CLI."""

from __future__ import annotations

import argparse
import json
import mimetypes
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .content import create_draft
from .errors import SocialAgentError
from .paths import app_home, drafts_path, secure_mkdir
from .platforms.xiaohongshu import (
    CREATOR_REPORT_URL,
    MAX_REPORT_BYTES,
    REPORT_CONTENT_TYPE,
    XiaohongshuAdapter,
)
from .publishing import dry_run_publish
from .storage import StateStore

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = PROJECT_ROOT / "web"

PLATFORM_CATALOG = [
    {
        "id": "xiaohongshu", "name": "小红书", "mark": "红", "url": CREATOR_REPORT_URL,
        "auth": "创作服务平台官方导出 · 本地读取",
        "available": ["已发布笔记", "作品基础指标", "跨平台草稿", "发布 dry-run 预览"],
        "planned": ["实时登录检查", "人工确认发布"],
        "next_step": "在小红书「内容分析」选择日期并导出数据，再将 XLSX 导入本机工作台。",
    },
    {"id": "douyin", "name": "抖音", "mark": "抖", "url": "https://creator.douyin.com/", "auth": "创作者服务中心登录；首版尚无账号读取连接器", "available": ["跨平台草稿", "发布 dry-run 预览"], "planned": ["账号状态", "作品/评论读取", "指标分析", "人工确认发布"], "next_step": "需要接入并验证专用连接器；平台 API 权限、浏览器会话和内容发布权限需分别核实。"},
    {"id": "zhihu", "name": "知乎", "mark": "知", "url": "https://www.zhihu.com/creator", "auth": "知乎创作中心登录；首版尚无账号读取连接器", "available": ["跨平台草稿", "发布 dry-run 预览"], "planned": ["热榜/搜索", "回答与文章读取", "账号指标", "人工确认发布"], "next_step": "需要确定官方授权或审查过的专用 CLI；不会把 Cookie 写入项目配置。"},
    {"id": "youtube", "name": "YouTube", "mark": "YT", "url": "https://studio.youtube.com/", "auth": "官方 Google OAuth；需要创建 OAuth 客户端并由用户授权", "available": ["跨平台草稿", "发布 dry-run 预览"], "planned": ["频道/视频读取", "评论管理", "Analytics", "人工确认发布"], "next_step": "需要 Google Cloud 项目、YouTube Data/Analytics API、OAuth 桌面客户端和配额/审核设置。"},
    {"id": "bilibili", "name": "B 站", "mark": "B", "url": "https://space.bilibili.com/", "auth": "复用本机 bili-cli 登录态", "available": ["热搜调研", "账号资料", "账号概览", "跨平台草稿", "发布 dry-run 预览"], "planned": ["作品/评论读取", "人工确认投稿"], "next_step": "已连接。只读调用 bili-cli；发布功能仍关闭。"},
]


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
        if length > 1_000_000:
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
                platforms = [dict(item, connector_installed=False, connected=False, state="not_connected") for item in PLATFORM_CATALOG]
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
            if parsed.path == "/api/accounts/probe":
                platform = parse_qs(parsed.query).get("platform", ["bilibili"])[0]
                self._send(HTTPStatus.OK, _cli(["accounts", "probe", "--platform", platform], timeout=90))
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
        except Exception as exc:
            self._send(HTTPStatus.INTERNAL_SERVER_ERROR, _error_payload(exc))

    def do_POST(self) -> None:  # noqa: N802
        if not self._same_local_origin():
            self._send(HTTPStatus.FORBIDDEN, {"ok": False, "error": {"code": "invalid_origin", "message": "只允许本机工作台访问。"}})
            return
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/xiaohongshu/import-notes":
                self._import_xiaohongshu_notes()
                return
            body = self._read_json()
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
