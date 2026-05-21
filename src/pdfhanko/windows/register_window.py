"""ハンコ登録 / 編集ウィンドウ。

新規登録 (``editing_hanko=None``) と編集 (``editing_hanko`` に既存ハンコを
渡す) の両モードをひとつのクラスで扱う。編集モードでは画像 / 証明書を
変更しなければ既存ファイルを保持し、証明書を差し替えたときだけ新しい
パスワードでの検証を要求する。
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Callable

import toga
from toga.style.pack import COLUMN, ROW, Pack

from ..signing import BadPasswordError, load_pkcs12_signer
from ..storage import Hanko
from .password_dialog import prompt_password

if TYPE_CHECKING:
    from ..app import PdfHankoApp

IMAGE_FILE_TYPES = ["png", "jpg", "jpeg"]
"""印影画像として受け付けるファイル拡張子。"""

CERT_FILE_TYPES = ["p12", "pfx"]
"""PKCS#12 証明書として受け付けるファイル拡張子。"""


class RegisterWindow:
    """ハンコ登録 / 編集ウィンドウ。

    Attributes:
        app: アプリケーション本体。ストアアクセスに使う。
        on_registered: 登録 / 編集が成功した時に呼ばれるコールバック。
        editing: 編集対象のハンコ。``None`` のときは新規登録モード。
        window: Toga の :class:`toga.Window` インスタンス。
        image_path: 新たに選択された印影画像のパス。
        cert_path: 新たに選択された証明書ファイルのパス。
    """

    def __init__(
        self,
        app: "PdfHankoApp",
        on_registered: Callable[[], None] | None = None,
        editing_hanko: Hanko | None = None,
    ) -> None:
        """ウィンドウを構築する。

        Args:
            app: :class:`pdfhanko.app.PdfHankoApp` インスタンス。
            on_registered: 登録 / 編集成功時に呼ばれるコールバック。
            editing_hanko: 編集対象のハンコ。``None`` で新規登録モード。
        """
        self.app = app
        self.on_registered = on_registered
        self.editing = editing_hanko
        title = "ハンコを編集" if self.editing else "ハンコを登録"
        self.window = toga.Window(title=title, size=(560, 540))

        self.image_path: Path | None = None
        self.cert_path: Path | None = None

        if self.editing:
            image_default = (
                self.editing.image_path(self.app.store.base_dir).name + " (現在のまま)"
            )
            cert_default = (
                self.editing.cert_path(self.app.store.base_dir).name + " (現在のまま)"
            )
            name_default = self.editing.name
            memo_default = self.editing.memo
            size_default = self.editing.size_mm
        else:
            image_default = "（未選択）"
            cert_default = "（未選択）"
            name_default = ""
            memo_default = ""
            size_default = 18

        self.image_label = toga.Label(image_default, style=Pack(flex=1, margin=(0, 8)))
        self.cert_label = toga.Label(cert_default, style=Pack(flex=1, margin=(0, 8)))
        self.name_input = toga.TextInput(
            value=name_default, placeholder="例: 個人実印", style=Pack(flex=1),
        )
        self.size_input = toga.NumberInput(
            value=size_default, min=5, max=50, step=1, style=Pack(width=80),
        )
        self.memo_input = toga.MultilineTextInput(
            value=memo_default, style=Pack(flex=1, height=80),
        )
        self.preview = toga.ImageView(style=Pack(width=120, height=120, margin=4))
        self.status = toga.Label("", style=Pack(margin=8, color="#666"))

        if self.editing:
            try:
                self.preview.image = toga.Image(
                    self.editing.image_path(self.app.store.base_dir)
                )
            except Exception:
                pass

        pick_image_btn = toga.Button(
            "画像を選択...", on_press=self._on_pick_image,
        )
        pick_cert_btn = toga.Button(
            "証明書を選択...", on_press=self._on_pick_cert,
        )
        save_text = "保存" if self.editing else "登録"
        save_btn = toga.Button(
            save_text, on_press=self._on_save, style=Pack(margin=8),
        )
        cancel_btn = toga.Button(
            "キャンセル", on_press=self._on_cancel, style=Pack(margin=8),
        )

        self.window.content = toga.Box(
            style=Pack(direction=COLUMN, margin=12),
            children=[
                _labeled_row("印影画像:", self.image_label, pick_image_btn),
                _labeled_row("証明書 (.p12):", self.cert_label, pick_cert_btn),
                _labeled_row("名前:", self.name_input),
                _labeled_row("サイズ (mm 角):", self.size_input),
                _labeled_row("メモ:", self.memo_input),
                toga.Box(
                    style=Pack(direction=ROW, margin_top=8),
                    children=[
                        toga.Label("プレビュー:", style=Pack(margin=(8, 4))),
                        self.preview,
                    ],
                ),
                self.status,
                toga.Box(
                    style=Pack(direction=ROW, margin_top=8),
                    children=[cancel_btn, save_btn],
                ),
            ],
        )

    def show(self) -> None:
        """ウィンドウをアプリのウィンドウ集合に登録して表示する。"""
        self.app.windows.add(self.window)
        self.window.show()

    async def _on_pick_image(self, widget: toga.Button) -> None:
        """「画像を選択...」ボタン押下時のハンドラ。

        ダイアログで選んだファイルをプレビュー表示し、保存対象として記憶する。
        """
        path = await self.window.dialog(
            toga.OpenFileDialog(
                title="印影画像を選択",
                file_types=IMAGE_FILE_TYPES,
            )
        )
        if path is None:
            return
        self.image_path = Path(path)
        self.image_label.text = self.image_path.name
        try:
            self.preview.image = toga.Image(self.image_path)
        except Exception as e:
            self.status.text = f"画像の読み込みに失敗: {e}"

    async def _on_pick_cert(self, widget: toga.Button) -> None:
        """「証明書を選択...」ボタン押下時のハンドラ。"""
        path = await self.window.dialog(
            toga.OpenFileDialog(
                title="PKCS#12 証明書を選択",
                file_types=CERT_FILE_TYPES,
            )
        )
        if path is None:
            return
        self.cert_path = Path(path)
        self.cert_label.text = self.cert_path.name

    async def _on_save(self, widget: toga.Button) -> None:
        """「登録」/「保存」ボタン押下時のハンドラ。

        以下の手順で保存処理を行う:

        1. 必須項目 (名前 / 画像 / 証明書) を検証する。
        2. 新規登録または証明書差し替え時はパスワードを入力させて検証する。
        3. ストアに対して :meth:`HankoStore.add` または
           :meth:`HankoStore.update` を呼ぶ。
        4. 成功したら ``on_registered`` コールバックを呼んでウィンドウを閉じる。
        """
        name = (self.name_input.value or "").strip()
        if not name:
            self.status.text = "名前を入力してください"
            return

        cert_path_to_verify: Path | None = None
        verify_message = ""
        if self.editing is None:
            if self.image_path is None:
                self.status.text = "印影画像を選択してください"
                return
            if self.cert_path is None:
                self.status.text = "証明書を選択してください"
                return
            cert_path_to_verify = self.cert_path
            verify_message = (
                f"{self.cert_path.name} のパスワードを入力してください。"
            )
        else:
            if self.cert_path is not None:
                cert_path_to_verify = self.cert_path
                verify_message = (
                    f"新しい証明書 {self.cert_path.name} のパスワードを入力してください。"
                )

        if cert_path_to_verify is not None:
            password = await prompt_password(self.window, verify_message)
            if password is None:
                self.status.text = "保存をキャンセルしました"
                return
            try:
                load_pkcs12_signer(cert_path_to_verify, password.encode("utf-8"))
            except BadPasswordError:
                self.status.text = "パスワードが正しくないか、証明書を読み取れません"
                return
            except Exception as e:
                self.status.text = f"証明書の検証に失敗: {e}"
                return
            finally:
                password = None

        size_mm = float(self.size_input.value or 18)
        memo = (self.memo_input.value or "").strip()
        try:
            if self.editing is None:
                self.app.store.add(
                    name=name,
                    size_mm=size_mm,
                    memo=memo,
                    image_src=self.image_path,
                    cert_src=self.cert_path,
                )
            else:
                self.app.store.update(
                    self.editing.id,
                    name=name,
                    size_mm=size_mm,
                    memo=memo,
                    image_src=self.image_path,
                    cert_src=self.cert_path,
                )
        except Exception as e:
            self.status.text = f"保存に失敗: {e}"
            return

        if self.on_registered is not None:
            self.on_registered()
        self.window.close()

    def _on_cancel(self, widget: toga.Button) -> None:
        """「キャンセル」ボタン押下時のハンドラ。"""
        self.window.close()


def _labeled_row(label: str, *children: toga.Widget) -> toga.Box:
    """ラベル + 入力ウィジェット 1 個以上を 1 行にまとめる。

    Args:
        label: 行頭に表示するラベル文字列。
        *children: ラベルの右側に並べるウィジェット。

    Returns:
        :class:`toga.Box` (ROW 方向)。
    """
    return toga.Box(
        style=Pack(direction=ROW, margin_bottom=8, align_items="center"),
        children=[
            toga.Label(label, style=Pack(width=120)),
            *children,
        ],
    )
