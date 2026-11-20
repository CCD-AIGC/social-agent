import json
import shutil
import subprocess
from typing import Any

from ..errors import SocialAgentError


class BilibiliAdapter:
    id = "bilibili"

    def __init__(self, executable: str | None = None):
        self.executable = executable or shutil.which("bili")

    def _run_json(self, args: list[str], *, timeout: int = 45) -> dict[str, Any]:
        if not self.executable:
            raise SocialAgentError(
                "dependency_missing",
                "未找到本机 bili 命令，B 站适配器不可用。",
                "安装 kukemc/bili-cli 后运行 social-agent doctor 检查。",
            )
        try:
            result = subprocess.run(
                [self.executable, *args],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise SocialAgentError("upstream_timeout", "B 站热搜读取超时") from exc
        except OSError as exc:
            raise SocialAgentError("upstream_unavailable", "无法启动 bili 命令") from exc
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise SocialAgentError(
                "invalid_upstream_response", "bili 未返回有效 JSON", result.stderr[-300:]
            ) from exc
        if result.returncode != 0 or not payload.get("ok"):
            error = payload.get("error", {})
            raise SocialAgentError(
                error.get("code", "upstream_error"),
                error.get("message", "B 站热搜读取失败"),
                error.get("hint"),
            )
        data = payload.get("data", {})
        return data if isinstance(data, dict) else {"value": data}

    def auth_status(self) -> dict[str, Any]:
        """Read the existing bili-cli session without touching or exporting credentials."""
        return self._run_json(["auth", "status"])

    def profile(self) -> dict[str, Any]:
        return self._run_json(["me", "show"])

    def metrics(self) -> dict[str, Any]:
        return self._run_json(["data", "overview"], timeout=60)

    def works(self, *, limit: int = 10) -> list[dict[str, Any]]:
        result = self._run_json(["upload", "list", "--size", str(limit)])
        items = result.get("items")
        if not isinstance(items, list):
            raise SocialAgentError("invalid_upstream_response", "bili 未返回稿件列表。")
        fields = ("bvid", "title", "state", "state_desc", "dynamic", "ptime", "pubdate", "ctime", "dtime")
        return [{key: item[key] for key in fields if key in item} for item in items if isinstance(item, dict)]

    def research(self, *, limit: int = 10) -> dict[str, Any]:
        return self._run_json(["hot", "search", "--limit", str(limit)])
