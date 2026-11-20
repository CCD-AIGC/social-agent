import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .paths import app_home, database_path, logs_path, secure_mkdir


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


class StateStore:
    def __init__(self, path: Path | None = None):
        secure_mkdir(app_home())
        self.path = path or database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._initialize()
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS operations (
                    id TEXT PRIMARY KEY,
                    action TEXT NOT NULL,
                    platform TEXT,
                    status TEXT NOT NULL,
                    dry_run INTEGER NOT NULL,
                    request_json TEXT NOT NULL,
                    result_json TEXT,
                    error_code TEXT,
                    created_at TEXT NOT NULL,
                    finished_at TEXT
                );
                CREATE TABLE IF NOT EXISTS accounts (
                    platform TEXT NOT NULL,
                    alias TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (platform, alias)
                );
                CREATE TABLE IF NOT EXISTS note_snapshots (
                    platform TEXT NOT NULL,
                    account TEXT NOT NULL,
                    exported_at TEXT,
                    imported_at TEXT NOT NULL,
                    notes_json TEXT NOT NULL,
                    PRIMARY KEY (platform, account)
                );
                CREATE TABLE IF NOT EXISTS account_verifications (
                    platform TEXT NOT NULL,
                    alias TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    checked_at TEXT NOT NULL,
                    PRIMARY KEY (platform, alias)
                );
                CREATE TABLE IF NOT EXISTS remote_draft_keys (
                    fingerprint TEXT PRIMARY KEY,
                    operation_id TEXT NOT NULL UNIQUE REFERENCES operations(id)
                );
                CREATE TABLE IF NOT EXISTS scheduled_jobs (
                    id TEXT PRIMARY KEY,
                    draft_path TEXT NOT NULL,
                    platforms_json TEXT NOT NULL,
                    due_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    finished_at TEXT
                );
                """
            )

    def start_operation(
        self, action: str, platform: str | None, dry_run: bool, request: dict[str, Any]
    ) -> str:
        operation_id = uuid.uuid4().hex
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO operations VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, NULL)",
                (operation_id, action, platform, "running", int(dry_run), json_text(request), utc_now()),
            )
        return operation_id

    def finish_operation(
        self, operation_id: str, status: str, result: dict[str, Any], error_code: str | None = None
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE operations SET status=?, result_json=?, error_code=?, finished_at=? WHERE id=?",
                (status, json_text(result), error_code, utc_now(), operation_id),
            )
        secure_mkdir(logs_path())
        entry = {
            "operation_id": operation_id,
            "status": status,
            "finished_at": utc_now(),
        }
        logfile = logs_path() / "operations.jsonl"
        with logfile.open("a", encoding="utf-8") as stream:
            stream.write(json_text(entry) + "\n")
        try:
            logfile.chmod(0o600)
        except OSError:
            pass

    def list_operations(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, action, platform, status, dry_run, request_json, result_json, error_code, created_at, finished_at "
                "FROM operations ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._operation(row) for row in rows]

    def reserve_draft(self, fingerprint: str, platform: str, request: dict, *, handoff: bool = False) -> tuple[dict, bool]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT operations.* FROM operations JOIN remote_draft_keys
                ON remote_draft_keys.operation_id=operations.id WHERE fingerprint=?""", (fingerprint,),
            ).fetchone()
            if row and row["status"] != "failed":
                return self._operation(row), False
            operation_id = row["id"] if row else uuid.uuid4().hex
            status = "handoff_ready" if handoff else "queued"
            if row:
                conn.execute(
                    """UPDATE operations SET status=?, request_json=?, created_at=?,
                    finished_at=NULL, error_code=NULL WHERE id=?""",
                    (status, json_text(request), utc_now(), operation_id),
                )
            else:
                conn.execute(
                    """INSERT INTO operations (id, action, platform, status, dry_run, request_json, created_at)
                    VALUES (?, ?, ?, ?, 0, ?, ?)""",
                    (operation_id, "remote_draft", platform, status, json_text(request), utc_now()),
                )
                conn.execute("INSERT INTO remote_draft_keys VALUES (?, ?)", (fingerprint, operation_id))
            row = conn.execute("SELECT * FROM operations WHERE id=?", (operation_id,)).fetchone()
            return self._operation(row), True

    def draft_operation(self, operation_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM operations WHERE id=? AND action='remote_draft'", (operation_id,),
            ).fetchone()
        return self._operation(row) if row else None

    def advance_draft(self, operation_id: str, source: str, target: str, result: dict | None = None,
                      error_code: str | None = None) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """UPDATE operations SET status=?, result_json=COALESCE(?, result_json), error_code=?,
                finished_at=? WHERE id=? AND action='remote_draft' AND status=?""",
                (target, json_text(result) if result is not None else None, error_code, utc_now(),
                 operation_id, source),
            )
            return cursor.rowcount == 1

    @staticmethod
    def _operation(row: sqlite3.Row) -> dict:
        return {
            **dict(row),
            "dry_run": bool(row["dry_run"]),
            "request": json.loads(row["request_json"]),
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
        }

    def add_account(self, platform: str, alias: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO accounts VALUES (?, ?, ?)", (platform, alias, utc_now())
            )
        return cursor.rowcount > 0

    def list_accounts(self) -> list[dict[str, str]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT platform, alias, created_at FROM accounts ORDER BY platform, alias"
            ).fetchall()
        return [dict(row) for row in rows]

    def save_account_verification(self, platform: str, alias: str, result: dict | None) -> None:
        with self._connect() as conn:
            if result is None:
                conn.execute("DELETE FROM account_verifications WHERE platform=? AND alias=?", (platform, alias))
                return
            conn.execute(
                """INSERT INTO account_verifications VALUES (?, ?, ?, ?)
                ON CONFLICT(platform, alias) DO UPDATE SET result_json=excluded.result_json,
                checked_at=excluded.checked_at""", (platform, alias, json_text(result), utc_now()),
            )

    def account_verification(self, platform: str, alias: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT result_json, checked_at FROM account_verifications WHERE platform=? AND alias=?",
                (platform, alias),
            ).fetchone()
        return {**json.loads(row["result_json"]), "checked_at": row["checked_at"]} if row else None

    def save_note_snapshot(
        self, platform: str, account: str, exported_at: str | None, notes: list[dict]
    ) -> dict:
        imported_at = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO note_snapshots VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(platform, account) DO UPDATE SET
                    exported_at=excluded.exported_at,
                    imported_at=excluded.imported_at,
                    notes_json=excluded.notes_json
                """,
                (platform, account, exported_at, imported_at, json_text(notes)),
            )
        return {
            "account": account,
            "exported_at": exported_at,
            "imported_at": imported_at,
            "note_count": len(notes),
        }

    def note_snapshot(self, platform: str, account: str | None = None) -> dict | None:
        with self._connect() as conn:
            if account is None:
                row = conn.execute(
                    "SELECT * FROM note_snapshots WHERE platform=? ORDER BY imported_at DESC LIMIT 1",
                    (platform,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM note_snapshots WHERE platform=? AND account=?",
                    (platform, account),
                ).fetchone()
        if row is None:
            return None
        return {
            "account": row["account"],
            "exported_at": row["exported_at"],
            "imported_at": row["imported_at"],
            "notes": json.loads(row["notes_json"]),
        }

    def schedule(self, draft_path: str, platforms: list[str], due_at: str) -> str:
        job_id = uuid.uuid4().hex
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO scheduled_jobs VALUES (?, ?, ?, ?, 'queued', ?, NULL)",
                (job_id, draft_path, json_text(platforms), due_at, utc_now()),
            )
        return job_id

    def list_jobs(self, status: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM scheduled_jobs WHERE status=? ORDER BY due_at", (status,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM scheduled_jobs ORDER BY due_at").fetchall()
        return [
            {**dict(row), "platforms": json.loads(row["platforms_json"])} for row in rows
        ]

    def due_jobs(self, now: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM scheduled_jobs WHERE status='queued' AND due_at<=? ORDER BY due_at",
                (now,),
            ).fetchall()
        return [
            {**dict(row), "platforms": json.loads(row["platforms_json"])} for row in rows
        ]

    def finish_job(self, job_id: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE scheduled_jobs SET status=?, finished_at=? WHERE id=?",
                (status, utc_now(), job_id),
            )

    def counts(self) -> dict[str, Any]:
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM operations").fetchone()[0]
            by_status = conn.execute(
                "SELECT status, COUNT(*) AS count FROM operations GROUP BY status ORDER BY status"
            ).fetchall()
            jobs = conn.execute(
                "SELECT status, COUNT(*) AS count FROM scheduled_jobs GROUP BY status ORDER BY status"
            ).fetchall()
        return {
            "operation_count": total,
            "operations_by_status": {row["status"]: row["count"] for row in by_status},
            "jobs_by_status": {row["status"]: row["count"] for row in jobs},
        }
