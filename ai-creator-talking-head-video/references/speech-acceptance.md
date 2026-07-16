# Graded Speech Acceptance

Use this policy after generation to protect meaning and factual accuracy without spending another paid video request on harmless pronunciation or ASR noise.

## Fidelity Modes

| Mode | Use when | Acceptance rule |
|---|---|---|
| `semantic_tolerance` | casual creator content where exact wording is not important | meaning, intelligibility, and approved facts must remain intact |
| `critical_facts_exact` | training, product, sales, FAQ, business-source, or other fact-sensitive videos | names, numbers, prices, dates, policies, negation, capability boundaries, CTA, and source-backed facts must be exact; harmless connective-word variation may pass with notes |
| `verbatim_required` | the user explicitly requires exact wording, legal copy, quotations, or fixed compliance language | any confirmed spoken deviation requires revision |

Default factual creator speech to `critical_facts_exact`; this protects required facts but still permits harmless wording variation through `pass_with_notes`. Use `semantic_tolerance` for casual creator speech where exact wording and fact-bearing terms are not important. Record the selected mode in the proposal and generation plan before paid generation.

## Delivery Classes

- `pass`: the approved speech is complete and no relevant discrepancy remains.
- `pass_with_notes`: the video is understandable and usable, all critical facts and meaning are preserved, but a minor non-semantic pronunciation difference or uncertain ASR fragment is documented.
- `revise_local`: the provider clip is usable but a stitch, trim, encoding, timing, or subtitle problem needs no-cost local correction.
- `blocked`: meaning, intelligibility, a critical fact, an approved required clause, audio presence, media integrity, or a verbatim requirement is materially affected in the isolated provider clip. Do not label this a qualified delivery and do not automatically submit another paid request.

`pass_with_notes` is a valid final delivery. Keep `delivery-manifest.json.status=pass` and set `delivery_classification=pass_with_notes` so downstream release checks remain compatible.

## PASS_WITH_NOTES Requirements

All of these must be true:

1. The fidelity mode is `semantic_tolerance` or `critical_facts_exact`, not `verbatim_required`.
2. Names, model names, numbers, prices, dates, policies, negation, capability claims, CTA, and source-backed facts are preserved.
3. The sentence meaning is preserved and an ordinary listener can understand it.
4. Every minor difference is recorded in `minor_discrepancies` with `severity=minor`, `affects_core_fact=false`, and `affects_meaning=false`.
5. `material_discrepancies` and `unresolved_discrepancies` are empty.

Examples that may qualify include punctuation/capitalization differences in ASR, harmless particles or fillers, a slightly blurred connective phrase, or unstable ASR readings while the core statement remains clear.

## When Qualified Delivery Is Blocked

Block qualified delivery when any of these is confirmed in the isolated provider output and local post-processing cannot fix it:

- a name, model, number, price, date, policy, negation, capability boundary, CTA, or source-backed fact changes;
- a full sentence or required clause is missing;
- speech is not understandable to an ordinary listener;
- the isolated source clip is defective in a way that changes meaning or intelligibility;
- there is an actual mouth/audio timing failure rather than only a transcript mismatch;
- `verbatim_required` is active and any spoken deviation is confirmed.

## Evidence And ASR Rules

1. A single ASR mismatch is evidence to inspect, not automatic permission for paid regeneration.
2. Compare the isolated generated segment with the final stitched boundary first. If only the final candidate is damaged, use a no-cost restitch or re-render.
3. For a suspected spoken discrepancy, use at least two ASR passes or one ASR pass plus a complete human listen. Save the evidence.
4. If repeated ASR runs produce different gibberish for the same short transition while the critical terms and sentence meaning remain clear, set `asr_consensus=uncertain`; do not invent a precise missing word.
5. Keep pronunciation/content fidelity separate from lip sync. A transcript mismatch alone must not set `lip_sync_acceptable=false`.
6. A user-reported swallowed character requires targeted comparison. If only the final edit is affected, fix it locally. If the isolated provider clip has a material defect, block qualified delivery and report it; do not automatically regenerate.

## Zero Automatic Paid Repair Rule

- Normal production fixes `repair_reserve=0`, `per_shot_repair_limit=0`, and `max_paid_submissions=base_paid_request_count`.
- Every base segment may be submitted once. A provider-declared terminal failure, verified quality defect, or ASR mismatch never creates authority for a second POST.
- Continue polling or downloading the same known request ID after a network interruption; this is recovery, not regeneration.
- Prefer no-cost inspection, restitching, trimming verified idle tail, subtitle correction, re-encoding, or local re-rendering.
- Do not block delivery for punctuation/capitalization, harmless particles/fillers, minor connective-word blur, or ASR-only uncertainty when meaning and required facts are intact; use `pass_with_notes`.
- When a material provider-output defect remains, save the evidence and return a blocked qualified-delivery report. If the user later explicitly asks for another generation, create a new independent paid authorization instead of modifying the old contract.

## Speech Evidence Schema

```json
{
  "status": "pass_with_notes",
  "speech_fidelity_mode": "critical_facts_exact",
  "critical_terms_preserved": true,
  "core_facts_preserved": true,
  "meaning_preserved": true,
  "intelligibility_acceptable": true,
  "asr_consensus": "uncertain",
  "minor_discrepancies": [
    {
      "segment_id": "shot_02",
      "expected": "更值得关注的是",
      "observed": "短连接词发音略含混，ASR 多次结果不一致",
      "severity": "minor",
      "affects_core_fact": false,
      "affects_meaning": false
    }
  ],
  "material_discrepancies": [],
  "unresolved_discrepancies": [],
  "paid_regeneration_authorized": false
}
```
