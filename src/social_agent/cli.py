import argparse
import getpass
import json
import os
import platform as platform_module
import sqlite3
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from . import __version__
from .config import load_config, write_default_config
from .content import create_draft
from .credentials import CredentialStore
from .errors import SocialAgentError
from .paths import app_home, config_path, database_path
from .platforms import get_adapter, list_platforms
from .platforms.xiaohongshu import MAX_REPORT_BYTES, XiaohongshuAdapter
from .publishing import dry_run_publish
from .scheduler import normalize_due_at, run_due_previews
from .storage import StateStore


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="social-agent", description="本地多平台自媒体运营 CLI")
    parser.add_argument("--version", action="version", version=f"social-agent {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="检查运行环境和只读适配器")
    sub.add_parser("init", help="创建默认 YAML 配置")
    sub.add_parser("platforms", help="列出插件平台及已实现能力")
    sub.add_parser("config", help="显示配置位置和非敏感配置")

    accounts = sub.add_parser("accounts", help="本地账号别名与凭证库管理")
    account_sub = accounts.add_subparsers(dest="accounts_command", required=True)
    account_sub.add_parser("list", help="列出本地登记的账号别名")
    account_add = account_sub.add_parser("add", help="登记账号别名，不会登录平台")
    account_add.add_argument("--platform", required=True)
    account_add.add_argument("--alias", required=True)
    account_probe = account_sub.add_parser("probe", help="读取平台现有登录状态，不导入凭证")
    account_probe.add_argument("--platform", required=True)
    cred = account_sub.add_parser("credential", help="系统 Keychain 中的凭证操作")
    cred_sub = cred.add_subparsers(dest="credential_command", required=True)
    cred_set = cred_sub.add_parser("set", help="交互式录入秘密到 Keychain")
    cred_set.add_argument("--platform", required=True)
    cred_set.add_argument("--alias", required=True)
    cred_set.add_argument("--key", default="session")
    cred_set.add_argument("--stdin", action="store_true", help="从标准输入读取一行秘密")
    for action in ("status", "remove"):
        item = cred_sub.add_parser(action)
        item.add_argument("--platform", required=True)
        item.add_argument("--alias", required=True)
        item.add_argument("--key", default="session")

    research = sub.add_parser("research", help="读取可用的平台公开趋势数据")
    research.add_argument("--platform", default="bilibili")
    research.add_argument("--limit", type=int, default=10)

    content = sub.add_parser("content", help="建立多平台内容草稿")
    content_sub = content.add_subparsers(dest="content_command", required=True)
    create = content_sub.add_parser("create", help="按同一素材创建各平台草稿版本")
    create.add_argument("--title", required=True)
    create.add_argument("--body", required=True)
    create.add_argument("--platform", action="append", required=True, dest="platforms")
    create.add_argument("--tag", action="append", default=[], dest="tags")
    create.add_argument("--media", action="append", default=[])
    create.add_argument("--output", type=Path)
    show = content_sub.add_parser("show", help="查看本地草稿")
    show.add_argument("draft", type=Path)

    publish = sub.add_parser("publish", help="检查并预览跨平台发布")
    publish.add_argument("--draft", type=Path, required=True)
    publish.add_argument("--platform", action="append", dest="platforms")
    mode = publish.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="仅本地预览（默认）")
    mode.add_argument("--execute", action="store_true", help="请求真实发布；首版会拒绝")

    metrics = sub.add_parser("metrics", help="查询账号或作品分析数据")
    metrics.add_argument("--platform")
    metrics.add_argument("--account")

    xiaohongshu = sub.add_parser("xiaohongshu", help="导入小红书创作服务平台的笔记明细")
    xiaohongshu_sub = xiaohongshu.add_subparsers(dest="xiaohongshu_command", required=True)
    import_notes = xiaohongshu_sub.add_parser("import-notes", help="导入本地官方 XLSX 报表")
    import_notes.add_argument("file", type=Path)
    import_notes.add_argument("--account", required=True, help="这份报表所属的账号名")

    report = sub.add_parser("report", help="汇总本地任务和调度记录")
    report.add_argument("--limit", type=int, default=20)

    scheduler = sub.add_parser("scheduler", help="本地排期队列；当前只执行 dry-run")
    scheduler_sub = scheduler.add_subparsers(dest="scheduler_command", required=True)
    schedule_add = scheduler_sub.add_parser("add", help="登记一个待预览的定时任务")
    schedule_add.add_argument("--draft", type=Path, required=True)
    schedule_add.add_argument("--platform", action="append", required=True, dest="platforms")
    schedule_add.add_argument("--at", required=True, help="ISO 8601 时间，必须带时区")
    schedule_sub = scheduler_sub.add_parser("list", help="查看排期任务")
    schedule_sub.add_argument("--status")
    scheduler_sub.add_parser("run-due", help="把到期任务转为本地发布预览，不会真实发布")
    return parser


def _emit(payload: dict[str, Any], json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return
    if payload.get("ok") is False:
        print(f"错误：{payload.get('error', {}).get('message', '操作失败')}", file=sys.stderr)
        hint = payload.get("error", {}).get("hint")
        if hint:
            print(f"提示：{hint}", file=sys.stderr)
        return
    for key in ("message", "path", "mode"):
        if payload.get(key):
            print(payload[key])
    data = payload.get("data")
    if data is not None:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    elif not any(payload.get(key) for key in ("message", "path", "mode")):
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _ok(data: Any = None, **fields: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": True}
    if data is not None:
        result["data"] = data
    result.update(fields)
    return result


def _doctor(store: StateStore) -> dict[str, Any]:
    try:
        yaml_version = version("PyYAML")
    except PackageNotFoundError:
        yaml_version = "missing"
    try:
        keyring_version = version("keyring")
    except PackageNotFoundError:
        keyring_version = "missing"
    credential_store = CredentialStore()
    bili_path = None
    try:
        adapter = get_adapter("bilibili")
        bili_path = adapter.executable
    except Exception:
        pass
    sqlite_ok = False
    with sqlite3.connect(store.path) as connection:
        sqlite_ok = connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    return _ok(
        {
            "version": __version__,
            "python": sys.version.split()[0],
            "architecture": platform_module.machine(),
            "platform": sys.platform,
            "yaml": yaml_version,
            "keyring": keyring_version,
            "keyring_backend": credential_store.backend_name(),
            "sqlite_integrity": sqlite_ok,
            "state_directory": str(app_home()),
            "config_exists": config_path().exists(),
            "database": str(store.path),
            "bili_executable": bili_path,
            "live_publish": False,
        }
    )


def _handle(args: argparse.Namespace, store: StateStore) -> dict[str, Any]:
    if args.command == "doctor":
        return _doctor(store)
    if args.command == "init":
        return _ok(path=str(write_default_config()), message="已创建默认配置；配置文件不包含账号凭证。")
    if args.command == "platforms":
        return _ok(list_platforms())
    if args.command == "config":
        return _ok({"path": str(config_path()), "config": load_config()})
    if args.command == "accounts":
        if args.accounts_command == "list":
            accounts = store.list_accounts()
            return _ok([dict(item, credential_status="未验证") for item in accounts])
        if args.accounts_command == "add":
            added = store.add_account(args.platform, args.alias)
            return _ok({"platform": args.platform, "alias": args.alias, "created": added, "logged_in": False})
        if args.accounts_command == "probe":
            if args.platform == "xiaohongshu":
                return _ok(XiaohongshuAdapter(store).probe())
            if args.platform != "bilibili":
                raise SocialAgentError(
                    "probe_unavailable",
                    f"{args.platform} 尚无现有登录态探测器。",
                    "可检查 B 站登录态或小红书本地快照状态。",
                )
            adapter = get_adapter("bilibili")
            status = adapter.auth_status()
            user = status.get("user") if status.get("logged_in") else None
            profile = None
            account_id = None
            if user:
                profile = {
                    **user,
                    "url": f"https://space.bilibili.com/{user['mid']}" if user.get("mid") else None,
                }
                account_id = str(user["mid"]) if user.get("mid") else None
            return _ok(
                {
                    "platform": "bilibili",
                    "source": "bili-cli",
                    "credential_imported": False,
                    "account_id": account_id,
                    "status": status,
                    "profile": profile,
                }
            )
        credentials = CredentialStore()
        if args.credential_command == "set":
            secret = sys.stdin.readline().rstrip("\r\n") if args.stdin else getpass.getpass("凭证内容（输入不回显）: ")
            if not args.stdin:
                confirm = getpass.getpass("再次输入确认: ")
                if secret != confirm:
                    raise SocialAgentError("credential_mismatch", "两次输入不一致")
            credentials.set(args.platform, args.alias, secret, args.key)
            store.add_account(args.platform, args.alias)
            return _ok({"platform": args.platform, "alias": args.alias, "stored_in": credentials.backend_name()})
        if args.credential_command == "status":
            return _ok(
                {
                    "platform": args.platform,
                    "alias": args.alias,
                    "key": args.key,
                    "present": credentials.get(args.platform, args.alias, args.key) is not None,
                    "backend": credentials.backend_name(),
                }
            )
        credentials.delete(args.platform, args.alias, args.key)
        return _ok({"platform": args.platform, "alias": args.alias, "deleted": True})
    if args.command == "research":
        if args.limit < 1 or args.limit > 50:
            raise SocialAgentError("invalid_limit", "limit 必须在 1 到 50 之间")
        try:
            adapter = get_adapter(args.platform)
        except KeyError as exc:
            raise SocialAgentError("research_unavailable", f"{args.platform} 暂无只读调研适配器") from exc
        research = getattr(adapter, "research", None)
        if not callable(research):
            raise SocialAgentError("research_unavailable", f"{args.platform} 暂无公开调研能力")
        operation_id = store.start_operation(
            "research", args.platform, True, {"kind": "hot_search", "limit": args.limit}
        )
        try:
            result = research(limit=args.limit)
        except SocialAgentError as exc:
            store.finish_operation(operation_id, "failed", {"message": exc.message}, exc.code)
            raise
        store.finish_operation(operation_id, "succeeded", {"item_count": len(result.get("items", []))})
        return _ok({"platform": args.platform, "operation_id": operation_id, "result": result})
    if args.command == "content":
        if args.content_command == "create":
            path = create_draft(args.title, args.body, args.platforms, args.tags, args.media, args.output)
            return _ok({"path": str(path), "platforms": args.platforms}, message="草稿已保存；当前为模板复制，没有调用生成模型。")
        try:
            data = json.loads(args.draft.expanduser().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SocialAgentError("invalid_draft", "无法读取草稿 JSON") from exc
        return _ok(data)
    if args.command == "publish":
        if args.execute:
            raise SocialAgentError(
                "live_publish_disabled",
                "首版未实现真实发布，--execute 已安全拒绝。",
                "只能运行 social-agent publish --draft <文件> --dry-run。",
            )
        result = dry_run_publish(args.draft, args.platforms, store)
        return _ok(result)
    if args.command == "xiaohongshu":
        try:
            with args.file.expanduser().open("rb") as stream:
                raw = stream.read(MAX_REPORT_BYTES + 1)
        except OSError as exc:
            raise SocialAgentError("report_unreadable", "无法打开指定的笔记明细文件。") from exc
        return _ok(XiaohongshuAdapter(store).import_report(args.account, raw))
    if args.command == "metrics":
        if args.platform == "xiaohongshu":
            return _ok(XiaohongshuAdapter(store).metrics(args.account))
        if args.platform == "bilibili":
            adapter = get_adapter("bilibili")
            operation_id = store.start_operation(
                "metrics", "bilibili", True, {"kind": "data_overview", "account": args.account}
            )
            try:
                result = adapter.metrics()
            except SocialAgentError as exc:
                store.finish_operation(operation_id, "failed", {"message": exc.message}, exc.code)
                raise
            store.finish_operation(operation_id, "succeeded", {"data_date": result.get("data_date")})
            return _ok(
                {
                    "platform": "bilibili",
                    "source": "bili-cli",
                    "credential_imported": False,
                    "operation_id": operation_id,
                    "result": result,
                }
            )
        return _ok(
            {
                "available": False,
                "platform": args.platform,
                "account": args.account,
                "reason": "平台作品数据连接器尚未实现；首版不会伪造平台指标。",
            }
        )
    if args.command == "report":
        return _ok({"local": store.counts(), "recent_operations": store.list_operations(args.limit)})
    if args.command == "scheduler":
        if args.scheduler_command == "add":
            due_at = normalize_due_at(args.at)
            job_id = store.schedule(str(args.draft.expanduser().resolve()), args.platforms, due_at)
            return _ok({"job_id": job_id, "due_at_utc": due_at, "status": "queued", "mode": "dry-run-only"})
        if args.scheduler_command == "list":
            return _ok(store.list_jobs(args.status))
        return _ok({"mode": "dry-run-only", "results": run_due_previews(store)})
    raise SocialAgentError("unknown_command", "未知命令")


def main(argv: list[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    json_mode = "--json" in values
    values = [item for item in values if item != "--json"]
    parser = _parser()
    try:
        args = parser.parse_args(values)
    except SystemExit as exc:
        return int(exc.code or 0)
    try:
        payload = _handle(args, StateStore())
    except SocialAgentError as exc:
        _emit({"ok": False, "error": {"code": exc.code, "message": exc.message, "hint": exc.hint}}, json_mode)
        return 2
    except ValueError as exc:
        _emit({"ok": False, "error": {"code": "invalid_input", "message": str(exc)}}, json_mode)
        return 2
    _emit(payload, json_mode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
