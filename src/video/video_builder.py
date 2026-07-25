"""
FFmpeg を使って「背景画像 + テキスト + 音声 + BGM」を1本のMP4に合成する共通ロジック。
short_video.py / long_video.py はこのモジュールが提供する部品を組み合わせて使う。
"""

from __future__ import annotations

import subprocess
import textwrap
from dataclasses import dataclass
from pathlib import Path

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)

VIDEO_OUTPUT_DIR = settings.output_dir / "videos"
VIDEO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

ZERO_WIDTH_SPACE = "\u200b"

@dataclass
class Segment:
    """1フレーズ分の素材一式"""
    image: Path
    phrase_audio: Path
    example_audio: Path
    phrase_text: str
    example_text: str


def _run(cmd: list[str]) -> None:
    # logger.info("Running ffmpeg: " + " ".join(cmd))
    # subprocess.run(cmd, check=True, capture_output=True)
    import subprocess
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("FFmpeg STDOUT:\n", result.stdout)
        print("FFmpeg STDERR:\n", result.stderr)
        raise subprocess.CalledProcessError(
            result.returncode, cmd, output=result.stdout, stderr=result.stderr
        )

class VideoBuilder:
    """
    レンダリングパイプライン: Background -> Text -> Voice -> Music -> MP4
    実装方針:
      1. 各セグメントの画像を音声長に合わせた静止画クリップに変換
      2. フレーズ音声+例文音声を結合してセグメント音声トラックを作る
      3. drawtextフィルタでフレーズ/例文テキストを画面に焼き込む
      4. 複数セグメントをconcatして1本に結合
      5. BGMをミックスして最終出力
    """

    def __init__(self, video_type: str):
        self.video_type = video_type
        self.profile = settings.profile(video_type)

    # -------------------------------------------------------------
    # セグメント単位のレンダリング
    # -------------------------------------------------------------

    def render_segment(self, segment: Segment, out_path: Path) -> Path:
        width, height = self.profile["width"], self.profile["height"]
        font_path = self.profile["font_path"]
        font_size = self.profile["font_size"]
        video_preset = self.profile["video_preset"]
        video_crf = self.profile["video_crf"]

        phrase_color = self.profile["phrase_font_color"].lstrip("#")
        example_color = self.profile["example_font_color"].lstrip("#")

        merged_audio = out_path.with_suffix(".audio.mp3")
        self._concat_audio_with_gap(
            segment.phrase_audio,
            segment.example_audio,
            merged_audio,
        )

        # ---------- テキストファイルを作成 ----------
        phrase_file = out_path.with_suffix(".phrase.txt")
        example_file = out_path.with_suffix(".example.txt")

        phrase_file.write_text(
            self._wrap_text(segment.phrase_text, 20 if width == 1080 else 36),
            encoding="utf-8",
        )

        example_file.write_text(
            self._wrap_text(segment.example_text, 24 if width == 1080 else 44),
            encoding="utf-8",
        )

        example_font_size = int(font_size * 0.9)

        filter_complex = (
            f"[0:v]"
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},"

            f"drawtext="
            f"fontfile='{font_path}':"
            f"textfile='{phrase_file}':"
            f"reload=0:"
            f"fontcolor={phrase_color}:"
            f"fontsize={font_size}:"
            f"x=(w-text_w)/2:"
            f"y=h*0.16:"
            f"line_spacing=12:"
            f"box=1:"
            f"boxcolor=black@0.45:"
            f"boxborderw=12,"

            f"drawtext="
            f"fontfile='{font_path}':"
            f"textfile='{example_file}':"
            f"reload=0:"
            f"fontcolor={example_color}:"
            f"fontsize={example_font_size}:"
            f"x=(w-text_w)/2:"
            f"y=h*0.45:"
            f"line_spacing=16:"
            f"box=1:"
            f"boxcolor=black@0.55:"
            f"boxborderw=16"
        )

        cmd = [
            "ffmpeg",
            "-y",
            "-loop",
            "1",
            "-i",
            str(segment.image),
            "-i",
            str(merged_audio),
            "-filter_complex",
            filter_complex,
            "-c:v",
            "libx264",
            "-preset",
            video_preset,
            "-crf",
            str(video_crf),
            "-tune",
            "stillimage",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            "-r",
            str(self.profile["fps"]),
            str(out_path),
        ]

        _run(cmd)

        merged_audio.unlink(missing_ok=True)
        phrase_file.unlink(missing_ok=True)
        example_file.unlink(missing_ok=True)

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

    # @staticmethod
    # def _escape_drawtext(text: str) -> str:
    #     text = text.replace(";", "，")  # セミコロンは置換
    #     return (
    #         text.replace("\\", "\\\\")
    #             .replace("'", "\\'")
    #             .replace(":", "\\:")
    #             .replace("%", "\\%")
    #             .replace("\n", "\\\\n")   # ← これが今回の致命的ポイント
    #     )

    # @staticmethod
    # def _wrap_text(text: str, max_chars: int) -> str:
    #     """単語を保ったまま折り返し、画面端へのはみ出しを防ぐ。"""
    #     lines = textwrap.wrap(
    #         text,
    #         width=max_chars,
    #         break_long_words=False,
    #         break_on_hyphens=False,
    #     )

    #     # 行末にゼロ幅スペースを追加（見えないが行末が消えなくなる）
    #     return "\n".join(line.rstrip() + ZERO_WIDTH_SPACE for line in lines)

    @staticmethod
    def _wrap_text(text: str, max_chars: int) -> str:
        lines = textwrap.wrap(
            text,
            width=max_chars,
            break_long_words=False,
            break_on_hyphens=False,
        )
        return "\n".join(line.rstrip() for line in lines)

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
    # BGMミックス（最終仕上げ）
    # -------------------------------------------------------------

    def finalize(self, raw_video: Path, out_path: Path) -> Path:
        bgm_path = settings.project_root / self.profile["background_music"]
        bgm_volume = self.profile["bgm_volume"]
        video_preset = self.profile["video_preset"]
        video_crf = self.profile["video_crf"]

        has_bgm = bgm_path.exists()
        if not has_bgm:
            logger.warning(f"BGM file not found at {bgm_path}, rendering without background music")

        if has_bgm:
            cmd = [
                "ffmpeg", "-y",
                "-i", str(raw_video),
                "-stream_loop", "-1", "-i", str(bgm_path),
                "-filter_complex",
                f"[1:a]volume={bgm_volume}[bgm];"
                f"[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]",
                "-map", "0:v", "-map", "[aout]",
                "-c:v", "libx264", "-preset", video_preset, "-crf", str(video_crf), "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k",
                "-shortest",
                str(out_path),
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                "-i", str(raw_video),
                "-c:v", "libx264", "-preset", video_preset, "-crf", str(video_crf), "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k",
                str(out_path),
            ]
        _run(cmd)
        logger.info(f"Final video rendered -> {out_path}")
        return out_path
