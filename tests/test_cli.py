import json
import os
import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from social_agent.cli import _handle, _parser, main
from social_agent.credentials import CredentialStore
from social_agent.platforms.bilibili import BilibiliAdapter
from social_agent.scheduler import normalize_due_at, run_due_previews
from social_agent.storage import StateStore


class MemoryKeyring:
    def __init__(self):
        self.values = {}

    def set_password(self, service, username, secret):
        self.values[(service, username)] = secret

    def get_password(self, service, username):
        return self.values.get((service, username))

    def delete_password(self, service, username):
        del self.values[(service, username)]


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.home = Path(self.tempdir.name)
        self.env = patch.dict(os.environ, {"SOCIAL_AGENT_HOME": str(self.home)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.stdout = patch("sys.stdout")
        self.stdout.start()
        self.addCleanup(self.stdout.stop)

    def test_publish_dry_run_logs_preview_without_live_side_effect(self):
        draft = self.home / "draft.json"
        draft.write_text(
            json.dumps(
                {
                    "id": "draft-1",
                    "targets": {
                        "xiaohongshu": {"title": "標題", "body": "正文", "tags": ["測試"], "media": []},
                        "douyin": {"title": "標題 2", "body": "正文 2", "tags": [], "media": []},
                    },
                }
            ),
            encoding="utf-8",
        )
        self.assertEqual(
            main(["publish", "--draft", str(draft), "--platform", "all", "--dry-run", "--json"]), 0
        )
        operations = StateStore().list_operations()
        self.assertEqual(len(operations), 2)
        self.assertTrue(all(item["dry_run"] for item in operations))
        self.assertTrue(all(item["status"] == "simulated" for item in operations))
        self.assertFalse(any("正文" in item["request_json"] for item in operations))

    def test_execute_is_rejected_before_any_publish_operation(self):
        draft = self.home / "draft.json"
        draft.write_text(json.dumps({"id": "d", "targets": {"bilibili": {"title": "t", "body": "b"}}}))
        self.assertEqual(main(["publish", "--draft", str(draft), "--execute", "--json"]), 2)
        self.assertEqual(StateStore().list_operations(), [])

    def test_bilibili_adapter_parses_bili_cli_json_without_shell(self):
        completed = type(
            "Result", (), {"returncode": 0, "stdout": '{"ok":true,"data":{"items":[{"keyword":"topic"}]}}', "stderr": ""}
        )()
        with patch("social_agent.platforms.bilibili.subprocess.run", return_value=completed) as run:
            result = BilibiliAdapter("/usr/local/bin/bili").research(limit=4)
        self.assertEqual(result["items"][0]["keyword"], "topic")
        self.assertEqual(run.call_args.args[0], ["/usr/local/bin/bili", "hot", "search", "--limit", "4"])
        self.assertFalse(run.call_args.kwargs.get("shell", False))

    def test_bilibili_existing_session_commands_are_read_only(self):
        responses = [
            '{"ok":true,"data":{"logged_in":true,"user":{"mid":1,"name":"test"}}}',
            '{"ok":true,"data":{"mid":1,"name":"test"}}',
            '{"ok":true,"data":{"data_date":"2026-11-16","totals":{"plays":1}}}',
        ]

        def run(*args, **kwargs):
            return type("Result", (), {"returncode": 0, "stdout": responses.pop(0), "stderr": ""})()

        with patch("social_agent.platforms.bilibili.subprocess.run", side_effect=run) as mocked:
            adapter = BilibiliAdapter("/usr/local/bin/bili")
            self.assertTrue(adapter.auth_status()["logged_in"])
            self.assertEqual(adapter.profile()["name"], "test")
            self.assertEqual(adapter.metrics()["data_date"], "2026-11-16")
        self.assertEqual(mocked.call_count, 3)
        self.assertTrue(all(not call.kwargs.get("shell", False) for call in mocked.call_args_list))

    def test_bilibili_probe_uses_uid_from_auth_status_as_stable_identity(self):
        completed = type(
            "Result",
            (),
            {
                "returncode": 0,
                "stdout": '{"ok":true,"data":{"logged_in":true,"user":{"mid":123456789,"name":"Sample Creator"}}}',
                "stderr": "",
            },
        )()
        with patch("social_agent.platforms.bilibili.subprocess.run", return_value=completed) as run:
            args = _parser().parse_args(["accounts", "probe", "--platform", "bilibili"])
            result = _handle(args, StateStore())
        data = result["data"]
        self.assertEqual(data["account_id"], "123456789")
        self.assertEqual(data["profile"]["name"], "Sample Creator")
        self.assertEqual(data["profile"]["url"], "https://space.bilibili.com/123456789")
        self.assertEqual(run.call_count, 1)
        command = run.call_args.args[0]
        self.assertEqual(Path(command[0]).name, "bili")
        self.assertEqual(command[1:], ["auth", "status"])

    def test_keychain_credentials_are_not_written_to_sqlite(self):
        fake = MemoryKeyring()
        credentials = CredentialStore(backend=fake)
        credentials.set("bilibili", "main", "do-not-log-this")
        self.assertEqual(credentials.get("bilibili", "main"), "do-not-log-this")
        StateStore()
        db = sqlite3.connect(self.home / "state.sqlite3")
        self.assertEqual(db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0], 0)
        self.assertNotIn("do-not-log-this", (self.home / "state.sqlite3").read_bytes().decode("latin1", errors="ignore"))

    def test_scheduler_only_runs_a_local_preview(self):
        draft = self.home / "draft.json"
        draft.write_text(json.dumps({"id": "scheduled", "targets": {"youtube": {"title": "t", "body": "b", "media": []}}}))
        store = StateStore()
        due = datetime.now(UTC) - timedelta(minutes=1)
        job_id = store.schedule(str(draft), ["youtube"], due.isoformat(timespec="seconds"))
        result = run_due_previews(store, datetime.now(UTC))
        self.assertEqual(result[0]["job_id"], job_id)
        self.assertEqual(store.list_jobs()[0]["status"], "simulated")
        self.assertEqual(store.list_operations()[0]["status"], "simulated")

    def test_schedule_time_requires_timezone(self):
        with self.assertRaises(ValueError):
            normalize_due_at("2026-12-01T10:00:00")


if __name__ == "__main__":
    unittest.main()
