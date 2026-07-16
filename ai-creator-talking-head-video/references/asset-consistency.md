# Asset Consistency

The video API can use only files explicitly passed to scripts. Images shown in chat or described in text are not automatically video inputs.

## Asset Roles

Use these roles:

- `avatar_reference`;
- `scene_reference`;
- `video_source`;
- `first_frame`;
- `last_frame`;
- `segment_source`;
- `storyboard`;
- `storyboard_sheet`;
- `broll_reference`;
- `cover`;
- `audio`;
- `subtitle`;
- `script`;
- `preview_only`.

## Confirmed Asset Ledger

Before paid generation, list:

- user-provided files;
- Codex-generated images;
- user-confirmed images;
- script file or script text;
- audio and subtitle files;
- B-roll plan;
- subtitle strategy;
- model config and capability warnings;
- autonomous execution contract: base paid request count, `repair_reserve=0`, `per_shot_repair_limit=0`, approved paid cap equal to the base count, no-cost post-processing authority, and hard stop conditions.

The proposal, manifest, dry-run request, and final paid request must refer to the same confirmed assets.

## Single-Image Routes

If the model does not support reference images, one source image must already contain the approved avatar, scene, composition, and style. For official `grok-imagine-video-1.5` and provider aliases such as `grok-video-1.5`, the source image becomes the first frame.

Use one of these patterns:

- `single_source_frame`: one approved `video_source` or `first_frame` for a continuous talking-head scene;
- `per_segment_source_frames`: one approved `segment_source` image per segment when pose, scene, or opening frame must change;
- `merged_source_frame`: merge avatar, scene, and storyboard intent into one final source image before video generation.

Do not upload a 6-grid or 9-grid storyboard sheet as the only source image. The model may animate the collage itself instead of reading it as a shot plan. Extra avatar, last-frame, or storyboard images will not affect a single-image route unless merged into the source image or used as per-segment source frames.

## Multi-Reference Routes

If the model supports references, map each uploaded reference to a clear role and prompt token. Do not exceed `max_reference_images`.

Use multi-reference routing when the selected model can actually accept reference images and the request needs role, outfit, scene, last-frame target, or storyboard guidance. For current xAI official docs, reference-to-video supports up to 7 reference images, caps duration at 10 seconds, and is not supported by `grok-imagine-video-1.5`; use the configured model route as the source of truth.

## Existing Audio And Subtitles

When audio or subtitles exist:

- record them in the manifest;
- use them to drive timing and edit decisions;
- avoid forcing TTS;
- include them in the API payload only if the selected model supports the fields.

## Dry-Run Check

Before paid generation, inspect:

- request has no API key;
- `asset_trace.confirmed_asset_roles`;
- `asset_trace.audio_included_in_payload`;
- `asset_trace.subtitle_included_in_payload`;
- `asset_trace.reference_count`;
- `asset_trace.source_asset`;
- `asset_trace.source_asset_segment_index`;
- `asset_trace.lipsync_supported`;
- `asset_trace.lipsync_required`.
- `duration_plan.delivery_max_seconds`, `minimum_required_segment_count`, and every legal `request_duration_seconds`;
- confirmation and jobs ledger show exactly one allowed POST per base segment and no quality/provider regeneration reserve.

If a user-confirmed asset is missing from dry-run, stop and fix the plan.

After paid submission, treat the plan, production contract, video confirmation, asset digests, and jobs contract digest as immutable. Local trim, stitch, encode, and subtitle work must preserve the original provider clips and write a separate `postprocess-manifest.json`; never rewrite the paid contract to make a later edit appear pre-confirmed.
