from concurrent.futures import Executor
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from .content import load_draft, preview_target
from .errors import SocialAgentError
from .platforms import get_adapter, list_platforms
from .platforms import sau
from .platforms.wechat_mp import Article, article_text_hash, prepare_article
from .storage import StateStore, json_text, utc_now

STALE_SECONDS = 240
HANDOFFS = {
    "xiaohongshu": "https://creator.xiaohongshu.com/new/note-manager",
    "wechat_mp": "https://mp.weixin.qq.com/",
    "wechat_channels": "https://channels.weixin.qq.com/",
}


def capabilities(platform: str, account: str | None, store: StateStore) -> dict:
    items = next((item for item in list_platforms() if item["id"] == platform), None)
    if items is None:
        raise SocialAgentError("unknown_platform", "找不到此平台。")
    registered = any(row["platform"] == platform and row["alias"] == account for row in store.list_accounts())
    return {**items, "account": account, "account_registered": registered,
            "last_verification": store.account_verification(platform, account) if account else None}


def probe_wechat_account(alias: str, store: StateStore) -> dict:
    alias = validate_alias(alias)
    try:
        session = get_adapter("wechat_mp").connect(alias)
        status = session.probe()
    except SocialAgentError as exc:
        store.save_account_verification("wechat_mp", alias, {"status": "failed", "error_code": exc.code})
        raise
    store.save_account_verification("wechat_mp", alias, {"status": "read_verified", "draft_count": status["draft_count"]})
    return {"platform": "wechat_mp", "source": "official_api", "account": alias,
            "account_id": session.account_id, "status": status}


def _target(draft_path: Path, platform: str):
    draft = load_draft(draft_path)
    target = draft["targets"].get(platform)
    if not isinstance(target, dict):
        raise SocialAgentError("target_missing", "本地草稿中没有这个平台版本。")
    return draft, target, preview_target(platform, target)


def validate_alias(alias: str) -> str:
    alias = alias.strip()
    if not alias or len(alias) > 100:
        raise SocialAgentError("invalid_account", "请填写目标账号名称，最多 100 字。")
    return alias


def operation(store: StateStore, operation_id: str) -> dict:
    row = store.draft_operation(operation_id)
    if row is None:
        raise SocialAgentError("operation_not_found", "找不到该草稿操作。")
    if row["status"] in {"queued", "running"}:
        timestamp = datetime.fromisoformat(row["finished_at"] or row["created_at"])
        wait = sau.TIMEOUT * 2 if row["request"].get("route") == "sau" else STALE_SECONDS
        if (datetime.now(UTC) - timestamp).total_seconds() > wait:
            state = "failed" if row["status"] == "queued" else "needs_verification"
            error = {"code": "interrupted", "message": "操作中断，请检查平台草稿或素材库。"}
            store.advance_draft(operation_id, row["status"], state, {**(row["result"] or {}), "error": error}, error["code"])
            row = store.draft_operation(operation_id)
    return row


def save_draft(draft_path: Path, platform: str, alias: str, store: StateStore,
               executor: Executor | None = None) -> dict:
    if platform != "wechat_mp":
        raise SocialAgentError("draft_unavailable", "该平台需要从工作台准备视频草稿交接。")
    alias = validate_alias(alias)
    draft, target, _ = _target(draft_path, platform)
    article = prepare_article(target)
    session = get_adapter(platform).connect(alias)
    request = {
        "draft_id": draft.get("id"), "alias": alias, "account_id": session.account_id,
        "content_type": "article", "route": "official_api", "title": article.title,
        "content_hash": article.content_hash,
    }
    key = [platform, session.account_id, "article", article.content_hash, sha256(article.cover).hexdigest()]
    fingerprint = sha256(json_text(key).encode()).hexdigest()
    row, start = store.reserve_draft(fingerprint, platform, request)
    if start:
        if executor is not None:
            executor.submit(_save_article, store, row["id"], session, article)
        else:
            _save_article(store, row["id"], session, article)
            row = operation(store, row["id"])
    return row if start else operation(store, row["id"])


def _check_article(session, request: dict, result: dict) -> None:
    article = session.read_article(result["reference"])
    observed = article_text_hash(str(article.get("title", "")), str(article.get("content", "")))
    if observed != request["content_hash"] or article.get("thumb_media_id") != result["cover_id"]:
        raise SocialAgentError("draft_mismatch", "平台草稿的标题、正文或封面与预览不一致。")


def _save_article(store: StateStore, operation_id: str, session, article: Article) -> None:
    if not store.advance_draft(operation_id, "queued", "running"):
        return
    row = operation(store, operation_id)
    result = {k: v for k, v in (row["result"] or {}).items() if k != "error"}
    try:
        session.probe()
        if not result.get("cover_id"):
            result["cover_id"] = session.upload_cover(article.cover)
            store.advance_draft(operation_id, "running", "running", result)
        result["reference"] = session.save_article(article, result["cover_id"])
        store.advance_draft(operation_id, "running", "needs_verification", result)
    except SocialAgentError as exc:
        _save_error(store, operation_id, "running", result, exc)
        return
    except Exception:
        exc = SocialAgentError("write_unconfirmed", "写入流程中断，请先检查公众号草稿箱和素材库。")
        _save_error(store, operation_id, "running", result, exc)
        return
    try:
        _check_article(session, row["request"], result)
    except SocialAgentError as exc:
        _save_error(store, operation_id, "needs_verification", result, exc)
        return
    store.advance_draft(operation_id, "needs_verification", "verified", {**result, "verified_at": utc_now()})


def _save_error(store: StateStore, operation_id: str, source: str, result: dict, exc: SocialAgentError) -> None:
    state = "needs_verification" if source == "needs_verification" or exc.code == "write_unconfirmed" else "failed"
    error = {"code": exc.code, "message": exc.message, "hint": exc.hint}
    store.advance_draft(operation_id, source, state, {**result, "error": error}, exc.code)


def verify_draft(store: StateStore, operation_id: str, reference: str | None = None) -> dict:
    row = operation(store, operation_id)
    if row["request"]["route"] != "official_api":
        raise SocialAgentError("manual_verification_required", "请重新打开平台草稿，再从工作台登记复查结果。")
    if row["status"] not in {"needs_verification", "verified"}:
        raise SocialAgentError("verification_unavailable", "此操作尚无可回读的草稿。")
    result = {k: v for k, v in (row["result"] or {}).items() if k != "error"}
    if reference is not None and (not isinstance(reference, str) or len(reference) > 256):
        raise SocialAgentError("invalid_receipt", "平台草稿编号无效。")
    if result.get("reference") and reference and reference != result["reference"]:
        raise SocialAgentError("draft_mismatch", "草稿编号与已记录的回执不同。")
    reference = result.get("reference") or reference
    if not reference or not result.get("cover_id"):
        raise SocialAgentError(
            "reference_required", "缺少可核验的草稿编号或封面回执。",
            "查看公众号草稿箱与素材库。如果已有稿件，保留现有内容并补查回执。",
        )
    result["reference"] = reference
    session = get_adapter(row["platform"]).connect(row["request"]["alias"])
    if session.account_id != row["request"]["account_id"]:
        raise SocialAgentError("account_mismatch", "当前公众号与原操作所用的 AppID 不一致。")
    try:
        _check_article(session, row["request"], result)
    except SocialAgentError as exc:
        persisted = row["result"] or {}
        _save_error(store, operation_id, "needs_verification", persisted, exc)
        if row["status"] == "verified" and exc.code in {"remote_not_found", "draft_mismatch"}:
            error = {"code": exc.code, "message": exc.message, "hint": exc.hint}
            store.advance_draft(operation_id, "verified", "needs_verification", {**persisted, "error": error}, exc.code)
        raise
    store.advance_draft(operation_id, row["status"], "verified", {**result, "verified_at": utc_now()})
    return operation(store, operation_id)


def _video_payload(draft_path: Path, platform: str) -> tuple[dict, dict, list[str]]:
    draft, target, preview = _target(draft_path, platform)
    videos = [Path(path) for path in preview["media"] if Path(path).suffix.lower() in {".mp4", ".mov", ".m4v"}]
    if len(videos) != 1:
        raise SocialAgentError("video_required", "请选择一个 MP4、MOV 或 M4V 视频。")
    body = target["body"]
    if target.get("ai_generated") and "AI 辅助" not in body:
        body += "\n\n本内容为 AI 辅助制作的原创动画。"
    files = videos + ([Path(preview["cover"])] if preview["cover"] else [])
    try:
        hashes = []
        for path in files:
            with path.open("rb") as stream:
                digest = sha256()
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
                hashes.append(digest.hexdigest())
    except OSError as exc:
        raise SocialAgentError("missing_media", "无法读取视频或封面。") from exc
    return draft, {"title": preview["title"], "body": body, "tags": preview["tags"],
                   "video": str(videos[0]), "cover": preview["cover"]}, hashes


def prepare_handoff(draft_path: Path, platform: str, alias: str, store: StateStore) -> dict:
    if platform not in HANDOFFS:
        raise SocialAgentError("draft_unavailable", "此平台没有视频草稿交接。")
    alias = validate_alias(alias)
    draft, video, hashes = _video_payload(draft_path, platform)
    key = [platform, alias, "video", video["title"], video["body"], video["tags"], hashes]
    fingerprint = sha256(json_text(key).encode()).hexdigest()
    request = {
        "draft_id": draft.get("id"), "alias": alias, "title": video["title"],
        "content_type": "video", "route": "creator_handoff", "creator_url": HANDOFFS[platform],
        "draft_path": str(draft_path.expanduser().resolve()),
    }
    row, _ = store.reserve_draft(fingerprint, platform, request, handoff=True)
    return {**row, "handoff": video}


def submit_sau(draft_path: Path, platform: str, alias: str, mode: str,
               store: StateStore, executor: Executor, scheduled: str | None = None,
               expected_account: str | None = None) -> dict:
    config = sau.accounts(platform)
    if mode != config["mode"] and (platform, mode) != ("xiaohongshu", "draft"):
        raise SocialAgentError("invalid_mode", "此平台当前未接入该操作。")
    if not config["installed"]:
        raise SocialAgentError("dependency_missing", "未找到已审核的本机 SAU。")
    if alias not in config["accounts"]:
        raise SocialAgentError("account_required", "该账号未在 SAU 的独立环境登录。")
    scheduled_at = sau.normalize_schedule(scheduled) if mode == "schedule" else None
    draft, video, hashes = _video_payload(draft_path, platform)
    if len(video["tags"]) > 10 and platform == "xiaohongshu":
        raise SocialAgentError("invalid_tags", "小红书视频最多填写 10 个话题。")
    args = sau.video_args(platform, alias, video, scheduled_at, expected_account, mode)
    key = ["sau", mode, platform, alias, video["title"], video["body"], video["tags"], hashes]
    fingerprint = sha256(json_text(key).encode()).hexdigest()
    request = {
        "draft_id": draft.get("id"), "alias": alias, "title": video["title"], "content_type": "video",
        "route": "sau", "mode": mode, "creator_url": HANDOFFS[platform], "scheduled_at": scheduled_at,
        "expected_account": expected_account,
    }
    row, start = store.reserve_draft(fingerprint, platform, request)
    if start:
        executor.submit(_submit_sau, store, row["id"], args)
    return row if start else operation(store, row["id"])


def _submit_sau(store: StateStore, operation_id: str, args: list[str]) -> None:
    if not store.advance_draft(operation_id, "queued", "running"):
        return
    try:
        result = sau.run_video(args)
        code = result["exit_code"]
    except SocialAgentError as exc:
        _save_error(store, operation_id, "running", {}, exc)
        return
    message = "SAU 流程已返回，请在目标账号核对稿件。"
    if code != 0:
        message = "SAU 返回错误，请在目标账号检查是否已产生稿件。"
    if result.get("receipt", {}).get("evidence") == "creator_draft_panel":
        message = "小红书草稿箱已出现这条视频，请复查草稿保存范围。"
    elif result.get("receipt"):
        message = "小红书已显示提交成功，请核对笔记列表中的实际排期。"
    store.advance_draft(operation_id, "running", "needs_verification",
                        {**result, "message": message}, "sau_failed" if code else None)


def record_handoff(store: StateStore, operation_id: str, account: str, scope: str, reference: str = "") -> dict:
    row = operation(store, operation_id)
    route = row["request"]["route"]
    if (row["status"], route) not in {("handoff_ready", "creator_handoff"), ("needs_verification", "sau")}:
        raise SocialAgentError("verification_unavailable", "此操作没有可登记的平台结果。")
    if validate_alias(account) != row["request"]["alias"]:
        raise SocialAgentError("account_mismatch", "复查账号和交接时选择的账号不同。")
    if (scope not in {"account", "browser"} or len(reference) > 160
            or route == "sau" and row["request"]["mode"] in {"publish", "schedule"} and (scope != "account" or not reference.strip())):
        raise SocialAgentError("invalid_receipt", "请选择草稿保存范围，编号最多 160 字。")
    store.advance_draft(operation_id, row["status"], "verified_manually", {
        "scope": scope, "reference": reference.strip() or None, "verified_at": utc_now(),
    })
    return operation(store, operation_id)
