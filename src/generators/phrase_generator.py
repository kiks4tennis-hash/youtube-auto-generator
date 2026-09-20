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

from config.prompts import PHRASE_GENERATION_PROMPT, PHRASE_GENERATION_PROMPT_FOR_TOPIC
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
    def _generate_batch(self, n: int, topic: Optional[str] = None) -> list[dict]:
        """Gemini呼び出し+パースをまとめて1単位とし、JSON破損時もこの単位でリトライする
        （_call_gemini自体も内部で2回試行するため、最悪1バッチあたり最大4回試行される）"""
        if topic:
            prompt = PHRASE_GENERATION_PROMPT_FOR_TOPIC.format(count=n, topic=topic)
        else:
            prompt = PHRASE_GENERATION_PROMPT.format(count=n)
        raw_text = self._call_gemini(prompt)
        phrases = self._parse_response(raw_text)
        if topic:
            # Geminiがtopicの表記を微妙に揺らして返すことがあるため、
            # 呼び出し元が指定した文字列に強制的に揃える
            # （揺れがあると fetch_unused_phrases(topic=...) で拾えなくなる）
            for p in phrases:
                p["topic"] = topic
        return phrases

    def generate_phrases(self, count: int, topic: Optional[str] = None) -> list[dict]:
        """count件のフレーズを生成する。1回のJSON出力が長すぎて打ち切られないよう、
        25件ずつ分割して呼び出す（max_output_tokens=8192との組み合わせで安全マージンを確保）。
        topicを指定すると、そのトピックのフレーズのみを狙い撃ちで生成する
        （Long動画を単一トピックで揃えるための追加補充に使用）。"""
        batch_size = 25
        collected: list[dict] = []

        remaining = count
        while remaining > 0:
            n = min(batch_size, remaining)
            topic_note = f" for topic='{topic}'" if topic else ""
            logger.info(f"Requesting {n} phrases from Gemini{topic_note}...")
            try:
                collected.extend(self._generate_batch(n, topic=topic))
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

    def generate_and_store(self, count: int, topic: Optional[str] = None) -> int:
        """フレーズを生成しDBへ保存する。挿入件数を返す。
        topic指定時はそのトピックのみを補充する（Long動画の単一トピック化のため）。"""
        phrases = self.generate_phrases(count, topic=topic)
        inserted = self.repository.insert_phrases(phrases)
        topic_note = f" for topic='{topic}'" if topic else ""
        logger.info(f"Inserted {inserted} new phrases{topic_note} into the database")
        return inserted


# def ensure_phrase_inventory() -> int:
#     """
#     Airflowタスクから呼ばれるエントリポイント。
#     在庫が閾値を下回っていればGeminiで補充する。返り値: 実際に生成した件数（0の場合は補充不要）。
#     """
#     repo = Repository()
#     current_count = repo.count_unused_phrases()
#     threshold = settings.pipeline.phrase_inventory_threshold
#     logger.info(f"Unused phrase inventory: {current_count} (threshold={threshold})")

#     if current_count >= threshold:
#         logger.info("Inventory sufficient. Skipping generation.")
#         return 0

#     batch = settings.pipeline.phrase_generation_batch
#     generator = PhraseGenerator(repository=repo)
#     return generator.generate_and_store(batch)

def ensure_phrase_inventory(required_count: int = 1) -> int:
    """
    Airflowタスクから呼ばれるエントリポイント。
    在庫が閾値を下回っていればGeminiで補充する。
    
    ※ required_count: 今回のタスクで最低限必要となるフレーズ数（デフォルト1）
    """
    repo = Repository()
    current_count = repo.count_unused_phrases()
    threshold = settings.pipeline.phrase_inventory_threshold
    logger.info(f"Unused phrase inventory: {current_count} (threshold={threshold})")

    # 在庫が「閾値」または「今回の必要数」を下回っていたら強制補充
    if current_count < threshold or current_count < required_count:
        logger.info(f"Inventory low ({current_count}). Generating new phrases...")
        batch = settings.pipeline.phrase_generation_batch
        generator = PhraseGenerator(repository=repo)
        
        inserted = generator.generate_and_store(batch)
        
        # 【重要】もしGemini生成に失敗して1件も追加できず、かつ在庫が1件もない場合は例外を投げてAirflowを止める
        if current_count + inserted < required_count:
            raise RuntimeError(f"Failed to secure enough phrases. Current: {current_count}, Inserted: {inserted}")
            
        return inserted

    logger.info("Inventory sufficient. Skipping generation.")
    return 0

if __name__ == "__main__":
    ensure_phrase_inventory()