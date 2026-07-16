# Post-Generation Review

Use this reference after video clips have been generated or stitched.

## Review Goal

The API returning an MP4 is not the same as delivery quality. The agent must inspect the actual local video before saying it is complete.

## Required Tool

Run:

```bash
python3 ai-creator-talking-head-video/scripts/review_render.py \
  --project-dir <project> \
  --video <project>/final.mp4
```

For a partial preview, pass the partial video path:

```bash
python3 ai-creator-talking-head-video/scripts/review_render.py \
  --project-dir <project> \
  --video <project>/partial-30s-preview.mp4
```

The script writes `<project>/final-review.json` unless `--output` is supplied.

## What The Review Checks

- actual container, duration, video stream, and audio stream;
- expected duration from `generation-plan.json`;
- the hard `delivery_max_seconds` limit on the real MP4; only the fixed one-frame container/probe allowance is accepted, and ordinary percentage tolerance cannot relax this maximum;
- missing `shot_*.mp4` clips;
- clip count mismatch;
- tail silence in each clip and final output using FFmpeg `silencedetect`;
- active audio in the final boundary guard window, which can mean a clip was cut while speech was still continuing without misclassifying a sentence that ended shortly before the cut;
- incoming-head preservation: compare the next source clip's first 100ms with the final output at the stitch boundary and flag material onset attenuation;
- stitch audio policy: multi-clip output must disable per-clip fades/crossfades and use one final AAC encode after PCM normalization;
- weak script boundaries such as a segment ending on an unfinished clause or enumerator;
- generated text, subtitles, logos, or watermarks visible in Provider frames; in a captioned final, any text beyond the approved local captions;
- frozen frames using FFmpeg `freezedetect`;
- sampled frame paths for manual visual spot-check;
- stitch report presence for multi-clip projects;
- `script_pacing` status from the generation plan.

## Status Rules

- `pass`: video is ready to present, and the review command exits `0`.
- `pass_with_notes`: valid final delivery classification for a minor non-semantic speech difference or uncertain ASR fragment that preserves meaning, intelligibility, and all critical facts. The technical review may remain `pass`; record this classification in `visual-review.json` speech evidence and `delivery-manifest.json`.
- `revise`: a no-cost local trim, restitch, or re-encode is required. Do not call it final; the review command exits non-zero by default.
- `fail`: critical output problem, such as missing final video or no video stream. The review command exits non-zero.

Technical review does not claim that face identity, outfit, scene, framing, mouth visibility, lip sync, generated text, unapproved visual inserts, or spoken-content completeness were visually verified. Record clean Provider checks in `visual-review.clean.json` for enabled subtitle plans, otherwise `visual-review.json`. Every delivery requires `no_generated_text=true` and `no_unapproved_visual_insert=true` on the clean output. A captioned delivery then requires a separate final visual review. Apply `speech-acceptance.md` for transcript evidence.

For every multi-segment boundary, listen to the outgoing final word and incoming first word in both the isolated clips and final candidate. If a Chinese first word is recognized as one compound token, that ASR match alone does not prove each character onset is intact. A user-reported swallowed character overrides an automatic ASR pass and requires targeted comparison, but never authorizes an automatic paid POST. If the source and final remain intelligible and critical facts are intact, use `pass_with_notes`; if the final alone is attenuated, restitch without fades; if the isolated source has a material defect, block qualified delivery and report it without regenerating.

Common recommended actions:

- `wait_for_missing_clips`: generation is incomplete; continue polling/downloading existing request IDs. A terminally failed or never-submitted shot blocks this contract instead of being automatically resubmitted.
- `block_generated_text`: Provider painted text into the pixels; record `no_generated_text=false`, block qualified delivery, and do not automatically spend on regeneration.
- `restitch_or_block_bad_boundary`: restitch when only the final edit is damaged; block qualified delivery when the isolated provider clip or pre-generation split is materially defective.
- `trim_verified_idle_tail`: tail silence or a shorter complete script caused an idle ending; preserve the original clip and record the local trim.
- `restitch`: clips exist but final duration/stitch report is wrong.
- `restitch_without_segment_fades`: the incoming first-word onset was attenuated or the stitch report used an unsafe audio-boundary policy.
- `accept_minor_speech_difference_with_notes`: repeated evidence shows a non-semantic difference or unstable ASR reading while meaning, intelligibility, and critical facts remain intact.
- `cut_locally_or_block_frozen_segment`: use a safe local cut only when speech and meaning remain complete; otherwise block qualified delivery.
- `present_to_user`: review passed.

## Editing Decision

When effects are enabled, `finalize_project.py` may trim a detected model-generated tail silence of at least 1.0s, keep 0.25s of natural pause, preserve the original clip, and record the edit. When effects are disabled, do not trim a one-shot video. External audio, user-provided timing, existing-video audio, and hybrid edits are not auto-trimmed by default. Write all no-cost edits to `postprocess-manifest.json` and do not mutate the confirmed generation plan or contract after paid submission. If a generated segment ends on an unfinished word or clause, local trimming cannot repair the source; block qualified delivery rather than issuing another paid POST.

`delivery-manifest.json` is the release authority. It binds SHA-256 values for all source clips, the clean stitched video, stitch report, technical review, visual review, plan, contract, confirmation, jobs ledger, every paid request, and every poll result. Finalization requires exactly one paid attempt per verified base shot and matching shot/request/contract/payload/clip evidence, then rechecks the protected files after local processing. A valid request, downloaded MP4, partial preview, or technical `pass` without hash-bound visual/speech review is not final delivery. `status=pass` with `delivery_classification=pass_with_notes` is valid when the graded speech requirements pass. Any later blocked/revise finalize removes the stale pass manifest but preserves per-run postprocess audit history.
