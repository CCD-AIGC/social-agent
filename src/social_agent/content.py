import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import SocialAgentError
from .paths import drafts_path, secure_mkdir

SUPPORTED_PLATFORMS = ("xiaohongshu", "douyin", "zhihu", "youtube", "bilibili")


def create_draft(
    title: str,
    body: str,
    platforms: list[str],
    tags: list[str] | None = None,
    media: list[str] | None = None,
    output: Path | None = None,
) -> Path:
    if not title.strip() or not body.strip():
        raise SocialAgentError("invalid_draft", "标题和正文不能为空")
    if not platforms:
        raise SocialAgentError("invalid_draft", "至少指定一个目标平台")
    unknown = sorted(set(platforms) - set(SUPPORTED_PLATFORMS))
    if unknown:
        raise SocialAgentError("unknown_platform", f"不支持的平台: {', '.join(unknown)}")
    media_paths = [str(Path(item).expanduser().resolve()) for item in (media or [])]
    draft_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    draft: dict[str, Any] = {
        "schema_version": 1,
        "id": draft_id,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": {"title": title.strip(), "body": body.strip(), "tags": tags or [], "media": media_paths},
        "targets": {
            platform: {
                "title": title.strip(),
                "body": body.strip(),
                "tags": tags or [],
                "media": media_paths,
            }
            for platform in dict.fromkeys(platforms)
        },
    }
    target = output.expanduser().resolve() if output else drafts_path() / f"{draft_id}.json"
    secure_mkdir(target.parent)
    target.write_text(json.dumps(draft, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        target.chmod(0o600)
    except OSError:
        pass
    return target


def load_draft(path: Path) -> dict[str, Any]:
    target = path.expanduser().resolve()
    try:
        draft = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SocialAgentError("invalid_draft", f"无法读取草稿: {target}") from exc
    if not isinstance(draft, dict) or not isinstance(draft.get("targets"), dict):
        raise SocialAgentError("invalid_draft", "草稿必须包含 targets 映射")
    return draft


def preview_target(platform: str, target: dict[str, Any]) -> dict[str, Any]:
    title = str(target.get("title", "")).strip()
    body = str(target.get("body", "")).strip()
    if not title or not body:
        raise SocialAgentError("invalid_draft", f"{platform} 的标题和正文不能为空")
    media = [str(item) for item in target.get("media", [])]
    missing = [item for item in media if not Path(item).expanduser().is_file()]
    if missing:
        raise SocialAgentError("missing_media", f"{platform} 素材文件不存在: {missing[0]}")
    return {
        "platform": platform,
        "title": title,
        "body_preview": body[:240],
        "body_characters": len(body),
        "tags": target.get("tags", []),
        "media": media,
        "media_count": len(media),
        "live_publish": False,
    }
