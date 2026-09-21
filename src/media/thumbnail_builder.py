"""
Pillow を使ってLong動画用サムネイルを生成するモジュール。
（設計書の通り、Shortsではサムネイルは生成しない）

人気の語学系動画のサムネを踏まえた4つの方針で設計:

  1. トピック名を最大・最優先で表示
     sub_title（例: "Restaurant English"）を画面内で最も大きい見出しにする。
     先頭の単語だけブランドイエローで強調し、ポップな印象を出す。
  2. フック（不安訴求・問いかけ）を2番目に目立つ要素として表示
     hook_phrase は暖色の角丸バナーに乗せ、トピックより一回り小さいが
     はっきり分かるサイズで配置する。
  3. 表情を右側に配置（写真ではなくPillowで描くアイコン）
     Pexels写真+背景除去はモデルダウンロードやDocker再ビルドが必要で
     「無料かつ確実」とは言い切れないため、フォントに依存しない図形描画で
     驚き/笑顔/考え中などの表情アイコンを直接描く。外部APIや追加の重い依存
     無しで、常に同じ品質で表示できる。
  4. 全体的に明るく・柔らかい雰囲気
     暖色（オレンジ）のフックバナー、黒より柔らかい焦げ茶のアウトライン、
     角丸を多用し、"楽しさが伝わる"配色にしている。

  加えて以下も維持:
  - Before/After・NG/OKの対比（❌/⭕は図形描画、フォント依存を避ける）
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
# ブランドカラー（④ 明るく柔らかい雰囲気を意識した配色）
# ------------------------------------------------------------------
COLOR_BG_FALLBACK = (36, 28, 56)
COLOR_TEXT_MAIN = "#FFFFFF"
COLOR_TEXT_OUTLINE = "#3A2415"     # 黒より柔らかい焦げ茶（アウトライン用）
COLOR_ACCENT = "#FFD54A"           # ブランドイエロー（topicの強調語・アイコン顔に統一）
COLOR_ACCENT_TEXT = "#141414"
COLOR_HOOK_BG = "#FF8A3D"          # フックバナー：暖色オレンジ（警告色より楽しい印象）
COLOR_HOOK_TEXT = "#FFFFFF"
COLOR_NG = "#FF5C5C"
COLOR_OK = "#3DDC84"
COLOR_ROW_BG = (28, 18, 12, 200)

# 表情アイコン（右側に配置、Pillowの図形描画のみで作成 = 追加コスト・依存ゼロ）
ICON_RADIUS = 190
ICON_CENTER_X = THUMB_WIDTH - 250
ICON_CENTER_Y = int(THUMB_HEIGHT * 0.54)
ICON_SAFETY_PAD = 30
COLOR_ICON_FACE = "#FFD54A"
COLOR_ICON_OUTLINE = "#3A2415"
COLOR_ICON_CHEEK = "#FF9F6B"
COLOR_ICON_SHADOW = (20, 12, 8, 90)

_EXPRESSIONS = ["surprised", "happy", "thinking", "curious"]

TEXT_TO_ICON_GAP = 40  # テキスト領域とアイコンの間の安全マージン

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

_MAX_HOOK_CHARS = 42
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


def _cover_resize(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """アスペクト比を保ったまま中央クロップでリサイズする（引き伸ばしによる歪みを防ぐ）。"""
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
        alpha = int(175 * (y / height) ** 1.4)
        grad_draw.line([(0, y), (width, y)], fill=alpha)
    dark_layer = Image.new("RGBA", base.size, (18, 12, 24, 255))
    dark_layer.putalpha(gradient)
    base = Image.alpha_composite(base, dark_layer)

    vignette = Image.new("L", (width, height), 0)
    v_draw = ImageDraw.Draw(vignette)
    v_draw.rectangle([0, 0, width, height], fill=45)
    v_draw.rectangle([40, 40, width - 40, height - 40], fill=0)
    vignette = vignette.filter(ImageFilter.GaussianBlur(40))
    vignette_layer = Image.new("RGBA", base.size, (0, 0, 0, 255))
    vignette_layer.putalpha(vignette)
    return Image.alpha_composite(base, vignette_layer)


def _draw_accented_line(
    draw: ImageDraw.ImageDraw,
    x: float,
    y: float,
    line: str,
    font: ImageFont.FreeTypeFont,
    stroke_width: int,
) -> None:
    """先頭の単語だけ差し色(COLOR_ACCENT)、残りは白で1行分のテキストを描画する。
    人気チャンネルのサムネによくある「STOP」「WHY」のような強調演出。"""
    words = line.split(" ", 1)
    first_word = words[0]
    rest = f" {words[1]}" if len(words) > 1 else ""

    draw.text(
        (x, y), first_word, font=font, fill=COLOR_ACCENT,
        stroke_width=stroke_width, stroke_fill=COLOR_TEXT_OUTLINE,
    )
    if rest:
        first_w = draw.textlength(first_word, font=font)
        draw.text(
            (x + first_w, y), rest, font=font, fill=COLOR_TEXT_MAIN,
            stroke_width=stroke_width, stroke_fill=COLOR_TEXT_OUTLINE,
        )


def _draw_reaction_icon(base: Image.Image, cx: int, cy: int, r: int, expression: str) -> None:
    """外部の写真やAPIに頼らず、Pillowの図形描画だけで表情アイコンを描く
    （常に無料・確実に表示できる）。ドロップシャドウで背景から浮かせる。"""
    # シャドウ
    shadow_layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow_layer)
    sd.ellipse([cx - r + 8, cy - r + 14, cx + r + 8, cy + r + 14], fill=COLOR_ICON_SHADOW)
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(16))
    base.alpha_composite(shadow_layer)

    draw = ImageDraw.Draw(base)
    outline_w = max(5, int(r * 0.035))
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=COLOR_ICON_FACE, outline=COLOR_ICON_OUTLINE, width=outline_w)

    eye_r = r * 0.11
    eye_dx = r * 0.32
    eye_y = cy - r * 0.08
    lw = max(5, int(r * 0.05))

    if expression == "happy":
        for sx in (-1, 1):
            ex = cx + sx * eye_dx
            draw.arc(
                [ex - eye_r * 1.3, eye_y - eye_r, ex + eye_r * 1.3, eye_y + eye_r * 1.7],
                start=200, end=340, fill=COLOR_ICON_OUTLINE, width=lw,
            )
        draw.arc(
            [cx - r * 0.5, cy + r * 0.02, cx + r * 0.5, cy + r * 0.55],
            start=15, end=165, fill=COLOR_ICON_OUTLINE, width=lw + 2,
        )
        for sx in (-1, 1):
            ccx = cx + sx * r * 0.58
            ccy = cy + r * 0.18
            cr = r * 0.13
            draw.ellipse([ccx - cr, ccy - cr * 0.75, ccx + cr, ccy + cr * 0.75], fill=COLOR_ICON_CHEEK)
    elif expression == "thinking":
        for sx in (-1, 1):
            ex = cx + sx * eye_dx
            draw.ellipse([ex - eye_r * 0.8, eye_y - eye_r * 0.8, ex + eye_r * 0.8, eye_y + eye_r * 0.8], fill=COLOR_ICON_OUTLINE)
        draw.line(
            [cx - eye_dx - eye_r * 1.5, eye_y - r * 0.16, cx - eye_dx + eye_r * 1.5, eye_y - r * 0.30],
            fill=COLOR_ICON_OUTLINE, width=lw,
        )
        draw.line(
            [cx + eye_dx - eye_r * 1.5, eye_y - r * 0.18, cx + eye_dx + eye_r * 1.5, eye_y - r * 0.18],
            fill=COLOR_ICON_OUTLINE, width=lw,
        )
        draw.line(
            [cx - r * 0.22, cy + r * 0.36, cx + r * 0.28, cy + r * 0.30],
            fill=COLOR_ICON_OUTLINE, width=lw,
        )
    elif expression == "curious":
        for sx in (-1, 1):
            ex = cx + sx * eye_dx
            draw.ellipse([ex - eye_r, eye_y - eye_r, ex + eye_r, eye_y + eye_r], fill=COLOR_ICON_OUTLINE)
        draw.line(
            [cx - eye_dx - eye_r * 1.5, eye_y - r * 0.32, cx - eye_dx + eye_r * 1.5, eye_y - r * 0.14],
            fill=COLOR_ICON_OUTLINE, width=lw,
        )
        mr = r * 0.14
        draw.ellipse([cx - mr, cy + r * 0.30 - mr, cx + mr, cy + r * 0.30 + mr], outline=COLOR_ICON_OUTLINE, width=lw)
    else:  # surprised（デフォルト）
        for sx in (-1, 1):
            ex = cx + sx * eye_dx
            draw.ellipse([ex - eye_r, eye_y - eye_r, ex + eye_r, eye_y + eye_r], fill=COLOR_ICON_OUTLINE)
            bx = ex
            draw.line(
                [bx - eye_r * 1.4, eye_y - r * 0.24, bx + eye_r * 1.4, eye_y - r * 0.34],
                fill=COLOR_ICON_OUTLINE, width=lw,
            )
        mr = r * 0.20
        draw.ellipse([cx - mr, cy + r * 0.30 - mr, cx + mr, cy + r * 0.30 + mr], fill=COLOR_ICON_OUTLINE)


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
        expression: str | None = None,
        ng_phrase: str | None = None,
        ok_phrase: str | None = None,
    ) -> Path:
        """
        Args:
            video_id: DB上の動画ID（ファイル名に使用）
            main_title: 現在未使用（呼び出し側との互換性のため引数だけ残している）。
            sub_title: トピック名。画面内で最も大きい主役の見出しとして表示される
                （例: "Restaurant English"）。先頭の単語だけブランドイエローで強調。
            background_image: 背景に使う画像（無ければ紺色の単色背景）
            hook_phrase: 2番目に目立つ要素として、暖色の角丸バナーに表示する
                短い英語キャッチコピー（3〜6単語・30文字程度を想定）。
                未指定なら既定の煽り文句からランダムに選ぶ。
            expression: 右側に描く表情アイコンの種類
                （"surprised" / "happy" / "thinking" / "curious"）。
                未指定ならランダムに選ぶ。写真ではなく図形描画なので、
                外部APIやモデルに依存せず常に同じ品質で表示できる。
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
        base = _apply_readability_treatment(base)

        # ---- 2. 表情アイコン（右側、鮮やかなまま可読性処理の上に乗せる） ----
        chosen_expression = expression or random.choice(_EXPRESSIONS)
        _draw_reaction_icon(base, ICON_CENTER_X, ICON_CENTER_Y, ICON_RADIUS, chosen_expression)
        reserved_right_width = (THUMB_WIDTH - (ICON_CENTER_X - ICON_RADIUS - ICON_SAFETY_PAD))

        draw = ImageDraw.Draw(base)

        margin = 56
        text_right_limit = (THUMB_WIDTH - reserved_right_width) - TEXT_TO_ICON_GAP
        max_text_width = text_right_limit - margin

        # ---- 3. フックバナー（2番目に目立つ、暖色の角丸バナー） ----
        hook_text = (hook_phrase or random.choice(_DEFAULT_HOOK_PHRASES)).strip()
        if len(hook_text) > _MAX_HOOK_CHARS:
            hook_text = hook_text[: _MAX_HOOK_CHARS - 1].rstrip() + _ELLIPSIS
        hook_text = hook_text.upper()

        hook_max_width = min(max_text_width, 680)
        hook_font, hook_lines = _fit_text(
            draw, hook_text, hook_max_width, start_size=52, min_size=30,
            max_lines=2, font_loader=_impact_font,
        )
        hook_line_h = draw.textbbox((0, 0), hook_lines[0], font=hook_font)[3]
        pad_x, pad_y, line_spacing = 26, 18, 10
        hook_w = max(draw.textlength(line, font=hook_font) for line in hook_lines) + pad_x * 2
        hook_h = hook_line_h * len(hook_lines) + pad_y * 2 + line_spacing * (len(hook_lines) - 1)
        hook_x, hook_y = margin, 48
        draw.rounded_rectangle(
            [hook_x, hook_y, hook_x + hook_w, hook_y + hook_h], radius=hook_h / 2.2, fill=COLOR_HOOK_BG
        )
        hy = hook_y + pad_y
        for line in hook_lines:
            draw.text((hook_x + pad_x, hy), line, font=hook_font, fill=COLOR_HOOK_TEXT)
            hy += hook_line_h + line_spacing
        hook_bottom = hook_y + hook_h

        # ---- 4. トピック名（最も目立つ、太字＋アウトラインの大見出し。先頭の単語だけ強調） ----
        topic_stroke_width = 7
        topic_font, topic_lines = _fit_text(
            draw, sub_title, max_text_width, start_size=100, min_size=56,
            max_lines=2, stroke_width=topic_stroke_width, font_loader=_impact_font,
        )
        topic_line_heights = [
            draw.textbbox((0, 0), line, font=topic_font, stroke_width=topic_stroke_width)[3]
            for line in topic_lines
        ]
        topic_line_gap = 10
        topic_x, topic_y = margin, hook_bottom + 30
        ty = topic_y
        for i, (line, line_h) in enumerate(zip(topic_lines, topic_line_heights)):
            if i == 0:
                # 最初の行だけ、先頭の単語を差し色で強調する
                _draw_accented_line(draw, topic_x, ty, line, topic_font, topic_stroke_width)
            else:
                draw.text(
                    (topic_x, ty), line, font=topic_font, fill=COLOR_TEXT_MAIN,
                    stroke_width=topic_stroke_width, stroke_fill=COLOR_TEXT_OUTLINE,
                )
            ty += line_h + topic_line_gap
        topic_bottom = ty - topic_line_gap

        # ---- 5. NG/OK 対比ブロック（トピックの下、収まる場合のみ描画） ----
        ng_phrase = (ng_phrase or "").strip()
        ok_phrase = (ok_phrase or "").strip()
        if ng_phrase and ok_phrase:
            block_top = topic_bottom + 26
            bottom_safe_margin = 40
            available_h = (THUMB_HEIGHT - bottom_safe_margin) - block_top
            ng_ok_rows = _layout_ng_ok_rows(draw, max_text_width, ng_phrase, ok_phrase)
            required_h = sum(r["row_h"] for r in ng_ok_rows) + 10 * (len(ng_ok_rows) - 1)
            if available_h >= required_h:
                _render_ng_ok_rows(draw, margin, block_top, ng_ok_rows)
            else:
                logger.info(
                    f"Skipping NG/OK block: needs {required_h}px, only {available_h}px available"
                )

        # ---- 6. 書き出し ----
        out_path = THUMBNAIL_OUTPUT_DIR / f"long_{video_id}.jpg"
        base.convert("RGB").save(out_path, quality=94)
        logger.info(f"Built thumbnail -> {out_path}")
        return out_path
