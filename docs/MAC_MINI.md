# Mac mini 部署、升级、备份与恢复

目标环境：常开 macOS Apple Silicon 设备（建议 16 GB 以上内存、256 GB 以上 SSD，可无显示器运行）。核心服务只运行 Python CLI、SQLite 和排期进程；重型 AI 生成放在工作站或云端，生成结果以 JSON/媒体文件同步。

## 安装

```bash
mkdir -p ~/Projects
cd ~/Projects
git clone <你的 GitHub 私有或公开仓库地址> social-agent
cd social-agent
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync --extra dev
uv run social-agent doctor --json
uv run social-agent init
uv run social-agent-web --host 127.0.0.1 --port 8798
```

首次启用平台账号时，只在本机交互式终端完成登录或 OAuth；不要把 Cookie、二维码或 `client_secret.json` 放进仓库。生产配置建议设置 `SOCIAL_AGENT_HOME` 到独立磁盘目录并限制权限。

## 运行方式

Mac mini 默认不做外部发布。可用 `launchd` 或定时任务只运行：

```bash
uv run social-agent scheduler run-due --json
```

如需查看本地工作台，使用 `uv run social-agent-web --host 127.0.0.1 --port 8798`。无显示器环境下不需要启用浏览器，CLI 和排期仍可独立运行。

只有在人工确认、平台连接器完成并经过专门验收后，才考虑启用真实发布服务；不要把尚未验证的 `--execute` 接入无人值守任务。

## 升级

```bash
cd ~/Projects/social-agent
git fetch --all --prune
git pull --ff-only
uv sync --extra dev
uv run pytest
uv run social-agent doctor --json
```

升级前复制 `~/Library/Application Support/social-agent/`。升级后先执行只读调研和 dry-run，再恢复排期；若数据库 schema 改变，必须先提供迁移脚本和回滚说明。

## 备份

备份以下内容：

- `~/Projects/social-agent` 中的 Git 工作树和提交记录；
- `~/Library/Application Support/social-agent/config.yaml`；
- `state.sqlite3`、`logs/` 和 `drafts/`，注意日志可能含运营元数据；
- 平台专项工具自己的账号会话目录，单独加密保存，不提交仓库。

Keychain 凭证不要通过复制数据库备份。迁移到另一台 Mac 时重新授权，或使用 macOS 自带的受控钥匙串迁移流程。先备份新机器现有配置，确认版本和绝对路径，再恢复文件。

## 恢复

```bash
uv run social-agent doctor --json
uv run pytest
uv run social-agent report --json
uv run social-agent publish --draft examples/draft.json --dry-run --json
```

恢复后先确认 SQLite 完整性、草稿路径、平台状态和排期状态；不要因为任务停在 `running` 就自动重发未知提交结果。
