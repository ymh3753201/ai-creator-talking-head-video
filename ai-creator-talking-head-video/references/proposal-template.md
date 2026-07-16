# Proposal Templates

## Contents

- Stage A: topic selection
- Stage B1: complete text proposal and Confirmation 1
- Stage B2: real production images and Confirmation 2
- Stage C: internal dry-run record

Show only the stage the user currently needs. Do not make a topic-only user review production details before choosing a topic.

## Stage A: Topic Selection Card

Use when the user has only a topic, account direction, or performance problem.

```markdown
# 选题方向

当前假设：目标平台、观众和账号定位。

| 选题 | 适合谁看 | 为什么值得做 | 前 3 秒钩子 | 风险/资料要求 |
|---|---|---|---|---|

请先选择一个方向。确认前不写完整脚本、不设计数字人图片，也不调用付费视频接口。
```

## Stage B1: Text Production Proposal

Use after a topic is selected or when the user supplies a script, business source material, audio, subtitle, or existing video.

Stage B1 is one text-only user-visible delivery containing the complete proposal. It must be the primary assistant response, not tool output. Do not call imagegen or a paid video API in this response. After the user confirms the plan, Stage B2 uses Codex built-in image_gen/image2 to generate real production images for a separate image-confirmation step.

Before filling the duration/segment section, run `prepare_project.py --duration-plan-only` with the optimized full script, confirmed duration, selected model config, language, and content mode. This is the same no-cost deterministic planner used by production; do not hand-count paragraphs or invent request durations.

```markdown
# 数字人口播视频方案

## 1. 路线判断
- 内容模式 / 业务场景：
- desired_output：
- speech_source：
- timing_authority：
- 为什么选择这条路线：
- 目标平台 / 观众 / 时长 / 比例 / 分辨率 / 语言：

## 2. 目标与合规边界
- 用户真实目的：
- 成功指标 / 验收目标：
- 风险边界：
- 明确不做或不能承诺的内容：

## 3. 素材与原脚本专业审查
- 已有素材逐项盘点及用途：
- 缺失素材：
- 用户素材中谁控制时间轴：
- 哪些素材控制事实、人物身份、场景或平台风格：
- 原脚本需要保留的事实、观点和表达意图：
- 原脚本的问题：事实证据 / 专业性 / 钩子 / 逻辑 / 重复 / 口语自然度 / 平台适配 / CTA / 时长与节奏：
- 不可直接采用或需要用户补证的内容：
- 专业优化策略和重要改写说明：
- 我做的假设：

## 4. source_fact_map
| fact_id | source_locator | must_preserve | allowed_rewrite | forbidden_inference | script_beat | status |
|---|---|---|---|---|---|---|

来源可以是 PPT 页码、FAQ 编号、政策章节、视频时间码或用户文档段落。没有来源的政策、价格、期限、保证和数据不得写成事实。

## 5. 优化后的完整口播稿
- 标题 / 开场钩子：
- 优化后的完整口播稿：必须给出可直接制作的完整逐字稿，不能只给结构、摘要或修改建议。
- 正文段落和转场：
- 重点信息（仅通过口播表达，不上屏文字）：
- 结尾 CTA：
- 改写说明：哪些内容被保留、删除、降级为待核实信息或重新组织，以及原因。
- 时长与分段：用户给出的时长默认是最终交付硬上限。先把口播稿专业优化到约占目标时长的 85%-95%，再用与 `prepare_project.py` 相同的无付费确定性计算选择最少片段。列出预计口播秒数、`spoken_fill_ratio`、`delivery_max_seconds`、模型 `allowed_durations_seconds`、每段 `request_duration_seconds`、预计本地裁尾时长和 `duration_plan_digest`。多段方案低于 75% 总口播填充率直接停止并先改稿。当前路由只允许 4/6/8/10/12/15 秒档位；30 秒内容能在两个安全口播窗口内完成时，必须使用 15 秒 + 15 秒，不得因原稿有三个自然段而增加第三次付费请求，也不得通过显式分段文件减少为一段或换成更短档位。每段必须是完整强句；句号本身不等于句意完整，不得把逗号或“从……到……”等未完成结构机械改成句号。逐字稿或关键事实过多且压缩后仍放不下时，停止并让用户在“缩短脚本”和“明确改变成片时长”之间选择。

## 6. 数字人、场景和镜头
- 数字人形象 / 权利边界：
- 服装 / 发型 / 气质 / 表情 / 姿态：
- 场景 / 构图 / 镜头 / 光线：
- visual_bible：所有片段保持不变的规则。
- 图片计划与确认说明：本轮只列出会生成的数字人源图、首帧/尾帧或分段首帧及精确意图；方案确认后再用 gpt-image-2 生成真实生产图片。多宫格分镜仅作为 `preview_only` 补充。

## 7. 特效选择
- 用户选择：启用 / 关闭：
- 关闭时：只保留视频模型生成的完整画面，不加入 B-roll、标题卡、插图、遮罩、转场、进度条或 BGM。
- 启用时，逐项列出获准特效：
| 时间 | 口播内容 | 获准特效/B-roll | 来源 | 音效/BGM |
|---|---|---|---|---|

## 8. 字幕选择与后期方案
- 默认：关闭字幕。视频模型、Provider prompt 和 Provider payload 始终无字幕、无标题、无文字标签、无标志和无水印。
- 用户在第一次确认时回复“确认方案，需要字幕”：同时完成方案确认和字幕开启，记录 `enabled=true`、`request_source=user_plan_confirmation`、`confirmation_status=confirmed`、`provider_policy=never_send` 与 `render_policy=postproduction_burn_only`，不增加第三次确认。
- 用户只说“需要字幕”：只代表要求修改方案，不视为已确认完整方案。
- 字幕开启时：先生成并质检 `final.clean.mp4`；确认 `no_generated_text=true` 后，再根据最终音频本地生成 SRT，用平台安全区样式本地烧录为 `final.captioned.mp4`。
- 竖屏/横屏和抖音、TikTok、小红书、YouTube Shorts、YouTube 横屏、Bilibili 使用各自样式预设；最多两行、透明背景、不遮挡脸、嘴和平台按钮。
- 模型自行画入文字时：在烧录前阻止合格交付，不将其当成后期字幕，且不自动付费重生。

## 9. 图片和模型路线
| 资产角色 | 用户已有/计划生成 | 依据的用户素材 | 精确生成提示词或文件 | `video_payload`/`preview_only` | 是否已确认 |
|---|---|---|---|---|---:|

- 模型 / provider_route / capability_source / verified_at：
- 口播与外部音频对齐级别：
- 口播忠实度模式：轻松且不含措辞敏感事实的内容可用 `semantic_tolerance` / 事实型自媒体、业务与来源事实默认 `critical_facts_exact` / 用户明确要求逐字时使用 `verbatim_required`：
- 必须准确保留的名称、数字、价格、日期、政策、否定词、能力边界、CTA 和来源事实：
- 可接受范围：仅允许不影响含义和理解的轻微连接词/发音差异，并以 `pass_with_notes` 记录；ASR 单次不一致不自动触发重生。
- 是否拆段：
- 分段原因：单段可完成 / 超过单段安全容量并按最少付费片段拆分：
- 模型支持的请求时长档位：来自 `allowed_durations_seconds`，不得只按最小/最大范围猜测。
- 每段时长：分别列出预计口播时长和合法的 API 请求时长；不要求口播填满请求时长，可在成片阶段只裁掉已确认无口播的尾部。
- 最少片段校验：说明为什么不能用更少片段；自然段数量、分镜美观或平均分配不能单独成为多一次付费请求的理由。
- 预计口播 / 必要自然停顿 / 预计成片时长 / 最终交付上限 / API 请求总时长 / 预计本地裁剪时长 / 请求总时长超交付上限：分别记录。固定档位量化可能让最后一项大于 0，但这只是请求时槽差额，必须被可验证的空闲尾部裁剪覆盖；预计真实内容仍需在上限内，`delivery_fit_status` 必须为 `ok`。
- 预计付费请求数：

## 10. 自动执行与零付费返修授权
- 基础付费请求数：正常生成全部片段需要多少次。
- 修复预留次数：固定为 0。
- 单片段最多付费提交次数：1；`per_shot_repair_limit=0`。
- 最大付费提交次数（approved paid cap）：必须等于基础付费请求数，不得留出自动返修额度。
- 已确认时长方案摘要：写出 Stage B1 的 `duration_plan_digest`；正式 prepare、preflight、第二次确认和 submit 必须完全匹配。
- 自动执行范围：预检、每段一次提交、按原 request ID 轮询/下载、无成本裁静音/重拼接/重编码、技术与画面质检、再次质检和最终交付；字幕开启时还包含干净版质检后的本地转写、平台样式烧录和字幕版质检，全程不增加付费请求。
- 明确禁止：因一次 ASR 不一致、轻微措辞变化、意思相同的口播差异、Provider 终止失败或画面瑕疵而自动再次 POST。轻微且不改含义的问题按 `pass_with_notes` 交付；严重问题阻止“合格交付”并报告。
- 免费后处理：写入独立 `postprocess-manifest.json`，不得事后修改已确认的付费方案、合同或 jobs 合同摘要。
- 确认后不再重复询问：上述获批范围内无需逐步征求同意。
- 仅在以下情况暂停：方案/脚本/素材/模型发生实质变化；付费请求状态不明且无法安全确认是否已扣费；Provider 明确终止失败；质检发现无法用本地处理修好的严重问题；出现无法自行解决的版权、安全或事实来源问题；API/鉴权故障且没有安全恢复方式。

## 11. 下一步与两次确认门槛
- 本轮状态：`stage=awaiting_plan_confirmation`、`proposal_delivered=true`、`plan_confirmed=false`、`image_assets_confirmed=false`、`paid_video_authorized=false`。
- 第一次确认覆盖最终脚本、最终交付时长上限、最少片段与合法请求时长、视觉方向、字幕选择、特效选择、模型路线、基础付费请求数、零修复预留、单片段一次提交和等于基础请求数的最大付费请求数；只授权进入图片生成阶段，不授权付费视频调用。
- 第一次确认后，调用 Codex `imagegen` 的 built-in gpt-image-2/image2，生成至少一张标记为 `video_payload` 的真实 `video_source`、`first_frame` 或 `segment_source`。多宫格分镜图只能标注 `preview_only`。
- 禁止生成“实际视觉确认板”、信息卡式确认图或线框占位图；图片必须是视频生产会真实使用或直接指导分镜的图像资产。
- 生图回复可能只显示图片，所以本方案必须提前告诉用户：满意请回复“确认图片并开始制作”；不满意请直接说明要改哪张图。
- 图片阶段状态：`stage=awaiting_image_confirmation`、`proposal_delivered=true`、`plan_confirmed=true`、`image_assets_confirmed=false`、`paid_video_authorized=false`。
- 第二次确认同时批准所见图片和开始制作。将选定图片从 `$CODEX_HOME/generated_images/...` 复制进项目，记录用途、路径和 SHA-256，并作为后续视频请求的固定素材，不得静默换图。
- 第二次确认后状态：`stage=production_authorized`、`proposal_delivered=true`、`plan_confirmed=true`、`image_assets_confirmed=true`、`paid_video_authorized=true`。
- 随后自动执行准备、预检、合同绑定、每段一次视频生成、原 request ID 轮询、剪辑/拼接、质检、免费本地后处理和最终交付；不再增加第三次常规确认，也不自动付费重生。
- 方案/脚本/模型/付费上限实质变化时回到本阶段；只调整图片且上述内容不变时保留第一次确认。

请确认本方案。确认后我会生成视频真实使用的图片；图片满意时，请回复“确认图片并开始制作”。
```

## Stage B2: Production Image Confirmation

Use only after the user confirms Stage B1. Generate the planned real production images with Codex built-in gpt-image-2/image2. Since imagegen can end the response, the Stage B1 text already carries the instruction to reply “确认图片并开始制作” or request a specific image revision. Do not call a paid video API in Stage B2. Do not create a third confirmation between the second confirmation and production.

## Stage C: Internal Dry-Run Record

Use internally after the user's second visible confirmation. Do not ask the user to approve the same unchanged plan or images again.

```markdown
# 内部预检记录

- production contract digest：
- 方案 / 模型 / 素材是否与确认版本一致：
- 模型路线和能力证据：
- 付费请求数与每段时长：
- script_pacing / script_boundary：
- 每段真实 source asset：
- 外部音频是否进入正确字段；字幕是否保持 `subtitle_included_in_payload=false`：
- 剩余警告：
- 本次最大付费提交次数：
- 基础付费请求数 / `repair_reserve=0` / `per_shot_repair_limit=0`：
- 最大付费提交次数是否严格等于基础片段数：
- 自动执行与零付费返修授权是否完整：
- 是否与用户两次确认的方案、图片、模型、创意选择和付费上限完全一致：
- 分段结果是否与首轮确定性计算完全一致；数量变化属于合同漂移，不得静默继续：

一致则创建绑定该合同的机器确认并继续；不一致则停止，向用户说明发生变化的项目。任何脚本、素材、模型或 dry-run 变化都会让旧确认失效。
```
