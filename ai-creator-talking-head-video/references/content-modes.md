# Content Modes

## Contents

- Business scenario overlay
- Topic planning and viral teardown
- Script rewrite and avatar talking head
- Hybrid B-roll edit and longform editing

## Business Scenario Overlay

This is not a separate CLI content mode. Apply it before selecting modes whenever the user provides business materials or asks for a professional digital-human talking-head方案.

Use `references/business-scenarios.md` to identify:

- business scenario route;
- user intent and target viewer;
- provided assets and missing assets;
- scenario-specific success metric;
- compliance or claim-risk boundary.

Then combine the route with the normal content modes below. Examples:

- enterprise training PPT -> `script_rewrite` + `avatar_talking_head` + optional `longform_editing`;
- FAQ or service policy -> `script_rewrite` + `avatar_talking_head` + optional `hybrid_broll_edit`;
- sales deck or product demo -> `script_rewrite` + `avatar_talking_head`; add a B-roll plan only when the user enables effects;
- existing MP4/audio/SRT -> `hybrid_broll_edit`;
- multilingual source video -> `script_rewrite` + `avatar_talking_head` or `hybrid_broll_edit`;
- creator-led explanation with a light commercial insertion -> `commerce_hybrid`; heavy product ads or pure selling go directly to `ai-commerce-video`.

The first proposal should explain the scenario route in plain language before presenting script, avatar, B-roll, and generation details.

## `topic_planning`

Use when the user provides a direction, niche, rough idea, account positioning, or complaint such as "播放量不好".

Output:

- 5 to 10 topic angles;
- target audience and pain point;
- platform fit;
- opening hook;
- controversy or curiosity point;
- practical value;
- title and cover potential;
- why this topic is worth making;
- production difficulty and recommended priority.

Do not behave like a title generator. A topic is only useful if it has an audience reason, content structure, and production path.

## `viral_teardown`

Use when the user provides competitor videos, screenshots, transcript, titles, covers, or links.

Output:

- first 3-second hook;
- narrative structure;
- emotion curve;
- camera rhythm;
- whether the source uses text/keyword styling, recorded only as teardown evidence and never copied into generated delivery;
- B-roll type;
- cover/title logic;
- reusable template;
- risks and what not to copy.

Do not copy the original script. Extract reusable mechanics.

## `script_rewrite` / 脚本改写

Use when the user provides a draft, topic, or rough notes and wants a platform-native talking-head script.

Output at minimum:

- a concise audit of the supplied draft/materials, including unsupported facts, weak structure, repetition, spoken-language problems, platform mismatch, and pacing risk;
- a note explaining which verified facts and user intentions are preserved and which claims need evidence;
- title;
- opening hook;
- the complete professionally optimized spoken script, not only body headings or an outline;
- body paragraphs;
- transitions;
- key spoken points that must remain audio-only;
- CTA;
- shot guidance, the Provider no-text rule, the default-disabled/optional-local subtitle choice, and the effects/B-roll choice.

Rewrite by platform instead of using one generic script.

## `avatar_talking_head`

Use when the target output is a generated digital-human talking-head video.

Output:

- avatar identity and boundary;
- clothing, hair, temperament, expression, posture;
- scene and background;
- camera framing;
- language and speaking style;
- aspect ratio and resolution;
- subtitle choice: default disabled; enabled is allowed only through the same Stage B1 confirmation and local `postproduction_burn_only` route;
- effects choice: enabled or disabled, with exact approved effects when enabled;
- BGM, B-roll, and cutaways only when effects are explicitly enabled;
- lip-sync requirement and model support.

If no avatar image is provided, plan an original virtual avatar reference image for user approval.

## `hybrid_broll_edit`

Use only when the user explicitly wants to enhance existing talking-head video/audio or use a subtitle file as offline transcript reference. Merely providing an existing asset does not authorize B-roll, title cards, music, masks, text overlays, or other effects.

Output:

- keep/source asset rule;
- transcript or subtitle-informed offline segmentation;
- Provider no-text rule and default-disabled/optional-local subtitle rule;
- explicit effects choice and, only when enabled, a B-roll/title-card plan by segment;
- multi-platform ratio versions;
- editing checklist.

When effects are disabled, preserve the complete source/model video without visual packaging. Confirmed subtitles are the only permitted exception and must be burned locally after clean review. Do not treat tools like OpenMontage as from-zero video generators.

## `longform_editing`

Use for 2-minute, 5-minute, or longer scripts/audio/video.

Output:

- opening structure;
- chapter map;
- case/example placement;
- summary and CTA;
- edit timeline;
- short-video slice candidates;
- platform adaptation for long and short outputs.
