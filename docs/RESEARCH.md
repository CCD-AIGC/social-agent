# 开源项目调研与选型

调研时间：2026-11-18（GitHub REST API 与仓库 `HEAD` 源码树）。Star、Fork、Issue、更新时间和许可证来自 GitHub API；能力判断同时查看 README、入口代码、测试和文档。README 写了但代码或测试没有证据的能力标为“待验证”。Star 会变化，不能当作质量结论。

## 评分方法

总分 10 分：源码/测试证据 3 分、Agent 接口 2 分、安全与可控性 2 分、维护活跃度 1.5 分、平台覆盖 1.5 分。浏览器自动化、逆向接口、Cookie 登录和未完成功能会扣风险分；官方 API/OAuth、稳定 JSON 契约和默认 dry-run 会加分。评分是本项目的集成优先级，不是对项目作者的质量评级。

## 核心候选对比

| 项目 | GitHub 状态（Star / Fork / Issue，最近提交） | 许可证 | 源码核实的能力 | 登录/依赖 | Agent 接口 | 风险与 macOS ARM64 | 评分 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [dreammis/social-auto-upload](https://github.com/dreammis/social-auto-upload) | 16,635 / 2,817 / 87；2026-10-22 | MIT | 统一 `sau` CLI；抖音、小红书、B站等视频/图文上传；知乎文章/视频；大量平台 Skill；YouTube 标为开发中 | 浏览器/会话，部分运行时安装 `patchright`、`biliup` | CLI + Skills；JSON/结果文件 | 覆盖最广但浏览器和平台页面变化成本高；ARM64 依赖需逐平台实测 | 8.2 |
| [hanliang97/MatrixMedia](https://github.com/hanliang97/MatrixMedia) | 1,535 / 233 / 12；2026-11-14 | GPL-2.0 | Electron GUI + CLI；8 平台视频发布；账号、历史、评论拉取；评论回复默认 dry-run；HTTP API/MCP | Electron/Puppeteer/持久化 partition；多数平台先 GUI 登录 | CLI、稳定 JSON、HTTP、MCP、Agent Skill | GPL-2.0 对闭源商业集成有约束；桌面端在无显示器 Mac mini 上需专项验证 | 8.0 |
| [cv-cat/All-IN-ONE](https://github.com/cv-cat/All-IN-ONE) | 123 / 28 / 2；2026-08-18 | MIT | 小红书/微博/抖音统一 CLI；代码显示上游仓库动态发现、命令映射、`--dry-run`、JSON | Cookie profile；依赖多个逆向上游仓库 | CLI + Agent Skill；JSON | 上游仓库和非官方接口耦合高；MIT 可复用；ARM64 主要取决于 Python/requests | 7.4 |
| [jackwener/xhs-cli](https://github.com/jackwener/xhs-cli) | 700 / 70 / 9；2026-10-09 | Apache-2.0 | 搜索、阅读、主页、点赞、收藏、评论、图文发布；测试覆盖 auth/client/CLI | Camoufox 浏览器；可提取 Chrome Cookie 或扫码 | CLI + JSON；适合只读和 Agent | README 明确是逆向 API/浏览器路线；真实账号风控和浏览器依赖需谨慎；ARM64 待实测 | 7.6 |
| [Youhai020616/xiaohongshu](https://github.com/Youhai020616/xiaohongshu) | 32 / 5 / 0；2026-09-12 | MIT | 搜索、详情、发布、互动、创作者数据分析；MCP 优先，CDP 回退；源码有命令和测试 | CDP/Chrome 或内置 Darwin ARM64 MCP 二进制；需要登录态 | CLI + MCP + JSON；Agent 友好 | 能力丰富但平台自动化和 MCP 二进制版本需持续维护；MIT 可复用 | 7.8 |
| [joohw/xhs-cli](https://github.com/joohw/xhs-cli) | 40 / 8 / 2；2026-09-20 | GPL-3.0 | 创作者指标、已发笔记、单篇详情、发帖归档；源码默认填表，`--publish` 才尝试点击发布 | Chrome/Chromium + Puppeteer；多账号隔离 | CLI；测试覆盖会话和发布按钮 | GPL-3.0 影响闭源商业分发；人机确认设计较稳；ARM64 需 Chrome 实测 | 7.0 |
| [Yht20927/douyin-cli](https://github.com/Yht20927/douyin-cli) | 305 / 59 / 0；2026-11-13 | MIT | 抖音视频搜索、评论/嵌套回复、图片评论、ReplyEngine、仪表盘；Bridge HTTP 客户端；源码和测试齐全 | Chrome 油猴脚本 + Bridge/WebSocket；LLM API 可选 | CLI + HTTP Bridge；JSON | 评论自动化、行为模拟和随机延迟带来账号风险；MIT；ARM64 依赖 Node/Chrome | 7.2 |
| [mf-yang/douyin-creator](https://github.com/mf-yang/douyin-creator) | 19 / 4 / 2；2026-04-02 | 未声明 | README 将视频/图文/文章发布、互动、分析标为待实现；源码有 Playwright 登录和骨架 | Playwright 浏览器会话、多账号目录 | CLI | 维护节奏弱、许可证未声明，不宜直接复用；ARM64 Playwright 可装但功能未完成 | 4.2 |
| [BAIGUANGMEI/zhihu-cli](https://github.com/BAIGUANGMEI/zhihu-cli) | 116 / 20 / 9；2026-05-04 | Apache-2.0 | 搜索、热榜、问题/回答、评论、提问、想法、文章；requests 客户端；测试覆盖 auth/client/CLI | QR 登录或 Cookie；知乎 Web API，写请求带 CSRF | CLI + JSON；无 MCP | 非官方 Web API、Cookie 失效和风控需处理；Apache-2.0；Python ARM64 友好 | 7.1 |
| [jdwit/ytstudio-cli](https://github.com/jdwit/ytstudio-cli) | 18 / 3 / 4；2026-07-01 | MIT | YouTube Data/Analytics API；视频上传、批量元数据、播放列表、评论和分析；上传默认 dry-run，`--execute` 才执行 | Google OAuth 官方 API；有配额和验证限制 | CLI + Agent Skill + JSON/sidecar | 官方 API 最稳；上传/公开状态受 Google 项目审核与配额影响；ARM64 Python 友好 | 8.5 |
| [porjo/youtubeuploader](https://github.com/porjo/youtubeuploader) | 895 / 115 / 9；2026-08-07 | Apache-2.0 | Go CLI 使用 YouTube Data API v3 上传、元数据、OAuth；源码有分块上传和限速 | OAuth client secrets；官方 API | CLI；无 MCP | 成熟、简单、可商用；README 明确未审核 API 项目上传默认私享；Go ARM64 可编译 | 7.5 |
| [kukemc/bili-cli](https://github.com/kukemc/bili-cli) | 401 / 29 / 3；2026-11-14 | MIT | 80+ 命令；热搜/搜索/评论/私信/投稿/数据中心；统一 JSON、错误码；源码有 ratelimit guard、MCP、Skill 和测试 | B站扫码登录；`bilibili-api`/Web API；状态和审计文件 | CLI + MCP + Skill；JSON | 默认风控即停、限速；MIT；macOS ARM64 已在本机安装并实际读取热搜 | 9.0 |

## 追加检索的活跃项目

| 项目 | 状态与用途 | 许可证 | 结论 |
| --- | --- | --- | --- |
| [Panniantong/Agent-Reach](https://github.com/Panniantong/Agent-Reach) | 112,799 Star；2026-11-08；MIT；面向 Agent 的互联网读取，含 YouTube、B站、小红书，测试有公开读取和登录边界 | MIT | 适合作为 Research 只读层参考；不是发布器，不能替代账号发布适配器 |
| [risingjerry/social-media-toolkit](https://github.com/risingjerry/social-media-toolkit) | 34 Star；2026-11-17；Apache-2.0；Python SDK/CLI/MCP，提取抖音、RedNote、B站、YouTube 元数据、字幕和评论 | Apache-2.0 | 适合作为内容调研/抽取插件候选；社区规模小，逐平台实测待补 |
| [Daily-AC/omnireach](https://github.com/Daily-AC/omnireach) | 24 Star；2026-11-03；MIT；统一 CLI/MCP，覆盖登录墙内容搜索，含小红书、抖音、B站、YouTube | MIT | 适合作为 Research 备选，代码有 adapter 合同和 fixtures；发布不在范围内 |
| [brightbeanxyz/brightbean-studio](https://github.com/brightbeanxyz/brightbean-studio) | 2,657 Star；2026-11-17；AGPL-3.0；Django 自托管社媒平台，排期、发布、分析、收件箱 | AGPL-3.0 | 产品能力完整但较重，适合作为竞品和后续 UI 参考；不适合当前轻量 Mac mini 核心 |
| [mrlong0129/yominpost](https://github.com/mrlong0129/yominpost) | 101 Star；2026-10-05；MIT；本地 AI 工作台，CLI/MCP/Agent Skill，内容风控；源码明确 MCP 没有 publish 工具 | MIT | 其“生成/风控/草稿由 Agent，发布由人确认”的边界非常适合本项目；平台覆盖不能直接照搬 |
| [Algovate/xhs-mcp](https://github.com/Algovate/xhs-mcp) | 58 Star；2026-05-17；MIT；小红书 MCP + CLI，登录、发布、搜索、推荐 | MIT | 可作为未来 XHS adapter 候选；需要账号实机验证和风控评估 |

官方 SDK/API 参考：`googleapis/google-api-python-client`（Apache-2.0，8,975 Star，2026-11-17 更新）适合 YouTube 官方 API；`tiktok/tiktok-business-api-sdk`（MIT，237 Star，2026-03-09 更新）是 TikTok Business API SDK，但不等同于抖音创作者发布能力。

## 能力核验摘要

- **真实只读验证**：本机 `bili hot search --limit 5` 成功返回一份 JSON；首版适配器通过 argv 调用同一命令并测试 JSON 错误边界。
- **源码确认的 Agent 形态**：MatrixMedia 有 CLI/HTTP/MCP；bili-cli 有 CLI/MCP/Skill/统一 JSON；Youhai 小红书项目有 CLI/MCP/CDP；YominPost 有 CLI/MCP/审批边界；ytstudio-cli 有 CLI/Skill/官方 API。
- **只能按文档暂记为待验证**：所有项目的真实账号发布成功率、定时发布是否跨版本稳定、平台风控后果、评论发送权限、长期指标同步和无显示器 Mac mini 运行，都不能由 README 或离线测试代替实机验证。
- **账号安全共同问题**：小红书/抖音/知乎专项工具普遍依赖 Cookie、浏览器会话或非公开 Web API；应隔离账号目录、限制频率、遇验证码或风控即停。不要把“随机延迟/行为模拟”视为安全保证。

## 选型结论

1. 核心采用 Python CLI + SQLite + YAML + Keychain，保持 Mac mini 轻量、可备份、可审计。
2. Research 优先复用 `bili-cli`、Agent-Reach、omnireach、social-media-toolkit 这类只读工具；只读数据不和发布会话混用。
3. YouTube 优先官方 OAuth/API，参考 ytstudio-cli 和 youtubeuploader；抖音、小红书、知乎、B站发布先作为隔离 adapter，默认需人工确认。
4. 将 MatrixMedia 的 CLI/HTTP/MCP 形态和 YominPost 的“Agent 只生成/检查/存草稿，人确认发布”原则作为后续接口参考，但不直接引入 Electron、GPL 代码或重型服务。
5. MCP 和 Agent Skills 放在 CLI 稳定后增加，不能绕过 CLI 的预览、审批、台账和失败边界。
