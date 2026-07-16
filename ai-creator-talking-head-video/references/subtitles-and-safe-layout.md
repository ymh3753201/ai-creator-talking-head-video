# Optional Postproduction Subtitles And Safe Layout

Subtitles are **default disabled**. They become part of the same Stage B1 plan confirmation only when the user explicitly approves the plan and requests captions, for example: “确认方案，需要字幕”. Record this as:

- `enabled=true`;
- `request_source=user_plan_confirmation`;
- `confirmation_status=confirmed`;
- `provider_policy=never_send`;
- `render_policy=postproduction_burn_only`.

This does not create a third confirmation. A standalone “需要字幕” changes the requested plan but does not confirm the rest of Stage B1.

## Provider Prompt And Payload Contract

The Provider path is always text-free, whether final subtitles are enabled or disabled:

- the prompt requires the entire frame to stay free of written or typographic elements;
- spoken dialogue remains audio only and is never visualized or quoted;
- forbid Provider-generated subtitles, captions, lower thirds, title cards, speech bubbles, labels, UI text, letters, numbers, punctuation, logos, and watermarks in every language;
- `subtitle_included_in_payload=false` for every dry-run and paid request;
- never map an SRT/VTT, transcript, or subtitle URL into the Provider payload;
- never tell the Provider to add captions that will later be replaced.

Negative prompting reduces risk but cannot guarantee compliance. `no_generated_text=true` on the clean MP4 remains a mandatory gate.

## Local-Only Runtime Contract

When subtitles are confirmed, preflight must succeed before any paid request:

- FFmpeg/ffprobe are installed and FFmpeg exposes the `subtitles`/libass filter;
- either a confirmed readable SRT is available, or `whisper-cli` plus a local Whisper model is available;
- the selected platform profile exists;
- SRT and audit outputs stay inside the project;
- no subtitle operation calls a paid video API.

When a confirmed spoken script exists, it is the subtitle word authority: record `lexical_source=confirmed_script`. Local whisper.cpp still reads the final audio, but only to determine cue start/end times. Preserve `subtitles/final.raw-asr.srt` and its SHA-256 in the audit. A small ASR model may confuse near-sounding Chinese words; those guesses must never overwrite the confirmed copy. When no confirmed script exists, record the actual lexical source explicitly and keep the captioned visual/speech review mandatory.

If local transcription is unavailable, stop before video spending and report the missing local dependency. Do not silently download a large model during a user production task.

## Clean-First Production Order

1. Generate, poll, trim, and stitch the normal clean MP4.
2. Run technical review and `visual-review.clean.json` on that exact clean MP4.
3. Require `no_generated_text=true` and `no_unapproved_visual_insert=true` before any burn.
4. Generate SRT timing from the clean final video's final audio, or use the supplied confirmed SRT. With a confirmed script, align its caption units to the final-audio cue windows and retain raw ASR separately.
5. Burn captions locally with `scripts/burn_subtitles.py` and the resolved platform profile.
6. Run technical review and `visual-review.json` on the captioned MP4.
7. Preserve `final.clean.mp4`, `subtitles/final.srt`, subtitle audits, and `final.captioned.mp4`.

If the Provider painted text into the clean video, block before Step 4. Embedded Provider text cannot be treated as approved captions or removed losslessly by the subtitle renderer. The zero-paid-repair rule remains unchanged.

## Platform Profiles

`assets/templates/subtitle-style-profiles.example.json` stores resolution-independent ratios. `scripts/subtitle_profiles.py` resolves those ratios against the actual video width and height.

FFmpeg's SRT renderer uses libass script coordinates rather than output pixels. Convert target pixels into libass's SRT script space before writing `FontSize`, `Outline`, and margins. Do not pass 720p pixel values directly into `force_style`: that can enlarge text and margins by about 2.5 times, create extra wrapped lines, and cover the presenter's face.

- Douyin/TikTok and YouTube Shorts reserve a larger right and bottom area for platform controls.
- Xiaohongshu uses its own vertical safe margins.
- YouTube and Bilibili horizontal use lower, narrower safe margins.
- Unknown 9:16 and 16:9 platforms fall back to separate generic vertical/horizontal profiles.
- Use at most two lines, white text, dark outline, transparent background, and no caption bar.
- Do not cover the face, mouth, product detail, key B-roll, progress bar, or platform buttons.

Profiles are production defaults, not proof that every app/device overlay is identical. Final visual review must still inspect representative frames.

## Captioned Visual Review

The final captioned review requires:

- `subtitle_present=true`;
- `subtitle_postproduced=true`;
- `subtitle_safe=true`;
- `subtitle_readable=true`;
- `subtitle_matches_speech=true`;
- `subtitle_background_absent=true`;
- `no_unapproved_text=true`;
- all normal identity, scene, framing, speech, and duration checks.

`no_generated_text=true` in the captioned review means the underlying Provider video introduced no text; it does not deny the separately approved postproduced captions.

## Local Repair Rule

Timing, line breaking, font size, safe-zone, or rendering problems may be repaired by regenerating SRT or rerendering the captioned copy locally. These repairs must record `paid_api_call=false` and must never create a new Provider POST. A material Provider defect still blocks qualified delivery.

## Disabled Path

When the user does not request subtitles:

- `subtitle_plan.enabled=false` and `choice=disabled`;
- `request_source=default` and `render_policy=none`;
- no SRT, burn audit, or captioned output is created;
- the verified clean MP4 remains the final delivery.
