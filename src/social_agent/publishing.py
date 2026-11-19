from pathlib import Path
from typing import Any

from .content import load_draft, preview_target
from .errors import SocialAgentError
from .storage import StateStore


def dry_run_publish(
    draft_path: Path, platforms: list[str] | None, store: StateStore
) -> dict[str, Any]:
    draft = load_draft(draft_path)
    targets: dict[str, dict[str, Any]] = draft["targets"]
    selected = platforms or list(targets)
    if selected == ["all"]:
        selected = list(targets)
    missing = [platform for platform in selected if platform not in targets]
    if missing:
        raise SocialAgentError(
            "target_missing", f"草稿未包含平台版本: {', '.join(missing)}", "先运行 social-agent content create。"
        )
    previews = [preview_target(platform, targets[platform]) for platform in selected]
    operation_ids = []
    for preview in previews:
        operation_id = store.start_operation(
            action="publish_preview",
            platform=preview["platform"],
            dry_run=True,
            request={
                "draft_id": draft.get("id"),
                "draft_path": str(draft_path.expanduser().resolve()),
                "title_characters": len(preview["title"]),
                "body_characters": preview["body_characters"],
                "media_count": preview["media_count"],
            },
        )
        store.finish_operation(operation_id, "simulated", {"live_publish": False})
        operation_ids.append(operation_id)
    return {
        "mode": "dry-run",
        "live_publish": False,
        "draft_id": draft.get("id"),
        "operations": operation_ids,
        "targets": previews,
        "message": "仅完成本地格式预览和任务记录，没有访问或发布到目标平台。",
    }
