# B-roll And Editing

## Default Generated-Video Policy

For normal `avatar_talking_head` generation, the default visual policy is `model_output_only`. Do not insert B-roll, title cards, cutaway images, diagrams, overlays, masks, music, or transitions unless the user explicitly enables effects in the single production confirmation.

If effects are disabled and the project has one generated clip, preserve that verified clip directly. If the confirmed duration requires multiple clips, stitch only those generated clips in order without inserting other media.

## Optional Timeline Design

Use this section only after the user enables effects.

Split scripts into beats. For each beat, specify:

- time range;
- spoken line summary;
- B-roll type;
- spoken keyword emphasis without on-screen text;
- camera move;
- sound cue;
- asset source.

Useful B-roll types:

- screenshot;
- product or software interface;
- source article or document;
- dynamic chart;
- keyword card;
- case visual;
- screen recording;
- generated reference image;
- stock-style conceptual visual;
- title card or chapter card.

## Hybrid Workflow

For existing talking-head video, audio, or subtitle transcript material:

1. Keep the original speech source unless the user asks to replace it.
2. Use audio/subtitles only to segment or understand the timeline offline.
3. Keep subtitles default disabled. If the same Stage B1 confirmation enables them, add only the local platform-profile burn after clean review. Apply only the exact confirmed B-roll, BGM, sound effects, and ratio versions; do not add title/chapter text cards.
4. Preserve important face/mouth areas.
5. Export platform versions only after layout checks.

Do not force TTS when audio exists. Do not treat OpenMontage-like tools as full from-zero video generators.

After the selected editing tool renders `final.postproduced.mp4`, write `postproduction-manifest.json` from the bundled template. It must bind the source and candidate SHA-256 values, identify the editing tool and applied operations, and confirm that source speech was preserved. An unchanged copy cannot pass unless the only confirmed operation is the later local subtitle burn; that subtitle-only route may use the source as its clean candidate. Record `postproduction_subtitle_burn` as `planned` before finalization. The finalizer changes it to `applied` and writes the output hashes only after local burn and captioned review succeed; never pre-label unfinished subtitle work as applied.

## Longform Editing

For long scripts/audio/video:

- divide into chapters;
- write chapter hooks;
- place cases/examples;
- add summary cards;
- plan retention beats;
- create short-video slice suggestions.

## Long Video Multi-Segment Generation

When a requested digital-human video is longer than the selected model can generate in one request:

- split by `max_duration_seconds`, not by guesswork;
- create one `visual_bible` for the whole video;
- keep the same confirmed avatar/source image, scene style, camera framing, zero-written-text rule, aspect ratio, and resolution in every segment;
- for a continuous talking-head scene, reuse one approved `video_source` or `first_frame`; for planned scene/pose/chapter changes, generate and confirm one consistent `segment_source` image per segment;
- give each segment its own script beat and continuity prompt, such as `Segment 2/4`;
- calibrate each segment's `script_pacing` so the script can actually fill the generated duration;
- treat 90-95% as a preferred fill range, keep clean head/tail pauses, allow complete shorter clips, and trim only verified idle tail so no filler or repeated approval is needed;
- keep `model_output_only` when effects are disabled; when enabled, allow only the exact B-roll/effects confirmed by the user;
- run dry-run for all segments and inspect every request payload before paid generation;
- poll every `shot_*.mp4`, then normalize and stitch with `scripts/stitch_clips.py`.
- after stitching, run `scripts/review_render.py` and inspect `final-review.json` before delivery.

The stitching behavior probes clips first, normalizes video to one resolution/FPS, keeps normalized intermediate audio as PCM without per-clip fades, concatenates in order, and performs one final AAC encode. Never apply a head fade or crossfade over an incoming spoken word. The `.stitch-report.json` must record `audio_boundary_policy`, `per_clip_fades_applied=false`, and `single_final_aac_encode=true` for multi-clip output.

The review behavior follows the OpenMontage-style gate: inspect the real rendered MP4, detect tail silence and frozen frames, confirm all expected clips exist, and mark the result as `pass`, `revise`, or `fail`. A `revise` result is not final delivery.

Short slice suggestions should include:

- slice title;
- start/end chapter;
- hook;
- standalone value;
- B-roll need;
- target platform.
