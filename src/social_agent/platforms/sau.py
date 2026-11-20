"""Use the pinned social-auto-upload CLI with its own account storage."""

import json
import os
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from zoneinfo import ZoneInfo

from ..errors import SocialAgentError
from ..paths import app_home

COMMIT = "3847fff01f5434a8a32829833163cd6723cabc59"
ROUTES = {
    "wechat_channels": ("tencent", "draft"),
    "xiaohongshu": ("xiaohongshu", "schedule"),
}
ALIAS = re.compile(r"[\w-]{1,64}\Z")
TIMEOUT = 900
BEIJING = ZoneInfo("Asia/Shanghai")
_login_lock = Lock()
_login_process = None
_login_platform: str | None = None
_login_alias: str | None = None


def root() -> Path:
    return app_home() / "tools/social-auto-upload"


def executable() -> Path:
    return root() / ".venv/bin/sau"


def accounts(platform: str) -> dict:
    if platform not in ROUTES:
        raise SocialAgentError("unsupported_platform", "SAU 未接入此平台。")
    site, mode = ROUTES[platform]
    prefix = site + "_"
    aliases = []
    for file in sorted((root() / "cookies").glob(prefix + "*.json")):
        alias = file.stem.removeprefix(prefix)
        if ALIAS.fullmatch(alias) and file.is_file() and not file.is_symlink():
            aliases.append(alias)
    return {
        "mode": mode, "accounts": aliases, "installed": executable().is_file(),
        "default_schedule": default_schedule() if mode == "schedule" else None,
        "login": login_status(platform),
    }


def _environment() -> dict[str, str]:
    return {**os.environ, "PLAYWRIGHT_BROWSERS_PATH": str(root() / "browsers"), "TZ": BEIJING.key}


def login_status(platform: str) -> dict | None:
    with _login_lock:
        if _login_platform != platform or _login_process is None:
            return None
        code = _login_process.poll()
        return {"alias": _login_alias, "running": code is None, "exit_code": code}


def start_login(platform: str, alias: str) -> dict:
    global _login_process, _login_platform, _login_alias
    if platform not in ROUTES:
        raise SocialAgentError("unsupported_platform", "SAU 未接入此平台。")
    if not ALIAS.fullmatch(alias):
        raise SocialAgentError("invalid_account", "账号别名可使用文字、数字、下划线和短横线，最多 64 字。")
    if not executable().is_file():
        raise SocialAgentError("dependency_missing", "未找到本机 SAU。")
    with _login_lock:
        if _login_process is not None and _login_process.poll() is None:
            raise SocialAgentError("login_running", "已有扫码窗口，请先完成当前扫码。")
        try:
            _login_process = subprocess.Popen(
                [str(executable()), ROUTES[platform][0], "login", f"--account={alias}", "--headed"],
                cwd=root(), env=_environment(), stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
            )
        except OSError:
            raise SocialAgentError("dependency_missing", "无法启动 SAU 扫码窗口。") from None
        _login_platform = platform
        _login_alias = alias
    return {"alias": alias, "running": True, "exit_code": None}


def default_schedule() -> str:
    suggested = (datetime.now(BEIJING) + timedelta(days=6)).replace(hour=20, minute=0)
    return suggested.strftime("%Y-%m-%dT%H:%M")


def normalize_schedule(value: str | None) -> str:
    try:
        scheduled = datetime.strptime(value or "", "%Y-%m-%dT%H:%M").replace(tzinfo=BEIJING)
    except ValueError:
        raise SocialAgentError("invalid_schedule", "请选择北京时间的定时发送日期和时间。") from None
    if scheduled <= datetime.now(BEIJING) + timedelta(hours=2):
        raise SocialAgentError("invalid_schedule", "小红书定时发送需要晚于当前时间 2 小时。")
    return scheduled.isoformat(timespec="minutes")


def video_args(platform: str, alias: str, video: dict, scheduled_at: str | None = None,
               expected_account: str | None = None, mode: str | None = None) -> list[str]:
    site, default_mode = ROUTES[platform]
    mode = mode or default_mode
    args = [
        site, "upload-video", f"--account={alias}", f"--file={video['video']}",
        f"--title={video['title']}", f"--desc={video['body']}", f"--tags={','.join(video['tags'])}",
    ]
    if video["cover"]:
        args.append(f"--thumbnail={video['cover']}")
    if platform == "xiaohongshu":
        expected_account = (expected_account or "").strip()
        if not expected_account or len(expected_account) > 100:
            raise SocialAgentError("account_required", "请填写小红书创作后台显示的账号昵称。")
        args.extend(["--expected-account", expected_account])
    if mode == "draft":
        args.append("--draft")
    else:
        if not scheduled_at:
            raise SocialAgentError("invalid_schedule", "小红书定时任务缺少发布时间。")
        scheduled = datetime.fromisoformat(scheduled_at).astimezone(BEIJING)
        args.extend(["--schedule", scheduled.strftime("%Y-%m-%d %H:%M")])
    return args


def run_video(args: list[str]) -> dict:
    from .sau_xhs_schedule import PREFLIGHT, RECEIPT, UNCONFIRMED

    is_xhs = args[0] == "xiaohongshu"
    command = [str(executable())]
    if is_xhs:
        command = [str(executable().with_name("python")), str(Path(__file__).with_name("sau_xhs_schedule.py"))]
    try:
        run = subprocess.run(
            [*command, *args], cwd=root(), env=_environment(),
            capture_output=True, text=True, errors="replace", timeout=TIMEOUT, check=False,
        )
    except subprocess.TimeoutExpired:
        raise SocialAgentError("write_unconfirmed", "SAU 操作超时。请先检查平台状态。") from None
    except OSError:
        raise SocialAgentError("dependency_missing", "无法启动本机 SAU。") from None
    result = {"exit_code": run.returncode}
    if not is_xhs:
        return result
    for line in run.stdout.splitlines():
        if run.returncode == 4 and line.startswith(PREFLIGHT):
            raise SocialAgentError("sau_preflight", line.removeprefix(PREFLIGHT)[:140])
        if run.returncode != 0 and line.startswith(UNCONFIRMED):
            raise SocialAgentError("write_unconfirmed", line.removeprefix(UNCONFIRMED)[:140])
        if run.returncode == 0 and line.startswith(RECEIPT):
            try:
                receipt = json.loads(line.removeprefix(RECEIPT))
            except ValueError:
                continue
            if isinstance(receipt, dict) and receipt.get("evidence") in {"creator_success_page", "creator_draft_panel"}:
                result["receipt"] = receipt
    return result
