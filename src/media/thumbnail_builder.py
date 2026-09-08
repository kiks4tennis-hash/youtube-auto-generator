"""
Pillow を使ってLong動画用サムネイルを生成するモジュール。
（設計書の通り、Shortsではサムネイルは生成しない）

人気の英語学習/教育系チャンネルのサムネイルに共通する要素を踏まえて設計:

  1. 明確なフォーカルポイント
     右上に「フックバッジ」（実際の例文 or 煽り文句）を置き、視線を集める
     一点を作る。実写の "驚き顔" は使えないため、色付きバッジで代替する。
  2. 太字＋アウトラインのインパクトテキスト
     小さいプレビューでも読めるよう、Poppins Bold + 黒縁取りで視認性を最大化。
     フォントは assets/fonts/ に同梱し、Dockerイメージにフォントパッケージが
     無くても動くようにする（video_profiles.yaml のフォントにもフォールバック）。
  3. 可読性を最優先したコントラスト
     背景写真の明るさに関わらず読めるよう、下側を重点的に暗くするグラデーション
     ＋外周ビネットを敷く。
  4. ブランドの一貫性
     トピック名は常にブランドイエローのピルで表示し、チャンネルとして
     見分けがつくようにする（色は video_profiles.yaml の example_font_color と統一）。
  5. 背景の歪み防止
     Pexels画像のアスペクト比はまちまちなので、引き伸ばしではなく
     中央クロップ（cover）でリサイズする。
  6. 長いタイトルでも破綻しない
     自動折返し＋段階的なフォントサイズ縮小で、はみ出し・文字潰れを防ぐ。
"""

from __future__ import annotations

import random
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)

THUMBNAIL_OUTPUT_DIR = settings.output_dir / "thumbnails"
THUMBNAIL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

THUMB_WIDTH, THUMB_HEIGHT = 1280, 720

# ------------------------------------------------------------------
# ブランドカラー
# チャンネル全体で統一し、シリーズものとして視聴者に覚えてもらう。
# アクセントイエローは video_profiles.yaml の example_font_color と揃えている。
# ------------------------------------------------------------------
COLOR_BG_FALLBACK = (15, 23, 42)
COLOR_TEXT_MAIN = "#FFFFFF"
COLOR_TEXT_OUTLINE = "#0B1220"
COLOR_ACCENT = "#FFD54A"       # トピックピル（ブランドイエロー）
COLOR_ACCENT_TEXT = "#141414"
COLOR_BADGE_BG = "#FF4D4D"     # フックバッジ（注意/間違いを想起させる赤）
COLOR_BADGE_TEXT = "#FFFFFF"

# 同梱の太字インパクトフォント（環境依存の system font に頼らない）
_BUNDLED_IMPACT_FONT = settings.assets_dir / "fonts" / "Poppins-Bold.ttf"

# 上記が無い場合の保険（一般的なDocker/Linux環境に入っていることが多い太字フォント）
_SYSTEM_FONT_FALLBACKS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]

# main_title / sub_title 用の文字列が用意できなかった場合の最終フォールバック
_DEFAULT_HOOK_PHRASES = [
    "DON'T SAY THIS WRONG",
    "MOST LEARNERS MISS #1",
    "NATIVES NEVER SAY THIS",
    "AVOID THIS MISTAKE",
]

_MAX_HOOK_CHARS = 70


def _resolve_impact_font_path() -> str:
    if _BUNDLED_IMPACT_FONT.exists():
        return str(_BUNDLED_IMPACT_FONT)
    for path in _SYSTEM_FONT_FALLBACKS:
        if Path(path).exists():
            return path
    # 最終手段: 既存の video_profiles.yaml に設定されているフォント
    return str(settings.project_root / settings.profile("long")["font_path"])


_IMPACT_FONT_PATH = _resolve_impact_font_path()


def _impact_font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(_IMPACT_FONT_PATH, size)
    except OSError:
        logger.warning(f"Impact font not found at {_IMPACT_FONT_PATH}, using Pillow default font")
        return ImageFont.load_default()


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    start_size: int,
    min_size: int,
    max_lines: int,
    stroke_width: int = 0,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """max_width に収まるよう、フォントサイズを段階的に縮小しながら
    折返しを行う。テキストがはみ出したり潰れたりしないための安全装置。"""
    size = start_size
    font = _impact_font(size)
    lines = [text]
    while size >= min_size:
        font = _impact_font(size)
        avg_char_w = (draw.textlength("Ag", font=font) / 2) or 1
        wrap_width = max(1, int(max_width / avg_char_w))
        lines = textwrap.wrap(text, width=wrap_width) or [text]
        widest = max(draw.textlength(line, font=font) for line in lines) + stroke_width * 2
        if widest <= max_width and len(lines) <= max_lines:
            return font, lines
        size -= 4
    # 最小サイズでも収まりきらない場合は、行数だけ切り詰めて最終手段とする
    return font, lines[:max_lines] if lines else [text]


def _cover_resize(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """アスペクト比を保ったまま中央クロップでリサイズする（引き伸ばしによる
    人物・物体の歪みを防ぐ）。"""
    src_w, src_h = img.size
    if src_w == 0 or src_h == 0:
        return img.resize((target_w, target_h), Image.LANCZOS)

    src_ratio = src_w / src_h
    target_ratio = target_w / target_h

    if src_ratio > target_ratio:
        new_h = target_h
        new_w = max(target_w, int(new_h * src_ratio))
    else:
        new_w = target_w
        new_h = max(target_h, int(new_w / src_ratio))

    resized = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return resized.crop((left, top, left + target_w, top + target_h))


def _apply_readability_treatment(base: Image.Image) -> Image.Image:
    """下部を重点的に暗くするグラデーション＋外周ビネットを重ねて、
    どんな背景写真でも文字が読めるようにする。"""
    width, height = base.size

    gradient = Image.new("L", (width, height), 0)
    grad_draw = ImageDraw.Draw(gradient)
    for y in range(height):
        alpha = int(195 * (y / height) ** 1.4)
        grad_draw.line([(0, y), (width, y)], fill=alpha)
    dark_layer = Image.new("RGBA", base.size, (5, 8, 20, 255))
    dark_layer.putalpha(gradient)
    base = Image.alpha_composite(base, dark_layer)

    vignette = Image.new("L", (width, height), 0)
    v_draw = ImageDraw.Draw(vignette)
    v_draw.rectangle([0, 0, width, height], fill=60)
    v_draw.rectangle([40, 40, width - 40, height - 40], fill=0)
    vignette = vignette.filter(ImageFilter.GaussianBlur(40))
    vignette_layer = Image.new("RGBA", base.size, (0, 0, 0, 255))
    vignette_layer.putalpha(vignette)
    return Image.alpha_composite(base, vignette_layer)


class ThumbnailBuilder:
    def build(
        self,
        video_id: int,
        main_title: str,
        sub_title: str,
        background_image: Path | None = None,
        hook_phrase: str | None = None,
    ) -> Path:
        """
        Args:
            video_id: DB上の動画ID（ファイル名に使用）
            main_title: 大きく表示するメインタイトル（例: "20 Daily English Expressions"）
            sub_title: トピック名。ブランドイエローのピルで強調表示される
            background_image: 背景に使う画像（無ければ紺色の単色背景）
            hook_phrase: 右上のバッジに表示する一言。実際の例文などを渡すと
                「このフレーズ知ってる?」という好奇心を刺激できる。
                未指定の場合は既定の煽り文句からランダムに選ぶ。
        """
        # ---- 1. 背景（歪ませず中央クロップ） ----
        if background_image and background_image.exists():
            try:
                src = Image.open(background_image).convert("RGB")
                base = _cover_resize(src, THUMB_WIDTH, THUMB_HEIGHT)
            except Exception as e:
                logger.warning(f"Failed to load background image {background_image}: {e}")
                base = Image.new("RGB", (THUMB_WIDTH, THUMB_HEIGHT), color=COLOR_BG_FALLBACK)
        else:
            base = Image.new("RGB", (THUMB_WIDTH, THUMB_HEIGHT), color=COLOR_BG_FALLBACK)

        base = _apply_readability_treatment(base.convert("RGBA"))
        draw = ImageDraw.Draw(base)

        margin = 56
        max_text_width = THUMB_WIDTH - margin * 2
        title_stroke_width = 6

        # ---- 2. メインタイトル（太字＋黒アウトラインのインパクトテキスト） ----
        title_font, title_lines = _fit_text(
            draw,
            main_title,
            max_text_width,
            start_size=104,
            min_size=56,
            max_lines=2,
            stroke_width=title_stroke_width,
        )
        line_heights = [
            draw.textbbox((0, 0), line, font=title_font, stroke_width=title_stroke_width)[3]
            for line in title_lines
        ]
        line_gap = 10
        title_block_h = sum(line_heights) + line_gap * (len(title_lines) - 1)

        # ---- 3. サブタイトル（トピック名、ブランドイエローのピル） ----
        sub_font = _impact_font(40)
        sub_w = draw.textlength(sub_title, font=sub_font)
        sub_h = draw.textbbox((0, 0), sub_title, font=sub_font)[3]

        bottom_margin = 54
        sub_y = THUMB_HEIGHT - bottom_margin - sub_h
        title_y = sub_y - 26 - title_block_h

        bar_pad_x, bar_pad_y = 22, 10
        bar_box = [
            margin - bar_pad_x,
            sub_y - bar_pad_y,
            margin + sub_w + bar_pad_x,
            sub_y + sub_h + bar_pad_y,
        ]
        draw.rounded_rectangle(bar_box, radius=10, fill=COLOR_ACCENT)
        draw.text((margin, sub_y), sub_title, font=sub_font, fill=COLOR_ACCENT_TEXT)

        y_cursor = title_y
        for line, line_h in zip(title_lines, line_heights):
            draw.text(
                (margin, y_cursor),
                line,
                font=title_font,
                fill=COLOR_TEXT_MAIN,
                stroke_width=title_stroke_width,
                stroke_fill=COLOR_TEXT_OUTLINE,
            )
            y_cursor += line_h + line_gap

        # ---- 4. フックバッジ（右上、明確なフォーカルポイントを作る） ----
        hook_text = (hook_phrase or random.choice(_DEFAULT_HOOK_PHRASES)).strip()
        if len(hook_text) > _MAX_HOOK_CHARS:
            hook_text = hook_text[: _MAX_HOOK_CHARS - 1].rstrip() + "…"
        hook_text = hook_text.upper()

        hook_font, hook_lines = _fit_text(
            draw, hook_text, max_width=420, start_size=34, min_size=22, max_lines=2
        )
        hook_line_h = draw.textbbox((0, 0), hook_lines[0], font=hook_font)[3]
        pad_x, pad_y, line_spacing = 24, 16, 6
        badge_w = max(draw.textlength(line, font=hook_font) for line in hook_lines) + pad_x * 2
        badge_h = hook_line_h * len(hook_lines) + pad_y * 2 + line_spacing * (len(hook_lines) - 1)
        badge_x = THUMB_WIDTH - margin - badge_w
        badge_y = margin
        draw.rounded_rectangle(
            [badge_x, badge_y, badge_x + badge_w, badge_y + badge_h],
            radius=14,
            fill=COLOR_BADGE_BG,
        )
        hy = badge_y + pad_y
        for line in hook_lines:
            draw.text((badge_x + pad_x, hy), line, font=hook_font, fill=COLOR_BADGE_TEXT)
            hy += hook_line_h + line_spacing

        # ---- 5. 書き出し ----
        out_path = THUMBNAIL_OUTPUT_DIR / f"long_{video_id}.jpg"
        base.convert("RGB").save(out_path, quality=94)
        logger.info(f"Built thumbnail -> {out_path}")
        return out_path
