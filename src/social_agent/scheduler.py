from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .publishing import dry_run_publish
from .storage import StateStore


def normalize_due_at(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("时间必须是 ISO 8601 格式，并包含时区，例如 2026-12-01T10:00:00+08:00") from exc
    if parsed.tzinfo is None:
        raise ValueError("时间必须包含时区，例如 +08:00 或 Z")
    return parsed.astimezone(UTC).isoformat(timespec="seconds")


def run_due_previews(store: StateStore, now: datetime | None = None) -> list[dict[str, Any]]:
    current = (now or datetime.now(UTC)).astimezone(UTC).isoformat(timespec="seconds")
    results = []
    for job in store.due_jobs(current):
        result = dry_run_publish(Path(job["draft_path"]), job["platforms"], store)
        store.finish_job(job["id"], "simulated")
        results.append({"job_id": job["id"], "result": result})
    return results
