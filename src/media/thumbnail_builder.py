"""
Pillow を使ってLong動画用サムネイルを生成するモジュール。
（設計書の通り、Shortsではサムネイルは生成しない）
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)

THUMBNAIL_OUTPUT_DIR = settings.output_dir / "thumbnails"
THUMBNAIL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

THUMB_WIDTH, THUMB_HEIGHT = 1280, 720


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    font_path = settings.project_root / settings.profile("long")["font_path"]
    try:
        return ImageFont.truetype(str(font_path), size)
    except OSError:
        logger.warning(f"Font not found at {font_path}, falling back to default font")
        return ImageFont.load_default()


class ThumbnailBuilder:
    def build(
        self,
        video_id: int,
        main_title: str,
        sub_title: str,
        background_image: Path | None = None,
    ) -> Path:
        if background_image and background_image.exists():
            base = Image.open(background_image).convert("RGB").resize((THUMB_WIDTH, THUMB_HEIGHT))
        else:
            base = Image.new("RGB", (THUMB_WIDTH, THUMB_HEIGHT), color=(15, 23, 42))

        # 可読性のため下側に半透明の黒帯を敷く
        overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
        draw_overlay = ImageDraw.Draw(overlay)
        draw_overlay.rectangle(
            [(0, THUMB_HEIGHT - 260), (THUMB_WIDTH, THUMB_HEIGHT)], fill=(0, 0, 0, 160)
        )
        base = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")

        draw = ImageDraw.Draw(base)
        title_font = _load_font(72)
        sub_font = _load_font(44)

        draw.text((60, THUMB_HEIGHT - 220), main_title, font=title_font, fill="#FFFFFF")
        draw.text((60, THUMB_HEIGHT - 120), sub_title, font=sub_font, fill="#FFD54A")

        out_path = THUMBNAIL_OUTPUT_DIR / f"long_{video_id}.jpg"
        base.save(out_path, quality=92)
        logger.info(f"Built thumbnail -> {out_path}")
        return out_path
