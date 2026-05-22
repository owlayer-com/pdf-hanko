"""PDF 表示・押印 UI コンポーネント。

ユーザー操作のフロー::

    1. ``load_pdf()`` で PDF を読み込む
    2. ``set_selected_hanko()`` で押印するハンコを指定する
    3. PDF 上でマウスボタンを押す  → 半透明の印影プレビュー描画
       ボタンを押したままドラッグ → プレビューがマウスに追従
       ボタンを離した位置で確定    → :attr:`pending_box_pdf` が更新される
    4. 呼び出し側は :attr:`pending_box_pdf` を取り出して PyHanko に渡す

ページ送りバーは複数ページ PDF の時だけ、閉じるボタンは PDF 読み込み中だけ
表示される。
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Callable

import pypdfium2 as pdfium
import toga
from PIL import Image, ImageChops
from toga.style.pack import CENTER, COLUMN, ROW, Pack

from ..coords import mm_to_pt, pdf_top_to_pdf_bottom_box
from ..rendering import RenderedPage, render_page
from ..storage import Hanko

PT_TO_PX = 1.0
"""1 PDF pt を何 canvas point で描画するかの係数。

1.0 のとき canvas 座標 = PDF top-origin pt となり、変換ロジックが単純化される。
"""

HANKO_PREVIEW_ALPHA = 130
"""押印プレビュー画像のアルファ値 (0-255)。値が小さいほど薄く透ける。"""

PAGE_BG = "#ffffff"
"""ページ用紙の背景色。"""

AREA_BG = "#e0e0e0"
"""PDF 外側 (スクロール領域) の背景色。"""


class PdfView:
    """PDF を表示し、押印位置を取得する UI コンポーネント。

    Attributes:
        doc: pypdfium2 の :class:`PdfDocument`。未読込時は ``None``。
        doc_path: 現在開いている PDF のパス。
        page_index: 現在表示中のページ番号 (0 始まり)。
        rendered: 現ページのレンダリング結果。
        page_image: 現ページの Toga 用画像。
        selected_hanko: 押印に用いるハンコ。
        click_canvas: 直近のクリック / ドラッグ位置 (canvas 座標)。
        pending_box_pdf: 確定済み押印矩形 (PDF bottom-left 原点 pt)。
        on_close_pdf_callback: PDF が「×」ボタンで閉じられた時のコールバック。
        container: 親に追加するためのルートウィジェット。
    """

    def __init__(
        self,
        on_status_change: Callable[[str], None] | None = None,
    ) -> None:
        """ウィジェット階層を構築する。

        Args:
            on_status_change: 状態が変わるたびに呼び出されるコールバック。
                ステータス文字列が引数として渡される。
        """
        self.doc: pdfium.PdfDocument | None = None
        self.doc_path: Path | None = None
        self.page_index: int = 0
        self.rendered: RenderedPage | None = None
        self.page_image: toga.Image | None = None

        self.selected_hanko: Hanko | None = None
        self.hanko_image_cache: dict[str, toga.Image] = {}
        self.click_canvas: tuple[float, float] | None = None
        self.pending_box_pdf: tuple[int, int, int, int] | None = None
        self.interactive: bool = True

        self._on_status_change = on_status_change

        self.prev_btn = toga.Button("◀", on_press=self._on_prev, style=Pack(margin=2))
        self.next_btn = toga.Button("▶", on_press=self._on_next, style=Pack(margin=2))
        self.page_label = toga.Label(
            "- / -", style=Pack(margin=(0, 8), width=80, text_align=CENTER),
        )

        self.canvas = toga.Canvas(
            on_press=self._on_canvas_press,
            on_drag=self._on_canvas_drag,
            on_release=self._on_canvas_release,
            style=Pack(width=10, height=10),
        )
        # Canvas を Box で囲み、PDF と外枠の間に余白を確保する。
        self.canvas_wrapper = toga.Box(
            style=Pack(margin=20, background_color=AREA_BG),
            children=[self.canvas],
        )
        self.scroll = toga.ScrollContainer(
            content=self.canvas_wrapper,
            style=Pack(flex=1, background_color=AREA_BG),
        )

        self.nav_inner = toga.Box(
            style=Pack(direction=ROW, align_items="center"),
            children=[self.prev_btn, self.page_label, self.next_btn],
        )
        self.close_btn = toga.Button(
            "×",
            on_press=self._on_close_pdf,
            style=Pack(margin=4, width=36),
        )
        self.on_close_pdf_callback: Callable[[], None] | None = None

        # ツールバーは PDF 読込時のみ表示する。左にナビ (複数ページ時のみ)、
        # 右端に閉じるボタンを配置する。
        self.spacer = toga.Box(style=Pack(flex=1))
        self.toolbar = toga.Box(
            style=Pack(direction=ROW, margin=4, align_items="center"),
            children=[],
        )
        self.container = toga.Box(
            style=Pack(direction=COLUMN, flex=1),
            children=[self.scroll],
        )
        self._toolbar_visible = False
        self._nav_in_toolbar = False

    # ---- 公開 API ----

    def load_pdf(self, pdf_path: Path) -> None:
        """指定 PDF を読み込み、最初のページを表示する。

        署名ウィジェット等のフォーム要素を描画するため
        :meth:`PdfDocument.init_forms` も呼ぶ (失敗しても無視する)。

        Args:
            pdf_path: 読み込む PDF のパス。
        """
        if self.doc is not None:
            self.doc.close()
        self.doc = pdfium.PdfDocument(pdf_path)
        try:
            self.doc.init_forms()
        except Exception:
            pass
        self.doc_path = pdf_path
        self.page_index = 0
        self.click_canvas = None
        self.pending_box_pdf = None
        self._render_current_page()
        self._update_toolbar()
        self._update_nav_buttons()
        self._emit_status()

    def cleanup(self) -> None:
        """終了時に保持するネイティブリソースを解放する。

        pypdfium2 の :class:`PdfDocument` はネイティブハンドルを抱えているため、
        Python の GC まかせにせず明示的に閉じる。``toga.Image`` のキャッシュも
        参照を切って Cocoa 側の autorelease 対象を減らす。
        """
        if self.doc is not None:
            try:
                self.doc.close()
            except Exception:
                pass
            self.doc = None
        self.doc_path = None
        self.rendered = None
        self.page_image = None
        self.hanko_image_cache.clear()
        try:
            self.canvas.root_state.drawing_actions.clear()
        except Exception:
            pass

    def close_pdf(self) -> None:
        """現在の PDF を閉じて、内部状態と Canvas をリセットする。"""
        if self.doc is not None:
            self.doc.close()
        self.doc = None
        self.doc_path = None
        self.page_index = 0
        self.rendered = None
        self.page_image = None
        self.click_canvas = None
        self.pending_box_pdf = None
        self.canvas.style.width = 10
        self.canvas.style.height = 10
        self.canvas.root_state.drawing_actions.clear()
        self.canvas.redraw()
        self._update_toolbar()
        self._emit_status()

    def set_selected_hanko(self, hanko: Hanko | None, base_dir: Path) -> None:
        """押印に使うハンコを指定する。

        Args:
            hanko: 選択中のハンコ。``None`` で解除。
            base_dir: ハンコ画像の解決に使うアプリ専用ディレクトリ。
        """
        self.selected_hanko = hanko
        self.hanko_image_cache.clear()
        if hanko is not None:
            self._load_hanko_preview(hanko, base_dir)
        self._redraw()
        self._emit_status()

    def has_pending(self) -> bool:
        """押印位置が確定済みかどうかを返す。

        Returns:
            ``pending_box_pdf`` が確定し、PDF が読み込まれていれば True。
        """
        return self.pending_box_pdf is not None and self.doc is not None

    # ---- 内部処理 ----

    def _emit_status(self) -> None:
        """現在の状態を ``on_status_change`` 経由で外部に通知する。"""
        if self._on_status_change is None:
            return
        if self.doc is None or self.doc_path is None:
            self._on_status_change("PDF が未読込")
            return
        parts = [self.doc_path.name, f"ページ {self.page_index + 1}/{len(self.doc)}"]
        if self.selected_hanko is None:
            parts.append("ハンコ未選択")
        else:
            parts.append(f"ハンコ: {self.selected_hanko.name}")
        if self.pending_box_pdf is not None:
            parts.append(f"押印位置 {self.pending_box_pdf}")
        self._on_status_change(" | ".join(parts))

    def _render_current_page(self) -> None:
        """現ページをレンダリングして Canvas サイズを更新する。"""
        if self.doc is None:
            return
        page = self.doc[self.page_index]
        self.rendered = render_page(page, scale=PT_TO_PX)
        self.page_image = toga.Image(self.rendered.png_bytes)
        self.canvas.style.width = self.rendered.width_px
        self.canvas.style.height = self.rendered.height_px
        self._redraw()

    def _redraw(self) -> None:
        """Canvas を再描画する (用紙背景 → ページ画像 → 縁 → 押印プレビュー)。"""
        self.canvas.root_state.drawing_actions.clear()
        if self.page_image is not None and self.rendered is not None:
            with self.canvas.fill(color=PAGE_BG):
                self.canvas.rect(0, 0, self.rendered.width_px, self.rendered.height_px)
            self.canvas.draw_image(self.page_image, 0, 0)
            with self.canvas.stroke(color="#888", line_width=1):
                self.canvas.rect(0, 0, self.rendered.width_px, self.rendered.height_px)
        if self.click_canvas is not None and self.selected_hanko is not None:
            self._draw_hanko_preview()
        self.canvas.redraw()

    def _draw_hanko_preview(self) -> None:
        """直近クリック位置にキャッシュ済みの半透明ハンコ画像を描画する。"""
        if self.click_canvas is None:
            return
        cx, cy = self.click_canvas
        toga_img = self.hanko_image_cache.get("preview")
        if toga_img is not None:
            self.canvas.draw_image(toga_img, cx, cy)

    def _load_hanko_preview(self, hanko: Hanko, base_dir: Path) -> None:
        """ハンコ画像をプレビュー用に半透明化・実寸リサイズしてキャッシュする。

        Args:
            hanko: 対象のハンコ。
            base_dir: アプリ専用ディレクトリ。
        """
        img_path = hanko.image_path(base_dir)
        pil = Image.open(img_path).convert("RGBA")
        alpha = pil.split()[3]
        new_alpha = ImageChops.multiply(
            alpha, Image.new("L", alpha.size, HANKO_PREVIEW_ALPHA),
        )
        pil.putalpha(new_alpha)
        size_px = max(1, int(round(mm_to_pt(hanko.size_mm) * PT_TO_PX)))
        pil = pil.resize((size_px, size_px), Image.LANCZOS)
        buf = io.BytesIO()
        pil.save(buf, format="PNG", dpi=(72, 72))
        self.hanko_image_cache["preview"] = toga.Image(buf.getvalue())

    def _update_toolbar(self) -> None:
        """ツールバーの表示要素を現在の状態に合わせて組み直す。

        PDF 読込中は閉じるボタンを表示し、複数ページならページ送りも表示する。
        """
        pdf_loaded = self.doc is not None
        multi_page = pdf_loaded and len(self.doc) > 1

        if pdf_loaded and not self._toolbar_visible:
            self.container.insert(0, self.toolbar)
            self._toolbar_visible = True
        elif not pdf_loaded and self._toolbar_visible:
            self.container.remove(self.toolbar)
            self._toolbar_visible = False

        self.toolbar.clear()
        if multi_page:
            self.toolbar.add(self.nav_inner)
        self.toolbar.add(self.spacer)
        if pdf_loaded:
            self.toolbar.add(self.close_btn)

    def _on_close_pdf(self, widget: toga.Button) -> None:
        """「×」ボタン押下時のハンドラ。"""
        self.close_pdf()
        if self.on_close_pdf_callback is not None:
            self.on_close_pdf_callback()

    def _update_nav_buttons(self) -> None:
        """ページ送りボタンの活性 / ラベルを更新する。"""
        if self.doc is None:
            return
        self.prev_btn.enabled = self.page_index > 0
        self.next_btn.enabled = self.page_index < len(self.doc) - 1
        self.page_label.text = f"{self.page_index + 1} / {len(self.doc)}"

    def _on_prev(self, widget: toga.Button) -> None:
        """「◀」ボタン押下時のハンドラ。前ページに移動し押印位置をリセットする。"""
        if self.doc is None or self.page_index <= 0:
            return
        self.page_index -= 1
        self.click_canvas = None
        self.pending_box_pdf = None
        self._render_current_page()
        self._update_nav_buttons()
        self._emit_status()

    def _on_next(self, widget: toga.Button) -> None:
        """「▶」ボタン押下時のハンドラ。次ページに移動し押印位置をリセットする。"""
        if self.doc is None or self.page_index >= len(self.doc) - 1:
            return
        self.page_index += 1
        self.click_canvas = None
        self.pending_box_pdf = None
        self._render_current_page()
        self._update_nav_buttons()
        self._emit_status()

    def _update_pending(self, x: float, y: float) -> None:
        """マウス位置から押印矩形 (PDF bottom-left 原点) を計算し再描画する。

        Args:
            x: Canvas 上のマウス x 座標。
            y: Canvas 上のマウス y 座標。
        """
        if self.rendered is None or self.selected_hanko is None:
            return
        self.click_canvas = (x, y)
        click_x_pt = x / PT_TO_PX
        click_y_pt_top = y / PT_TO_PX
        hanko_pt = mm_to_pt(self.selected_hanko.size_mm)
        self.pending_box_pdf = pdf_top_to_pdf_bottom_box(
            x0_top=click_x_pt,
            y0_top=click_y_pt_top,
            x1_top=click_x_pt + hanko_pt,
            y1_top=click_y_pt_top + hanko_pt,
            page_h_pt=self.rendered.page_height_pt,
        )
        self._redraw()

    def _on_canvas_press(self, widget, x, y, **_) -> None:
        """Canvas でのマウスボタン押下イベント。"""
        if self.doc is None or self.selected_hanko is None or not self.interactive:
            return
        self._update_pending(x, y)
        self._emit_status()

    def _on_canvas_drag(self, widget, x, y, **_) -> None:
        """Canvas 上でのドラッグイベント。プレビューをマウスに追従させる。"""
        if self.doc is None or self.selected_hanko is None or not self.interactive:
            return
        self._update_pending(x, y)

    def _on_canvas_release(self, widget, x, y, **_) -> None:
        """Canvas でのマウスボタン解放イベント。押印位置を確定する。"""
        if self.doc is None or self.selected_hanko is None or not self.interactive:
            return
        self._update_pending(x, y)
        self._emit_status()
