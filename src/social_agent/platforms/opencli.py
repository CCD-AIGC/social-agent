"""Public topic research through the locally installed OpenCLI."""

import json
import shutil
import subprocess
from urllib.parse import urlsplit

from ..errors import SocialAgentError
from ..paths import app_home

VERSION = "2.0.3"
PUBLIC_SOURCES = {
    "hackernews": ("Hacker News 热门", "top", "title", "score", 50),
    "github-trending": ("GitHub Trending", "repos", "repo", "starsSince", 25),
    "juejin": ("掘金热榜", "hot", "title", "hot_rank", 50),
}


def executable() -> list[str] | None:
    managed = app_home() / "tools/opencli/node_modules/@jackwener/opencli/dist/src/main.js"
    node = shutil.which("node")
    if node and managed.is_file():
        return [node, str(managed)]
    cli = shutil.which("opencli")
    return [cli] if cli else None


def research_sources() -> list[dict]:
    return [{"id": "bilibili", "name": "B 站热搜", "provider": "bili-cli", "max_limit": 50}] + [
        {"id": name, "name": label, "provider": "OpenCLI", "max_limit": limit}
        for name, (label, _, _, _, limit) in PUBLIC_SOURCES.items()
    ]


def public_url(value) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        url = urlsplit(value)
    except ValueError:
        return None
    return value if url.scheme in {"https", "http"} and url.hostname and not url.username else None


class OpenCLIResearch:
    def __init__(self, source: str):
        self.source = source

    def research(self, *, limit: int = 10) -> dict:
        _, action, title_key, score_key, maximum = PUBLIC_SOURCES[self.source]
        if not 1 <= limit <= maximum:
            raise SocialAgentError("invalid_limit", f"此调研源支持 1 至 {maximum} 条。")
        cli = executable()
        if not cli:
            raise SocialAgentError("dependency_missing", "未找到 OpenCLI。", "请参阅 MacBook Pro 试运行指南。")
        try:
            run = subprocess.run(
                [*cli, self.source, action, "--limit", str(limit), "-f", "json"],
                capture_output=True, text=True, timeout=24, check=False,
            )
        except subprocess.TimeoutExpired:
            raise SocialAgentError("upstream_timeout", "OpenCLI 调研请求超时。") from None
        except OSError:
            raise SocialAgentError("upstream_unavailable", "无法启动 OpenCLI。") from None
        try:
            payload = json.loads(run.stdout)
            items = payload.get("data") if isinstance(payload, dict) and payload.get("ok") is True else None
            if run.returncode != 0 or not isinstance(items, list):
                raise ValueError
        except ValueError:
            raise SocialAgentError("upstream_error", "OpenCLI 未返回可用的调研数据。") from None
        results = []
        for rank, row in enumerate(items[:limit], 1):
            title = row.get(title_key) if isinstance(row, dict) else None
            if not isinstance(title, str) or not title.strip():
                continue
            results.append({
                "rank": rank, "title": title, "heat": row.get(score_key), "url": public_url(row.get("url")),
            })
        return {"source": "OpenCLI", "platform": self.source, "items": results}
