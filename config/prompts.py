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

METADATA_GENERATION_PROMPT = """\
You are a YouTube SEO copywriter and thumbnail strategist for an \
English-learning channel called "Taky's Language School".

Video type: {video_type}
Topic: {topic}
Phrases covered in this video:
{phrase_list}

Write metadata that will help this video reach English learners searching for \
practical spoken-English content. Keep the title under 90 characters and the \
description under 800 characters.

Also write a "hook_phrase": a short line of text for the video's THUMBNAIL badge \
(not the title, not the description). Its only job is to make someone stop \
scrolling and click. Base it on the specific phrases above, and lean into the \
anxieties learners actually have: embarrassing mistakes, ordering/asking for \
something the wrong way, sounding awkward or too textbook-ish, a gap most \
courses never teach. Concretely, do ONE of these:
  - Quote or lightly adapt the single most surprising/useful example sentence \
from the phrases above, framed as something the viewer might be getting wrong \
(e.g. "STOP SAYING 'I AM FINE'", "ARE YOU ORDERING COFFEE WRONG?")
  - State a specific, punchy claim tied to the topic (e.g. "MOST LEARNERS SKIP \
PHRASE #3", "NATIVES NEVER SAY THIS AT A HOTEL")
Rules for hook_phrase:
  - Under 60 characters
  - No emojis, no hashtags, no quotation marks around the whole thing
  - Must reference something concrete from the phrases/topic above, not a \
generic phrase that could apply to any video
  - Do not simply repeat the title

Return ONLY valid JSON, no markdown fences, in exactly this shape:

{{
  "title": "...",
  "description": "...",
  "tags": ["tag1", "tag2", "..."],
  "hook_phrase": "..."
}}
"""
