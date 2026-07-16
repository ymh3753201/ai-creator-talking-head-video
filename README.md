# AI Creator Talking Head Video

[![CI](https://github.com/ymh3753201/ai-creator-talking-head-video/actions/workflows/tests.yml/badge.svg)](https://github.com/ymh3753201/ai-creator-talking-head-video/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Codex Skill](https://img.shields.io/badge/Codex-Skill-111827)](ai-creator-talking-head-video/SKILL.md)

面向 Codex 的专业数字人口播视频 Skill。它覆盖选题策划、素材审查、脚本改写、数字人方案、最小成本分段、受控视频 API 调用、拼接、成片检查，以及用户明确确认后的本地字幕后期。

它默认服务于自媒体、知识分享、企业培训、产品讲解、客服 FAQ、内部沟通和多语言本地化，不默认把所有视频做成带货广告。

## 核心特点

- 首轮必须先交付完整文字方案和优化后的口播稿，不会直接调用付费视频 API。
- 采用两次用户确认：先确认方案，再确认真实生成图片并授权制作。
- 付费请求数等于基础分段数，不预留自动返修额度，也不重复提交同一片段。
- 视频模型输入只使用用户确认过的素材，并记录路径、用途和 SHA-256。
- Provider 画面固定禁止字幕、标题、Logo、水印和其他未批准文字。
- 字幕默认关闭；只有用户在方案确认时明确要求，才允许在干净成片通过后本地烧录。
- 支持已有 MP4 后期增强、正常生成式口播和模型能力允许时的外部音频路线。
- 通过 `production-contract.json`、`jobs.json` 和 `delivery-manifest.json` 区分方案、付费提交、候选成片和最终合格交付。

## 适用场景

- 抖音、TikTok、小红书、Bilibili、YouTube Shorts 和 YouTube 横屏口播
- AI 工具、知识科普、行业观点和个人 IP 内容
- 企业培训、新员工入职、内部制度讲解
- 客服 FAQ、售后流程、服务说明
- 产品讲解和销售赋能，但不是默认商品广告
- 多语言本地化数字人口播
- 已有口播视频的 B-roll、字幕和版式增强

纯商品广告、带货和种草转化项目建议使用独立的 `ai-commerce-video` Skill。

## 运行要求

- Codex
- Python 3.10 或更高版本
- FFmpeg 和 ffprobe
- 可选：whisper.cpp 与本地 Whisper 模型，仅用于用户确认后的本地字幕计时
- 可选：受支持的视频生成 API

图片生成使用 Codex 内置 `image_gen`，不需要在本项目里配置单独的图片 API Key。

## 安装

### 从 GitHub Release 安装

在 [Releases](https://github.com/ymh3753201/ai-creator-talking-head-video/releases) 下载最新的 `.skill` 文件，然后解压到 Codex Skills 目录：

```bash
unzip ai-creator-talking-head-video.skill -d "${CODEX_HOME:-$HOME/.codex}/skills"
```

### 从源码安装

```bash
git clone https://github.com/ymh3753201/ai-creator-talking-head-video.git
cd ai-creator-talking-head-video
rsync -a ai-creator-talking-head-video/ "${CODEX_HOME:-$HOME/.codex}/skills/ai-creator-talking-head-video/"
```

安装后可在 Codex 中这样调用：

```text
$ai-creator-talking-head-video
请把这份企业培训材料改成 60 秒数字人口播视频方案。
```

## 标准工作流

1. 分析用户提供的主题、脚本、PPT、FAQ、视频、音频或字幕。
2. 输出完整文字制作方案、优化后的口播稿、时长和最小分段计划。
3. 用户确认方案，但此时不会调用付费视频 API。
4. 使用 Codex 内置图片能力生成真实数字人视频源图或首帧。
5. 用户确认具体图片并授权开始制作。
6. 执行无付费的 preflight，锁定素材哈希、模型能力和付费上限。
7. 每个片段最多提交一次付费请求。
8. 下载、检查、拼接并执行允许的免费本地后期。
9. 只有最终检查通过后才生成 `delivery-manifest.json`。

详细规则见 [SKILL.md](ai-creator-talking-head-video/SKILL.md) 和 [workflow.md](ai-creator-talking-head-video/references/workflow.md)。

## 视频 API 配置

仓库不包含任何真实 API Key。示例环境文件中的 Key 必须保持为空。

推荐使用交互式脚本创建权限为 `600` 的私有配置文件：

```bash
python3 ai-creator-talking-head-video/scripts/setup_private_env.py
```

默认写入：

```text
~/.codex/ai-creator-talking-head-video.env
```

也可以手动配置环境变量：

```text
AI_CREATOR_TALKING_HEAD_VIDEO_API_KEY=
AI_CREATOR_TALKING_HEAD_VIDEO_BASE_URL=
AI_CREATOR_TALKING_HEAD_VIDEO_MODEL=
FAL_KEY=
```

不要把真实 Key 写入：

- `SKILL.md`
- `model-config.example.json`
- 测试文件
- 请求记录
- Git 提交
- Issue 或公开日志

### 第三方 Provider 提醒

示例模型配置包含一个名为 `119337` 的 third-party gateway 路由，用于展示已经测试过的 Provider 别名配置方式。它不是 xAI 官方服务，也不代表项目作者对其稳定性、安全性、价格或长期可用性作出保证。

正式使用前请：

- 审核 Provider 的服务条款、隐私政策和计费方式。
- 将 `model-config.example.json` 复制为自己的私有配置。
- 核对请求地址、模型名称、合法时长和素材字段。
- 先运行无付费 preflight，再授权真实生成。

官方能力资料：

- [xAI Image-to-Video](https://docs.x.ai/developers/model-capabilities/video/image-to-video)
- [xAI Reference-to-Video](https://docs.x.ai/developers/model-capabilities/video/reference-to-video)
- [Fal Seedance 2.0 Reference-to-Video](https://fal.ai/models/bytedance/seedance-2.0/reference-to-video)

## 常用命令

检查模型配置：

```bash
python3 ai-creator-talking-head-video/scripts/validate_config.py \
  --config ai-creator-talking-head-video/assets/templates/model-config.example.json
```

只计算时长与最小分段，不创建项目，也不读取 API Key：

```bash
python3 ai-creator-talking-head-video/scripts/prepare_project.py \
  --name demo \
  --content-mode avatar_talking_head \
  --platform douyin \
  --language zh \
  --duration 30 \
  --script-text "这里填写已优化的完整口播稿。" \
  --duration-plan-only
```

项目准备完成后，统一通过工作流入口执行：

```bash
python3 ai-creator-talking-head-video/scripts/workflow_engine.py \
  --project-dir /path/to/project status
```

不要绕过确认合同直接调用付费提交脚本。

## 目录结构

```text
.
├── ai-creator-talking-head-video/
│   ├── SKILL.md
│   ├── agents/
│   ├── assets/templates/
│   ├── evals/
│   ├── references/
│   └── scripts/
├── tests/
├── tools/
├── .github/workflows/
├── CONTRIBUTING.md
├── SECURITY.md
└── LICENSE
```

`evals/` 用于源码开发与回归评测，发布 `.skill` 安装包时会自动排除。

## 测试

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  tests/test_ai_creator_talking_head_video_skill.py \
  tests/test_ai_creator_talking_head_workflow_engine.py \
  tests/test_ai_creator_talking_head_policy_contracts.py

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s tests -p 'test_talking_head_*.py'
```

部分成片、静音、冻结和拼接测试需要 FFmpeg。

## 发布检查与打包

发布前执行：

```bash
python3 tools/audit_release.py
python3 tools/package_skill.py
unzip -t dist/ai-creator-talking-head-video.skill
```

审查脚本会阻止以下内容进入发布：

- API Key、Bearer Token 和 GitHub Token
- `.env`、`.env.local`
- 本机绝对路径
- Python 缓存
- 视频、音频、请求日志和运行项目
- 软链接和损坏的 Markdown 本地链接

## 安全与隐私

- 视频 API 是可选能力，不配置 Key 仍可使用策划、脚本、时长计算和 dry-run 能力。
- 用户素材可能包含肖像、声音、企业制度和客户信息，上传第三方模型前必须确认授权范围。
- 不要将生成请求、素材文件或完整项目目录提交到公开仓库。
- 安全问题请按 [SECURITY.md](SECURITY.md) 使用 GitHub Private Security Advisory 报告。

## 项目边界

- 测试通过只代表本地代码和离线规则通过，不代表第三方视频服务实时可用。
- MP4 拼接成功不等于角色、口型和内容连续性已经通过。
- 候选视频存在不等于最终交付合格。
- 模型能力、价格和接口字段可能变化，正式付费前必须重新核对。

## 贡献

欢迎提交 Issue 和 Pull Request。开始前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。

## License

[MIT](LICENSE)
