# 技术架构与路线

```text
Codex / Claude Code / OpenClaw
              │ shell + JSON
        social-agent CLI
              │
  ┌───────────┼───────────┐
  │           │           │
Research   Content     Publisher
  │           │           │
platform adapters   draft schema → preflight → dry-run/live gate
              │           │
          SQLite ledger  Keychain
              │
          Scheduler / Report
```

## 模块边界

Research 只读取公开趋势、关键词、作品元数据和可授权的评论数据；每个连接器独立超时、错误码和缓存。首版 B 站热搜通过已安装 `bili` 命令验证，后续可加入 Agent-Reach、omnireach 和 social-media-toolkit。

Content 以一份 source 素材生成平台版本。首版先复制结构并保存 JSON，未来再接 Codex/Claude/OpenAI 生成文案、脚本、封面和字幕。生成结果必须保留 source、模型、提示摘要、人工修改和素材来源。

Publisher 接收草稿，不允许连接器自行绕过核心闸门。流程固定为：读取草稿 → 校验素材 → 平台差异检查 → 风控检查 → dry-run 预览 → 人工确认 → 幂等发布 → 回写结果。首版只到 dry-run；`--execute` 明确拒绝。

Engagement 未来先做评论只读和回复草稿，发送必须单独确认、限额和台账。不得加入批量骚扰、刷互动、绕过验证码或绕过平台安全措施的功能。

Analytics 只保存原始快照和采集时间，计算指标与平台 API 版本分离，避免把估算值当平台真实值。首版 `metrics` 返回未实现。

Scheduler 使用 SQLite 队列，任务状态采用 `queued → running → simulated/succeeded/failed`；重试只针对明确的网络瞬态错误，不能对登录失效、风控和未知提交结果盲目重发。

## 安全设计

- 秘密进入系统 Keychain；配置和 Git 只保存平台能力、非敏感参数。
- 账号按平台和别名隔离；浏览器 Cookie 由专项工具自己管理，不复制进本项目日志。
- 发布日志只记录操作 ID、平台、参数摘要和状态，不记录正文秘密、Cookie 或 Token。
- 每个平台 adapter 都有独立超时、错误码和熔断状态；一个平台失败不阻塞其他平台草稿。
- 生产默认 `dry-run-only`，真实发布需明确的人工确认和平台授权。

## 阶段路线

### 已完成

- CLI 骨架、JSON 契约、插件 entry point 规范。
- YAML 配置、Keychain 凭证接口、SQLite 操作/账号/排期台账。
- B 站热搜只读适配器与本机真实验证。
- 跨平台草稿、媒体存在性检查、发布 dry-run 和定时 dry-run。
- 测试、doctor、中文研究报告和部署说明。

### 下一阶段

- YouTube 官方 OAuth/Data API 只读：频道、视频、评论和 Analytics；发布保留 execute 开关并先做私享/草稿验证。
- B站 `bili-cli` 只读扩展：搜索、账号资料、概览、作品数据和评论读取；发布仅在账号实机验证后单独放行。
- 小红书/抖音/知乎适配器优先做只读，分别记录浏览器/CDP/Cookie 依赖和风控证据。
- 增加 `social-agent mcp`，只暴露 `platforms`、`research`、`content.create`、`publish.preview`、`report` 等安全工具；不默认暴露真实 publish。
- 增加 Agent Skill 文档，描述 JSON 契约、人工确认语义和错误码。
