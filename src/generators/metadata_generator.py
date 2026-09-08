"""
Gemini API を使って動画のタイトル・説明文・タグを生成するモジュール。
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from typing import Optional

import google.generativeai as genai
from tenacity import retry, stop_after_attempt, wait_exponential

from config.prompts import METADATA_GENERATION_PROMPT
from config.settings import settings
from database.repository import Phrase
from utils.logger import get_logger

logger = get_logger(__name__)

_JSON_FENCE_RE = re.compile(r"^```(?:json)?|```$", re.MULTILINE)


@dataclass
class VideoMetadata:
    title: str
    description: str
    tags: list[str]
    hook_phrase: str = ""


# トピックが無かった場合のフォールバック用テンプレート（Gemini API呼び出し失敗時に使用）
_FALLBACK_TITLES = {
    "short": "Daily English Phrase | {topic}",
    "long": "{count} Daily English Expressions | {topic}",
}

# hook_phrase 生成に失敗した場合の最終フォールバック（サムネイル側のデフォルトと役割は同じだが、
# ここではフレーズDBの内容に触れられないため汎用的な煽り文句にする）
_FALLBACK_HOOK_PHRASES = [
    "DON'T SAY THIS WRONG",
    "MOST LEARNERS MISS THIS",
    "NATIVES NEVER SAY THIS",
    "AVOID THIS MISTAKE",
]

_MAX_HOOK_CHARS = 60


class MetadataGenerator:
    def __init__(self):
        genai.configure(api_key=settings.gemini.api_key)
        self.model = genai.GenerativeModel(settings.gemini.model)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=20))
    def _call_gemini(self, prompt: str) -> str:
        response = self.model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.7,
                response_mime_type="application/json",
            ),
        )
        return response.text

    def generate(self, video_type: str, topic: str, phrases: list[Phrase]) -> VideoMetadata:
        phrase_list = "\n".join(f"- {p.phrase} ({p.example})" for p in phrases)
        prompt = METADATA_GENERATION_PROMPT.format(
            video_type=video_type, topic=topic, phrase_list=phrase_list
        )
        try:
            raw_text = self._call_gemini(prompt)
            cleaned = _JSON_FENCE_RE.sub("", raw_text).strip()
            data = json.loads(cleaned)
            hook_phrase = self._sanitize_hook_phrase(data.get("hook_phrase", ""), phrases)
            return VideoMetadata(
                title=data["title"],
                description=data["description"],
                tags=data.get("tags", []),
                hook_phrase=hook_phrase,
            )
        except Exception as e:
            logger.warning(f"Metadata generation via Gemini failed, using fallback: {e}")
            return self._fallback_metadata(video_type, topic, phrases)

    @staticmethod
    def _sanitize_hook_phrase(hook_phrase: str, phrases: list[Phrase]) -> str:
        """Geminiが空文字/長すぎる/プレースホルダーを返した場合に備えた安全装置"""
        hook_phrase = (hook_phrase or "").strip()
        if not hook_phrase:
            hook_phrase = MetadataGenerator._derive_hook_from_phrases(phrases)
        if len(hook_phrase) > _MAX_HOOK_CHARS:
            hook_phrase = hook_phrase[: _MAX_HOOK_CHARS - 1].rstrip() + "…"
        return hook_phrase

    @staticmethod
    def _derive_hook_from_phrases(phrases: list[Phrase]) -> str:
        if phrases:
            return random.choice(phrases).example
        return random.choice(_FALLBACK_HOOK_PHRASES)

    @classmethod
    def _fallback_metadata(cls, video_type: str, topic: str, phrases: list[Phrase]) -> VideoMetadata:
        title_template = _FALLBACK_TITLES.get(video_type, "Daily English | {topic}")
        title = title_template.format(topic=topic, count=len(phrases))
        description_lines = [f"Learn natural English expressions with examples.", ""]
        description_lines += [f"- {p.phrase}" for p in phrases[:10]]
        description = "\n".join(description_lines)
        tags = ["english", "learnenglish", "dailyenglish", "englishphrases"]
        hook_phrase = cls._sanitize_hook_phrase("", phrases)
        return VideoMetadata(title=title, description=description, tags=tags, hook_phrase=hook_phrase)
