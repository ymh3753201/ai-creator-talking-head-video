# Contributing

感谢你参与改进 AI Creator Talking Head Video。

## 开始开发

1. Fork 本仓库并创建功能分支。
2. 保持 `ai-creator-talking-head-video/SKILL.md` 精简，把详细规则放入 `references/`。
3. 可重复、易出错或涉及付费保护的操作应放入 `scripts/`。
4. 新增行为必须补充对应回归测试。

推荐分支名称：

```text
feature/short-description
fix/short-description
docs/short-description
```

## 开发原则

- 不绕过两次确认和付费请求上限。
- 不允许同一片段自动重复付费提交。
- 不把字幕文件或字幕字段发送给视频 Provider。
- 不把候选成片写成最终合格交付。
- 不在 Skill 中保存 API Key、用户素材、视频或真实请求记录。
- 新模型能力必须注明资料来源、验证日期和验证等级。
- 保持商品广告与通用数字人口播的业务边界。

## 提交前检查

```bash
python3 tools/audit_release.py
python3 tools/package_skill.py

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  tests/test_ai_creator_talking_head_video_skill.py \
  tests/test_ai_creator_talking_head_workflow_engine.py \
  tests/test_ai_creator_talking_head_policy_contracts.py

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s tests -p 'test_talking_head_*.py'
```

## Pull Request 要求

Pull Request 请说明：

- 修改了什么。
- 为什么需要修改。
- 是否影响付费调用、确认流程、字幕、素材或最终交付。
- 增加或更新了哪些测试。
- 实际运行了哪些验证命令。

不要在 Issue、Pull Request、截图或日志中提交真实 API Key、客户信息或未授权媒体。
