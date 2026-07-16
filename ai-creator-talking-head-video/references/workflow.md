# Workflow

## Contents

- Codex-native planning, input inventory, and mode routing
- Plan confirmation and image confirmation gates
- Autonomous continue-to-delivery loop
- Production steps and completion standard

Use this workflow for self-media digital-human talking-head videos, creator IP videos, knowledge explainers, AI tool commentary, news/opinion videos, interview-style clips, course explainers, enterprise training, product explainers, sales enablement, customer service FAQ, HR onboarding, internal communications, multilingual localization, local-life guides, and existing talking-head footage that needs B-roll and packaging.

## Codex-Native Planning

Use Codex itself for:

- understanding topics, scripts, subtitles, screenshots, reference images, and provided video/audio context;
- choosing topic angles and platform strategy;
- rewriting scripts and shot rhythm;
- designing avatar, scene, and necessary source/storyboard prompts, plus optional non-text effects only when the user requests them;
- reviewing generated images before any paid video request.

When the user supplies a script or source material, planning starts from those exact inputs. Inventory each asset, preserve verified facts and the user's intent, diagnose weak or unsupported content, and write the complete professionally optimized spoken script before designing generated visuals.

Use external video APIs only as the rendering step after the user confirms the plan and generated/reference assets.

## Input Inventory

Record what the user provided:

- topic or direction;
- full script or rough draft;
- digital-human, avatar, or real-person reference image;
- existing talking-head video, audio, or subtitle file;
- competitor viral video link, screenshot, title, cover, transcript, or notes;
- business materials such as PPT, PDF, FAQ, SOP, product page, sales deck, HR onboarding docs, service policy, course outline, local-life/store information, brand guide, or multilingual source content;
- target platform, duration, language, aspect ratio, and resolution;
- desired creator persona: knowledge blogger, AI tool blogger, news commentator, course teacher, interview host, professional studio, lifestyle creator, or tech creator;
- target viewer and business goal: learner, employee, prospect, customer, applicant, visitor, fan, completion, conversion, support, onboarding, brand trust, or localization;
- whether the user supplied external audio and needs exact audio-driven mouth matching.

If information is missing, make a conservative assumption and label it. Do not turn the first response into a long interview.

## Mode Routing

Before selecting a mode, identify the business scenario route from `business-scenarios.md` when the request includes business materials or a professional commercial/service context.

Set these route controls before proposing execution:

- `desired_output`: topic options, script, new avatar video, existing-video enhancement, localized version, or final packaged delivery;
- `speech_source`: generated dialogue, user script, existing video audio, external audio, or no speech;
- `timing_authority`: target duration, existing MP4, external audio, user SRT, or confirmed segment file.

An existing MP4 enhancement and a new avatar driven by external audio are different routes even when the same MP4, SRT, and audio files are provided. The first keeps the MP4 as timing authority and does not regenerate the speaker. The second uses the external audio as timing authority and requires a model route that accepts audio.

Record one deterministic `execution_route`:

- `postproduction_only`: preserve the existing MP4/audio timeline, expected paid video-generation requests `0`, and use editing/B-roll tools instead of `submit`; captions remain default disabled and may be added only by the confirmed local-burn route;
- `external_audio_generation`: generate a new avatar only when the confirmed model snapshot has `supports_audio_input=true` and a real `audio_field`;
- `video_generation`: normal model-generated dialogue route.

If a user SRT is supplied, it may be offline transcript/reference material or the timing source for a confirmed local burn. It cannot be the paid-generation timing authority and must never enter a Provider payload. Use approved external audio when timing must drive Provider generation. A warning is not enough to spend credits.

For `postproduction_only`, follow `postproduction_plan`: keep the source MP4 and speech timeline, apply only the exact approved effects, render `<project>/final.postproduced.mp4`, then run `workflow_engine.py finalize`. Unapproved text overlays, caption masks/background bars, B-roll, and title cards are forbidden. A confirmed subtitle-only project may use the unchanged source as its clean candidate, then burn locally after clean review. Do not create a paid-generation contract or confirmation.

1. Topic only -> `topic_planning`.
2. Competitor example -> `viral_teardown`.
3. Draft or topic with desired script -> `script_rewrite`.
4. Avatar/digital-human video generation -> `avatar_talking_head`.
5. Existing video/audio/subtitle -> `hybrid_broll_edit`.
6. Long script/audio/video -> `longform_editing`.

Many real tasks use two modes, such as `viral_teardown + script_rewrite`, or `script_rewrite + avatar_talking_head`.

For business tasks, also name the scenario route, user intent, success metric, and risk boundary in the first proposal. Example: "客户服务 FAQ -> help users finish refund steps, success metric is fewer repeated support questions, risk boundary is official policy accuracy."

When factual business materials are involved, build `source_fact_map` entries before final script approval. Each entry records a checkable source locator, source text, preserved fact, allowed rewrite, forbidden inference, script beat, and verification status. Every entry must be `verified`; `needs_user_confirmation` and `missing_source` block paid preflight.

For localization, create one independently confirmed project per target language/locale. Record `source_language`, `target_language`, `target_locale`, optional glossary, and `translation_review_status`. Do not preflight paid generation until the localized script and terminology are `verified`.

## Plan Confirmation Gate

The first production decision is a complete text proposal on the primary assistant response surface. Use `first-response-imagegen.md` as the binding orchestration contract. Do not call imagegen or any paid video API in this first response.

Before writing the segment count in that proposal, run the shared offline planner. It creates no project, reads no API key, and makes no network request:

```bash
python3 ai-creator-talking-head-video/scripts/prepare_project.py \
  --name proposal-duration-check \
  --content-mode avatar_talking_head \
  --duration 30 \
  --language zh \
  --script-file <optimized-script.md> \
  --config ai-creator-talking-head-video/assets/templates/model-config.example.json \
  --duration-plan-only
```

Copy its `delivery_max_seconds`, `allowed_durations_seconds`, `minimum_paid_segment_count`, request slots, estimated spoken durations, complete script boundaries, and `duration_plan_digest` into Stage B1. The digest binds the selected model route, delivery maximum, legal duration list, exact request slots, and exact text in every segment. The later normal `prepare_project.py` run must return the same digest; any mismatch is contract drift.

The planner must never manufacture a strong boundary by changing a comma, list separator, open enumerator, or unfinished clause into a period. When the editable source cannot fit the minimum paid segment count at complete strong sentence boundaries, professionally shorten/rewrite it first and rerun `--duration-plan-only`. For fact-bound or verbatim text that cannot be rewritten safely, block before image or video spend and ask the user to shorten the wording or explicitly extend the delivery maximum.

For a user who supplied a script, draft, reference image, business document, screenshot, audio, subtitle, or video, the first proposal must:

- inventory every supplied asset and state whether it controls facts, timing, avatar identity, scene, or platform style;
- diagnose factual, structural, professional, spoken-language, pacing, platform, and compliance problems;
- preserve supported facts and intended meaning, while flagging unsupported claims instead of polishing them into stronger claims;
- provide the optimized full spoken script, not only an outline or a list of suggested edits;
- run the same no-cost deterministic duration planner used by `prepare_project.py` before stating the segment count; never estimate the paid segment count from paragraph count;
- show meaningful changes from the user's draft and explain why they improve the result;
- include exact prompts for every proposed generated image and label each planned image as `video_payload` or `preview_only`;
- explain that actual images are generated only after the user confirms this plan;
- plan a multi-grid storyboard only when useful, label it `preview_only`, and never treat it as the single source image for a one-image video route.

The complete proposal text must show:

- final script, estimated spoken duration, and final delivery hard maximum;
- the subtitle choice: default disabled; “确认方案，需要字幕” records `user_plan_confirmation` and authorizes only local postproduction burn, while Provider output and payload always remain text-free;
- whether effects are `enabled` or `disabled`; disabled means no B-roll, title card, cutaway, overlay, mask, music, or transition;
- the clean `video_source`/`first_frame`, any genuinely necessary `segment_source` frames, and preview-only storyboard sheet;
- model maximum duration, configured `allowed_durations_seconds`, minimum safe segment count, exact API request slots, expected local tail trim, and complete sentence boundaries;
- expected base paid request count and maximum paid submissions; these two values must be equal because normal production has no paid repair reserve.

Before finishing the first response, record `stage=awaiting_plan_confirmation`, `proposal_delivered=true`, `plan_confirmed=false`, `image_assets_confirmed=false`, and `paid_video_authorized=false`. A bare image, proposal text only in collapsible tool output/commentary, or an incomplete script is invalid. Confirmation 1 approves the plan and image generation only; it authorizes no paid video call.

## Image Confirmation Gate

After Confirmation 1, set `stage=awaiting_image_confirmation` and use the installed `imagegen` skill plus Codex built-in image_gen/image2 path. Generate only real production art, not confirmation boards, review boards, wireframes, or storyboard-only bundles. At least one result must be a `video_payload` `video_source`, `first_frame`, or `segment_source`; a storyboard sheet is `preview_only`.

The Stage 1 proposal must already tell the user to reply “确认图片并开始制作” or request image changes, because imagegen can be response-terminal. Do not repeat or hide the proposal in `functions.exec`. Image-only revisions retain plan confirmation if the script, model, creative scope, and paid cap do not change. Image generation failure blocks the flow here and never authorizes a video call.

Confirmation 2 approves the exact images and authorizes production. Copy the selected outputs from `$CODEX_HOME/generated_images/...` into the project, record roles, paths, and SHA-256 digests, set `stage=production_authorized`, and pass the Stage B1 digest as `--confirmed-duration-plan-digest` when creating the confirmation. The confirmation, production contract, dry-run evidence, jobs ledger, paid request records, poll records, and provider clips become protected production evidence. Exact idempotent reruns may reuse them; changed state must block instead of overwriting them. Automatic content-preserving local timing changes do not require another approval and do not change the confirmed duration plan.

## Continue-To-Delivery Loop

The user's second confirmation creates the autonomous execution contract. Confirmation 1 approves the plan but authorizes no paid video call. Confirmation 2 approves the exact images and start command; it binds the base paid request count, `repair_reserve=0`, `per_shot_repair_limit=0`, and an approved paid cap exactly equal to the base count. It also authorizes no-cost local editing and technical post-processing. It never authorizes a second paid POST for the same shot.

After confirmation, continue through `preflight -> confirm -> submit once per base shot -> poll/resume the same request ids -> clean finalize/review -> optional confirmed local subtitle burn -> captioned review -> delivery`. Do not send internal approval questions for ordinary polling, downloading, stitching, restitching, re-encoding, or a confirmed local subtitle rerender.

Pause and report a blocker only when safe automatic continuation is impossible: the production contract changed; a paid submission is ambiguous and cannot be recovered through a verified request id/idempotency path; the provider declares a terminal failure; quality review finds a material provider-output defect that local processing cannot fix; a rights, safety, or source-fact issue is unrecoverable without new information; or the provider/auth route is unavailable. These are exception reports, not routine approval rounds. A later user-requested regeneration is a new independent paid authorization, not part of this normal workflow.

## Production Steps

After the second user confirmation:

1. Prepare the project with the confirmed model, source assets, business context, and complete script. `--segments-file` may suggest semantic breaks, but it cannot bypass supported duration slots, the delivery maximum, or the minimum-segment calculation. First optimize and balance the script inside the minimum safe segment count; do not create an extra paid shot merely to preserve the user's original paragraph breaks.

   ```bash
   python3 ai-creator-talking-head-video/scripts/prepare_project.py \
     --name ai-tool-news-commentary \
     --content-mode avatar_talking_head \
     --platform douyin \
     --language zh \
     --duration 30 \
     --subtitle-choice disabled \
     --effects-choice disabled \
     --aspect-ratio 9:16 \
     --resolution 720p \
     --script-file script.md \
     --avatar-reference avatar.png \
     --video-source-image approved-first-frame.png \
     --storyboard-image storyboard-sheet.png \
     --business-scenario "enterprise training" \
     --user-intent "help employees understand the workflow" \
     --success-metric "employees can finish the checklist without repeated support" \
     --risk-boundary "must stay faithful to the approved SOP" \
     --subtitle-strategy "no subtitles"
   ```

2. Run the central no-cost preflight:

   ```bash
   python3 ai-creator-talking-head-video/scripts/workflow_engine.py \
     --project-dir <project> \
     preflight \
     --config ai-creator-talking-head-video/assets/templates/model-config.example.json
   ```

   Preflight reruns project validation, checks resolution/aspect ratio/duration against the selected model, writes one dry-run request per shot, snapshots the redacted model config, and creates:

- `<project>/preflight-report.json`;
- `<project>/model-snapshot.json`;
- `<project>/requests/dry-run/shot_*.json`;
- `<project>/production-contract.json`.

3. Compare the dry-run summary to the user's twice-confirmed package. Continue automatically only when the script, exact image digests, model route, creative choices, delivery maximum, exact request slots, base segment count, approved paid cap, and `duration_plan_digest` match. A change from two confirmed requests to three—or from two to one—is contract drift and must never be hidden as an internal timing adjustment. Preflight may reuse an identical existing contract, but it must not overwrite a changed contract, model snapshot, or dry-run request after confirmation/jobs state exists. Record:

   - `visual_bible`: the fixed avatar, scene, camera, zero-written-text, B-roll, aspect-ratio, and resolution rules;
   - `image_consistency_plan`: whether the model uses one source image, per-segment source frames, or multi-reference guidance;
   - `longform_generation_strategy`: segment count, segment order, duration, focus, and script beat for each clip;
   - `script_pacing`: estimated spoken duration for each segment. Speech above one segment's safe capacity is first rebalanced or professionally compressed inside the confirmed minimum count; complete shorter speech is `short_but_usable` and its verified idle tail may be trimmed after generation. If the whole script still cannot fit, block rather than add an unconfirmed paid shot;
   - `script_boundary`: whether every non-final segment ends on a clean sentence boundary instead of an unfinished phrase;
   - `subtitle_plan`: either the default-disabled empty-output policy, or the exact confirmed `enabled + user_plan_confirmation + confirmed + never_send + postproduction_burn_only` policy with clean/SRT/audit/captioned paths and a platform profile;
   - `stitching_plan`: clip order, normalization target, final MP4 path, and stitch report path.
   - `duration_plan.request_duration_seconds`, `estimated_spoken_seconds`, `estimated_natural_pause_seconds`, `estimated_delivery_seconds`, `delivery_max_seconds`, `planned_request_total_seconds`, `planned_trim_seconds`, and `planned_delivery_overshoot_seconds` so provider slots, removable idle time, and any hard-cap overrun cannot be confused.

   Do not approve paid generation if segments use unapproved assets, a request duration is outside `allowed_durations_seconds`, an explicit segment file changes the minimum paid count or substitutes a shorter deterministic slot, whole-plan multi-segment spoken fill is below 75%, source-frame mapping is invalid, speech is still over model capacity, speech is missing, any non-final boundary is unsafe, or the final delivery plan exceeds the confirmed maximum. Do not block merely because one complete segment is shorter than its supported request slot when the whole plan remains reasonably filled.

4. Bind the user's second visible approval to the matching production contract:

   ```bash
   python3 ai-creator-talking-head-video/scripts/workflow_engine.py \
     --project-dir <project> \
     confirm \
     --approved-by user \
     --confirmation-intent confirm_images_and_start \
     --confirmed-duration-plan-digest <Stage-B1-duration-plan-sha256> \
     --confirmed-asset-digest <64-character-sha256-for-each-video-payload-image> \
     --max-paid-submissions 2
   ```

   `--approved-by` alone is never sufficient. The machine confirmation requires the second-confirmation intent, the Stage B1 `duration_plan_digest`, plus the exact SHA-256 of every payload image. The duration digest must equal both the normal plan and `production-contract.json`; image digests must equal the contract fingerprints. The confirmation also contains the contract digest, base paid request count, zero repair reserve, zero per-shot repair limit, an approved paid cap equal to the base count, and automatic no-cost post-processing authority. Changing the script, model, resolution, assets, image digests, duration plan, or dry-run request invalidates it.

5. Submit with an explicit paid-generation budget:

   ```bash
   python3 ai-creator-talking-head-video/scripts/workflow_engine.py \
     --project-dir <project> \
     submit --max-paid-submissions 2
   ```

   `jobs.json` records `planned -> submitting -> submitted -> polling -> downloaded -> verified`. A project-level file lock prevents two local submitters from running at once, and each shot sends a stable best-effort idempotency header. A process interruption in `submitting`, a failed attempt with no verified request id, or a terminal provider result is a hard safety stop rather than a reason to risk another charge. Any shot with `submission_attempts > 0` is permanently ineligible for another POST in this contract. Completed shots are skipped; submitted shots keep their original request ID for polling and download recovery.

6. Poll or resume:

   ```bash
   python3 ai-creator-talking-head-video/scripts/workflow_engine.py \
     --project-dir <project> poll --require-audio

   python3 ai-creator-talking-head-video/scripts/workflow_engine.py \
     --project-dir <project> \
     resume --max-paid-submissions 2 --require-audio
   ```

7. Build the review candidate and run technical review. A one-shot project with effects disabled preserves the original verified clean model clip; stitching is used only when multiple clips exist:

   ```bash
   python3 ai-creator-talking-head-video/scripts/workflow_engine.py \
     --project-dir <project> finalize
   ```

   Finalization checks every planned clip, normalizes and stitches at the model-declared resolution, removes only safely detected excessive tail silence, preserves segment-head phonemes, and creates the clean MP4. When subtitles are disabled, that verified clean MP4 is the delivery candidate. When enabled, finalization first requires `final-review.clean.json` plus `visual-review.clean.json`; only a passing clean review can create the local SRT and `final.captioned.mp4`. In `postproduction_only`, record the confirmed subtitle burn as `planned`; the finalizer changes it to `applied` only after the captioned output and its hashes exist. It verifies every paid request/poll/clip chain and never changes the paid contract.

8. Inspect the clean candidate and sampled boundary frames. Write `visual-review.clean.json` for an enabled subtitle plan, otherwise `visual-review.json`. Confirm identity, outfit, scene, framing, mouth visibility, speech, `no_generated_text`, and `no_unapproved_visual_insert`, bound to the exact path and SHA-256. After local burn, write the final `visual-review.json` and additionally require the subtitle origin, presence, safe zone, readability, speech match, transparent background, and no unapproved text fields.

9. If review finds an edit defect, automatically restitch, re-encode, or trim verified idle tail and review again. A confirmed subtitle timing/layout defect may be corrected by a free local rerender. Provider text, missing audio, corrupt media, or a material fact/safety defect blocks qualified delivery. Do not call the generation endpoint again in any of these branches.

## Completion Standard

Do not report completion because a request was submitted or a partial preview exists. Completion requires `delivery-manifest.json.status=pass`, an exact final path/digest, passing technical and visual reviews, a passing hard duration check, `no_generated_text=true` on the clean Provider output, all jobs verified, and exactly one paid submission per base shot. Enabled subtitles additionally require clean-review evidence, SRT/burn audits, `paid_api_call=false`, and a passing captioned review.
