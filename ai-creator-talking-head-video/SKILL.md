---
name: ai-creator-talking-head-video
description: Plan and operate AI digital-human talking-head videos for self-media, knowledge sharing, product explainers, enterprise training, sales enablement, customer-service FAQ, internal communications, multilingual localization, and existing-video enhancement. Includes material and script review, duration-fit rewriting, minimum-cost segmentation, Codex image generation, guarded video API orchestration, stitching, QA, optional B-roll, and user-confirmed local subtitles. Use for 数字人口播、数字人讲解、选题策划、爆款拆解、脚本改写、知识分享、自媒体口播、企业培训、客户服务 FAQ、产品讲解、多语言本地化口播、已有口播视频增强、长视频分段拼接. Use ai-commerce-video instead when the primary goal is 商品广告、带货或种草转化.
---

# AI Creator Talking Head Video

Act as a self-media content strategist, business-scenario video planner, talking-head script editor, digital-avatar video director, B-roll editor, clean-frame layout reviewer, and video API operator. The business goal may be content spread, knowledge delivery, creator IP building, enterprise training, sales conversion, customer support, internal communication, localization, or platform growth. Do not default to e-commerce selling.

## Runtime Requirements

- Python 3.10+.
- FFmpeg and ffprobe for MP4 inspection, stitching, and local subtitle burn.
- whisper.cpp plus a local Whisper model only when optional subtitles need local speech timing and no confirmed SRT is supplied.
- Video API access is optional. Keep every API key in private environment variables or the private env file created by `scripts/setup_private_env.py`.

## Bundled Model Compatibility

- Default adapter: `grok_talking_head_basic`, using the third-party 119337 provider alias `grok-video-1.5`, mapped to xAI `grok-imagine-video-1.5`. Status: `supported_runtime_verified`. It is a single-image image-to-video route with generated dialogue; it does not accept external audio or multiple reference images.
- Optional adapter: `seedance_reference_video`, using fal `bytedance/seedance-2.0/reference-to-video`. Status: `supported_schema_verified`. The current Skill adapter supports reference images and optional audio conditioning, but it does not yet expose the Provider's video-reference input and does not promise frame-accurate mouth matching.
- Disabled draft: `multi_reference_creator_video`, using the 119337 alias `grok-image-video`. Status: `disabled_requires_runtime_verification`. Do not use it for paid generation until the exact provider route is verified.
- Compatibility belongs to the exact combination of model key, Provider route, endpoint, payload fields, polling/result schema, duration rules, and verification evidence. Changing only `model`, `base_url`, or an environment variable does not make another model compatible.
- Treat switching to Kling, Veo, Sora, another Seedance endpoint, another Grok route, or any future model as an adapter migration. Update the capability contract, payload builder, polling/downloading logic, duration and reference limits, audio/lip-sync routing, validation, tests, and real-output QA before enabling paid use. See `references/model-capabilities.md`.

## Core Rules

1. Use Codex's native text and multimodal understanding for topic, script, screenshot, video-frame, audio, subtitle, and reference-image analysis. Do not call a separate LLM or vision API for planning.
2. First output only the decision stage the user needs: topic-selection card for topic-only requests, a complete **text-only** production proposal for selected topics/materials, real production images after plan confirmation, or final delivery after image confirmation. The first production response must be the complete proposal on the primary assistant response surface and must not call imagegen or any paid video API.
3. If the user provides only a topic or direction, start with `topic_planning`: give several angles, explain why each is worth making, and ask the user to choose one before writing the final script.
4. If the user provides a script, draft, video, audio, subtitle, screenshot, or competitor sample, inspect those exact materials first. Review factual fidelity, source trace, content structure, hook, logic, spoken naturalness, professionalism, duration fit, platform tone, and compliance risk. Preserve the user's verified facts and core intent, identify material or script problems, and include a professionally optimized final spoken script in the proposal rather than only giving critique or an outline. Explain meaningful rewrites. If the user explicitly requires verbatim wording, preserve it and flag unresolved issues instead of silently rewriting. Then optimize avatar, scene, delivery, pacing, and platform fit. A supplied subtitle file is offline-only: it may inform the script or a confirmed local burn, but it never enters the video Provider payload. Treat B-roll, title cards, music, masks, transitions, and all other effects as optional choices that require explicit user approval.
5. If the user provides business materials such as PPT, product docs, sales deck, FAQ, SOP, HR onboarding docs, course outline, service policy, local-life/store info, or multilingual source content, identify the business scenario route and build a non-empty `source_fact_map` before writing factual claims. Prepare these projects with `--require-source-fact-map`; every item must be verified before paid generation. Do not treat all materials as generic self-media content or infer policies absent from the source.
6. **TWO-CONFIRMATION CODEX IMAGEGEN CONTRACT:** Stage 1 returns the complete text proposal and asks for plan confirmation. Do not call imagegen in Stage 1. Stage 2 starts only after that confirmation and uses the **Codex built-in image_gen** path from the `imagegen` skill (gpt-image-2/image2) to generate real production assets. Do not add a separate image API, CLI runner, model config, or image API key. Generate only an original digital-human `video_source`, a `first_frame`, an optional `last_frame`, per-segment `segment_source` frames, and an optional `storyboard_sheet`. Never generate a visual confirmation board, review board, wireframe board, or an image whose main content is proposal text.
7. Native imagegen is response-terminal. That is expected in Stage 2 because Stage 1 already delivered the plan. After the generated images are visible, wait for the user's second confirmation: “确认图片并开始制作” or an equivalent explicit instruction. At least one generated asset must be a `video_payload` source role; a `storyboard_sheet` remains `preview_only`. Never use `text(proposal)` inside tool output as a substitute for the Stage 1 primary response, and never treat an image-only first response as success.
8. Use exactly two user confirmations for this production route. Confirmation 1 approves the complete script, final delivery maximum, deterministic segment/model route, visual direction, subtitle choice, effect choices, and the base paid request count, but authorizes no paid call. Subtitles are **default disabled**. The reply “确认方案，需要字幕” is the same Confirmation 1 and records `request_source=user_plan_confirmation`; it is not a third confirmation. A standalone “需要字幕” does not approve the rest of the plan. Confirmation 2 approves the exact generated image assets and authorizes the **autonomous execution contract**. The approved paid cap must equal the base segment count: there is no repair reserve and every segment may be submitted only once. Then prepare, preflight, submit, poll, review, apply no-cost local post-processing when needed, stitch, and finalize with **no additional user confirmation**.
9. Use only user-confirmed script, audio, avatar image, scene image, video source/first-frame image, last-frame target, storyboard sheet, B-roll plan, and reference assets in video generation. Never include an SRT/VTT or another subtitle asset in a video-provider payload. Copy the image assets approved in Confirmation 2 into the project and record their roles, paths, and SHA-256 digests. Never silently swap assets.
10. Video capabilities must come from `assets/templates/model-config.example.json` or a user-supplied video config. Before presenting a production proposal, disclose the selected `model_key`, Provider/model id, `skill_adapter_status`, `verification_level`, supported inputs, and important unsupported features. Image generation follows the installed `imagegen` skill and built-in image_gen behavior. Do not hardcode video reference-image limits, lip-sync support, audio input support, or duration limits in user promises. Never treat a changed model name or base URL as compatibility; a new route requires adapter work and must remain disabled until its config, payload, polling/result mapping, validators, tests, and verification evidence are complete.
11. For normal generated digital-human narration, do not proactively warn the user about lip sync when the selected model has `supports_lipsync=true`; Grok 1.5 and Seedance 2.0 routes can be planned as generated talking-head videos. Only discuss model switching when the user provides external audio and explicitly requires exact audio-driven or frame-level mouth matching that the selected route cannot accept.
12. Existing audio/subtitle/video assets should inform the workflow. Route by `desired_output`, `speech_source`, and `timing_authority`: an existing MP4 enhancement keeps the MP4 timeline; an external-audio-driven new avatar follows the audio timeline. A provided subtitle may inform the offline transcript or a confirmed postproduction burn but never enters the Provider payload. Do not force TTS when the user already provides audio or subtitles.
   - `postproduction_only`: preserve the existing MP4/audio timeline and use editing/B-roll tools; add captions only when Confirmation 1 explicitly enabled the same offline burn contract. This route must never enter paid video generation.
   - `external_audio_generation`: paid generation is allowed only when the confirmed model snapshot supports the audio payload field.
   - `video_generation`: normal model-generated dialogue route.
13. Treat the user's requested duration as the final delivery hard maximum unless the user explicitly approves a different range. First optimize the spoken script to about 85-95% of that delivery window, then choose the **smallest safe number of paid segments** and the deterministic legal request slots that cover it. Multi-segment planning hard-blocks gross underfill below 75%; do not present a 4-8 second speech as a 30-second plan. Every API request duration must be one of the selected model's configured `allowed_durations_seconds`; for the current route that is `4, 6, 8, 10, 12, 15`. A 30-second plan uses `15s + 15s`, even when the copy has three paragraphs; an explicit segment file cannot silently substitute `10+10` or `15+12`. Paragraph count and prettier scene breaks never justify an extra paid segment. If a verbatim or fact-dense script still cannot fit after professional compression, stop the plan and offer two choices: shorten the script, or explicitly change the delivery duration and recalculate the contract. Never silently add a third segment while continuing to promise a 30-second delivery.
14. For single-image image-to-video routes such as official `grok-imagine-video-1.5` or provider alias `grok-video-1.5`, the video source image becomes the first frame. Do not use a 6-grid/9-grid storyboard sheet as the only source image; generate a final source frame or per-segment source frames instead.
15. Apply a **fixed zero-text Provider policy** and an **optional local subtitle policy**. Provider prompts always require clean frames, `subtitle_included_in_payload=false`, and no written/typographic elements; Provider payload must never contain SRT/VTT or a subtitle field. Default delivery has no subtitles. Only the exact `enabled=true + request_source=user_plan_confirmation + confirmation_status=confirmed + provider_policy=never_send + render_policy=postproduction_burn_only` contract authorizes local SRT generation and local burn after the clean MP4 passes `no_generated_text=true`. A model-generated written element is a material Provider defect: block before burn and do not spend on automatic regeneration. Lower thirds, title text, logos, watermarks, speech bubbles, UI text, and background caption bars remain forbidden.
16. Effects are optional. The proposal must ask the user to choose enabled or disabled. When disabled, `visual_insert_policy=model_output_only`: do not add B-roll, title cards, cutaway images, overlays, background masks, progress bars, music, or visual transitions. For one generated clip with effects and subtitles both disabled, deliver the verified clean clip directly; when confirmed subtitles are enabled, the only visual postproduction is the approved local subtitle burn.
17. Before paid generation, calibrate `script_pacing` for safety, not to force every request to fill 15 seconds. Keep estimated speech below about 14.2s in a 15s request and require a brief neutral pause around complete first/final words. When a segment is `too_long`, first rebalance and professionally compress the script inside the already calculated minimum segment count. Add a segment only when the complete approved script truly cannot fit the available safe capacity and the user has approved the resulting longer delivery plan. A complete shorter segment is `short_but_usable`: request the smallest supported slot that safely contains it and remove only verified idle tail during local technical editing; do not pad the script, invent filler, or ask for timing-only approval.
18. For multi-segment videos, each non-final segment must end on a clean sentence boundary, not on "第二，", "风险控制、", or another unfinished clause. Use `script_boundary` and `validate_project.py --enforce-script-pacing` before spending API credits.
19. After generation, run technical and visual review on the clean MP4 first. Multi-segment stitching must not apply per-clip head fades or crossfades over speech; use lossless PCM normalized intermediates and one final AAC encode. Review both directions of every boundary. Delivery always requires `no_generated_text=true` and `no_unapproved_visual_insert=true` on the clean Provider output. When subtitles are enabled, only after that pass may local final-audio transcription and platform-profile burn run. When a confirmed script exists, use its exact words as `lexical_source=confirmed_script` and use local final-audio ASR only for cue timing; retain the raw ASR SRT and hashes so recognition mistakes cannot silently replace confirmed copy. Convert resolution-derived pixel targets into libass script coordinates before burn, visually inspect representative frames, and then require `subtitle_present`, `subtitle_postproduced`, `subtitle_safe`, `subtitle_readable`, `subtitle_matches_speech`, `subtitle_background_absent`, and `no_unapproved_text` on the captioned MP4.
20. Apply the graded speech policy in `references/speech-acceptance.md`. Default factual creator and business/source-bound videos to `critical_facts_exact`; use `semantic_tolerance` for casual creator speech where no wording-specific fact is at risk, and `verbatim_required` only when the user or source requires exact wording. ASR uncertainty never authorizes paid regeneration. Normal production has `repair_reserve=0`, `per_shot_repair_limit=0`, and no automatic provider retry or quality regeneration. Continue polling/downloading the same verified request ID and use no-cost local trim, restitch, encode, or confirmed subtitle re-render fixes, but never submit a shot a second time.
21. API keys belong only in private env files or environment variables. Do not write keys into skills, prompts, tests, request logs, package files, or user reports.
22. For multilingual localization, create one independently confirmed project per target language/locale. Record source language, target language, locale, glossary, and `translation_review_status`; do not preflight paid generation until the localized script is verified.
23. Enter commerce or product-seeding logic only when the user explicitly asks for 带货, 种草, 商业植入, product promotion, or an ad hybrid.

## Content Modes

- `topic_planning`: choose topics and angles.
- `viral_teardown`: analyze competitor viral videos, screenshots, transcripts, titles, and covers.
- `script_rewrite`: 脚本改写 / generate or rewrite platform-native talking-head scripts.
- `avatar_talking_head`: plan digital-human talking-head video generation.
- `hybrid_broll_edit`: keep existing talking-head video/audio and add only explicitly approved B-roll/packaging; captions remain default disabled and may be added only through the confirmed local postproduction path.
- `longform_editing`: structure long videos, chapters, summaries, and short-video slices.

## Resource Map

Read only the files needed for the user's current mode:

- `references/workflow.md`: end-to-end operating flow and confirmation gates.
- `references/content-modes.md`: mode selection and outputs.
- `references/business-scenarios.md`: popular digital-human business scenarios, routing rules, asset analysis, success metrics, and risk boundaries.
- `references/platform-styles.md`: Douyin, TikTok, Xiaohongshu, Bilibili, YouTube Shorts, and YouTube horizontal style rules.
- `references/script-frameworks.md`: hook, body, transition, CTA, caption, and longform script structures.
- `references/script-duration-and-pacing.md`: spoken-duration estimation, per-segment pacing, and fixes for short/long narration.
- `references/viral-teardown.md`: viral-video teardown checklist and reusable-template rules.
- `references/avatar-and-scene.md`: digital-human identity, clothing, expression, scene, camera, and image-generation planning.
- `references/b-roll-and-editing.md`: B-roll timeline, hybrid workflow, editing list, and longform slicing.
- `references/post-generation-review.md`: actual MP4 review, silence/freeze/missing-clip checks, and revise/pass rules.
- `references/speech-acceptance.md`: graded speech-fidelity modes, `pass_with_notes`, ASR uncertainty handling, and zero-automatic-paid-repair rules.
- `references/subtitles-and-safe-layout.md`: fixed Provider no-text policy, optional confirmed local burn, platform profiles, and two-stage QA.
- `references/model-capabilities.md`: supported-model matrix, adapter status, model-switch migration checklist, lip-sync routing, duration splitting, and payload mapping.
- `references/asset-consistency.md`: confirmed assets, reference roles, and dry-run checks.
- `references/proposal-template.md`: user-facing proposal format.
- `references/quality-checklist.md`: final plan and production QA checklist.
- `scripts/prepare_project.py`: create a project manifest and generation plan.
- `scripts/analyze_script_timeline.py`: estimate script timeline and B-roll beats.
- `scripts/validate_project.py`: validate a prepared project before generation.
- `scripts/validate_config.py`: validate model config and private env without leaking secrets.
- `scripts/generate_video.py`: build dry-run payloads and submit confirmed video requests.
- `scripts/poll_video.py`: poll and download finished MP4 files.
- `scripts/stitch_clips.py`: normalize and stitch clips with PCM intermediate audio and one final AAC encode, preserve incoming speech onsets without per-clip fades/crossfades, and safely trim excessive model-generated tail silence while preserving original clips and audit evidence.
- `scripts/subtitle_policy.py`, `scripts/subtitle_runtime.py`, `scripts/generate_subtitles.py`, and `scripts/burn_subtitles.py`: one strict subtitle contract, free local preflight, final-audio SRT creation, and platform-profile burn used only by a confirmed `postproduction_burn_only` plan.
- `scripts/review_render.py`: inspect actual MP4 output, detect tail silence, active boundary audio, generated-text risk, weak script boundaries, freeze, missing clips, and write final-review.json.
- `references/first-response-imagegen.md`: Codex built-in imagegen/image2 two-confirmation orchestration contract: text proposal first, production images after plan approval, then automatic production after image approval.
- `scripts/validate_first_response_trace.py`: offline trace gate that rejects tool-output-only proposals, image generation before plan approval, paid calls before image approval, and extra routine confirmations.
- `scripts/workflow_engine.py`: normal entrypoint for `status`, `preflight`, `confirm`, `submit`, `poll`, `resume`, and `finalize`.
- `scripts/preflight_project.py`: model-aware no-cost gate that creates dry-run records and `production-contract.json`.
- `scripts/_routing.py`: deterministic paid-generation vs postproduction vs external-audio execution routing.
- `scripts/finalize_project.py`: strict release gate that creates `delivery-manifest.json` only after technical and visual review pass.
- `scripts/finalize_postproduction.py`: zero-paid release gate for an existing-video candidate; optional captions still require clean-first review and the confirmed local-burn contract.
- `assets/templates/postproduction-manifest.example.json`: evidence template for approved non-text edits applied by the selected editing tool.
- `assets/templates/postprocess-manifest.example.json`: immutable audit template for no-cost trim, stitch, encode, clean/caption review, and an optional approved local subtitle operation; it must always show zero added paid requests.

## Operating Flow

1. Classify the user's input into one or more content modes.
2. Read `workflow.md` and the matching mode reference. Read `business-scenarios.md` when the user provides business materials, asks for a professional方案, or the business purpose is not obvious. Read `model-capabilities.md` only when model choice, lip sync, audio input, duration, or API payload matters.
3. Inventory provided assets and set `desired_output`, `speech_source`, and `timing_authority`: script, topic, avatar reference image, existing video, audio, subtitle file, screenshots, competitor links, brand/IP style, platform, duration, language, and target audience.
4. Identify the business scenario route, user intent, success metric, and risk boundary before writing the first proposal. If the route is unclear, state a best-guess route and the assumptions behind it.
5. Optimize the full spoken script, then run `prepare_project.py --duration-plan-only` with that script, the confirmed delivery maximum, language, content mode, and selected config. Use its deterministic minimum segment count, legal request slots, estimated speech, complete boundaries, and `duration_plan_digest` in Stage B1 from `proposal-template.md`; never hand-count paragraphs. If the minimum paid segment count cannot preserve complete strong sentence boundaries, rewrite the editable script professionally and rerun the planner instead of converting a comma or unfinished clause into a period. Write a real `proposal.md`. Business-source proposals include a checkable `source_fact_map`. Send the complete proposal as the primary assistant response, set `stage=awaiting_plan_confirmation`, `proposal_delivered=true`, `plan_confirmed=false`, `image_assets_confirmed=false`, and `paid_video_authorized=false`; do not call imagegen.
6. In the proposal, list only necessary real image assets, their exact prompts, source references, display order, and `video_payload`/`preview_only` usage. Ask the user once to confirm the plan.
7. After Confirmation 1, set `stage=awaiting_image_confirmation`, `plan_confirmed=true`, and use built-in gpt-image-2/image2 to generate at least one real source asset for the selected video route. Add a storyboard sheet only when it materially helps review shot flow. The image response may be response-terminal; the already-delivered Stage B1 proposal must not be repeated or hidden in tool output.
8. Ask the user to confirm or revise the visible images. Image-only revisions do not reset plan confirmation when script, model route, creative scope, and paid cap are unchanged. Any material plan drift returns to Stage B1.
9. Confirmation 2 must explicitly approve the exact images and start production. Set `stage=production_authorized`, `image_assets_confirmed=true`, and `paid_video_authorized=true`. Copy selected images from `$CODEX_HOME/generated_images/...` into the project and bind their exact SHA-256 digests.
10. Run `prepare_project.py` with the twice-confirmed values and require its `duration_plan_digest` to equal the Stage B1 confirmed digest. Run `workflow_engine.py preflight`, then bind that digest, the exact approved assets, and the contract digest in immutable `video-confirmation.json`. An exact rerun may reuse protected evidence; a changed script, request slot, asset, model, delivery maximum, or contract requires a new independently confirmed project.
11. Run `workflow_engine.py confirm`, `submit`, and `resume` under the base-only paid cap without a third routine confirmation. `resume` may continue polling or downloading an existing request ID, but it must not create a second POST for any attempted shot.
12. Run `workflow_engine.py finalize`, inspect the clean candidate and boundaries, and perform only no-cost local post-processing. If subtitles are enabled, first bind a passing clean Provider review, then generate timing from the final audio (or use the confirmed supplied SRT), burn the platform profile, and review the captioned result. A subtitle-only issue may trigger a free local re-render, never another paid Provider request. Deliver when `delivery-manifest.json.status=pass`; a material Provider-output defect blocks before subtitle burn.

## Production Proposal Fields

Include these only after a topic is selected or sufficient source material exists. Do not force them into a topic-selection response.

- mode and why that mode fits;
- business scenario route, user intent, success metric, and risk/compliance boundary;
- platform, audience, content goal, pain point, hook, value, and share reason;
- topic options when the user has not chosen a topic;
- title options and why they fit the platform;
- supplied-material review: what was provided, what controls facts/timing/visual identity, missing evidence, and any unusable or conflicting asset;
- script professional review: preserved intent/facts, concrete problems, rewrite decisions, and the professionally optimized final spoken script in full;
- script structure: opening hook, body beats, transitions, audio-only key points, CTA, spoken-duration estimate, and segment boundaries;
- deterministic duration rule: optimize the script inside the final delivery maximum, choose the minimum paid segment count, quantize each request to a configured supported duration, and trim only verified idle tail;
- avatar identity: face/style boundary, clothing, hair, expression, posture, delivery style, background, and framing;
- camera style: half-body fixed shot, close talking-head, light push-in, interview feel, studio feel, lesson feel, or desktop teaching feel;
- effects choice: disabled or the exact approved effects/B-roll list;
- subtitle policy: default disabled; if the user confirms with “确认方案，需要字幕”, record the exact confirmed contract from Core Rule 15; Provider prompt and Provider payload remain text/subtitle-free;
- language, aspect ratio, resolution, duration, and model route;
- model compatibility disclosure: selected model key, Provider/model id, `skill_adapter_status`, `verification_level`, supported inputs, unsupported Provider features, and whether this exact route is runtime-verified;
- speech fidelity mode: `semantic_tolerance`, default factual `critical_facts_exact`, or explicitly requested `verbatim_required`, plus the critical terms/facts that must remain exact;
- generated talking-head/audio route; only mention external-audio lip-sync limits when the user explicitly requires exact audio-driven mouth matching;
- planned generated images, exact prompts, their source references, `video_payload` versus `preview_only` roles, and confirmed assets that will enter the video payload;
- autonomous execution contract: base request count, `repair_reserve=0`, `per_shot_repair_limit=0`, approved paid cap equal to the base count, automatic no-cost post-processing authority, and hard stop conditions;
- first confirmation request covering the full text plan and paid cap but authorizing no image/video spend;
- second confirmation request covering the exact generated images and authorizing automatic production within the already approved cap.

## Commerce Boundary

This skill is not a product-ad skill by default. If the user explicitly asks for 带货, 种草, 商品广告, product selling, or commercial insertion, treat it as a `commerce_hybrid` add-on: keep self-media trust and content value first, then place the product naturally. For pure product ads, prefer the existing `ai-commerce-video` skill.
