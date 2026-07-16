# Avatar And Scene

## Avatar Planning

For each digital-human talking-head plan, describe:

- identity: original virtual avatar, user-provided avatar, or permitted real-person reference;
- age range and style;
- clothing;
- hair;
- temperament;
- expression;
- posture;
- hand movement;
- speaking style;
- trust signal;
- face and mouth visibility for lip sync.

If the user provides a usable avatar/source image, plan to use it as a reference through Codex built-in imagegen. If no usable image exists, plan an original permission-safe digital-human source image. Deliver the complete text proposal first; generate and show the actual result only after the user confirms that plan.

## Scene Types

- professional studio;
- desk setup;
- tech background;
- classroom or whiteboard;
- lifestyle room;
- news commentary desk;
- interview corner;
- screen-recording plus presenter layout.

Pick the scene based on the content. A news/commentary video should not look like a product ad by default.

## Camera Styles

- half-body fixed camera;
- close talking-head;
- light push-in;
- side-angle interview;
- course explanation with board;
- desktop teaching with screen overlay.

## Image Generation Plan

After the proposal is visibly delivered and the user confirms it, generate only the applicable real assets with built-in imagegen:

- avatar reference prompt, only when no accepted avatar/source image already exists;
- scene or first-frame prompt, only when the route needs a generated source frame;
- cover prompt, only when the user explicitly requested a cover deliverable;
- storyboard or B-roll reference prompts, only when the user explicitly enabled those effects;
- which images will be uploaded to the video model;
- which images are only `preview_only`.

When cover, storyboard, or B-roll is not explicitly requested or enabled, mark it `disabled`; do not plan or generate it by default.

Use the two-stage contract in `first-response-imagegen.md`. Stage 1 is the complete text proposal with no imagegen. Stage 2 uses Codex built-in imagegen after plan confirmation and waits for image confirmation before any paid video call. At least one `video_source`, `first_frame`, or `segment_source` must be marked `video_payload`, then copied into the project with its role, path, and SHA-256 bound to the video request. A `storyboard_sheet` is always `preview_only`. Never create a confirmation board, proposal screenshot, or wireframe substitute.

## Lip-Sync Boundary

For normal generated digital-human narration, do not warn the user to switch models when the selected Grok 1.5 or Seedance 2.0 route has `supports_lipsync=true`.

When the user provides external audio and asks for exact audio-driven mouth matching, check model config:

- `supports_lipsync`;
- `supports_audio_input`;
- `external_audio_lipsync`;
- `audio_field`;
- `max_script_chars`;
- `max_duration_seconds`.

If unsupported for external audio, say that the selected route can still generate talking-head narration, but cannot follow the uploaded audio exactly. Recommend Seedance reference-to-video or another configured audio-input route.
