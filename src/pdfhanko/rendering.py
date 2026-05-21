"""PDF ページと画像のレンダリングユーティリティ。

本モジュールが提供する関数は出力 PNG をすべて 72 DPI に正規化する。
macOS の NSImage は PNG の DPI メタデータをそのまま描画スケールに反映する
ため、DPI が 72 と異なると Toga 上で意図しない倍率で表示されてしまう。
72 DPI に正規化することで「1 PDF pt = 1 canvas point」の関係を維持する。
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image


@dataclass(frozen=True, slots=True)
class RenderedPage:
    """1 ページのレンダリング結果。

    Attributes:
        png_bytes: 72 DPI に正規化された PNG バイト列。``toga.Image`` に
            そのまま渡せる。
        width_px: 出力画像の幅 (ピクセル)。
        height_px: 出力画像の高さ (ピクセル)。
        page_width_pt: ページ幅 (PDF pt)。
        page_height_pt: ページ高 (PDF pt)。
    """

    png_bytes: bytes
    width_px: int
    height_px: int
    page_width_pt: float
    page_height_pt: float


def render_page(page: "pdfium.PdfPage", scale: float = 1.0) -> RenderedPage:
    """PDF ページを 72 DPI 正規化済み PNG にレンダリングする。

    署名ウィジェットやフォーム要素も含めて描画するよう、``may_draw_forms``
    と ``draw_annots`` を有効化している。フォーム要素を表示するには事前に
    ``PdfDocument.init_forms()`` の呼び出しが必要。

    Args:
        page: pypdfium2 のページオブジェクト。
        scale: 出力倍率。1.0 で 1 PDF pt = 1 px = 1 canvas point。

    Returns:
        レンダリング結果を保持する :class:`RenderedPage`。
    """
    width_pt, height_pt = page.get_size()
    bitmap = page.render(
        scale=scale,
        rotation=0,
        draw_annots=True,
        may_draw_forms=True,
    )
    pil = bitmap.to_pil()
    if pil.mode != "RGB":
        pil = pil.convert("RGB")
    buf = io.BytesIO()
    pil.save(buf, format="PNG", dpi=(72, 72))
    return RenderedPage(
        png_bytes=buf.getvalue(),
        width_px=pil.width,
        height_px=pil.height,
        page_width_pt=float(width_pt),
        page_height_pt=float(height_pt),
    )


def normalize_image_dpi(src_path: Path, dst_path: Path) -> None:
    """画像ファイルを 72 DPI の PNG として保存し直す。

    印影画像は撮影ソースによって DPI がまちまちなので、ハンコ登録時に
    本関数で正規化してから保存する。透過情報は保持される。

    Args:
        src_path: 入力画像ファイル (PNG / JPEG など Pillow が読める形式)。
        dst_path: 出力 PNG の保存先。
    """
    img = Image.open(src_path)
    if img.mode not in ("RGBA", "RGB", "LA", "L"):
        img = img.convert("RGBA")
    img.save(dst_path, format="PNG", dpi=(72, 72))
