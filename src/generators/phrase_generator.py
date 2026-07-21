"""
Gemini API を使って英語フレーズを大量生成し、DBに保存するモジュール。
フレーズ在庫が閾値を下回った場合に Airflow から呼び出される。
"""

from __future__ import annotations

import json
import re
from typing import Optional

import google.generativeai as genai
from tenacity import retry, stop_after_attempt, wait_exponential

from config.prompts import PHRASE_GENERATION_PROMPT
from config.settings import settings
from database.repository import Repository
from utils.logger import get_logger

logger = get_logger(__name__)

_JSON_FENCE_RE = re.compile(r"^```(?:json)?|```$", re.MULTILINE)


def _clean_json_text(text: str) -> str:
    """Geminiがまれに付けてしまうmarkdownのコードフェンスを除去する"""
    return _JSON_FENCE_RE.sub("", text).strip()


class PhraseGenerator:
    def __init__(self, repository: Optional[Repository] = None):
        if not settings.gemini.api_key:
            logger.warning("GEMINI_API_KEY is not set. Gemini calls will fail.")
        genai.configure(api_key=settings.gemini.api_key)
        self.model = genai.GenerativeModel(settings.gemini.model)
        self.repository = repository or Repository()

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=2, min=2, max=20))
    def _call_gemini(self, prompt: str) -> str:
        response = self.model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.9,
                response_mime_type="application/json",
                max_output_tokens=8192,
            ),
        )
        # レスポンスが出力上限で途中打ち切りになっていないか確認する
        candidate = response.candidates[0] if response.candidates else None
        if candidate and candidate.finish_reason == 2:  # 2 = MAX_TOKENS
            logger.warning(
                "Gemini response was truncated due to max_output_tokens. "
                "Consider lowering the batch size."
            )
        return response.text

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=2, min=2, max=20))
    def _generate_batch(self, n: int) -> list[dict]:
        """Gemini呼び出し+パースをまとめて1単位とし、JSON破損時もこの単位でリトライする
        （_call_gemini自体も内部で2回試行するため、最悪1バッチあたり最大4回試行される）"""
        prompt = PHRASE_GENERATION_PROMPT.format(count=n)
        raw_text = self._call_gemini(prompt)
        return self._parse_response(raw_text)

    def generate_phrases(self, count: int) -> list[dict]:
        """count件のフレーズを生成する。1回のJSON出力が長すぎて打ち切られないよう、
        25件ずつ分割して呼び出す（max_output_tokens=8192との組み合わせで安全マージンを確保）"""
        batch_size = 25
        collected: list[dict] = []

        remaining = count
        while remaining > 0:
            n = min(batch_size, remaining)
            logger.info(f"Requesting {n} phrases from Gemini...")
            try:
                collected.extend(self._generate_batch(n))
            except Exception as e:
                # リトライを尽くしてもなお失敗した場合のみ、そのバッチを諦めて次へ進む
                logger.error(f"Skipping a batch of {n} phrases after retries exhausted: {e}")
            remaining -= n

        return collected

    @staticmethod
    def _parse_response(raw_text: str) -> list[dict]:
        cleaned = _clean_json_text(raw_text)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Gemini response as JSON: {e}\nRaw: {raw_text[:500]}")
            raise

        phrases = data.get("phrases", [])
        valid = [
            p
            for p in phrases
            if all(k in p and p[k] for k in ("phrase", "example", "scene"))
        ]
        logger.info(f"Parsed {len(valid)} valid phrases out of {len(phrases)} returned")
        return valid

    def generate_and_store(self, count: int) -> int:
        """フレーズを生成しDBへ保存する。挿入件数を返す。"""
        phrases = self.generate_phrases(count)
        inserted = self.repository.insert_phrases(phrases)
        logger.info(f"Inserted {inserted} new phrases into the database")
        return inserted


def ensure_phrase_inventory() -> int:
    """
    Airflowタスクから呼ばれるエントリポイント。
    在庫が閾値を下回っていればGeminiで補充する。返り値: 実際に生成した件数（0の場合は補充不要）。
    """
    repo = Repository()
    current_count = repo.count_unused_phrases()
    threshold = settings.pipeline.phrase_inventory_threshold
    logger.info(f"Unused phrase inventory: {current_count} (threshold={threshold})")

    if current_count >= threshold:
        logger.info("Inventory sufficient. Skipping generation.")
        return 0

    batch = settings.pipeline.phrase_generation_batch
    generator = PhraseGenerator(repository=repo)
    return generator.generate_and_store(batch)


if __name__ == "__main__":
    ensure_phrase_inventory()