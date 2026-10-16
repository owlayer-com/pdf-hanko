"""PDF ページと画像のレンダリングユーティリティ。

本モジュールが提供する関数は出力 PNG をすべて 72 DPI に正規化する。
macOS の NSImage は PNG の DPI メタデータをそのまま描画スケールに反映する
ため、DPI が 72 と異なると Toga 上で意図しない倍率で表示されてしまう。
72 DPI に正規化することで「1 PDF pt = 1 canvas point」の関係を維持する。

巨大なページや高圧縮の PDF・画像による資源枯渇を防ぐため、
:class:`pdfhanko.limits.ResourceLimits` の上限をビットマップの確保や画像の
展開の**前に**確認する。上限を超えた場合は
:class:`pdfhanko.limits.ResourceLimitError` を送出する。
"""
from __future__ import annotations

import io
import math
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import pypdfium2 as pdfium
from PIL import Image

from .fileutil import atomic_write
from .limits import MB, MEGAPIXEL, ResourceLimitError, ResourceLimits


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


def check_pdf_file(path: Path, limits: ResourceLimits | None = None) -> None:
    """PDF のファイルサイズが上限以内か確認する。

    Args:
        path: PDF ファイル。
        limits: 上限。``None`` のときは既定値。

    Raises:
        ResourceLimitError: ファイルサイズが ``pdf_file_mb`` を超える場合。
    """
    limits = limits or ResourceLimits()
    size = os.stat(path).st_size
    if size > limits.pdf_file_bytes:
        raise ResourceLimitError("pdf_file_mb", size / MB, limits.pdf_file_mb)


def check_pdf_pages(page_count: int, limits: ResourceLimits | None = None) -> None:
    """PDF のページ数が上限以内か確認する。

    Raises:
        ResourceLimitError: ページ数が ``pdf_pages`` を超える場合。
    """
    limits = limits or ResourceLimits()
    if page_count > limits.pdf_pages:
        raise ResourceLimitError("pdf_pages", page_count, limits.pdf_pages)


def render_page(
    page: "pdfium.PdfPage",
    scale: float = 1.0,
    limits: ResourceLimits | None = None,
) -> RenderedPage:
    """PDF ページを 72 DPI 正規化済み PNG にレンダリングする。

    署名ウィジェットやフォーム要素も含めて描画するよう、``may_draw_forms``
    と ``draw_annots`` を有効化している。フォーム要素を表示するには事前に
    ``PdfDocument.init_forms()`` の呼び出しが必要。

    ビットマップを確保する前に、描画後のピクセル数が ``render_megapixels``
    以内であることを確認する。

    Args:
        page: pypdfium2 のページオブジェクト。
        scale: 出力倍率。1.0 で 1 PDF pt = 1 px = 1 canvas point。
        limits: 上限。``None`` のときは既定値。

    Returns:
        レンダリング結果を保持する :class:`RenderedPage`。

    Raises:
        ValueError: ページ寸法が有限の正の値でない場合。
        ResourceLimitError: 描画ピクセル数が上限を超える場合、または
            メモリを確保できなかった場合。
    """
    limits = limits or ResourceLimits()
    width_pt, height_pt = page.get_size()
    if not all(math.isfinite(v) and v > 0 for v in (width_pt, height_pt)):
        raise ValueError(f"ページの寸法が不正です ({width_pt} x {height_pt} pt)")
    pixels = math.ceil(width_pt * scale) * math.ceil(height_pt * scale)
    if pixels > limits.render_pixels:
        raise ResourceLimitError(
            "render_megapixels", pixels / MEGAPIXEL, limits.render_megapixels,
        )
    try:
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
    except MemoryError:
        raise ResourceLimitError.out_of_memory(
            "render_megapixels", limits.render_megapixels,
        ) from None
    return RenderedPage(
        png_bytes=buf.getvalue(),
        width_px=pil.width,
        height_px=pil.height,
        page_width_pt=float(width_pt),
        page_height_pt=float(height_pt),
    )


@contextmanager
def _open_limited_image(
    path: Path, limits: ResourceLimits | None,
) -> Iterator[Image.Image]:
    """上限を確認したうえで画像を開くコンテキストマネージャ。

    ファイルサイズを確認してから ``Image.open`` (ヘッダだけを読む遅延読み
    込み) で開き、ピクセル数を確認する。画素の展開はこの後に行うため、
    上限を超える画像のメモリは確保されない。

    Pillow 標準の保護 (``Image.MAX_IMAGE_PIXELS``) はアプリのチェックと
    二重になり、ユーザーが上限を上げても Pillow 側で拒否されてしまうため、
    このブロックの間だけ無効にしてアプリのチェックに一本化する。

    Raises:
        ResourceLimitError: ファイルサイズまたはピクセル数が上限を超える場合。
    """
    limits = limits or ResourceLimits()
    size = os.stat(path).st_size
    if size > limits.image_file_bytes:
        raise ResourceLimitError("image_file_mb", size / MB, limits.image_file_mb)

    saved_max = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = None
    try:
        with Image.open(path) as img:
            width, height = img.size
            if width * height > limits.image_pixels:
                raise ResourceLimitError(
                    "image_megapixels",
                    width * height / MEGAPIXEL,
                    limits.image_megapixels,
                )
            try:
                yield img
            except MemoryError:
                raise ResourceLimitError.out_of_memory(
                    "image_megapixels", limits.image_megapixels,
                ) from None
    finally:
        Image.MAX_IMAGE_PIXELS = saved_max


def check_image_file(path: Path, limits: ResourceLimits | None = None) -> None:
    """画像のファイルサイズとピクセル数が上限以内か確認する (展開はしない)。

    印影画像を選択した直後、プレビュー表示の前に呼ぶ想定。

    Raises:
        ResourceLimitError: 上限を超える場合。
        PIL.UnidentifiedImageError: 画像として読めない場合。
    """
    with _open_limited_image(path, limits):
        pass


def normalize_image_dpi(
    src_path: Path,
    dst_path: Path,
    *,
    mode: int | None = None,
    limits: ResourceLimits | None = None,
) -> None:
    """画像ファイルを 72 DPI の PNG として保存し直す。

    印影画像は撮影ソースによって DPI がまちまちなので、ハンコ登録時に
    本関数で正規化してから保存する。透過情報は保持される。出力は一時
    ファイル経由で書き込み、失敗時に不完全な PNG を残さない。

    Args:
        src_path: 入力画像ファイル (PNG / JPEG など Pillow が読める形式)。
        dst_path: 出力 PNG の保存先。
        mode: 出力ファイルの権限。``None`` のときは
            :func:`pdfhanko.fileutil.atomic_write` の既定に従う。
        limits: 上限。``None`` のときは既定値。

    Raises:
        ResourceLimitError: 画像のファイルサイズまたはピクセル数が上限を
            超える場合。出力ファイルは作成されない。
    """
    with _open_limited_image(src_path, limits) as img:
        if img.mode not in ("RGBA", "RGB", "LA", "L"):
            img = img.convert("RGBA")
        with atomic_write(dst_path, mode=mode) as f:
            img.save(f, format="PNG", dpi=(72, 72))
