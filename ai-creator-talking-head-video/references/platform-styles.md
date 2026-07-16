# Platform Styles

## Douyin / 抖音

- Fast hook in the first 1 to 3 seconds.
- Short sentences and clear opinions. Use caption emphasis only when subtitles were confirmed for local postproduction.
- 9:16 default.
- Strong opening claim, contrast, or result-first framing.
- B-roll should change every 2 to 4 seconds for short videos.

## TikTok

- Casual, direct, high-energy opening.
- English or bilingual lines should be short and spoken naturally.
- Use pattern interrupts: zoom, title card, screenshot pop-in, reaction cut.
- Avoid long setup.

## Xiaohongshu / 小红书

- More trust-building and explanation than hard selling.
- Use "experience, checklist, pitfall, before/after, personal lesson" angles.
- When captions are confirmed, keep the style clean and editorial; keyword highlighting remains an optional approved effect, not a Provider instruction.
- Cover/title logic matters as much as the first frame.

## Bilibili / B站

- Allow more context and explanation.
- Structure should include setup, reasoning, example, conclusion.
- 16:9 or 9:16 depending on the account format.
- More tolerant of chapters, screen recordings, and deeper analysis.

## YouTube Shorts

- English hooks should be simple and concrete.
- Avoid overly literal translation from Chinese.
- Use one idea per short.
- 9:16 default, with safe captions away from UI overlays.

## YouTube Horizontal

- 16:9 default.
- Strong opening promise, then chapters.
- Use screen recording, diagrams, examples, and section cards.
- Longer videos need clear retention beats every 30 to 60 seconds.

## Default Ratios

- Short vertical: `9:16`, 1080x1920 or 720x1280.
- Horizontal longform: `16:9`, 1920x1080 or 1280x720.
- Avoid placing subtitles over face, mouth, key B-roll detail, platform buttons, or progress bars.

## Optional Subtitle Safe-Zone Profiles

Subtitles are default disabled. When Stage B1 confirms them, resolve `assets/templates/subtitle-style-profiles.example.json` against the final video resolution:

- Douyin/TikTok: `vertical_social`, with larger right/bottom margins for controls;
- YouTube Shorts: `youtube_shorts`;
- Xiaohongshu: `xiaohongshu_vertical`;
- YouTube horizontal: `youtube_horizontal`;
- Bilibili horizontal: `bilibili_horizontal`;
- unknown vertical/horizontal: the matching generic profile.

All profiles use at most two lines, transparent background, white text with a dark outline, and final frame inspection. These are practical defaults; platform overlays can change.
