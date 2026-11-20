# Social Agent

English documentation: [README.md](README.md).

Social Agent 是一套本地优先的多平台自媒体运营 CLI，面向 Codex、Claude Code、OpenClaw 等可以调用外部命令并消费 JSON 的 Agent。首版把账号安全、预览、模拟发布和本地台账放在核心路径上，真实发布连接器按平台逐个接入。

项目同时提供一个本地 Web 工作台，用浏览器查看账号状态、B 站概览、热搜、内容草稿、发布预览和操作记录。它只监听 `127.0.0.1`，不会把账号数据暴露到局域网。

B 站通过本机 `bili` CLI 读取账号概览和热搜。小红书通过创作服务平台导出的报表读取已发布笔记和指标。通用发布仍为本地预览。微信公众号图文支持通过官方 API 保存草稿并回读，小红书和微信视频号可准备视频交接，并分别提供 SAU 定时发表和保存草稿入口。选题调研可通过 OpenCLI 查询公开来源。使用流程见 [MacBook Pro 试运行指南](docs/MACBOOK_TRIAL.md)。

## 快速开始

```bash
cd ~/Projects/social-agent
uv sync --extra dev
uv run social-agent doctor --json
uv run social-agent init
uv run social-agent platforms --json
uv run social-agent research --platform bilibili --limit 10 --json

# 启动本地 Web 工作台
uv run social-agent-web --host 127.0.0.1 --port 8798
# 浏览器打开 http://127.0.0.1:8798
```

创建一份跨平台草稿并预览：

```bash
uv run social-agent content create \
  --title "一份选题，多个平台版本" \
  --body "正文先经过事实核验、素材授权检查和平台适配。" \
  --platform xiaohongshu \
  --platform douyin \
  --platform zhihu \
  --platform youtube \
  --platform bilibili \
  --tag 内容运营 \
  --tag AI

uv run social-agent publish \
  --draft "$HOME/Library/Application Support/social-agent/drafts/<文件名>.json" \
  --dry-run --json
```

所有命令都可以追加 `--json`。JSON 输出使用 `{"ok": true, "data": ...}` 或 `{"ok": false, "error": {"code", "message", "hint"}}`，便于 Agent 判断成功、失败和下一步。

## 命令

| 命令 | 首版行为 |
| --- | --- |
| `doctor` | 检查 Python、arm64、依赖、SQLite、Keychain 和 B 站只读工具 |
| `init` | 创建不含凭证的 YAML 配置 |
| `platforms` | 列出内置平台和插件平台 |
| `accounts` | 登记账号别名；凭证写入系统 Keychain；`accounts probe --platform bilibili` 复用现有 `bili-cli` 登录态 |
| `research` | B 站热搜只读调研；其他平台返回不可用，不伪造数据 |
| `content create/show` | 创建和查看多平台草稿 |
| `publish --dry-run` | 校验素材、生成目标平台预览、写入 SQLite 台账 |
| `publish --execute` | 首版安全拒绝，待人工授权和平台连接器完成后再开放 |
| `metrics` | 查看 B 站账号概览或小红书已导入的笔记数据 |
| `drafts` | 保存和回读公众号图文草稿，生成视频交接并登记复查结果 |
| `capabilities` | 查看能力、调用方式和账号授权检查结果 |
| `xiaohongshu import-notes` | 将官方 XLSX 笔记明细导入本地快照 |
| `report` | 汇总本地操作、排期和状态 |
| `scheduler` | 登记和执行本地 dry-run 排期 |

可选的 macOS 启动器脚本位于 `launchers/social-agent.applescript`，默认从 `~/Projects/social-agent` 启动本地工作台。

## 凭证安全

账号别名和操作记录保存在 `~/Library/Application Support/social-agent/state.sqlite3`，文件权限为 `0600`。秘密通过 Python `keyring` 写入 macOS Keychain，不写入 YAML、SQLite、日志或 Git。配置示例只包含能力开关和时区，不包含 Cookie、Token、OAuth secret 或代理密码。

不要把浏览器 Cookie、二维码、OAuth client secret、导出的账号目录或生产日志提交到 GitHub。真实发布连接器必须经过预览、模拟运行、人工确认、幂等键、速率限制和失败分类后才能进入生产。

### 复用已有 bili-cli 登录态

Social Agent 不读取或复制 `bili-cli` 的 Cookie 文件，也不会触发重新扫码。它通过 PATH 中的 `bili` 子进程调用只读命令，继承现有 `BILI_CLI_HOME` / `BILI_CLI_STATE_DIR` 环境变量：

```bash
uv run social-agent accounts probe --platform bilibili --json
uv run social-agent metrics --platform bilibili --json
```

如果没有设置环境变量，`bili-cli` 会使用自己的默认状态目录。`social-agent accounts add` 和 Keychain 凭证是另一套账号登记机制，不会覆盖或迁移 `bili-cli` 登录态。

### 导入小红书已发布笔记

在[小红书创作服务平台的内容分析页](https://creator.xiaohongshu.com/statistics/data-analysis)选择日期，点击「导出数据」。打开本地工作台的「平台接入 → 小红书 → 查看笔记数据」，填写报表所属账号并导入下载的 XLSX。也可以运行：

```bash
uv run social-agent xiaohongshu import-notes ./笔记列表明细表.xlsx --account '账号名' --json
uv run social-agent accounts probe --platform xiaohongshu --json
uv run social-agent metrics --platform xiaohongshu --account '账号名' --json
```

快照覆盖该次报表所选日期和筛选范围，每个账号保留最近一次导入。省略 `--account` 时查看最近导入的账号。官方内容分析页最多可查询近半年的已发布笔记，实际数据以导出结果为准。刷新时重新导出和导入。小红书的 `accounts probe` 返回快照状态，`logged_in` 为 `null`。账号名、笔记和指标保存在本机 SQLite，Chrome 负责登录。

## 插件规范

第三方适配器通过 Python entry point 注册：

```toml
[project.entry-points."social_agent.platforms"]
my_platform = "my_package.adapter:Adapter"
```

适配器至少提供 `id` 和 `research(limit=...)`。发布适配器应单独实现，并由核心发布服务统一负责 dry-run、确认、台账和错误边界。单个平台连接器失败不能阻塞其他平台的草稿生成或预览。

## 当前边界

- 尚未实现小红书、抖音、知乎、YouTube、B 站的真实发布、评论发送或 MCP Server；B 站账号状态、资料和概览读取已通过已有 `bili-cli` 登录态接入。
- `content create` 是模板复制和结构化草稿，不调用 LLM，也不声称完成选题、文案或封面生成。
- `scheduler run-due` 只执行本地预览，不访问平台。
- B 站热搜验证依赖本机已经安装的 `bili` 命令；适配器通过 argv 调用，不使用 shell 拼接。

## 测试

```bash
uv run pytest
uv run python -m compileall -q src tests
```

首版测试覆盖：dry-run 台账、真实执行拒绝、B 站 JSON 适配器、Keychain 不落 SQLite、定时预览和带时区校验。
