"""メインウィンドウ。

レイアウト::

    +-----------------------------------------------+
    | [PDF を開く...] [ハンコを登録...] [署名して保存...] |
    +--------------------------------+--------------+
    |  左ペイン: PDF 表示             | 登録済みハンコ |
    |  (ページ送り + 押印プレビュー)   | [サムネ + 名前]|
    |                                | [変更] [削除] |
    +--------------------------------+--------------+
"""
from __future__ import annotations

import asyncio
import io
from pathlib import Path
from typing import TYPE_CHECKING, Callable

import toga
from PIL import Image
from toga.style.pack import COLUMN, ROW, Pack

from ..signing import BadPasswordError, load_pkcs12_signer, sign_pdf_with_signer
from ..storage import Hanko
from .password_dialog import prompt_password
from .pdf_view import PdfView
from .register_window import RegisterWindow

if TYPE_CHECKING:
    from ..app import PdfHankoApp


BASE_TITLE = "PDF Hanko"
"""ウィンドウタイトルのベース。PDF を開くとファイル名が末尾に付く。"""

THUMBNAIL_PX = 64
"""ハンコ一覧で使うサムネイルの 1 辺ピクセル数。"""

NAME_TRUNCATE_AT = 5
"""ハンコ名表示の最大文字数。これを超えた分は ``…`` で省略する。"""


def _truncate(text: str, max_chars: int = NAME_TRUNCATE_AT) -> str:
    """日本語向けに文字列を省略する。

    Args:
        text: 元の文字列。
        max_chars: 省略を開始するしきい値の文字数。

    Returns:
        ``max_chars`` 文字以下ならそのまま、それを超えたら末尾を ``…``
        に置換した文字列。
    """
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "…"


def _make_thumbnail(image_path: Path, size: int = THUMBNAIL_PX) -> toga.Image:
    """印影画像から正方形サムネイルの :class:`toga.Image` を生成する。

    Toga (Cocoa) の :class:`toga.ImageView` は width/height を指定しても
    元画像をスケーリングせずスクロール表示してしまうため、PIL で事前に
    リサイズしてから渡す必要がある。

    Args:
        image_path: 元画像ファイルのパス。
        size: 1 辺ピクセル数。

    Returns:
        透過 PNG にラップした :class:`toga.Image`。
    """
    pil = Image.open(image_path).convert("RGBA")
    pil.thumbnail((size, size), Image.LANCZOS)
    bg = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bg.paste(pil, ((size - pil.width) // 2, (size - pil.height) // 2), pil)
    buf = io.BytesIO()
    bg.save(buf, format="PNG", dpi=(72, 72))
    return toga.Image(buf.getvalue())


def _build_clickable_hanko_area(
    image_path: Path,
    hanko: Hanko,
    is_selected: bool,
    on_press: Callable[[], None],
) -> toga.Canvas:
    """サムネ + 名前 + サイズを 1 枚の Canvas に描画してクリック可能にする。

    Toga の Box / Label / ImageView は ``on_press`` イベントを持たないため、
    まとめて Canvas に描画することでエリア全体をクリック判定に使えるようにしている。

    Args:
        image_path: 印影画像ファイルのパス。
        hanko: 表示対象のハンコ。
        is_selected: 選択状態のとき True。背景色で強調表示する。
        on_press: クリック時に呼ばれるコールバック。

    Returns:
        描画済みの :class:`toga.Canvas`。
    """
    width = 160
    height = 72
    canvas = toga.Canvas(
        on_press=lambda widget, x, y, **_: on_press(),
        style=Pack(width=width, height=height, margin=4),
    )
    if is_selected:
        with canvas.fill(color="#dde6ff"):
            canvas.rect(0, 0, width, height)
    try:
        thumb = _make_thumbnail(image_path, THUMBNAIL_PX)
        canvas.draw_image(thumb, 4, (height - THUMBNAIL_PX) // 2)
    except Exception:
        pass
    name_x = THUMBNAIL_PX + 12
    with canvas.fill(color="#000"):
        canvas.write_text(
            _truncate(hanko.name),
            name_x,
            22,
            font=toga.Font(family="system", size=13, weight="bold"),
        )
    with canvas.fill(color="#666"):
        canvas.write_text(
            f"{hanko.size_mm:.0f} mm 角",
            name_x,
            44,
            font=toga.Font(family="system", size=11),
        )
    canvas.redraw()
    return canvas


class MainWindow:
    """アプリのメインウィンドウ。

    Attributes:
        app: アプリケーション本体。ストアやウィンドウ管理にアクセスする。
        window: Toga のメインウィンドウインスタンス。
        selected_hanko: 現在押印用に選択されているハンコ。
        pdf_view: PDF 表示・押印 UI コンポーネント。
    """

    def __init__(self, app: "PdfHankoApp") -> None:
        """ウィンドウを構築する。

        Args:
            app: :class:`pdfhanko.app.PdfHankoApp` インスタンス。
        """
        self.app = app
        # 直近の署名保存時の (ページ番号, 矩形, ハンコ ID) スナップショット。
        # クローズ時に現状と比較し、一致していれば「未保存ではない」と判定する。
        # PDF を開き直すなど意味を失うタイミングでは None に戻す。
        self._last_saved_state: tuple | None = None
        self.window = toga.MainWindow(title=BASE_TITLE, size=(1200, 900))
        # File > Close (Cmd+W) / Close All / 左上の赤ボタンはいずれも本ハンドラに
        # 到達する。未保存があれば確認ダイアログを挟んだうえでアプリを終了させる。
        self.window.on_close = self._on_main_window_close
        self.selected_hanko: Hanko | None = None
        self.pdf_view = PdfView(on_status_change=self._on_pdf_status_change)
        self.pdf_view.on_close_pdf_callback = self._after_pdf_close
        self.pdf_view.set_show_field(self.app.settings.show_field)

        self.open_pdf_btn = toga.Button(
            "PDF を開く...", on_press=self._on_open_pdf, style=Pack(margin=4),
        )
        register_btn = toga.Button(
            "ハンコを登録...", on_press=self._on_register, style=Pack(margin=4),
        )
        self.sign_btn = toga.Button(
            "署名して保存...",
            on_press=self._on_sign,
            style=Pack(margin=4),
            enabled=False,
        )
        toolbar = toga.Box(
            style=Pack(direction=ROW, align_items="center"),
            children=[
                self.open_pdf_btn,
                self.sign_btn,
                toga.Box(style=Pack(flex=1)),
                register_btn,
            ],
        )

        self.left_pane = toga.Box(
            style=Pack(direction=COLUMN, flex=1),
            children=[self.pdf_view.container],
        )

        self.hanko_list_box = toga.Box(style=Pack(direction=COLUMN, margin=8))
        right_pane = toga.Box(
            style=Pack(direction=COLUMN, width=260),
            children=[
                toga.Label("登録済みハンコ", style=Pack(margin=8, font_weight="bold")),
                self.hanko_list_box,
            ],
        )
        self._refresh_hanko_list()

        # Toga SplitContainer は配下の COLUMN の高さ計算が崩れて内容が
        # クリップされる事象があるため、水平 Box で代替している。
        body = toga.Box(
            style=Pack(direction=ROW, flex=1),
            children=[self.left_pane, right_pane],
        )
        self.window.content = toga.Box(
            style=Pack(direction=COLUMN, flex=1),
            children=[toolbar, body],
        )

    def cleanup(self) -> None:
        """アプリ終了前に保有リソースを明示的に解放する。

        :class:`PdfHankoApp.on_exit` から呼ばれる。Toga / rubicon-objc と
        Cocoa autorelease pool の終了タイミング競合による segfault を
        抑制するための補助処理。
        """
        try:
            self.pdf_view.cleanup()
        except Exception:
            pass

    def _on_pdf_status_change(self, text: str) -> None:
        """PDF ビューの状態変化時に呼ばれるコールバック。

        押印位置・ハンコ選択・PDF 読込の 3 条件が揃った時のみ署名ボタンを
        有効化する。

        Args:
            text: PDF ビュー側で生成された人間可読のステータス文字列。
                現状は副作用のみのため使用しない。
        """
        enabled = self.pdf_view.has_pending() and self.selected_hanko is not None
        self.sign_btn.enabled = enabled
        # ツールバーと File メニューの「署名して保存」を同一条件で活性制御する。
        sign_command = getattr(self.app, "_sign_command", None)
        if sign_command is not None:
            sign_command.enabled = enabled

    def _refresh_hanko_list(self) -> None:
        """右ペインのハンコ一覧を再構築する。"""
        self.hanko_list_box.clear()
        if not self.app.store.hankos:
            self.hanko_list_box.add(
                toga.Label(
                    "（未登録）右上の「ハンコを登録...」から\n追加してください",
                    style=Pack(margin=8, color="#888"),
                )
            )
            return
        for hanko in self.app.store.hankos:
            self.hanko_list_box.add(self._make_hanko_row(hanko))

    def _make_hanko_row(self, hanko: Hanko) -> toga.Box:
        """ハンコ 1 件分の表示行を構築する。

        Args:
            hanko: 表示対象のハンコ。

        Returns:
            行 (サムネクリック領域 + 変更/削除ボタン) を含む :class:`toga.Box`。
        """
        is_selected = (
            self.selected_hanko is not None and self.selected_hanko.id == hanko.id
        )
        image_path = hanko.image_path(self.app.store.base_dir)

        clickable_area = _build_clickable_hanko_area(
            image_path=image_path,
            hanko=hanko,
            is_selected=is_selected,
            on_press=lambda: self._on_select_hanko(hanko),
        )

        # async ハンドラを `lambda` で生成するとコルーチンが await されずに
        # 失われるため、明示的に async 関数を返すクロージャでラップする。
        def make_modify_handler(h: Hanko):
            def handler(widget: toga.Button) -> None:
                self._on_modify_hanko(h)
            return handler

        def make_delete_handler(h: Hanko):
            async def handler(widget: toga.Button) -> None:
                await self._on_delete_hanko(h)
            return handler

        modify_btn = toga.Button(
            "変更",
            on_press=make_modify_handler(hanko),
            style=Pack(margin=2, width=58),
        )
        delete_btn = toga.Button(
            "削除",
            on_press=make_delete_handler(hanko),
            style=Pack(margin=2, width=58),
        )

        return toga.Box(
            style=Pack(
                direction=ROW,
                margin_bottom=6,
                background_color="#eef" if is_selected else "transparent",
            ),
            children=[
                clickable_area,
                toga.Box(
                    style=Pack(
                        direction=COLUMN,
                        margin_top=2,
                        margin_right=2,
                        margin_bottom=2,
                        margin_left=8,
                    ),
                    children=[modify_btn, delete_btn],
                ),
            ],
        )

    async def _on_register(self, widget: toga.Button) -> None:
        """「ハンコを登録...」ボタン押下時のハンドラ。"""
        win = RegisterWindow(self.app, on_registered=self._after_register)
        win.show()

    def _on_modify_hanko(self, hanko: Hanko) -> None:
        """ハンコ行の「変更」ボタン押下時のハンドラ。

        Args:
            hanko: 編集対象のハンコ。
        """
        win = RegisterWindow(
            self.app,
            on_registered=self._after_register,
            editing_hanko=hanko,
        )
        win.show()

    def _after_pdf_close(self) -> None:
        """PdfView 側で PDF が閉じられた時のコールバック。

        タイトルバーをベース文字列に戻し、保存スナップショットも破棄する。
        """
        self.window.title = BASE_TITLE
        self._last_saved_state = None

    def _current_stamp_state(self) -> tuple | None:
        """現在の押印状態 (ページ, 矩形, ハンコ ID) のスナップショットを返す。

        押印確定済み且つハンコ選択済みのときだけタプルを返し、それ以外は
        ``None`` を返す。:attr:`_last_saved_state` と等価判定で比較する用途。
        """
        if not (self.pdf_view.has_pending() and self.selected_hanko is not None):
            return None
        return (
            self.pdf_view.page_index,
            self.pdf_view.pending_box_pdf,
            self.selected_hanko.id,
        )

    def has_unsaved_changes(self) -> bool:
        """未保存の押印が残っているかを判定する。

        押印確定済みで、かつ直近保存時のスナップショットと不一致のとき True。
        赤ボタン / Cmd+W (``on_close``) と Cmd+Q (``on_exit``) の両方から
        共通の判定ロジックとして使われる。
        """
        current = self._current_stamp_state()
        return current is not None and current != self._last_saved_state

    def _on_main_window_close(self, _window: toga.Window, **_kwargs) -> bool:
        """メインウィンドウのクローズ要求ハンドラ。

        ウィンドウ左上の赤ボタン・File > Close (Cmd+W)・File > Close All は
        いずれも NSWindow の ``performClose:`` を経由して本ハンドラに到達する。
        macOS のメニュー API では送信元を区別できないため、すべて同じ
        「アプリ終了動作」として扱う:

        - PDF 未読込 → そのまま終了
        - PDF 読込済 & 押印未確定 (署名ボタンがグレーアウト状態) → そのまま終了
        - PDF 読込済 & 押印確定済 (= 未保存) → 確認ダイアログを別タスクで出し、
          OK なら ``app.exit()`` でアプリ終了。本ハンドラ自体は False を返して
          いったんクローズを保留する (確認結果が出るまでウィンドウを生かす)。

        本ハンドラは ``async`` にしない: async にすると Toga がイベントループ
        経由で戻り値を伝播するため、次のイベント (マウス移動など) が来るまで
        実際の close が遅延してしまう。

        Returns:
            True ならウィンドウを閉じる (= 単一ウィンドウ構成なのでアプリ終了)、
            False ならクローズ保留 (= 確認ダイアログ経由で改めて exit を呼ぶ)。
        """
        # 押印確定済み、かつ直近保存時のスナップショットと不一致のときだけ
        # 未保存とみなす。保存直後はスナップショットと一致するため、ダイアログを
        # 出さず即終了する。
        if not self.has_unsaved_changes():
            return True
        asyncio.create_task(self._confirm_unsaved_then_exit())
        return False

    async def _confirm_unsaved_then_exit(self) -> None:
        """未保存の押印がある状態でのクローズ要求に対する確認フロー。

        確認ダイアログで OK が押された場合のみ :meth:`toga.App.exit` を呼んで
        アプリを終了する。キャンセル時は何もせずウィンドウを維持する。
        """
        confirm = await self.window.dialog(
            toga.ConfirmDialog(
                "アプリを終了",
                "押印位置がまだ保存されていません。\n本当に終了してよろしいですか?",
            )
        )
        if confirm:
            self.app.exit()

    def _after_register(self) -> None:
        """ハンコ登録 / 編集が完了した時のコールバック。

        選択中ハンコが編集された場合に備えてストアから最新の情報を取り直し、
        PDF ビューにも反映する。
        """
        if self.selected_hanko is not None:
            updated = next(
                (h for h in self.app.store.hankos if h.id == self.selected_hanko.id),
                None,
            )
            self.selected_hanko = updated
            self.pdf_view.set_selected_hanko(updated, self.app.store.base_dir)
        self._refresh_hanko_list()
        self._on_pdf_status_change("")

    def _on_select_hanko(self, hanko: Hanko) -> None:
        """ハンコ行のクリック領域が押された時のハンドラ。

        既に選択中のハンコを再度クリックした場合は選択を解除する。

        Args:
            hanko: クリックされたハンコ。
        """
        if self.selected_hanko is not None and self.selected_hanko.id == hanko.id:
            self.selected_hanko = None
            self.pdf_view.interactive = False
        else:
            self.selected_hanko = hanko
            self.pdf_view.set_selected_hanko(hanko, self.app.store.base_dir)
            self.pdf_view.interactive = True
        self._refresh_hanko_list()
        self._on_pdf_status_change("")

    async def _on_delete_hanko(self, hanko: Hanko) -> None:
        """ハンコ行の「削除」ボタン押下時のハンドラ。

        Args:
            hanko: 削除対象のハンコ。
        """
        confirm = await self.window.dialog(
            toga.ConfirmDialog(
                "ハンコを削除",
                f"「{hanko.name}」を削除します。\n"
                "印影画像と証明書ファイルもアプリ領域から削除されます。",
            )
        )
        if not confirm:
            return
        self.app.store.remove(hanko.id)
        if self.selected_hanko is not None and self.selected_hanko.id == hanko.id:
            self.selected_hanko = None
            self.pdf_view.set_selected_hanko(None, self.app.store.base_dir)
        self._refresh_hanko_list()
        self._on_pdf_status_change("")

    async def _on_open_pdf(self, widget: toga.Button) -> None:
        """「PDF を開く...」ボタン押下時のハンドラ。

        選択された PDF をビューに読み込み、タイトルバーにファイル名を反映する。
        """
        path = await self.window.dialog(
            toga.OpenFileDialog(
                title="署名する PDF を選択",
                file_types=["pdf"],
            )
        )
        if path is None:
            return
        try:
            self.pdf_view.load_pdf(Path(path))
        except Exception as e:
            self.window.title = BASE_TITLE
            await self.window.dialog(
                toga.ErrorDialog("PDF を開けません", str(e))
            )
            return
        # 別の PDF を開いたタイミングで保存スナップショットは無効になる。
        self._last_saved_state = None
        self.window.title = f"{BASE_TITLE} - {Path(path).name}"

    async def _on_sign(self, widget: toga.Button) -> None:
        """「署名して保存...」ボタン押下時のハンドラ。

        保存先・パスワードの確認をしたうえで PyHanko により可視署名を付与し、
        結果を保存する。パスワード誤りはユーザー向けに専用のダイアログを出す。
        """
        if self.selected_hanko is None:
            await self.window.dialog(
                toga.InfoDialog("ハンコ未選択", "右ペインからハンコを選んでください")
            )
            return
        if not self.pdf_view.has_pending() or self.pdf_view.doc_path is None:
            await self.window.dialog(
                toga.InfoDialog("押印位置未指定", "PDF 上で押印したい位置をクリックしてください")
            )
            return

        default_name = self.pdf_view.doc_path.stem + "_signed.pdf"
        save_path = await self.window.dialog(
            toga.SaveFileDialog(
                title="署名済み PDF の保存先",
                suggested_filename=default_name,
                file_types=["pdf"],
            )
        )
        if save_path is None:
            return

        password = await prompt_password(
            self.window,
            f"「{self.selected_hanko.name}」の証明書パスワードを入力してください。",
        )
        if password is None:
            return

        cert_path = self.selected_hanko.cert_path(self.app.store.base_dir)
        try:
            signer = load_pkcs12_signer(cert_path, password.encode("utf-8"))
        except BadPasswordError:
            await self.window.dialog(
                toga.ErrorDialog(
                    "パスワード誤り",
                    "証明書を復号できませんでした。パスワードをご確認ください。",
                )
            )
            return
        except Exception as e:
            await self.window.dialog(
                toga.ErrorDialog("証明書の読み込みに失敗", str(e))
            )
            return
        finally:
            password = None

        try:
            await sign_pdf_with_signer(
                src_pdf=self.pdf_view.doc_path,
                dst_pdf=Path(save_path),
                hanko_image=self.selected_hanko.image_path(self.app.store.base_dir),
                signer=signer,
                page_index=self.pdf_view.page_index,
                box_pdf=self.pdf_view.pending_box_pdf,
            )
        except Exception as e:
            await self.window.dialog(toga.ErrorDialog("署名に失敗", str(e)))
            return

        # 保存完了時点の (ページ, 矩形, ハンコ ID) をスナップショットとして
        # 記録する。クローズ時にこのスナップショットと現状を比較し、
        # 一致していれば未保存ではないと判定する (印影プレビューは残す)。
        self._last_saved_state = self._current_stamp_state()

        await self.window.dialog(
            toga.InfoDialog(
                "署名完了",
                f"保存しました:\n{save_path}",
            )
        )
