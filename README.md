# Social Agent

Social Agent is a local-first CLI and web workspace for multi-platform creator operations. It is designed for Codex, Claude Code, OpenClaw, and other agents that consume stable JSON output.

The current release keeps account data local while adding guarded platform workflows: Bilibili read-only data through `bili`, Xiaohongshu XLSX metrics import plus browser handoff and SAU scheduling, WeChat Official Account article drafts through the official API, and WeChat Channels video-draft handoff or SAU draft mode. OpenCLI can provide public topic research. Live publishing remains gated and every remote write has idempotency, readback or manual-verification requirements.

[Read the Chinese documentation](README.zh-CN.md), including the [MacBook Pro trial guide](docs/MACBOOK_TRIAL.md).

## Quick Start

Requirements: macOS or Linux, Python 3.10+, and [`uv`](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/CCD-AIGC/social-agent.git
cd social-agent
uv sync --extra dev
uv run social-agent doctor --json
uv run social-agent init
uv run social-agent-web --host 127.0.0.1 --port 8798
```

Open `http://127.0.0.1:8798` in a browser. The server binds to localhost and keeps account data on the machine.

Useful commands:

```bash
uv run social-agent platforms --json
uv run social-agent capabilities --platform wechat_mp --json
uv run social-agent research --platform hackernews --limit 10 --json
uv run social-agent metrics --platform bilibili --json
uv run social-agent xiaohongshu import-notes ./notes.xlsx --account 'creator-name' --json
```

All commands support machine-readable JSON with a stable `ok` / `error` envelope.

## Platform Status

| Platform | Available | Guardrails or limits |
| --- | --- | --- |
| Bilibili | Account overview, hot search, and work list through the installed `bili` CLI | Writes use the existing CLI boundary and remain separately verified |
| Xiaohongshu | Official XLSX metrics, browser handoff, and SAU scheduled-video route | Account nickname preflight, future-time check, idempotency, and creator-panel readback |
| WeChat Official Account | Official API credential probe, article draft save, cover upload, and draft readback | AppID/AppSecret stay in the OS keychain; API access depends on the account allowlist |
| WeChat Channels | Browser handoff and SAU video-draft route | The logged-in creator and resulting draft must be checked in the official console |
| Hacker News, GitHub Trending, Juejin | Public topic research through OpenCLI | Read-only public sources with bounded result counts |
| Douyin, Zhihu, YouTube | Local draft previews | No account connector or publishing route in this release |

`publish --dry-run` validates a draft and records a local operation. `publish --execute` is intentionally rejected. Remote draft and scheduling routes are explicit commands, idempotent, and return `needs_verification` when the platform result is ambiguous.

## Privacy and Security

- Account aliases, imported metrics, drafts, and operation records stay under the local application data directory (`~/Library/Application Support/social-agent` on macOS by default).
- Secrets entered through credential commands use the operating system keychain. The project does not copy browser cookies or Bilibili CLI credentials.
- The repository excludes local configuration, databases, logs, exports, credentials, browser test artifacts, and generated media. Review `git status` before committing.
- The web workspace binds to localhost and does not send telemetry. Do not commit exported reports, browser profiles, cookies, QR codes, OAuth secrets, or production logs.

## Development

```bash
uv run pytest
uv run python -m compileall -q src tests
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for safety boundaries, [docs/MACBOOK_TRIAL.md](docs/MACBOOK_TRIAL.md) for the local trial workflow, [docs/RESEARCH.md](docs/RESEARCH.md) for source-based comparisons, and [docs/MAC_MINI.md](docs/MAC_MINI.md) for deployment guidance.

## License

MIT. See [LICENSE](LICENSE).
