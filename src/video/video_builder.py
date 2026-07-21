"""
FFmpeg を使って「背景画像 + テキスト + 字幕 + 音声 + BGM」を1本のMP4に合成する共通ロジック。
short_video.py / long_video.py はこのモジュールが提供する部品を組み合わせて使う。
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)

VIDEO_OUTPUT_DIR = settings.output_dir / "videos"
VIDEO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class Segment:
    """1フレーズ分の素材一式"""
    image: Path
    phrase_audio: Path
    example_audio: Path
    phrase_text: str
    example_text: str


def _run(cmd: list[str]) -> None:
    logger.info("Running ffmpeg: " + " ".join(cmd))
    subprocess.run(cmd, check=True, capture_output=True)


class VideoBuilder:
    """
    レンダリングパイプライン: Background -> Text -> Subtitles -> Voice -> Music -> MP4
    実装方針:
      1. 各セグメントの画像を音声長に合わせた静止画クリップに変換
      2. フレーズ音声+例文音声を結合してセグメント音声トラックを作る
      3. drawtextフィルタでフレーズ/例文テキストを画面に焼き込む
      4. 複数セグメントをconcatして1本に結合
      5. 字幕(SRT)をハードサブとして焼き込む
      6. BGMをミックスして最終出力
    """

    def __init__(self, video_type: str):
        self.video_type = video_type
        self.profile = settings.profile(video_type)

    # -------------------------------------------------------------
    # セグメント単位のレンダリング
    # -------------------------------------------------------------

    def render_segment(self, segment: Segment, out_path: Path) -> Path:
        width, height = self.profile["width"], self.profile["height"]
        font_path = settings.project_root / self.profile["font_path"]
        font_size = self.profile["font_size"]
        phrase_color = self.profile["phrase_font_color"].lstrip("#")
        example_color = self.profile["example_font_color"].lstrip("#")

        # 音声を結合（フレーズ -> 無音 -> 例文）してセグメントの尺を決める
        merged_audio = out_path.with_suffix(".audio.mp3")
        self._concat_audio_with_gap(segment.phrase_audio, segment.example_audio, merged_audio)

        phrase_escaped = self._escape_drawtext(segment.phrase_text)
        example_escaped = self._escape_drawtext(segment.example_text)

        drawtext_phrase = (
            f"drawtext=fontfile='{font_path}':text='{phrase_escaped}':"
            f"fontcolor={phrase_color}:fontsize={font_size}:"
            f"x=(w-text_w)/2:y=(h*0.35):box=1:boxcolor=black@0.45:boxborderw=20"
        )
        drawtext_example = (
            f"drawtext=fontfile='{font_path}':text='{example_escaped}':"
            f"fontcolor={example_color}:fontsize={int(font_size*0.6)}:"
            f"x=(w-text_w)/2:y=(h*0.55):box=1:boxcolor=black@0.45:boxborderw=16"
        )

        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", str(segment.image),
            "-i", str(merged_audio),
            "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                   f"crop={width}:{height},{drawtext_phrase},{drawtext_example}",
            "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            "-r", str(self.profile["fps"]),
            str(out_path),
        ]
        _run(cmd)
        merged_audio.unlink(missing_ok=True)
        return out_path

    @staticmethod
    def _concat_audio_with_gap(a: Path, b: Path, out_path: Path, gap_seconds: float = 0.4) -> Path:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(a), "-i", str(b),
            "-filter_complex",
            f"[0:a]apad=pad_dur={gap_seconds}[a0];[a0][1:a]concat=n=2:v=0:a=1[aout]",
            "-map", "[aout]",
            str(out_path),
        ]
        _run(cmd)
        return out_path

    @staticmethod
    def _escape_drawtext(text: str) -> str:
        return (
            text.replace("\\", "\\\\")
            .replace(":", "\\:")
            .replace("'", "\u2019")  # シングルクォートはffmpegフィルタ構文と衝突するため全角記号に置換
        )

    # -------------------------------------------------------------
    # セグメントの連結
    # -------------------------------------------------------------

    def concat_segments(self, segment_paths: list[Path], out_path: Path) -> Path:
        list_file = out_path.with_suffix(".txt")
        list_file.write_text(
            "\n".join(f"file '{p.resolve()}'" for p in segment_paths), encoding="utf-8"
        )
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-c", "copy",
            str(out_path),
        ]
        _run(cmd)
        list_file.unlink(missing_ok=True)
        return out_path

    # -------------------------------------------------------------
    # 字幕焼き込み + BGMミックス（最終仕上げ）
    # -------------------------------------------------------------

    def finalize(self, raw_video: Path, srt_path: Path, out_path: Path) -> Path:
        bgm_path = settings.project_root / self.profile["background_music"]
        bgm_volume = self.profile["bgm_volume"]

        has_bgm = bgm_path.exists()
        if not has_bgm:
            logger.warning(f"BGM file not found at {bgm_path}, rendering without background music")

        subtitles_filter = f"subtitles='{srt_path}'"

        if has_bgm:
            cmd = [
                "ffmpeg", "-y",
                "-i", str(raw_video),
                "-stream_loop", "-1", "-i", str(bgm_path),
                "-filter_complex",
                f"[0:v]{subtitles_filter}[v];"
                f"[1:a]volume={bgm_volume}[bgm];"
                f"[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]",
                "-map", "[v]", "-map", "[aout]",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k",
                "-shortest",
                str(out_path),
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                "-i", str(raw_video),
                "-vf", subtitles_filter,
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k",
                str(out_path),
            ]
        _run(cmd)
        logger.info(f"Final video rendered -> {out_path}")
        return out_path
