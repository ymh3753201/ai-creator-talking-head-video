# Quality Checklist

## Contents

- Plan and scenario quality
- Avatar and editing quality
- Multi-segment consistency
- Safety, configuration, and final delivery

## Plan Quality

- The plan is not just a title list.
- The first assistant response contains the complete text proposal on the primary assistant response surface and makes no imagegen or paid video call; an unexplained image-only result fails.
- Proposal text, full optimized script, planned image role labels, and the first plan-confirmation request exist on the primary assistant response surface, not only in tool output or progress commentary.
- `proposal_in_tool_output_only`, `empty_final_after_image`, an image before plan confirmation, a mismatched image or duration-plan digest, an incomplete production loop, or an extra routine confirmation fails trace validation.
- Stage 1 records `proposal_delivered=true`, `plan_confirmed=false`, `image_assets_confirmed=false`, and `paid_video_authorized=false`.
- After plan confirmation, Stage 2 generates actual gpt-image-2 production images and waits for explicit image confirmation.
- The Stage 2 response shows real production images after plan confirmation. External image APIs, extra image API keys, confirmation boards, proposal-text images, wireframes, and storyboard-only bundles fail.
- Every user-supplied script, image, document, audio, subtitle, or video is inventoried and assigned a factual, timing, identity, scene, or style role.
- The plan diagnoses unsupported facts, structural weakness, hook, logic, spoken naturalness, professionalism, platform fit, compliance, and duration/pacing before rewriting.
- The optimized full spoken script is present and production-ready; an outline, critique, or edit list alone does not pass.
- Meaningful rewrites preserve verified facts and intent, explain important changes, and flag unsupported claims rather than inventing evidence.
- The plan identifies the business scenario route before choosing script, avatar, B-roll, and model steps.
- The plan states user intent, target viewer, success metric, and risk/compliance boundary.
- Business materials such as PPT, FAQ, SOP, sales deck, HR docs, or product pages are not treated as generic self-media drafts.
- Factual business scripts include a `source_fact_map`; required facts have checkable locators and no `missing_source` status.
- It explains platform fit and audience reason.
- It includes hook, body, transitions, CTA, the Provider no-text rule, the default-disabled/optional-local subtitle choice, and an explicit effects choice.
- It records `speech_fidelity_mode`; factual creator and business speech defaults to `critical_facts_exact`, casual non-fact-sensitive speech may use `semantic_tolerance`, and exact-wording projects use `verbatim_required`.
- It does not plan B-roll, title cards, masks, or other effects unless the user enables them.
- It records either default-disabled subtitle fields or the full same-confirmation contract: `enabled + user_plan_confirmation + confirmed + never_send + postproduction_burn_only`; no third confirmation is added.
- It clearly separates self-media content from product advertising.
- It does not add unnecessary lip-sync warnings for normal generated talking-head routes.

## Scenario Fit

- Training and course videos include learning objectives, chapter flow, examples, recap, and next action.
- Customer service or FAQ videos include direct answer, steps, exceptions, and official service path.
- Product explainer and sales videos connect pain point, proof, demo/B-roll, objection handling, and CTA.
- HR/internal communication videos clearly state who is affected, what changed, what to do, and deadline/path.
- High-compliance topics use conservative wording, source-aware claims, and disclaimers instead of definitive advice.
- Local-life, real-estate, auto, travel, and venue videos are grounded in real user-provided assets.
- Multilingual localization preserves visual identity while adapting spoken wording, CTA, and examples; captions remain default disabled and may be locally burned only when confirmed.

## Avatar Quality

- Avatar identity is original or permission-safe.
- Clothing, hair, temperament, expression, posture, and delivery are described.
- Face and mouth are not blocked by B-roll or confirmed postproduction subtitles; unapproved text overlays are absent.
- Scene matches content purpose.

## Editing Quality

- Script is split into timeline beats.
- Fixed-duration scripts include `script_pacing` estimates before paid generation.
- New generated videos have `duration_plan.source=user_confirmed`; a model default cannot enter paid generation without duration confirmation.
- The user's confirmed duration is stored as `delivery_max_seconds` and never silently expands during planning or post-processing.
- A confirmed duration at or below the model limit creates one shot. An explicit segment file cannot force extra paid shots when the script safely fits one.
- The proposal and `generation-plan.json` use the same deterministic minimum-segment calculation.
- Stage B1 exposes a valid `duration_plan_digest`; the normal generation plan, preflight contract, second confirmation, paid submit gate, and final delivery all bind that exact digest.
- The full editable script is optimized to roughly 85%-95% of the delivery window before segmentation; paragraph count does not determine paid request count.
- A multi-segment script below 75% total spoken fill fails offline instead of producing a grossly underfilled target; single complete short clips may still use `short_but_usable` and local idle-tail trim.
- Every request uses a value from the model's `allowed_durations_seconds`; for the bundled current route `11`, `13`, and `14` fail offline.
- A safe 30-second plan uses two 15-second requests. One/three segments or legal-but-shorter substitutions such as `10+10` and `15+12` fail unless the user explicitly changes the delivery maximum and the complete contract is recalculated.
- Multi-segment scripts include `script_boundary` and each non-final segment ends on a complete sentence or natural transition.
- No automatic splitter turns a comma, list separator, open enumerator, or unfinished clause into a period. When the minimum paid count cannot preserve complete strong boundaries, editable copy is professionally rewritten before the proposal; fact-bound/verbatim copy blocks before spend.
- Generated straight talking-head segments keep a normal 15s request at or below about 14.2s estimated speech. A complete shorter segment is `short_but_usable`, not a blocker, and verified idle tail is automatically trimmed.
- Every beat preserves the generated talking-head video by default; optional visual inserts are listed only when approved.
- Existing audio may drive timing; subtitle assets may inform offline transcription or a confirmed local burn only.
- `execution_route` prevents an existing-video enhancement project from entering paid generation.
- External audio timing is blocked unless the selected model accepts the audio payload field; external subtitle timing is always blocked for paid generation.
- Every `source_fact_map` entry and localized script review is verified before paid preflight.
- Longform plans include chapters and short-video slice suggestions.

## Multi-Segment Consistency

- Requested duration is compared with the selected model's `max_duration_seconds`.
- `minimum_required_segment_count` equals the actual base paid request count; prettier scene changes and original paragraph boundaries cannot increase it.
- `request_duration_seconds`, `estimated_spoken_seconds`, `estimated_natural_pause_seconds`, `estimated_delivery_seconds`, `delivery_max_seconds`, `planned_request_total_seconds`, `planned_trim_seconds`, and `planned_delivery_overshoot_seconds` are separate fields; `delivery_fit_status=ok` is mandatory, and any discrete-slot overshoot must be covered by safe removable idle time.
- Over-limit videos have `longform_generation_strategy.segment_count > 1`.
- One `visual_bible` controls avatar identity, source assets, scene style, camera framing, the zero-written-text rule, aspect ratio, and resolution.
- `image_consistency_plan.strategy` is clear: shared source frame, per-segment source frames, or multi-reference storyboard.
- Single-image routes use an approved `video_source`, `first_frame`, or current segment's `segment_source` as the real source image.
- Multi-panel storyboard sheets are not used as the only source image for single-image routes.
- Every shot includes `segment_index`, `segment_count`, `segment_focus`, `script_segment`, and `continuity_contract`.
- Every shot includes `script_pacing`; automatic planning first rebalances/compresses copy inside the minimum count, and no shot is `too_long` or `missing_script` before paid generation. `short_but_usable` is allowed. If the script still cannot fit, preflight blocks instead of silently adding a segment beyond the confirmed plan.
- Every non-final shot includes `script_boundary.stitch_safe=true`; do not generate if a segment ends on an unfinished clause, list separator, or open enumerator.
- Dry-run creates one request file per segment and each request reuses the same confirmed avatar/source assets.
- If `per_segment_source_frames` is used, dry-run shows the matching `segment_source` for each shot.
- Stitching uses `scripts/stitch_clips.py` to normalize clips before concat.
- `scripts/review_render.py` checks the actual final or partial MP4 after stitching.
- The actual final MP4 is hard-blocked above `delivery_max_seconds` except for the fixed one-frame container/probe allowance; the normal percentage tolerance never relaxes this maximum.
- `final-review.json` status is `pass` before final delivery; `revise` means no-cost local trim, restitch, or re-encode first. It never grants paid regeneration authority.
- `visual-review.json` status is `pass` or `pass_with_notes` and confirms identity, outfit, scene, framing, mouth visibility, delivery-level lip sync, `no_generated_text=true`, and complete spoken content.
- Final review checks there is no sudden face, outfit, scene, ratio, audio-style, or written-text jump across segment boundaries.
- Multi-segment stitching uses PCM normalized intermediate audio, no per-clip fade/crossfade, and one final AAC encode.
- Final review compares every incoming source clip's first 100ms with the final boundary; final-edit onset attenuation is a local `revise`, while a material defect already present in the isolated provider clip blocks qualified delivery. Minor non-semantic differences use `pass_with_notes` when meaning and required facts remain intact.
- Final review requires `no_generated_text=true` and `no_unapproved_visual_insert=true`.
- Every Provider frame must be free of subtitles, text, logos, and watermarks; `no_generated_text=false` blocks before local burn. Final captioned frames may contain only the separately approved postproduced captions.
- Final review checks missing clips, clip-count mismatch, duration mismatch, tail silence, active audio at stitch boundaries, weak script boundaries, generated text, frozen frames, and stitch report.

## Safety And Config

- No API key is written to skill files, tests, logs, request JSON, or packages.
- Model capability claims come from config.
- Dry-run occurs after the user's second visible confirmation and before paid generation.
- Confirmation 1 covers script, duration, visual direction, subtitle choice, effects choice, model, segment strategy, and paid cap, but authorizes no paid video call.
- Confirmation 2 covers the exact generated/reference images and authorizes production within the already approved paid cap.
- The confirmation records base paid requests, `repair_reserve=0`, `per_shot_repair_limit=0`, approved paid cap equal to the base count, and automatic no-cost post-processing authority. It contains no targeted quality/provider regeneration authority.
- No ordinary post-confirmation step asks the user to approve polling, downloading, stitching, technical review, restitching, re-encoding, or a confirmed no-cost subtitle rerender.
- Post-confirmation hard stops include production-contract drift, ambiguous paid submission without verified request-id recovery, provider terminal failure, a material provider-output defect, unrecoverable safety/rights/source-fact issues, or provider/auth outage.
- Codex built-in imagegen outputs are generated only after Confirmation 1 and never authorize a paid video call by themselves.
- `proposal_delivered=true` requires the complete proposal on the primary assistant response; tool output and an image-only first response never qualify.
- `paid_video_authorized=true` requires Confirmation 2 plus exact confirmed image paths and SHA-256 digests.
- `create_confirmation.py` rejects `--approved-by` alone; it requires `confirm_images_and_start` and an exact digest match against every production-contract payload image.
- Exactly two user confirmations are used; no ordinary third confirmation is requested before submit, polling, stitching, review, no-cost local post-processing, or delivery.
- Unsupported external-audio lip sync is called out clearly only when the user explicitly requests exact uploaded-audio mouth matching.
- `ready_for_paid_generation` is false when avatar/source assets still need confirmation.
- Request payloads follow configured field names and payload formats.
- Multi-reference payloads merge source and reference images without dropping the confirmed source image.
- Multi-segment plans include `visual_bible`, `longform_generation_strategy`, and `stitching_plan`.
- Multi-segment plans include `image_consistency_plan` and `visual_asset_strategy`.
- Multi-segment paid generation is blocked when `validate_project.py --enforce-script-pacing` finds missing/over-capacity speech, unsupported request slots, more than the minimum paid segments, a delivery-limit overrun, or unsafe boundaries—not merely because a clip is shorter than the model maximum.

## Final Delivery

- Manifest exists.
- Generation plan exists.
- Request payload exists after dry-run.
- `production-contract.json` binds the exact plan, model snapshot, assets, and dry-run request digests.
- `production-contract.json`, `model-snapshot.json`, dry-run requests, and `video-confirmation.json` are immutable after protected confirmation/jobs state exists; only an exact idempotent rerun may reuse them.
- `jobs.json` shows every planned shot as `verified`, total `paid_submission_attempts` exactly equals the base shot count, every verified shot has exactly one submission attempt and a request ID, and no attempt reason is `quality_regeneration` or terminal-failure retry.
- Every paid request record matches its contract-bound dry-run payload and asset trace; every poll record matches the same shot, request ID, contract, local clip path, and verified clip SHA-256.
- Disabled plans generate no SRT/VTT or captioned MP4. Enabled plans bind the clean MP4, local SRT, burn audits, captioned MP4, and zero added paid requests.
- When effects and subtitles are disabled and only one clip exists, the final video is the verified clean model clip. Confirmed subtitles allow only the local burn after clean review.
- Stitch report exists for multi-clip output.
- `final-review.json` exists and has status `pass`.
- `delivery-manifest.json` exists, has status `pass`, and its final-video digest matches `final-review.json.output_sha256`.
- The clean visual review binds `reviewed_video.path` and SHA-256 to the clean output. An enabled subtitle plan also binds the final visual review to the captioned output and verifies subtitle origin, safety, readability, and speech match.
- The delivery manifest binds all clips, the clean final video, stitch/technical/visual reports, `postprocess-manifest.json` when local edits occurred, plan, contract, and jobs ledger.
- The delivery manifest also binds `video-confirmation.json`, every paid request record, and every poll result; finalization rechecks all protected evidence after local processing before writing a passing delivery.
- Original provider clips remain immutable. Local edits produce new files and a separate postprocess record; they never change the confirmed plan, contract, confirmation, or jobs contract digest.
- Normal production has no repair reserve and no second paid POST. ASR-only uncertainty, harmless particles, a minor connective-word blur, provider terminal failure, or a visual quality defect does not trigger automatic paid regeneration.
- Final report names exact local paths.
