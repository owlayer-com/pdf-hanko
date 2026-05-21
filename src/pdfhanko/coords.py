"""座標系変換ユーティリティ。

本アプリで扱う 3 つの座標系：

- ``canvas``: Toga Canvas の座標 (top-left 原点、単位 = canvas point)
- ``pdf_top``: 画面表示と整合した PDF 上の位置 (top-left 原点、単位 = pt)
- ``pdf_bottom``: PDF 仕様 / PyHanko が要求する座標 (bottom-left 原点、単位 = pt)

PDF を画像化して Canvas に等倍 (1 PDF pt = 1 canvas point) で表示する前提。
これは :func:`pdfhanko.rendering.render_page` が PNG を 72 DPI に正規化する
ことで保証される。
"""
from __future__ import annotations

MM_TO_PT: float = 72 / 25.4
"""ミリメートル → PDF ポイントの換算係数 (1 mm ≈ 2.835 pt)。"""


def mm_to_pt(mm: float) -> float:
    """ミリメートルを PDF ポイントに変換する。

    Args:
        mm: 変換元の長さ (mm)。

    Returns:
        変換後の長さ (pt)。
    """
    return mm * MM_TO_PT


def canvas_to_pdf_top(cx: float, cy: float) -> tuple[float, float]:
    """Canvas 座標を PDF top-left 原点座標に変換する。

    現状の実装では 1 canvas point = 1 PDF pt なので恒等変換になる。
    関数を介すことで意図を明示し、将来スケール係数を導入する余地を残す。

    Args:
        cx: Canvas 上の x 座標。
        cy: Canvas 上の y 座標。

    Returns:
        ``(x_pt, y_pt)`` PDF top-left 原点の座標。
    """
    return cx, cy


def pdf_top_to_pdf_bottom_box(
    x0_top: float,
    y0_top: float,
    x1_top: float,
    y1_top: float,
    page_h_pt: float,
) -> tuple[int, int, int, int]:
    """top-left 原点の矩形を PDF 仕様の bottom-left 原点に変換する。

    PyHanko の ``SigFieldSpec.box`` が要求する形式 ``(x0, y0, x1, y1)``
    (bottom-left 原点、整数 pt) を返す。

    Args:
        x0_top: 矩形左端の x 座標 (top-left 原点 pt)。
        y0_top: 矩形上端の y 座標 (top-left 原点 pt)。
        x1_top: 矩形右端の x 座標 (top-left 原点 pt)。
        y1_top: 矩形下端の y 座標 (top-left 原点 pt)。
        page_h_pt: ページ高 (pt)。y 軸反転に使用。

    Returns:
        ``(x0, y0, x1, y1)`` の bottom-left 原点の整数座標タプル。
    """
    return (
        int(round(x0_top)),
        int(round(page_h_pt - y1_top)),
        int(round(x1_top)),
        int(round(page_h_pt - y0_top)),
    )
