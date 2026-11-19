# Social Agent Agent 约定

- 先调用 `social-agent doctor --json`，再调用其他命令。
- 默认只使用 `--dry-run`；首版 `--execute` 必须保持拒绝，不能绕过代码闸门。
- 需要读取能力时优先使用 `research`，不要把平台 Cookie 复制到项目文件或日志。
- 解析 CLI 输出时使用稳定 JSON 契约：成功为 `ok=true`，失败读取 `error.code/message/hint`。
- 不把尚未验证的发布、定时、评论或指标能力描述为已实现。
- 遇到验证码、风控、登录失效或未知提交结果立即停止，交给人工处理。
