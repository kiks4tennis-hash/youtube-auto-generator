"""
音声ファイルの長さを取得し、フレーズ/例文それぞれに対応するSRT字幕を生成するモジュール。
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)

SUBTITLE_OUTPUT_DIR = settings.output_dir / "subtitles"
SUBTITLE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class SubtitleCue:
    start: float
    end: float
    text: str


def get_audio_duration(path: Path) -> float:
    """ffprobeを使って音声ファイルの長さ(秒)を取得する"""
    result = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def _format_timestamp(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def write_srt(cues: list[SubtitleCue], out_path: Path) -> Path:
    lines = []
    for i, cue in enumerate(cues, start=1):
        lines.append(str(i))
        lines.append(f"{_format_timestamp(cue.start)} --> {_format_timestamp(cue.end)}")
        lines.append(cue.text)
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"Wrote subtitle file -> {out_path}")
    return out_path


class SubtitleGenerator:
    def build_segment_cues(
        self, phrase_id: int, phrase: str, example: str,
        phrase_audio: Path, example_audio: Path, offset: float = 0.0,
    ) -> tuple[list[SubtitleCue], float]:
        """
        1フレーズ分の字幕キューを作る。
        offset: この動画内でこのフレーズが開始する時刻（Long動画で複数フレーズを連結する際に使用）
        戻り値: (キューのリスト, このセグメントの合計時間)
        """
        phrase_duration = get_audio_duration(phrase_audio)
        example_duration = get_audio_duration(example_audio)

        gap = 0.4  # フレーズ音声と例文音声の間の無音時間
        cues = [
            SubtitleCue(start=offset, end=offset + phrase_duration, text=phrase),
            SubtitleCue(
                start=offset + phrase_duration + gap,
                end=offset + phrase_duration + gap + example_duration,
                text=example,
            ),
        ]
        total_duration = phrase_duration + gap + example_duration
        return cues, total_duration

    def build_video_srt(
        self, video_type: str, video_id: int, all_cues: list[SubtitleCue]
    ) -> Path:
        out_path = SUBTITLE_OUTPUT_DIR / f"{video_type}_{video_id}.srt"
        return write_srt(all_cues, out_path)
