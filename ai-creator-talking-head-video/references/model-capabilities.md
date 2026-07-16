# Model Capabilities

## Contents

- Required fields and planning rules
- Duration splitting and Grok/xAI route notes
- Image, lip-sync, and payload routing
- Evidence and readiness gates

This skill is model-config driven. Use `assets/templates/model-config.example.json` or the user's selected config as the source of truth.

## Required Capability Fields

Each model entry should define:

- `supports_image_to_video`;
- `supports_reference_images`;
- `supports_reference_to_video`;
- `source_image_becomes_first_frame`;
- `max_reference_images`;
- `supports_audio_input`;
- `supports_lipsync`;
- `supports_script_to_speech`;
- `lipsync_mode`;
- `external_audio_lipsync`;
- `supports_avatar_reference`;
- `supports_text_to_video`;
- `max_duration_seconds`;
- `allowed_durations_seconds` when the provider accepts only discrete request slots;
- `max_script_chars`;
- `source_image_field`;
- `reference_field`;
- `audio_field`;
- `duration_field`;
- `auth_scheme`;
- `api_key_env_names`;
- `payload_defaults`.
- `capability_source`;
- `verified_at`;
- `provider_route`;
- `verification_level`;
- `external_audio_alignment_level`.

## Planning Rules

- If `supports_lipsync=true`, normal generated digital-human narration can be planned without warning the user to switch models.
- If `external_audio_lipsync=false`, do not claim uploaded audio can drive exact mouth timing.
- If `supports_audio_input=false`, do not send audio files to that model.
- If `supports_reference_images=false`, use one confirmed source image or one segment source image per clip.
- If `source_image_becomes_first_frame=true`, treat `video_source`, `first_frame`, or `segment_source` as the actual opening frame of the generated clip.
- If `max_reference_images` is limited, choose the most important confirmed references and label the rest `preview_only`.
- If the optimized script exceeds one segment's safe capacity, choose the smallest safe segment count, quantize every request to `allowed_durations_seconds`, write `longform_generation_strategy`, reuse one `visual_bible`, and stitch.
- If the script is longer than `max_script_chars`, rewrite or split before generation.
- Treat official model documentation and a third-party provider alias as separate evidence. `provider_route` and `verification_level` must show whether the exact endpoint has been runtime-tested.

## Duration Splitting

`prepare_project.py` must handle over-limit duration before any paid request:

- use the selected model's `max_duration_seconds` and `min_duration_seconds`;
- when `allowed_durations_seconds` exists, treat it as stricter than the minimum/maximum range and reject every other integer before key lookup or network access;
- distinguish `delivery_max_seconds` from provider request slots; compute `estimated_delivery_seconds` from speech plus required natural pauses, `planned_trim_seconds` from removable idle slot time, and `planned_delivery_overshoot_seconds` from request total above the hard cap. Discrete-slot overshoot is allowed only when safe idle trimming can remove it; `delivery_fit_status` must be `ok`, and no field may authorize final content exceeding the user's confirmed maximum;
- calculate `minimum_required_segment_count` from the user's confirmed delivery maximum and the model's legal maximum request slot, then verify the optimized speech fits those safe windows before considering paragraph or scene boundaries;
- rebalance copy into complete strong sentences inside that exact minimum count and deterministic minimum slot list; an explicit segment file cannot reduce/add paid requests or substitute shorter slots without an explicitly changed delivery plan. A longer legal slot is acceptable only when measured speech capacity requires it and local trim keeps the final delivery inside the hard maximum;
- write and preserve `duration_plan_digest` over the model route, delivery maximum, legal slots, exact request slots, and exact segment text so proposal and production cannot silently diverge;
- create `shot_01`, `shot_02`, and later shots in chronological order;
- write segment index, segment count, start/end time, duration, focus, and script beat into each shot;
- write the same `visual_bible` into the plan and into every shot;
- create `stitching_plan` with clip order, target fps, target resolution, final output path, and report path.

Paid generation is not ready if a multi-segment plan lacks the visual bible, continuity contract, or stitching plan.

For the bundled `grok-video-1.5` provider route, local runtime evidence from 2026-07-12 reports the accepted values as `[4, 6, 8, 10, 12, 15]`. Local projects contain successful 12-second and 15-second results. The other declared slots came from the route's own validation response and were not individually paid-tested during this repair. Never infer that 11, 13, or 14 is valid merely because it falls between 4 and 15.

## Grok / xAI Route Notes

The configured production route is the already-tested middle-station endpoint `https://api.119337.xyz/v1` with provider model id `grok-video-1.5`, mapped by the provider to `grok-imagine-video-1.5-preview`. Treat those two request settings as fixed project configuration. This route is single-image image-to-video and has `supports_reference_images=false`; do not send multiple reference images or replace the provider model id with an official xAI id.

Official xAI docs currently distinguish these paths:

- `grok-imagine-video-1.5`: image-to-video. It animates one still image, and the source image becomes the first frame.
- `grok-imagine-video`: video generation, reference-to-video, editing, and extension routes.
- Reference-to-video accepts up to 7 reference images, has a 10-second maximum duration, and official docs state that `grok-imagine-video-1.5` does not support this mode.

Some gateways expose provider aliases such as `grok-video-1.5` or `grok-image-video`. Do not infer capabilities from the model name alone. Use the configured fields in `model-config.example.json`.

## Image Strategy Routing

- Use `single_source_frame` when one approved `video_source` or `first_frame` is enough for a continuous talking-head shot.
- Use `per_segment_source_frames` when a long video needs different opening poses, scenes, or chapter cards. Provide one `segment_source` per segment.
- Use `multi_reference_storyboard` only when `supports_reference_images=true`. In that route, avatar, scene, last-frame, and storyboard images can be reference guides.
- Never use a multi-panel storyboard sheet as the only image for a single-image route. It is a plan/reference, not the source frame.

## Lip-Sync Routing

Generated talking-head narration:

- Use the selected model normally when `supports_lipsync=true`.
- Do not add a user-facing warning such as "current model only produces talking-head-like motion" for Grok 1.5 or Seedance 2.0 routes.

External-audio or frame-level mouth matching:

- `supports_lipsync=true`;
- `supports_audio_input=true` or a supported script-to-speech route.

If the user provides audio and explicitly asks the generated avatar to follow that exact audio, prefer a route with `external_audio_lipsync=true` and an `audio_field`. If the selected model cannot accept uploaded audio, keep those files in the edit plan and do not claim exact audio-driven sync.

`external_audio_lipsync=true` means the route can condition generation on uploaded audio. It does not automatically prove frame-accurate mouth matching. Use `external_audio_alignment_level` to distinguish reference-audio conditioning from a verified frame-accurate service, and confirm quality on the real output.

## Evidence Rechecked 2026-07-15

- xAI `grok-imagine-video-1.5` is image-to-video and the source image becomes the first frame: `https://docs.x.ai/developers/models/grok-imagine-video-1.5`.
- xAI reference-to-video uses `grok-imagine-video`, supports up to 7 reference images, and caps that mode at 10 seconds; 1.5 does not support reference-to-video: `https://docs.x.ai/developers/model-capabilities/video/reference-to-video`.
- fal Seedance 2.0 reference-to-video accepts up to 9 images, 3 videos, and 3 audio files, supports 4-15 second output, and the standard route supports up to 1080p: `https://fal.ai/models/bytedance/seedance-2.0/reference-to-video`.

Provider aliases can differ from the official model. Keep conservative route limits until a real request verifies the exact configured endpoint.

## Payload Mapping

Build request payloads from config:

- source image goes to `source_image_field`;
- references go to `reference_field`;
- audio goes to `audio_field` only when supported;
- subtitle assets are intentionally unsupported in Provider payloads; optional captions are generated and burned only by the confirmed local postproduction route;
- duration goes to `duration_field`;
- source image shape follows `source_payload_format`, for example `url_array`, `url_string`, or `url_object`;
- reference image shape follows `reference_payload_format`, for example `url_strings`, `url_objects`, or `role_url_objects`;
- when source and reference fields are the same field, such as `image_urls`, merge values into one array instead of overwriting the source image;
- extra defaults come from `payload_defaults`.

Never embed API keys in payload records, dry-run files, or logs.

## Readiness Gate

Before a real paid call, the project manifest should have `ready_for_paid_generation=true`.

Block paid generation when:

- a model requires an image but no confirmed visual source, avatar reference, final `video_source`, or `segment_source` exists;
- the user still needs an original avatar/reference image generated and confirmed;
- exact external-audio lip sync is requested but the selected model cannot support it;
- the script exceeds `max_script_chars` and has not been split or rewritten;
- `script_pacing` is `missing_script` or remains `too_long` after automatic repartition; `short_but_usable` is trim-safe;
- a multi-segment script boundary is not stitch-safe.
- a request duration is absent from the model's non-empty `allowed_durations_seconds`;
- the plan uses more than the minimum required paid segments without an explicitly revised longer-duration contract;
- `duration_plan.delivery_max_seconds` exceeds the user's confirmed maximum or the field is confused with `planned_request_total_seconds`.

Dry-run may still be used to inspect the planned payload, but real submission should stop until the blocking reasons are resolved. Normal paid submission must use a confirmation file with both `image_assets_confirmed=true` and `video_generation_confirmed=true`.
