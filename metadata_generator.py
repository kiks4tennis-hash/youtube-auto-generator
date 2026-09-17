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
    ng_phrase: str = ""
    ok_phrase: str = ""


# トピックが無かった場合のフォールバック用テンプレート（Gemini API呼び出し失敗時に使用）
_FALLBACK_TITLES = {
    "short": "Daily English Phrase | {topic}",
    "long": "{count} Daily English Expressions | {topic}",
}

# hook_phrase 生成に失敗した場合の最終フォールバック（英語の短いキャッチコピー）。
# フレーズDBの内容には触れられないため、汎用的な煽り文句にする。
_FALLBACK_HOOK_PHRASES = [
    "DON'T SAY THIS WRONG",
    "MOST LEARNERS MISS THIS",
    "NATIVES NEVER SAY THIS",
    "AVOID THIS MISTAKE",
]

_MAX_HOOK_CHARS = 32        # 英語の短いキャッチコピー用
_MAX_NG_OK_CHARS = 40       # NG/OK各フレーズの安全上限（英単語ベース）


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
            hook_phrase = self._sanitize_hook_phrase(data.get("hook_phrase", ""))
            ng_phrase, ok_phrase = self._sanitize_ng_ok_pair(data.get("ng_ok_pair", {}), phrases)
            return VideoMetadata(
                title=data["title"],
                description=data["description"],
                tags=data.get("tags", []),
                hook_phrase=hook_phrase,
                ng_phrase=ng_phrase,
                ok_phrase=ok_phrase,
            )
        except Exception as e:
            logger.warning(f"Metadata generation via Gemini failed, using fallback: {e}")
            return self._fallback_metadata(video_type, topic, phrases)

    @staticmethod
    def _sanitize_hook_phrase(hook_phrase: str) -> str:
        """Geminiが空文字/長すぎる/プレースホルダーを返した場合に備えた安全装置。
        英語の短いキャッチコピーが前提なので、単語境界を優先しつつ文字数で丸める。"""
        hook_phrase = (hook_phrase or "").strip()
        if not hook_phrase:
            return random.choice(_FALLBACK_HOOK_PHRASES)
        if len(hook_phrase) > _MAX_HOOK_CHARS:
            hook_phrase = hook_phrase[: _MAX_HOOK_CHARS - 1].rstrip() + "…"
        return hook_phrase

    @staticmethod
    def _sanitize_ng_ok_pair(raw: dict, phrases: list[Phrase]) -> tuple[str, str]:
        """NG/OK対比の安全装置。

        「OK」側は必ず実際にこの動画で教えているフレーズと一致する場合のみ採用する。
        Geminiが無関係/不正確な文を作ってしまうと教育コンテンツとして誤りになるため、
        フレーズDBと一致しない場合や情報が不十分な場合は、ペアごと省略する
        （ThumbnailBuilder側はng/okが空ならNG/OKブロックを描画しない）。
        """
        raw = raw or {}
        ng = str(raw.get("ng", "") or "").strip()
        ok = str(raw.get("ok", "") or "").strip()

        valid_phrases = {p.phrase.strip().lower() for p in phrases}
        if not ng or not ok:
            return "", ""
        if ok.strip().lower() not in valid_phrases:
            logger.warning(f"ng_ok_pair 'ok' did not match any taught phrase, discarding: {ok!r}")
            return "", ""
        if len(ng) > _MAX_NG_OK_CHARS or len(ok) > _MAX_NG_OK_CHARS:
            return "", ""
        return ng, ok

    @classmethod
    def _fallback_metadata(cls, video_type: str, topic: str, phrases: list[Phrase]) -> VideoMetadata:
        title_template = _FALLBACK_TITLES.get(video_type, "Daily English | {topic}")
        title = title_template.format(topic=topic, count=len(phrases))
        description_lines = [f"Learn natural English expressions with examples.", ""]
        description_lines += [f"- {p.phrase}" for p in phrases[:10]]
        description = "\n".join(description_lines)
        tags = ["english", "learnenglish", "dailyenglish", "englishphrases"]
        hook_phrase = cls._sanitize_hook_phrase("")
        # Gemini呼び出し自体が失敗している状況なので、NG側の妥当な文言を機械的に
        # 作ることはできない。誤った例文を出すリスクを避け、ペアごと省略する。
        return VideoMetadata(
            title=title, description=description, tags=tags, hook_phrase=hook_phrase,
            ng_phrase="", ok_phrase="",
        )
