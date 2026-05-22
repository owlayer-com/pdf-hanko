"""PDF Hanko の仮アプリアイコン (PNG) を生成する。

朱色の丸印 + 中央に「印」のシンプルなデザインで 1024×1024 の PNG を
``src/pdfhanko/resources/pdfhanko.png`` に書き出す。本物のデザインに
差し替える場合は、同じパスに 1024×1024 PNG を直接配置すればよい。

このスクリプトは PNG 生成のみを担当する。``.icns`` への変換は
:file:`build_icns.py` を別途実行する。

実行::

    uv run python scripts/generate_placeholder_icon.py
    uv run python scripts/build_icns.py

依存: Pillow (本体の依存に含まれる)
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
RESOURCE_DIR = ROOT / "src" / "pdfhanko" / "resources"

BASE_SIZE = 1024
"""ベースキャンバスサイズ (px)。"""

HANKO_RED = (200, 35, 30, 255)
"""印影の朱色 (R, G, B, A)。実物の朱肉に近い色。"""


def _resolve_japanese_font(font_size: int) -> ImageFont.ImageFont:
    """macOS 上で利用可能な日本語フォントを順に試して TrueType を返す。"""
    candidates = [
        "/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc",
        "/System/Library/Fonts/ヒラギノ明朝 ProN.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=font_size)
        except OSError:
            continue
    return ImageFont.load_default()


def render_base_png(size: int = BASE_SIZE) -> Image.Image:
    """指定サイズの正方形 PNG (RGBA) としてアイコンを生成する。

    Args:
        size: 出力画像の一辺ピクセル数。

    Returns:
        PIL Image (mode="RGBA")。
    """
    img = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)

    margin = int(size * 0.08)
    stroke_width = int(size * 0.07)
    draw.ellipse(
        (margin, margin, size - margin, size - margin),
        outline=HANKO_RED,
        width=stroke_width,
    )

    font = _resolve_japanese_font(int(size * 0.55))
    text = "印"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text(
        ((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1]),
        text,
        fill=HANKO_RED,
        font=font,
    )
    return img


def main() -> int:
    """スクリプトのエントリポイント。"""
    base = render_base_png(BASE_SIZE)
    png_path = RESOURCE_DIR / "pdfhanko.png"
    png_path.parent.mkdir(parents=True, exist_ok=True)
    base.save(png_path, format="PNG", dpi=(72, 72))
    print(f"wrote: {png_path}")
    print("次に scripts/build_icns.py を実行して .icns を生成してください。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
