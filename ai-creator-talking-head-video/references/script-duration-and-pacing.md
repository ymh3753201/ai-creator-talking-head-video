# Script Duration And Pacing

Use this reference whenever the user asks for a fixed-duration talking-head video, especially when the requested duration is longer than the video model can generate in one request.

## Why This Matters

Digital-human clips can visually continue after narration ends. This is manageable: when the spoken content is complete, generate the supported request duration and remove only verified idle tail during technical editing. The costly failure is forcing filler into the script or repeatedly asking the user to approve timing-only changes.

The opposite problem is also common in multi-segment generation: the clip may be technically the right length, but the text is split at an unfinished phrase such as `第二，` or `风险控制、`. This feels like bad cutting even when FFmpeg stitching is technically correct.

## Planning Rule

For generated straight digital-human talking-head output:

- for the whole video, optimize ordinary editable copy to roughly 85-95% of the user's delivery window; this is a planning window, not a demand that every segment end on an exact frame;
- for multi-segment targets, under 75% spoken fill is a hard planning failure because it no longer reasonably represents the requested duration. Professionally rewrite toward 85-95%, or explicitly confirm a shorter delivery duration and recalculate the slots;
- reserve roughly 0.3-0.5s of neutral quiet before the complete first word and after the complete final word;
- for a normal 15s segment, estimated speech should usually be no more than about 14.2s;
- a segment above 95% fill is `too_long`, even when it does not exceed the nominal model duration, because zero-headroom delivery can swallow the first or last phoneme;
- every non-final segment must end on a complete strong sentence or genuinely complete clean transition;
- never turn a comma, list separator, open enumerator, or unfinished clause into a period merely to make a boundary validator pass;
- classify an individual complete underfilled segment as `short_but_usable`, continue generation, and trim only detected idle tail when the whole multi-segment plan still meets the 75% floor;
- choose the minimum number of paid clips that safely contains the optimized script;
- choose every request duration from the model's configured `allowed_durations_seconds`, not from any integer inside its minimum/maximum range;
- for the bundled current route the declared choices are `4, 6, 8, 10, 12, 15`; therefore `11`, `13`, and `14` must fail offline before credentials or network access;
- a 30-second delivery that safely fits two speech windows uses two 15-second requests. Three original paragraphs are rewritten into two complete spoken segments instead of creating a third paid request;
- an explicit segment file must contain exactly the deterministic minimum number of paid segments and meet every deterministic minimum request slot. It cannot reduce a confirmed 30-second `15+15` plan to one segment, expand it to three, or silently substitute `10+10`/`15+12`; a longer legal slot is allowed only when measured speech capacity needs it and the hard final cap remains safe;
- user-provided segment files are semantic-break suggestions and cannot bypass the minimum-segment or allowed-duration gates.

For visual-heavy explainers or existing-footage edits:

- 75-85% spoken fill can be acceptable when B-roll, screen recording, title cards, or pauses are explicitly planned;
- the edit plan must name those non-speaking beats and where they appear.

## Required Checks Before Paid Generation

Run `prepare_project.py` and inspect:

- `script_pacing.status`;
- each `shots[].script_pacing.status`;
- each `shots[].script_boundary.stitch_safe`;
- `estimated_spoken_seconds` vs `target_duration_seconds`;
- `spoken_fill_ratio`.
- `head_padding_seconds` and `tail_padding_seconds`;
- `maximum_recommended_spoken_seconds`.
- `delivery_max_seconds` and the fact that it still equals the user's confirmed maximum;
- every `request_duration_seconds` against `allowed_durations_seconds`;
- `minimum_required_segment_count` against the actual base request count;
- `estimated_natural_pause_seconds`, `estimated_delivery_seconds`, and `delivery_fit_status`;
- `planned_request_total_seconds`, `planned_trim_seconds`, and `planned_delivery_overshoot_seconds`. Request total and removable idle time are provider/editing facts. Overshoot may be non-zero only because the next supported request slot is longer; it must be covered by safe local idle-tail trimming and never grants permission for spoken/visual content to exceed the delivery maximum.
- `duration_plan_digest` in both plan-only output and the normal generation plan. The two values must be identical before preflight and must stay unchanged through confirmation and delivery.

Then run:

```bash
python3 ai-creator-talking-head-video/scripts/validate_project.py \
  --plan <project>/generation-plan.json \
  --enforce-script-pacing
```

Do not continue to paid generation if any segment is:

- `missing_script`: no line assigned to that segment;
- `too_long`: likely to rush, truncate, or drift from the desired segment.
- `script_boundary.stitch_safe=false`: likely to sound like the speaker was cut mid-sentence.

`short_but_usable` is not a per-segment blocker. It means the approved wording is complete and the final technical edit may remove verified idle tail; it does not override the whole-plan 75% minimum for multi-segment targets.

The real final MP4 has a separate hard delivery gate: its probed duration must not exceed `delivery_max_seconds` except for the fixed one-frame measurement allowance used for container/frame rounding. The ordinary absolute/percentage duration-mismatch tolerance can flag short or unexpectedly long edits, but it can never raise the hard maximum.

## Fixes

If a segment is too short:

- keep the approved script unchanged;
- select the smallest configured duration slot that still preserves safe head/tail room;
- if no exact slot matches the expected spoken duration, round the request **up** to the next supported slot and automatically trim only verified silent/idle tail;
- do not add filler or ask the user to approve a timing-only correction.

If a segment is too long:

- first rebalance the existing minimum number of segments at complete sentence boundaries;
- for editable copy, remove repetition, weak filler, and redundant CTA while preserving intent and verified facts;
- do not change a fact-bound or verbatim script silently;
- when the script still cannot fit the confirmed delivery window, stop before image/video spend and offer two explicit choices: shorten the script, or extend the delivery duration and recalculate the base paid requests;
- never silently add a paid segment while continuing to claim the old duration or paid cap.

## Long Video Segment Rule

For a 45s target on the current 15s-limit route, first optimize the complete speech to the delivery window, then use the minimum three paid clips. Request slots must be legal—for example `15s + 15s + 15s`, or a smaller supported final slot such as `15s + 15s + 12s` when the measured script safely fits. `14s + 13s + 12s` is invalid because 14 and 13 are not supported request values. The final stitched duration follows complete natural speech but may not exceed the user's delivery maximum; verified idle tail may be removed locally.

Do not use `Avoid idle tail` as an unconditional model instruction. It can force speech to start at 0ms. Require the planned head/tail pause and a complete first word instead.
