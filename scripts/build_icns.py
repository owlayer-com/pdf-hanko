"""``src/pdfhanko/resources/pdfhanko.png`` から macOS 用 ``.icns`` を生成する。

入力: ``src/pdfhanko/resources/pdfhanko.png`` (1024×1024、RGBA 推奨)
出力: ``src/pdfhanko/resources/pdfhanko.icns`` (16/32/64/128/256/512/1024 マルチサイズ)

入力 PNG はユーザーが用意した任意のデザインで構わない。サイズが
1024×1024 でない場合は自動でリサイズ + 正方形パディングする。

実行::

    uv run python scripts/build_icns.py

依存: Pillow (本体の依存に含まれる)
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
RESOURCE_DIR = ROOT / "src" / "pdfhanko" / "resources"
SOURCE_PNG = RESOURCE_DIR / "pdfhanko.png"
DEST_ICNS = RESOURCE_DIR / "pdfhanko.icns"

ICON_SIZES = [16, 32, 64, 128, 256, 512, 1024]
"""ICNS に同梱するピクセルサイズ群。"""

TARGET_SIZE = 1024
"""ICNS の最大ピクセルサイズ。入力 PNG が異なれば自動正規化する。"""

MACOS_SAFE_AREA_RATIO = 0.824
"""macOS Big Sur 以降のアイコンガイドラインに合わせた本体コンテンツ比率。

1024×1024 キャンバスに対して、本体は約 824×824 px に収めるのが標準。
これより大きくキャンバスを使うと、Dock や Launchpad で他のアプリ
アイコンより一回り大きく見えてしまう。
"""


def _load_and_normalize(
    src_path: Path,
    size: int = TARGET_SIZE,
    safe_area_ratio: float = MACOS_SAFE_AREA_RATIO,
) -> Image.Image:
    """入力 PNG を読み込み、macOS 標準の安全領域に収めた ``size×size`` RGBA 画像を返す。

    入力 PNG をフルブリード (1024×1024 全面) のデザインとみなし、
    ``safe_area_ratio`` (デフォルト 82.4%) のコンテンツとしてキャンバス
    中央に配置する。アスペクト比は維持され、余白は透過になる。

    Args:
        src_path: 入力 PNG のパス。
        size: 出力する正方形の一辺ピクセル数。
        safe_area_ratio: コンテンツが占めるキャンバス比率。1.0 にすると
            パディングなしのフルブリードになる。

    Returns:
        正方形に揃えた RGBA Image。
    """
    img = Image.open(src_path).convert("RGBA")
    content_size = int(round(size * safe_area_ratio))
    w, h = img.size
    scale = content_size / max(w, h)
    new_w, new_h = int(round(w * scale)), int(round(h * scale))
    resized = img.resize((new_w, new_h), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(resized, ((size - new_w) // 2, (size - new_h) // 2), resized)
    return canvas


def build_icns(src_png: Path, dst_icns: Path) -> None:
    """PNG ファイルから ``.icns`` を生成して保存する。

    Pillow の ICNS writer に ``append_images`` で複数サイズを渡すと、
    macOS が期待する .icns 形式 (16/32/64/128/256/512/1024px) になる。

    Args:
        src_png: 入力 PNG パス。
        dst_icns: 出力 ``.icns`` パス。
    """
    base = _load_and_normalize(src_png, TARGET_SIZE)
    variants = [base.resize((s, s), Image.LANCZOS) for s in ICON_SIZES]
    first, *rest = variants
    dst_icns.parent.mkdir(parents=True, exist_ok=True)
    first.save(
        dst_icns,
        format="ICNS",
        sizes=[(s, s) for s in ICON_SIZES],
        append_images=rest,
    )


def main() -> int:
    """スクリプトのエントリポイント。"""
    if not SOURCE_PNG.exists():
        print(f"error: {SOURCE_PNG} が見つかりません。", file=sys.stderr)
        print(
            "ヒント: 1024×1024 PNG をこのパスに配置するか、"
            "scripts/generate_placeholder_icon.py で仮アイコンを生成してください。",
            file=sys.stderr,
        )
        return 1

    print(f"reading: {SOURCE_PNG}")
    try:
        build_icns(SOURCE_PNG, DEST_ICNS)
    except Exception as e:
        print(f"error: ICNS の書き出しに失敗: {e}", file=sys.stderr)
        return 1
    print(f"wrote:   {DEST_ICNS}")
    print(
        "`uv run briefcase update macOS --update-resources` で .app に反映してください "
        "(--update-resources がないとアイコンは更新されない)。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
