# Two-Confirmation Codex Imagegen Orchestration

Use this contract for production requests that need a complete plan, generated digital-human/source images, and paid video generation.

## Why The Flow Has Two Stages

Codex built-in imagegen is response-terminal: after it returns an image, the assistant cannot reliably append more text in that same turn. Text emitted inside `functions.exec`, tool output, or progress commentary is not the primary assistant response. The observed legacy sequence could therefore leave the user with only an image even though a proposal existed inside tool output.

Do not attempt to rebuild an atomic text-plus-image response with `text(proposal)`, `yield_control()`, or a composite tool call. Deliver the proposal and the images in separate user-visible stages instead.

## Stage 1 — Complete Text Proposal

Return the complete proposal as the normal primary assistant response. It must include:

- supplied-material and original-script review;
- the professionally optimized full spoken script;
- final delivery maximum, estimated spoken duration, deterministic minimum-segment result, legal request slots, model route, and base paid request count;
- digital-human, scene, camera, subtitle, and effects choices;
- planned real image roles, exact prompt intent, and `video_payload`/`preview_only` labels;
- base paid requests, `repair_reserve=0`, `per_shot_repair_limit=0`, and approved paid cap equal to the base count;
- a single request to confirm the plan.

Do not call imagegen in Stage 1. Do not call a paid video API. Record:

```text
stage=awaiting_plan_confirmation
proposal_delivered=true
plan_confirmed=false
image_assets_confirmed=false
paid_video_authorized=false
```

An image-only first response, proposal text hidden in tool output, or an incomplete script is invalid.

## Confirmation 1 — Plan Approval Only

The user's first confirmation approves the script, final delivery maximum, model-supported request slots, minimum segment count, exact segment text, `duration_plan_digest`, visual direction, subtitles/effects, model route, base request count, zero repair reserve, zero per-shot repair limit, and a paid cap equal to the base count. It authorizes Stage 2 image generation only. It does not authorize a paid video call.

If the user requests material changes to the script, model, creative scope, or paid cap, update and redeliver Stage 1 before imagegen.

## Stage 2 — Real Production Images

After Confirmation 1, use the installed `imagegen` skill's built-in image2 / gpt-image-2 route. Do not call an external image endpoint, add an image API key, or create a custom image runner.

Generate only applicable real production assets:

- `video_source`;
- `first_frame`;
- optional `last_frame`;
- per-segment `segment_source`;
- optional `storyboard_sheet`, always `preview_only`.

At least one `video_source`, `first_frame`, or `segment_source` must be marked `video_payload`. Never generate a proposal board, confirmation board, review board, wireframe, or text-heavy substitute.

Because imagegen may end the response, the Stage 1 proposal must already have told the user what to do next: reply “确认图片并开始制作” to approve the exact visible images and begin automatic production, or describe the image changes needed.

Record:

```text
stage=awaiting_image_confirmation
proposal_delivered=true
plan_confirmed=true
image_assets_confirmed=false
paid_video_authorized=false
```

If imagegen fails, remain in Stage 2 and report the failure on the next available assistant response. Do not enter video preflight or call a paid video API.

Image-only revisions keep `plan_confirmed=true` when the script, model route, creative scope, and paid cap are unchanged. Material plan drift resets the flow to Stage 1.
In a normalized trace, mark a replacement image batch with `revision_replaces_previous=true`; confirmation digests then bind only the latest visible payload images. Do not retain superseded image digests.

## Confirmation 2 — Images And Production Authorization

The user's second confirmation must explicitly approve the exact displayed images and instruct the skill to start production. Copy the selected built-in outputs from `$CODEX_HOME/generated_images/...` into the project, record role/path/SHA-256, carry the Stage B1 `duration_plan_digest` into the contract-bound confirmation, and never silently regenerate or swap either images or the approved segmentation.

Record:

```text
stage=production_authorized
proposal_delivered=true
plan_confirmed=true
image_assets_confirmed=true
paid_video_authorized=true
```

Then run `prepare -> preflight -> confirm -> one submit per base shot -> poll/resume existing request ids -> finalize -> review -> no-cost local postprocess if needed -> delivery` without a third routine confirmation. No review result or provider terminal failure authorizes a second paid POST. Pause for production-contract drift, ambiguous paid submission without safe recovery, terminal provider failure, a material provider-output defect, unrecoverable rights/safety/source-fact issues, or provider/auth outage.

## Trace Validation

For recorded or normalized traces, run:

```bash
python3 ai-creator-talking-head-video/scripts/validate_first_response_trace.py <trace.json>
```

The validator rejects `proposal_in_tool_output_only`, `empty_final_after_image`, `image_before_plan_confirmation`, `paid_before_image_confirmation`, missing or mismatched image digests, a missing/mismatched `duration_plan_digest` across Stage B1 and both confirmations, `paid_video_calls` above `base_paid_request_count`, paid-repair actions, missing confirmations, incomplete or out-of-order automatic production, and a third routine confirmation.

For `postproduction_only`, keep the source MP4 and speech timeline, apply only explicitly approved edits, and do not create a paid-generation contract. The two-confirmation image route is unnecessary unless the user explicitly asks to replace or generate visual assets.
