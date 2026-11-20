# MacBook Pro 工作台试运行

双击桌面的 Social Agent.app，或打开 http://127.0.0.1:8798/。首次运行可在项目目录执行 `uv sync --extra dev`。本机已有环境时，使用 `.venv/bin/social-agent doctor --json` 检查 SQLite、钥匙串和 bili。

## 从一条视频开始

1. 在「内容草稿」填写标题和正文，选择 MP4 或 MOV 视频，以及 JPEG 封面。公众号封面的 JPEG 上限是 64 KiB。AI 辅助制作的作品勾选相应字段。
2. 选需要的目标平台并保存。在「发布预览」查看各平台版本。已有试运行素材可以直接选择《假如你的咪偷偷接住了月亮》。
3. 公众号图文使用「保存公众号图文草稿」。保存完成后，工作台显示官方回读结果和草稿编号。视频平台使用「准备视频草稿交接」，核对创作后台当前账号、视频与标题。重新打开草稿后登记复查和保存范围。
4. 从「操作记录」点击进度状态重新查看任务。若显示「待核对」，打开对应账号的草稿箱检查是否已有同一稿件。已收到平台编号的任务可直接回读。写入回执不明时，记录保留用于核对，重复点保存会回到同一操作。

## 微信公众号授权

在公众号官方后台找到 AppID、AppSecret 和接口 IP 白名单。在工作台「平台接入 → 微信公众号 → 设置接口账号」录入这组凭证，再点「保存并检查草稿权限」。AppSecret 存在 macOS 钥匙串。若后台提示当前出口 IP 未获授权，由账号管理员处理官方白名单，之后回到工作台重新检查。账号需有草稿读取、永久封面素材上传和新增草稿权限。

官方 API 操作依次检查草稿权限、上传封面、写图文草稿、回读标题、正文和封面。工作台支持另外登记可播放视频稿的实际结果。正式投稿和定时由原有 B 站 CLI 流程继续执行；工作台的「查看最近稿件」可读取状态。

- [公众号草稿接口](https://developers.weixin.qq.com/doc/subscription/api/draftbox/draftmanage/api_draft_add.html)
- [公众号草稿详情](https://developers.weixin.qq.com/doc/subscription/api/draftbox/draftmanage/api_getdraft.html)
- [公众号素材接口](https://developers.weixin.qq.com/doc/subscription/api/material/permanent/api_addmaterial.html)

## 小红书与视频号

小红书官方 XLSX 导入支持已发布笔记和基础指标。它反映导出时的快照。账号开放平台的基础身份授权，与智能体平台的发布能力分别申请和核实。工作台可生成视频交接，目标草稿可在创作后台人工复查，并提供 SAU 的远期定时入口。小红书草稿只在当前浏览器可见时，在工作台登记为「此浏览器草稿」。

视频号通过视频号助手完成最终草稿保存与复查。先看当前登录的创作者，再选择样片。OpenCLI 的视频号发布适配器实际使用浏览器，列有草稿模式。工作台提供 SAU 自动存草稿和手动交接两条路径。账号获授官方短视频接口时，可沿用同一份草稿和操作台账。

- [小红书开放平台授权范围](https://openaccount.xiaohongshu.com/docs/quick-start)
- [小红书智能体开放平台](https://miniapp.xiaohongshu.com/doc/DC897827)
- [OpenCLI 视频号说明](https://github.com/jackwener/OpenCLI/blob/main/docs/adapters/browser/wechat-channels.md)

## SAU 自动化与 OpenCLI 调研

SAU 是工作台短视频自动化的可选依赖。视频号调用 SAU 的草稿操作，小红书使用远期定时操作，默认选 6 天后北京时间 20:00，提交前可改，后者需要在预览中选择账号并确认。两种操作都由同一个本机工作台提交、串行执行和保存台账。SAU 底层使用浏览器及自己的登录态。浏览器扫码凭证留在 SAU 的本机数据目录。

首次使用前，在工作台「发布预览」选中视频并生成预览。为所需平台点击「打开扫码窗口」，用手机完成扫码和确认。工作台载入账号后，就可以提交该平台任务。也可以在 SAU 安装目录通过终端扫码。别名由你填写，建议用能识别实际创作账号的文字。

```bash
cd "$HOME/Library/Application Support/social-agent/tools/social-auto-upload"
export PLAYWRIGHT_BROWSERS_PATH="$PWD/browsers"
.venv/bin/sau tencent login --account my-channels --headed
.venv/bin/sau xiaohongshu login --account my-xiaohongshu --headed
```

回到工作台的「发布预览」，刷新相应草稿即可选择 SAU 账号。视频号执行「自动保存视频草稿」。小红书在你选定账号、核对时间并勾选后执行「确认定时发送」。你可以在平台后台查看实际排期并手动提前。到点会自动发表。若记录显示「待核对」，从相应后台找到该作品并登记结果。上游退出状态不代表平台已确认，工作台会保留操作记录并阻止重传相同版本。

本机采用 social-auto-upload 提交 `3847fff01` 和 OpenCLI `2.0.3`。SAU 依赖在其独立环境，原锁文件缺少上游所需的 `tinycss2`，本机补装了 `tinycss2==1.4.0`。重装时使用 `uv sync --frozen --no-dev --python 3.12`，再运行 `uv pip install --python .venv/bin/python tinycss2==1.4.0` 和 `PLAYWRIGHT_BROWSERS_PATH="$PWD/browsers" .venv/bin/patchright install chromium`。工具放在工作台数据目录的 `tools` 子目录。

「选题调研」可在 B 站、Hacker News、GitHub Trending 和掘金之间切换。后三项走 OpenCLI 的公开适配器。也可运行 `social-agent research --platform hackernews --limit 10 --json`。

- [social-auto-upload 视频号命令](https://github.com/dreammis/social-auto-upload/blob/3847fff01/sau_commands/tencent.py)
- [social-auto-upload 小红书命令](https://github.com/dreammis/social-auto-upload/blob/3847fff01/sau_commands/xiaohongshu.py)
- [OpenCLI 公开调研适配器](https://github.com/jackwener/OpenCLI/blob/main/docs/adapters/index.md)

## 诊断与备份

- 检查工作台是否运行，可访问 `http://127.0.0.1:8798/api/health`。
- 检查公众号可用性，可使用 `social-agent accounts probe --platform wechat_mp --account <本机别名> --json`。
- 查询已登记操作，可使用 `social-agent report --limit 30 --json`。
- 复查公众号草稿可使用 `social-agent drafts verify --operation <操作编号> --json`。已确认平台草稿存在且写入时丢失草稿回执的情况下，可加 `--reference <草稿编号>`。
- 默认数据目录是 Mac 的 `~/Library/Application Support/social-agent`。备份 SQLite、草稿 JSON 和素材目录，之后可恢复草稿及台账。凭证通过本机钥匙串单独管理。
