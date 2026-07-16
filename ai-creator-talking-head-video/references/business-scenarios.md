# Business Scenario Routing

Use this reference whenever the user provides business materials, asks whether a talking-head digital-human video方案 is professional, or the target use case is broader than creator self-media.

The goal is to turn "user material + user intent" into a scenario-specific video plan. Do not output a generic talking-head plan before identifying the business scenario, audience, success metric, and risk boundary.

## Analysis Before Proposal

Inspect the user request and provided assets for:

- business scenario: creator content, training, product explainer, sales enablement, customer service, HR/internal communication, local-life guide, high-compliance explainer, localization, or existing-video enhancement;
- user intent: educate, convert, support, onboard, announce, explain, build trust, localize, or package existing media;
- viewer: customer, learner, employee, prospect, applicant, patient/client, visitor, fan, or platform algorithm audience;
- source material: script, PPT, PDF, FAQ, SOP, product page, sales deck, course outline, policy, transcript, subtitle, audio, video, screenshots, brand guide, or competitor sample;
- success metric: completion rate, lead click, FAQ deflection, training comprehension, sales follow-up rate, consultation booking, localization output count, or platform engagement;
- risk boundary: claim evidence, regulated industry disclaimer, brand tone, privacy, consent, avatar rights, medical/legal/financial advice limits, and platform review risk.

If the scenario is unclear, state the best-guess route and include it in the single production confirmation package.

## Source Fact Map

For PPT, FAQ, SOP, policy, product, training, HR, finance, medical, legal, news, and other factual source material, create `source_fact_map` before final script approval:

| Field | Meaning |
|---|---|
| `fact_id` | Stable id such as `FACT-001` |
| `source_locator` | PPT page, FAQ id, policy section, document paragraph, URL section, or video timestamp |
| `source_text` | Short source excerpt or faithful summary |
| `must_preserve` | Meaning that cannot change |
| `allowed_rewrite` | Simplification or localization that is allowed |
| `forbidden_inference` | Policy, price, deadline, guarantee, result, or exception that must not be invented |
| `script_beat` | Script segment that uses the fact |
| `verification_status` | `verified`, `needs_user_confirmation`, or `missing_source` |

Do not approve a factual script while required entries are `missing_source`. Keep this map in the proposal and project brief so later revisions remain traceable.

## Popular Scenario Map

| Scenario route | Common user material | Business purpose | Proposal focus | Suggested modes | Success signal | Risk boundary |
|---|---|---|---|---|---|---|
| Creator / knowledge IP | topic, draft, screenshots, competitor samples | Build account trust, spread a point of view, gain followers | strong hook, opinion value, platform-native script, avatar IP, share reason | `topic_planning`, `viral_teardown`, `script_rewrite`, `avatar_talking_head` | retention, shares, comments, follows | do not copy competitor script or identity |
| Course / enterprise training | PPT, course outline, SOP, lesson notes, screen recordings | Make learning clearer and easier to update | learning objective, chapter flow, examples, recap, quiz/checkpoint, stable teacher avatar | `script_rewrite`, `avatar_talking_head`, `longform_editing`, `hybrid_broll_edit` | completion rate, learner comprehension, fewer repeated explanations | keep facts faithful to source material; avoid invented policies |
| Product explainer / sales enablement | product doc, sales deck, website, demo screenshots | Explain value and help sales follow-up | pain-point framing, feature-to-benefit proof, demo B-roll, CTA, sales objections | `script_rewrite`, `avatar_talking_head`, `hybrid_broll_edit` | demo booking, reply rate, click-through, sales reuse | claims need evidence; avoid guaranteed results |
| Customer service / FAQ / after-sales (客户服务) | FAQ, policy, service flow, support transcripts | Reduce repetitive support and explain procedures | problem category, step-by-step answer, visual process card, calm service avatar | `script_rewrite`, `avatar_talking_head`, `hybrid_broll_edit` | fewer support tickets, faster answer time, higher satisfaction | avoid replacing official policy; mention source/date if policy-sensitive |
| HR / recruiting / onboarding / internal comms | job description, onboarding docs, company announcement, handbook | Help candidates or employees understand key information | warm but precise tone, company culture, timeline, checklist, version update notes | `script_rewrite`, `avatar_talking_head`, `longform_editing` | onboarding completion, message reach, fewer HR repeats | avoid exaggerating benefits or making unsupported employment promises |
| Brand / corporate introduction | brand guide, founder note, company deck, event material | Establish trust and present a consistent public face | brand voice, spokesperson avatar, scene design, credibility proof, clean CTA | `script_rewrite`, `avatar_talking_head` | brand recall, inquiry, event conversion | keep brand assets authorized and consistent |
| E-commerce / product seeding / local-life lead generation | product page, store photos, menu, real-estate listing, tour info | Convert interest while keeping content useful | benefit-led script, real asset B-roll, proof points, offer/booking CTA | `script_rewrite`, `avatar_talking_head`, `hybrid_broll_edit`, `commerce_hybrid` | click, booking, coupon use, consultation, GMV | if pure ad or heavy product selling, prefer `ai-commerce-video` |
| News / media / professional commentary | news brief, expert notes, transcript, research summary | Publish timely explanation or analysis | neutral presenter, source-aware script, chronology, fact separation | `script_rewrite`, `avatar_talking_head`, `longform_editing` | clarity, credibility, watch time | separate fact from opinion; avoid unverified claims |
| Finance / insurance / legal / medical explainers | policy, compliance notes, public education material | Explain complex topics in a safer, easier format | conservative wording, source-backed claims, disclaimer, no individualized advice | `script_rewrite`, `avatar_talking_head`, `longform_editing` | comprehension, consultation quality, reduced misunderstanding | no diagnosis, legal conclusion, investment promise, or guaranteed outcome |
| Real estate / auto / travel / cultural tourism | listing, brochure, route map, venue photos, vehicle spec | Guide decisions through visual explanation | guided tour structure, real-scene B-roll, comparison points, booking CTA | `script_rewrite`, `avatar_talking_head`, `hybrid_broll_edit` | inquiry, booking, saved video, route completion | do not hide material limitations or outdated details |
| Multilingual localization / cross-border | source script, finished video, brand glossary, target markets | Scale the same message across languages and regions | language version plan, cultural adaptation, spoken-language review, voice/avatar consistency, no on-screen text | `script_rewrite`, `avatar_talking_head`, `hybrid_broll_edit` | number of localized versions, market engagement, lower production time | avoid literal translation that breaks local meaning or compliance |
| Existing talking-head enhancement | MP4, audio, SRT, transcript | Keep original speaker while upgrading watchability | preserve source timing, SRT as offline transcript only, approved non-text B-roll, ratio versions | `hybrid_broll_edit`, `longform_editing` | watch time, repackaging efficiency, platform-ready exports | do not add captions/title text, force TTS, or change the original speech without approval |

## Scenario-to-Design Rules

- Training videos need a teaching structure: objective -> problem -> explanation -> example -> recap -> next action. The avatar should feel credible and calm, not overly promotional.
- Customer service videos need answer clarity: user problem -> direct answer -> steps -> exception cases -> official path. The avatar should be patient and service-oriented.
- Sales or product explainer videos need proof: pain point -> outcome -> key feature -> demonstration/B-roll -> objection handling -> CTA. Avoid unsupported claims.
- HR and internal communication videos need trust and precision: who it affects -> what changed -> what to do -> deadline/path -> where to ask questions.
- High-compliance videos need conservative language: source basis -> general education -> risk reminder -> consult professional/official channel. Do not produce definitive advice.
- Local-life, real-estate, auto, travel, and venue videos need real asset grounding: use actual photos/maps/specs when provided and flag missing or outdated details.
- Multilingual videos need consistency plus adaptation: keep the same visual identity, but adapt spoken examples, measurement units, idioms, and CTA; captions remain optional local postproduction.

For multilingual delivery, keep one project and production contract per target language/locale. Record `source_language`, `target_language`, `target_locale`, optional glossary, and `translation_review_status`. The localized script and terminology must be `verified` before paid preflight; each locale receives its own clean Provider video, optional confirmed captioned copy, reviews, and delivery manifest.

## Proposal Requirements

The first proposal must include:

- selected scenario route and why it fits the provided materials;
- user intent and target viewer;
- source material inventory and missing material;
- scenario-specific video structure;
- avatar, scene, tone, and B-roll logic;
- success metric or acceptance target;
- risk/compliance boundary;
- generated/reference image list and which images may enter the video model;
- a first plan-confirmation question covering duration, planned images, subtitle choice, effects, model route, segments, and paid cap; after image generation, a second confirmation approves the exact images and starts production.

## Red Flags

- The proposal only rewrites a script but does not explain the business scenario.
- Enterprise, FAQ, SOP, HR, or course material is treated as generic self-media content.
- A high-compliance topic is written with absolute claims or personalized advice.
- Product or local-life claims are invented when the user did not provide proof.
- Existing audio/subtitle/video is ignored and the plan forces TTS.
- Multilingual localization only translates words and does not preserve brand, layout, or cultural fit.
