"""
Pillow を使ってLong動画用サムネイルを生成するモジュール。
（設計書の通り、Shortsではサムネイルは生成しない）

語学系動画で効果的なサムネイルの4要素を踏まえて設計（テキストは全て英語で統一）:

  1. 文字情報は短くインパクト重視
     hook_phrase は「3〜6単語・30文字程度の英語キャッチコピー」に限定し、
     ポスターの見出しのように大きく・太く・短く表示する（説明文にしない）。
  2. 文字の視認性（コントラスト・フォント）
     太字＋黒アウトラインで、スマホの小さいプレビューでも読めるようにする。
     同梱の Poppins Bold を使い、環境依存の system font に頼らない。
  3. 表情や感情の表現
     Pexelsで「疑問/驚き/ひらめき」等の表情キーワードを掛け合わせて検索した
     人物写真を、顔が大きく収まるようズームし気味に右側パネルへ配置する。
  4. Before/After・NG/OKの対比
     ❌/⭕ のアイコン（フォント依存を避けるため図形として描画）付きの
     2行ブロックで、不自然な言い方 vs ネイティブの言い方を対比表示する。
     元ネタが無い/信頼できない場合は自動的にこのブロックを省略する。

  加えて以下も維持:
  - トピック名を最大の太字見出しとして配置（前回の改修を踏襲）
  - 背景の歪み防止（中央クロップ）
  - 長いテキストでも破綻しない自動折返し＋省略記号での丸め込み
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
# ------------------------------------------------------------------
COLOR_BG_FALLBACK = (15, 23, 42)
COLOR_TEXT_MAIN = "#FFFFFF"
COLOR_TEXT_OUTLINE = "#0B1220"
COLOR_ACCENT = "#FFD54A"       # 見出しタグ（ブランドイエロー）
COLOR_ACCENT_TEXT = "#141414"
COLOR_BADGE_BG = "#FF4D4D"     # キャッチコピー banner（注意/好奇心を想起させる赤）
COLOR_BADGE_TEXT = "#FFFFFF"
COLOR_NG = "#FF5C5C"
COLOR_OK = "#3DDC84"
COLOR_ROW_BG = (10, 14, 25, 200)

# 人物パネルのサイズ・馴染ませ量
PERSON_PANEL_WIDTH = 460
PERSON_PANEL_FEATHER = 150     # 左端をこの幅(px)でグラデーション馴染ませ
PERSON_PANEL_TOP_BIAS = 0.12   # 0=上端基準, 0.5=中央基準（顔が残るよう上寄りに）
PERSON_PANEL_ZOOM = 1.18       # >1 で少しズームし、顔を大きく見せる
TEXT_TO_PANEL_GAP = 40         # テキスト領域とパネルの間の安全マージン

# 同梱フォント（環境依存の system font に頼らない。テキストは全て英語のため1種類でよい）
_BUNDLED_IMPACT_FONT = settings.assets_dir / "fonts" / "Poppins-Bold.ttf"

_SYSTEM_FONT_FALLBACKS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]

# hook_phrase が用意できなかった場合の最終フォールバック（英語キャッチコピー）
_DEFAULT_HOOK_PHRASES = [
    "DON'T SAY THIS WRONG",
    "MOST LEARNERS MISS THIS",
    "NATIVES NEVER SAY THIS",
    "AVOID THIS MISTAKE",
]

_MAX_HOOK_CHARS = 32
_ELLIPSIS = "…"


def _resolve_font_path(bundled: Path, system_fallbacks: list[str], profile_fallback: bool) -> str:
    if bundled.exists():
        return str(bundled)
    for path in system_fallbacks:
        if Path(path).exists():
            return path
    if profile_fallback:
        return str(settings.project_root / settings.profile("long")["font_path"])
    return system_fallbacks[0] if system_fallbacks else str(bundled)


_IMPACT_FONT_PATH = _resolve_font_path(_BUNDLED_IMPACT_FONT, _SYSTEM_FONT_FALLBACKS, profile_fallback=True)


def _impact_font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(_IMPACT_FONT_PATH, size)
    except OSError:
        logger.warning(f"Impact font not found at {_IMPACT_FONT_PATH}, using Pillow default font")
        return ImageFont.load_default()


def _truncate_to_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    stroke_width: int = 0,
    force_ellipsis: bool = False,
) -> str:
    """text が max_width に収まるまで、末尾から1文字ずつ削って "…" を付ける。
    英語(スペース区切り)でも1文字ずつでも安全に動作する。"""
    candidate = f"{text}{_ELLIPSIS}" if force_ellipsis else text
    if draw.textlength(candidate, font=font) + stroke_width * 2 <= max_width:
        return candidate

    chars = list(text)
    while chars:
        chars.pop()
        candidate = f"{''.join(chars)}{_ELLIPSIS}"
        if draw.textlength(candidate, font=font) + stroke_width * 2 <= max_width:
            return candidate
    return _ELLIPSIS


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    start_size: int,
    min_size: int,
    max_lines: int,
    stroke_width: int = 0,
    font_loader=_impact_font,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """max_width に収まるよう、フォントサイズを段階的に縮小しながら折返しを行う。
    最小サイズでもmax_linesに収まらない場合は、最終行を省略記号で丸めて
    必ず max_width × max_lines に収まる状態で返す（物理的な文字ちぎれを防ぐ）。"""
    size = start_size
    font = font_loader(size)
    lines = [text]
    while size >= min_size:
        font = font_loader(size)
        # まず1行で収まるかを直接測る（textwrapの文字数ベース見積もりは保守的すぎて、
        # 本来1行に収まる文章まで2行に折り返してしまうことがあるため）。
        full_width = draw.textlength(text, font=font) + stroke_width * 2
        if full_width <= max_width:
            return font, [text]

        avg_char_w = (draw.textlength("Ag", font=font) / 2) or 1
        wrap_width = max(1, int(max_width / avg_char_w))
        lines = textwrap.wrap(text, width=wrap_width, break_long_words=False, break_on_hyphens=False) or [text]
        widest = max(draw.textlength(line, font=font) for line in lines) + stroke_width * 2
        if widest <= max_width and len(lines) <= max_lines:
            return font, lines
        size -= 4

    font = font_loader(min_size)
    avg_char_w = (draw.textlength("Ag", font=font) / 2) or 1
    wrap_width = max(1, int(max_width / avg_char_w))
    lines = textwrap.wrap(text, width=wrap_width, break_long_words=False, break_on_hyphens=False) or [text]
    if len(lines) > max_lines:
        kept = lines[:max_lines]
        kept[-1] = _truncate_to_width(draw, kept[-1], font, max_width, stroke_width, force_ellipsis=True)
        lines = kept
    else:
        lines = [_truncate_to_width(draw, line, font, max_width, stroke_width) for line in lines]
    return font, lines


def _cover_resize(
    img: Image.Image,
    target_w: int,
    target_h: int,
    vertical_bias: float = 0.5,
    zoom: float = 1.0,
) -> Image.Image:
    """アスペクト比を保ったままクロップでリサイズする（引き伸ばしによる歪みを防ぐ）。

    vertical_bias: 0=上端基準でクロップ, 0.5=中央, 1=下端基準。
        人物ポートレートは被写体が上部に写っていることが多いため、
        人物パネルでは小さめの値(上寄り)を指定して顔が切れないようにする。
    zoom: 1より大きい値で被写体を少し拡大する（顔を大きく見せたい場合に使用）。
    """
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

    new_w = max(target_w, int(new_w * zoom))
    new_h = max(target_h, int(new_h * zoom))

    resized = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top = int((new_h - target_h) * max(0.0, min(1.0, vertical_bias)))
    top = max(0, min(top, new_h - target_h))
    return resized.crop((left, top, left + target_w, top + target_h))


def _apply_readability_treatment(base: Image.Image) -> Image.Image:
    """下部を重点的に暗くするグラデーション＋外周ビネットを重ねて、
    どんな背景写真・人物パネルでも文字が読めるようにする。"""
    width, height = base.size

    gradient = Image.new("L", (width, height), 0)
    grad_draw = ImageDraw.Draw(gradient)
    for y in range(height):
        alpha = int(190 * (y / height) ** 1.4)
        grad_draw.line([(0, y), (width, y)], fill=alpha)
    dark_layer = Image.new("RGBA", base.size, (5, 8, 20, 255))
    dark_layer.putalpha(gradient)
    base = Image.alpha_composite(base, dark_layer)

    vignette = Image.new("L", (width, height), 0)
    v_draw = ImageDraw.Draw(vignette)
    v_draw.rectangle([0, 0, width, height], fill=55)
    v_draw.rectangle([40, 40, width - 40, height - 40], fill=0)
    vignette = vignette.filter(ImageFilter.GaussianBlur(40))
    vignette_layer = Image.new("RGBA", base.size, (0, 0, 0, 255))
    vignette_layer.putalpha(vignette)
    return Image.alpha_composite(base, vignette_layer)


def _composite_person_panel(base: Image.Image, person_image: Path) -> Image.Image:
    """右側に、左端をフェザー馴染ませした縦長の人物パネルを合成する。
    表情が伝わりやすいよう、顔が残る上寄りでズーム気味にクロップする。"""
    width, height = base.size
    panel_x = width - PERSON_PANEL_WIDTH

    try:
        src = Image.open(person_image).convert("RGB")
    except Exception as e:
        logger.warning(f"Failed to load person image {person_image}: {e}")
        return base

    panel_img = _cover_resize(
        src, PERSON_PANEL_WIDTH, height,
        vertical_bias=PERSON_PANEL_TOP_BIAS, zoom=PERSON_PANEL_ZOOM,
    ).convert("RGBA")

    mask = Image.new("L", (PERSON_PANEL_WIDTH, height), 255)
    mask_draw = ImageDraw.Draw(mask)
    for x in range(min(PERSON_PANEL_FEATHER, PERSON_PANEL_WIDTH)):
        alpha = int(255 * (x / PERSON_PANEL_FEATHER))
        mask_draw.line([(x, 0), (x, height)], fill=alpha)
    panel_img.putalpha(mask)

    base = base.copy()
    base.alpha_composite(panel_img, dest=(panel_x, 0))
    return base


def _draw_ng_icon(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float) -> None:
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=COLOR_NG)
    inset = r * 0.42
    lw = max(3, int(r * 0.24))
    draw.line([cx - inset, cy - inset, cx + inset, cy + inset], fill="white", width=lw)
    draw.line([cx - inset, cy + inset, cx + inset, cy - inset], fill="white", width=lw)


def _draw_ok_icon(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float) -> None:
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=COLOR_OK)
    lw = max(3, int(r * 0.24))
    p1 = (cx - r * 0.5, cy + r * 0.05)
    p2 = (cx - r * 0.08, cy + r * 0.45)
    p3 = (cx + r * 0.55, cy - r * 0.35)
    draw.line([p1, p2], fill="white", width=lw)
    draw.line([p2, p3], fill="white", width=lw)


def _layout_ng_ok_rows(
    draw: ImageDraw.ImageDraw, max_width: int, ng_text: str, ok_text: str
) -> list[dict]:
    """NG/OK各行のレイアウトを実測する（描画はしない）。"""
    font = _impact_font(30)
    icon_r = 20
    pad_x, pad_y = 16, 9
    icon_gap = 14

    rows = []
    for kind, text, icon_fn in (("NG", ng_text, _draw_ng_icon), ("OK", ok_text, _draw_ok_icon)):
        text_max_width = max(max_width - (icon_r * 2 + icon_gap + pad_x * 2), 60)
        line_font, lines = _fit_text(
            draw, text, text_max_width, start_size=30, min_size=20, max_lines=1, font_loader=_impact_font
        )
        label = lines[0]
        text_bbox = draw.textbbox((0, 0), label, font=line_font)
        text_h = text_bbox[3] - text_bbox[1]
        text_w = draw.textlength(label, font=line_font)
        row_h = max(int(icon_r * 2), text_h) + pad_y * 2
        row_w = pad_x * 2 + icon_r * 2 + icon_gap + text_w
        rows.append({
            "kind": kind, "label": label, "font": line_font, "icon_fn": icon_fn,
            "icon_r": icon_r, "pad_x": pad_x, "icon_gap": icon_gap,
            "row_h": row_h, "row_w": row_w, "text_bbox": text_bbox,
        })
    return rows


def _render_ng_ok_rows(draw: ImageDraw.ImageDraw, x: int, y: int, rows: list[dict]) -> int:
    """_layout_ng_ok_rows() の結果を実際に描画する。使用した高さ(px)を返す。"""
    row_gap = 10
    cursor_y = y
    for row in rows:
        row_h = row["row_h"]
        draw.rounded_rectangle(
            [x, cursor_y, x + row["row_w"], cursor_y + row_h], radius=row_h / 2, fill=COLOR_ROW_BG
        )
        icon_cx = x + row["pad_x"] + row["icon_r"]
        icon_cy = cursor_y + row_h / 2
        row["icon_fn"](draw, icon_cx, icon_cy, row["icon_r"])

        text_x = icon_cx + row["icon_r"] + row["icon_gap"]
        tb = row["text_bbox"]
        text_y = cursor_y + (row_h - (tb[3] - tb[1])) / 2 - tb[1]
        draw.text((text_x, text_y), row["label"], font=row["font"], fill="white")

        cursor_y += row_h + row_gap
    return cursor_y - y - row_gap


class ThumbnailBuilder:
    def build(
        self,
        video_id: int,
        main_title: str,
        sub_title: str,
        background_image: Path | None = None,
        hook_phrase: str | None = None,
        person_image: Path | None = None,
        ng_phrase: str | None = None,
        ok_phrase: str | None = None,
    ) -> Path:
        """
        Args:
            video_id: DB上の動画ID（ファイル名に使用）
            main_title: 付随情報として控えめに表示するテキスト
                （例: "20 Daily English Expressions"）。見出しタグとして表示される。
            sub_title: トピック名。最も目立つ大きな見出しとして表示される
                （例: "Restaurant English"）。
            background_image: 背景に使う画像（無ければ紺色の単色背景）
            hook_phrase: 左上のバナーに表示する、短い英語キャッチコピー
                （3〜6単語・30文字程度を想定）。未指定なら既定の煽り文句からランダムに選ぶ。
            person_image: トピックに合う人物の縦長ポートレート画像。
                指定があれば右側にパネルとして合成する。None または
                読み込み失敗時は、パネル無しの従来レイアウトに自動フォールバックする。
            ng_phrase / ok_phrase: NG(不自然な言い方) / OK(ネイティブの言い方) の
                対比ペア。両方とも指定された場合のみ ❌/⭕ ブロックを描画する。
                根拠が薄い場合は呼び出し側(metadata_generator)で空文字にされ、
                ここでは自動的にブロックごと省略される。
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
        base = base.convert("RGBA")

        # ---- 2. 人物パネル（あれば先に合成し、この後の可読性処理を全体に効かせる） ----
        has_person_panel = bool(person_image and person_image.exists())
        if has_person_panel:
            base = _composite_person_panel(base, person_image)

        base = _apply_readability_treatment(base)
        draw = ImageDraw.Draw(base)

        margin = 56
        if has_person_panel:
            panel_x = THUMB_WIDTH - PERSON_PANEL_WIDTH
            text_right_limit = panel_x - TEXT_TO_PANEL_GAP
        else:
            text_right_limit = THUMB_WIDTH - margin
        max_text_width = text_right_limit - margin

        # ---- 3. トピック名（最も目立つ、太字＋黒アウトラインの大見出し） ----
        topic_stroke_width = 6
        topic_font, topic_lines = _fit_text(
            draw, sub_title, max_text_width, start_size=96, min_size=52,
            max_lines=2, stroke_width=topic_stroke_width, font_loader=_impact_font,
        )
        topic_line_heights = [
            draw.textbbox((0, 0), line, font=topic_font, stroke_width=topic_stroke_width)[3]
            for line in topic_lines
        ]
        topic_line_gap = 10
        topic_block_h = sum(topic_line_heights) + topic_line_gap * (len(topic_lines) - 1)

        # ---- 4. 見出しタグ（main_title、ブランドイエローのピル、控えめなサイズ） ----
        tag_font = _impact_font(34)
        tag_w = draw.textlength(main_title, font=tag_font)
        tag_h = draw.textbbox((0, 0), main_title, font=tag_font)[3]

        bottom_margin = 54
        tag_y = THUMB_HEIGHT - bottom_margin - tag_h
        topic_y = tag_y - 26 - topic_block_h

        tag_pad_x, tag_pad_y = 20, 9
        tag_box = [
            margin - tag_pad_x, tag_y - tag_pad_y,
            margin + tag_w + tag_pad_x, tag_y + tag_h + tag_pad_y,
        ]
        draw.rounded_rectangle(tag_box, radius=9, fill=COLOR_ACCENT)
        draw.text((margin, tag_y), main_title, font=tag_font, fill=COLOR_ACCENT_TEXT)

        y_cursor = topic_y
        for line, line_h in zip(topic_lines, topic_line_heights):
            draw.text(
                (margin, y_cursor), line, font=topic_font, fill=COLOR_TEXT_MAIN,
                stroke_width=topic_stroke_width, stroke_fill=COLOR_TEXT_OUTLINE,
            )
            y_cursor += line_h + topic_line_gap

        # ---- 5. キャッチコピー banner（左上、短い英語で不安訴求/問いかけ） ----
        hook_text = (hook_phrase or random.choice(_DEFAULT_HOOK_PHRASES)).strip()
        if len(hook_text) > _MAX_HOOK_CHARS:
            hook_text = hook_text[: _MAX_HOOK_CHARS - 1].rstrip() + _ELLIPSIS
        hook_text = hook_text.upper()

        hook_max_width = min(max_text_width, 680)
        hook_font, hook_lines = _fit_text(
            draw, hook_text, hook_max_width, start_size=48, min_size=30,
            max_lines=2, font_loader=_impact_font,
        )
        hook_line_h = draw.textbbox((0, 0), hook_lines[0], font=hook_font)[3]
        pad_x, pad_y, line_spacing = 28, 20, 10
        badge_w = max(draw.textlength(line, font=hook_font) for line in hook_lines) + pad_x * 2
        badge_h = hook_line_h * len(hook_lines) + pad_y * 2 + line_spacing * (len(hook_lines) - 1)
        badge_x, badge_y = margin, margin
        draw.rounded_rectangle(
            [badge_x, badge_y, badge_x + badge_w, badge_y + badge_h], radius=18, fill=COLOR_BADGE_BG
        )
        hy = badge_y + pad_y
        for line in hook_lines:
            draw.text((badge_x + pad_x, hy), line, font=hook_font, fill=COLOR_BADGE_TEXT)
            hy += hook_line_h + line_spacing

        # ---- 6. NG/OK 対比ブロック（banner の下、topic の上に収まる場合のみ描画） ----
        ng_phrase = (ng_phrase or "").strip()
        ok_phrase = (ok_phrase or "").strip()
        if ng_phrase and ok_phrase:
            block_top = badge_y + badge_h + 14
            available_h = topic_y - 10 - block_top
            ng_ok_rows = _layout_ng_ok_rows(draw, max_text_width, ng_phrase, ok_phrase)
            required_h = sum(r["row_h"] for r in ng_ok_rows) + 10 * (len(ng_ok_rows) - 1)
            if available_h >= required_h:
                _render_ng_ok_rows(draw, margin, block_top, ng_ok_rows)
            else:
                logger.info(
                    f"Skipping NG/OK block: needs {required_h}px, only {available_h}px available"
                )

        # ---- 7. 書き出し ----
        out_path = THUMBNAIL_OUTPUT_DIR / f"long_{video_id}.jpg"
        base.convert("RGB").save(out_path, quality=94)
        logger.info(f"Built thumbnail -> {out_path}")
        return out_path
