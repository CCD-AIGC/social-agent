# Social Agent

Social Agent is a local-first CLI and web workspace for multi-platform creator operations. It is designed to be called by Codex, Claude Code, OpenClaw, and other agents through stable JSON output.

The current release focuses on account safety and local data handling. Bilibili account overview and hot-search reads use the existing `bili` CLI session. Xiaohongshu metrics can be imported from an official creator-center XLSX export. Publishing remains a local dry-run on every platform; the project does not upload or publish posts.

[Read the Chinese documentation](README.zh-CN.md).

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

Open `http://127.0.0.1:8798` in a browser. The web server binds to localhost by default; keep it local when handling account data.

Use the CLI directly:

```bash
uv run social-agent platforms --json
uv run social-agent research --platform bilibili --limit 10 --json
uv run social-agent metrics --platform bilibili --json
```

Import an XLSX report exported from the Xiaohongshu creator center:

```bash
uv run social-agent xiaohongshu import-notes ./notes.xlsx --account 'creator-name' --json
uv run social-agent metrics --platform xiaohongshu --account 'creator-name' --json
```

All commands support machine-readable JSON with a stable `ok` / `error` envelope.

## Platform Status

| Platform | Available | Not available |
| --- | --- | --- |
| Bilibili | Read-only account overview and hot search through the installed `bili` CLI | Uploading, scheduling, comments, and other write actions |
| Xiaohongshu | Import published-note metrics from an official XLSX export | Live account checks and publishing |
| Douyin, Zhihu, YouTube | Draft previews | Account connectors and publishing |

`publish --dry-run` validates a draft, renders platform previews, and records a local operation. `publish --execute` is intentionally rejected. The scheduler only runs local dry-run previews. There is no MCP server yet.

## Privacy and Security

- Account aliases, imported note snapshots, and operation records stay in the local state directory (`~/Library/Application Support/social-agent` on macOS by default).
- Secrets entered through the credential commands use the operating system keychain. The project does not copy browser cookies or Bilibili CLI credentials.
- The repository excludes local configuration, databases, logs, exports, credentials, and browser test artifacts. Review `git status` before committing new files.
- The app does not send telemetry. Do not commit exported account reports, browser profiles, cookies, QR codes, OAuth secrets, or production logs.
- The web workspace is for local use. Do not bind it to a public interface while it contains account information.

## Development

```bash
uv run pytest
uv run python -m compileall -q src tests
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the adapter and safety boundaries, [docs/RESEARCH.md](docs/RESEARCH.md) for source-based project comparisons, and [docs/MAC_MINI.md](docs/MAC_MINI.md) for deployment and backup guidance.

## License

MIT. See [LICENSE](LICENSE).
