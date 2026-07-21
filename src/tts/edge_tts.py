"""
Edge TTS (Microsoft Edge の無料音声合成) を使って、フレーズ・例文の音声ファイルを生成する。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import edge_tts

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)

AUDIO_OUTPUT_DIR = settings.output_dir / "audio"
AUDIO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


async def _synthesize(text: str, voice: str, out_path: Path) -> None:
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(out_path))


def synthesize_sync(text: str, voice: str, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(_synthesize(text, voice, out_path))
    logger.info(f"Synthesized audio -> {out_path}")
    return out_path


class TTSGenerator:
    """フレーズ / 例文 それぞれ別の声で読み上げ、mp3ファイルを生成する"""

    def __init__(self):
        self.phrase_voice = settings.tts.phrase_voice
        self.example_voice = settings.tts.example_voice

    def generate_phrase_audio(self, phrase_id: int, text: str) -> Path:
        out_path = AUDIO_OUTPUT_DIR / f"phrase_{phrase_id}.mp3"
        return synthesize_sync(text, self.phrase_voice, out_path)

    def generate_example_audio(self, phrase_id: int, text: str) -> Path:
        out_path = AUDIO_OUTPUT_DIR / f"example_{phrase_id}.mp3"
        return synthesize_sync(text, self.example_voice, out_path)

    def generate_for_phrase(self, phrase_id: int, phrase: str, example: str) -> dict:
        return {
            "phrase_audio": self.generate_phrase_audio(phrase_id, phrase),
            "example_audio": self.generate_example_audio(phrase_id, example),
        }
