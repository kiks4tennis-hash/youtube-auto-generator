"""
Gemini API を使って動画のタイトル・説明文・タグを生成するモジュール。
"""

from __future__ import annotations

import json
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


# トピックが無かった場合のフォールバック用テンプレート（Gemini API呼び出し失敗時に使用）
_FALLBACK_TITLES = {
    "short": "Daily English Phrase | {topic}",
    "long": "{count} Daily English Expressions | {topic}",
}


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
            return VideoMetadata(
                title=data["title"],
                description=data["description"],
                tags=data.get("tags", []),
            )
        except Exception as e:
            logger.warning(f"Metadata generation via Gemini failed, using fallback: {e}")
            return self._fallback_metadata(video_type, topic, phrases)

    @staticmethod
    def _fallback_metadata(video_type: str, topic: str, phrases: list[Phrase]) -> VideoMetadata:
        title_template = _FALLBACK_TITLES.get(video_type, "Daily English | {topic}")
        title = title_template.format(topic=topic, count=len(phrases))
        description_lines = [f"Learn natural English expressions with examples.", ""]
        description_lines += [f"- {p.phrase}" for p in phrases[:10]]
        description = "\n".join(description_lines)
        tags = ["english", "learnenglish", "dailyenglish", "englishphrases"]
        return VideoMetadata(title=title, description=description, tags=tags)
