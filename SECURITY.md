# Security Policy

## Supported Versions

安全修复仅针对默认分支和最新 GitHub Release。

## Reporting a Vulnerability

请使用 GitHub 的 Private Security Advisory 私下报告以下问题：

- API Key、Token 或私有配置泄露。
- 可以绕过两次确认或付费请求上限的问题。
- 可以导致同一片段重复付费提交的问题。
- 未经确认上传用户素材的问题。
- 路径穿越、任意文件覆盖或命令注入。
- 请求日志、错误信息或交付文件泄露敏感内容。

请不要在公开 Issue 中粘贴真实密钥、客户素材、请求响应或个人信息。

报告中建议包含：

- 受影响的版本或提交。
- 最小复现步骤。
- 预期行为与实际行为。
- 是否发生真实付费调用或数据外传。
- 建议的修复方向。

## Credential Handling

- 真实视频 API Key 只能存在于环境变量或私有 env 文件。
- 推荐使用 `scripts/setup_private_env.py` 创建权限为 `600` 的配置文件。
- 仓库中的 `env.example` 必须保持空值。
- 发现密钥误提交后，应立即在 Provider 后台撤销并重新生成，不要只删除最新文件。

## Third-Party Providers

示例配置可能包含第三方网关。使用者需要自行审核第三方服务的认证、隐私、数据保留、内容政策、价格和可用性。本项目不保证第三方服务持续可用。
