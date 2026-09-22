"""
Gemini API に投げるプロンプトのテンプレート集。
生成物は必ず JSON のみを返すよう厳密に指示する（パース失敗を防ぐため）。
"""

PHRASE_GENERATION_PROMPT = """\
You are an assistant that creates content for an English-learning YouTube channel.

Generate {count} natural, commonly-used daily English phrases that intermediate \
learners would find genuinely useful (greetings, travel, restaurants, shopping, \
business, airport, hotel, small talk, etc). Avoid duplicates and avoid overly \
academic or rare expressions.

For each phrase provide:
- "phrase": the short expression itself
- "example": one natural example sentence using the phrase in context
- "scene": a single English keyword describing the situation, suitable as an \
image search keyword (e.g. "airport", "restaurant", "office", "shopping", "hotel")
- "topic": a short topic category in Title Case (e.g. "Travel English", \
"Business English", "Restaurant English", "Shopping English")

Return ONLY valid JSON, with no markdown code fences and no extra commentary, \
in exactly this shape:

{{
  "phrases": [
    {{"phrase": "...", "example": "...", "scene": "...", "topic": "..."}}
  ]
}}
"""

PHRASE_GENERATION_PROMPT_FOR_TOPIC = """\
You are an assistant that creates content for an English-learning YouTube channel.

Generate {count} natural, commonly-used daily English phrases that intermediate \
learners would find genuinely useful, ALL specifically for this one topic: \
"{topic}". Every phrase must clearly belong to this topic - do not drift into \
unrelated situations. Avoid duplicates and avoid overly academic or rare \
expressions.

For each phrase provide:
- "phrase": the short expression itself
- "example": one natural example sentence using the phrase in context
- "scene": a single English keyword describing the situation, suitable as an \
image search keyword, consistent with the topic "{topic}"
- "topic": always exactly "{topic}" (copy it verbatim for every phrase)

Return ONLY valid JSON, with no markdown code fences and no extra commentary, \
in exactly this shape:

{{
  "phrases": [
    {{"phrase": "...", "example": "...", "scene": "...", "topic": "{topic}"}}
  ]
}}
"""

METADATA_GENERATION_PROMPT = """\
You are a YouTube SEO copywriter and thumbnail strategist for an \
English-learning channel called "Taky's Language School", which teaches \
Japanese speakers practical spoken English.

Video type: {video_type}
Topic: {topic}
Phrases covered in this video:
{phrase_list}

Write metadata that will help this video reach English learners searching for \
practical spoken-English content. Keep the title under 90 characters and the \
description under 800 characters (title and description stay in English).

This video covers exactly ONE topic ("{topic}") - it is not a mixed-topic \
video. The title MUST make that topic unmistakable at a glance: lead with the \
topic itself (e.g. start with "{topic}" or a natural equivalent of it) rather \
than burying it after a generic phrase count. "20 Daily English Expressions" \
is too generic on its own; "{topic}: 20 Phrases You'll Actually Use" or \
"{topic} - 20 Natural Ways to..." are the right shape. The description's \
first sentence should also make the topic explicit.

Also write two thumbnail-only fields:

1. "hook_phrase": a SHORT, high-impact catch-copy WRITTEN IN ENGLISH for the \
thumbnail's headline banner (not the title, not the description). This is the \
single most important piece of text on the thumbnail, so it must be SHORT \
(roughly 3-7 words, under 40 characters) and create curiosity or a sense of \
urgency - like a magazine cover line, not a caption or full sentence. Base it \
on the specific phrases above and lean into anxieties learners actually have: \
not being understood, sounding unnatural/textbook-ish, embarrassing mistakes, \
a gap most courses never teach. Style examples (write your own new one, don't \
reuse these): "NATIVES NEVER SAY THIS" / "STOP SOUNDING ROBOTIC" / "FIX THIS \
MISTAKE NOW" / "THE #1 REASON YOU'RE MISUNDERSTOOD". Do NOT write a full \
sentence or explanation - it must read like a poster headline.

2. "ng_ok_pair": contrasts a common unnatural/textbook English phrase ("ng") \
with the natural native phrase actually taught in this video ("ok"), for a \
❌ vs ⭕ visual on the thumbnail. Both must be SHORT (2-6 words, not full \
sentences).
  - "ok" MUST be copied verbatim from one of the "phrase" values listed above \
(pick whichever is the most clearly "natural native phrasing vs textbook \
phrasing" contrast).
  - "ng" is a plausible unnatural/overly-literal English phrase a Japanese \
learner might mistakenly use instead of "ok". It must be grammatically valid, \
real English - just awkward/non-native. Never gibberish, never offensive.
  - If none of the phrases above lend themselves to a clean NG vs OK contrast, \
return {{"ng": "", "ok": ""}} instead of forcing a weak or misleading example.

Rules for hook_phrase:
  - English only, roughly 3-7 words, under 40 characters
  - No emojis, no hashtags, no quotation marks around the whole thing
  - Must reference something concrete from the phrases/topic above, not a \
generic line that could apply to any video
  - Do not simply repeat the title

Return ONLY valid JSON, no markdown fences, in exactly this shape:

{{
  "title": "...",
  "description": "...",
  "tags": ["tag1", "tag2", "..."],
  "hook_phrase": "...",
  "ng_ok_pair": {{"ng": "...", "ok": "..."}}
}}
"""
