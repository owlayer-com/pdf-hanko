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

from ..signing import (
    BadPasswordError,
    JpkiCertMismatchError,
    load_jpki_signer,
    load_pkcs12_signer,
)
from ..storage import CERT_TYPE_JPKI, CERT_TYPE_PKCS12, Hanko
from .password_dialog import prompt_password
from .pin_dialog import prompt_jpki_pin

if TYPE_CHECKING:
    from ..app import PdfHankoApp

IMAGE_FILE_TYPES = ["png", "jpg", "jpeg"]
"""印影画像として受け付けるファイル拡張子。"""

CERT_FILE_TYPES = ["p12", "pfx"]
"""PKCS#12 証明書として受け付けるファイル拡張子。"""

CERT_TYPE_RADIO_LABEL_PKCS12 = "PKCS#12ファイル(*.p12)"
CERT_TYPE_RADIO_LABEL_JPKI = "マイナンバーカード"
# Toga 0.5 系には RadioButton ウィジェットが無い (公式ロードマップに記載のみ)
# ため、Switch 2 つを相互排他制御してラジオの代用とする。macOS では
# toga-cocoa の Switch が NSButtonTypeSwitch でレンダリングされるため
# 見た目はチェックボックス。将来 toga.RadioButton が実装されたら置換可。


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

        # JPKI 確認結果の保持。編集時は既存値で初期化。
        self.jpki_cert_serial: str | None = (
            self.editing.jpki_cert_serial if self.editing else None
        )
        self.jpki_cert_subject_cn: str | None = (
            self.editing.jpki_cert_subject_cn if self.editing else None
        )
        # 編集中にユーザーがカード再確認を行ったか。再確認していなければ
        # 既存の値をそのまま保持する。
        self.jpki_reverified: bool = False

        initial_cert_type = (
            self.editing.cert_type if self.editing else CERT_TYPE_PKCS12
        )

        if self.editing:
            image_default = (
                self.editing.image_path(self.app.store.base_dir).name + " (現在のまま)"
            )
            if self.editing.cert_type == CERT_TYPE_PKCS12 and self.editing.cert:
                cert_default = (
                    self.editing.cert_path(self.app.store.base_dir).name + " (現在のまま)"
                )
            else:
                cert_default = "（PKCS#12 ファイル未選択）"
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

        # JPKI 確認状態ラベル。
        self.jpki_status_label = toga.Label(
            self._jpki_status_text(),
            style=Pack(flex=1, margin=(0, 8)),
        )
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
        verify_jpki_btn = toga.Button(
            "カードを確認...", on_press=self._on_verify_jpki,
        )

        # 証明書種別ラジオ。Toga 0.5 には RadioButton が無いため、
        # Switch 2 つを相互排他制御して擬似的なラジオボタンとして使う。
        # 排他ロジック内での再入を防ぐためのガード。
        self._cert_type_radio_updating = False
        self.cert_type_radio_pkcs12 = toga.Switch(
            CERT_TYPE_RADIO_LABEL_PKCS12,
            value=(initial_cert_type == CERT_TYPE_PKCS12),
            on_change=self._on_cert_type_radio_pkcs12_change,
            style=Pack(margin_right=16),
        )
        self.cert_type_radio_jpki = toga.Switch(
            CERT_TYPE_RADIO_LABEL_JPKI,
            value=(initial_cert_type == CERT_TYPE_JPKI),
            on_change=self._on_cert_type_radio_jpki_change,
        )

        # PKCS#12 用 / JPKI 用の各行をあらかじめ構築しておき、選択状態に
        # 応じて cert_source_box の子要素を入れ替える。
        self._pkcs12_row = _labeled_row(
            "証明書 (.p12):", self.cert_label, pick_cert_btn,
        )
        self._jpki_row = _labeled_row(
            "マイナンバーカード:", self.jpki_status_label, verify_jpki_btn,
        )
        self.cert_source_box = toga.Box(style=Pack(direction=COLUMN))
        self._refresh_cert_source_visibility(initial_cert_type)

        save_text = "保存" if self.editing else "登録"
        save_btn = toga.Button(
            save_text, on_press=self._on_save, style=Pack(margin=8),
        )
        cancel_btn = toga.Button(
            "キャンセル", on_press=self._on_cancel, style=Pack(margin=8),
        )

        cert_type_row = _labeled_row(
            "証明書種別:",
            self.cert_type_radio_pkcs12,
            self.cert_type_radio_jpki,
        )
        # 「名前」/「証明書ファイル選択」との視覚的な区切りのため上下に
        # 8pt ずつ余白を足す (_labeled_row 既定の margin_bottom=8 に追加で 8pt)。
        cert_type_row.style.margin_top = 8
        cert_type_row.style.margin_bottom = 16

        self.window.content = toga.Box(
            style=Pack(direction=COLUMN, margin=12),
            children=[
                _labeled_row("名前:", self.name_input),
                cert_type_row,
                self.cert_source_box,
                _labeled_row("印影画像:", self.image_label, pick_image_btn),
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

    def _selected_cert_type(self) -> str:
        """現在ラジオで選ばれている証明書種別を返す。"""
        if self.cert_type_radio_jpki.value:
            return CERT_TYPE_JPKI
        return CERT_TYPE_PKCS12

    def _jpki_status_text(self) -> str:
        """JPKI 確認状態の表示文字列を組み立てる。"""
        if self.jpki_cert_subject_cn:
            prefix = "確認済" if self.jpki_reverified else "登録済"
            return f"{prefix}: {self.jpki_cert_subject_cn}"
        if self.jpki_cert_serial:
            prefix = "確認済" if self.jpki_reverified else "登録済"
            return f"{prefix}: シリアル {self.jpki_cert_serial}"
        return "未確認 (右のボタンから確認してください)"

    def _refresh_cert_source_visibility(self, cert_type: str) -> None:
        """選択中の証明書種別に応じて cert_source_box の中身を入れ替える。"""
        for child in list(self.cert_source_box.children):
            self.cert_source_box.remove(child)
        if cert_type == CERT_TYPE_JPKI:
            self.cert_source_box.add(self._jpki_row)
        else:
            self.cert_source_box.add(self._pkcs12_row)

    def _set_cert_type_radio(self, cert_type: str) -> None:
        """ラジオ表示状態と cert_source_box を同期する (再入ガード付き)。"""
        if self._cert_type_radio_updating:
            return
        self._cert_type_radio_updating = True
        try:
            self.cert_type_radio_pkcs12.value = (cert_type == CERT_TYPE_PKCS12)
            self.cert_type_radio_jpki.value = (cert_type == CERT_TYPE_JPKI)
            self._refresh_cert_source_visibility(cert_type)
        finally:
            self._cert_type_radio_updating = False

    def _on_cert_type_radio_pkcs12_change(self, widget: toga.Switch) -> None:
        """PKCS#12 ラジオの変化ハンドラ。

        - ON にされたら JPKI を OFF にして cert_source を PKCS#12 行に切替
        - OFF にされた (= JPKI 側 ON 操作の連鎖) ときは何もしない
        - 両方 OFF にされた場合は元の状態に戻して常に片方が ON を維持
        """
        if self._cert_type_radio_updating:
            return
        if widget.value:
            self._set_cert_type_radio(CERT_TYPE_PKCS12)
        elif not self.cert_type_radio_jpki.value:
            # 両方 OFF を許さない: PKCS#12 を ON に戻す
            self._set_cert_type_radio(CERT_TYPE_PKCS12)

    def _on_cert_type_radio_jpki_change(self, widget: toga.Switch) -> None:
        """マイナンバーカードラジオの変化ハンドラ。"""
        if self._cert_type_radio_updating:
            return
        if widget.value:
            self._set_cert_type_radio(CERT_TYPE_JPKI)
        elif not self.cert_type_radio_pkcs12.value:
            self._set_cert_type_radio(CERT_TYPE_JPKI)

    async def _on_verify_jpki(self, widget: toga.Button) -> None:
        """「カードを確認...」ボタン押下時のハンドラ。

        カードリーダー検出 → PIN 残回数取得 → PIN 入力ダイアログ →
        VERIFY → 署名用証明書読み出し までを行い、シリアル番号と
        Subject CN を画面に表示する。実際の保存はまだ行わない。
        """
        try:
            from .. import jpki as jpki_mod
        except ImportError as e:
            self.status.text = f"pyscard が利用できません: {e}"
            return

        readers = jpki_mod.list_readers()
        if not readers:
            self.status.text = (
                "カードリーダーが見つかりません。リーダーを接続してください"
            )
            return

        try:
            with jpki_mod.JpkiSession() as sess:
                sess.select_signature_ap()
                remaining = sess.get_pin_attempts_remaining()
        except jpki_mod.CardNotFoundError as e:
            self.status.text = str(e)
            return
        except jpki_mod.JpkiError as e:
            self.status.text = f"カード読み取り失敗: {e}"
            return

        if remaining == 0:
            self.status.text = (
                "署名用 PIN がロックされています。市区町村窓口で解除してください"
            )
            return

        pin = await prompt_jpki_pin(
            self.window,
            "登録するカードを挿入し、署名用パスワード (6〜16 桁英数字) を入力してください。",
            attempts_remaining=remaining,
        )
        if pin is None:
            self.status.text = "カード確認をキャンセルしました"
            return

        signer = None
        try:
            signer = load_jpki_signer(pin.encode("ascii"))
            cert = signer.signing_cert
            self.jpki_cert_serial = format(cert.serial_number, "X")
            subject_native = cert.subject.native or {}
            self.jpki_cert_subject_cn = subject_native.get("common_name")
            self.jpki_reverified = True
            self.jpki_status_label.text = self._jpki_status_text()
            self.status.text = "カードの確認に成功しました"
        except jpki_mod.JpkiPinError as e:
            self.status.text = (
                f"PIN が誤っています (残り {e.attempts_remaining} 回)"
            )
        except jpki_mod.JpkiCardLockedError:
            self.status.text = (
                "署名用 PIN がロックされました。市区町村窓口で解除してください"
            )
        except jpki_mod.JpkiError as e:
            self.status.text = f"カード認証失敗: {e}"
        except Exception as e:
            self.status.text = f"カード確認失敗: {e}"
        finally:
            pin = None
            if signer is not None:
                signer.close()

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
        2. PKCS#12 モードで新規登録または証明書差し替え時はパスワードで
           検証する。マイナンバーカードモードでは事前に「カードを確認」が
           完了している必要がある。
        3. ストアに :meth:`HankoStore.add` または :meth:`HankoStore.update`
           を呼ぶ。
        4. 成功したら ``on_registered`` コールバックを呼んでウィンドウを
           閉じる。
        """
        name = (self.name_input.value or "").strip()
        if not name:
            self.status.text = "名前を入力してください"
            return

        cert_type = self._selected_cert_type()

        if self.editing is None and self.image_path is None:
            self.status.text = "印影画像を選択してください"
            return

        if cert_type == CERT_TYPE_PKCS12:
            cert_path_to_verify: Path | None = None
            verify_message = ""
            if self.editing is None or self.editing.cert_type != CERT_TYPE_PKCS12:
                # 流用できる既存 .p12 が無いため、.p12 の選択を必須にする。
                if self.cert_path is None:
                    self.status.text = "証明書 (.p12) を選択してください"
                    return
                cert_path_to_verify = self.cert_path
                verify_message = (
                    f"{self.cert_path.name} のパスワードを入力してください。"
                )
            elif self.cert_path is not None:
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
                    self.status.text = (
                        "パスワードが正しくないか、証明書を読み取れません"
                    )
                    return
                except Exception as e:
                    self.status.text = f"証明書の検証に失敗: {e}"
                    return
                finally:
                    password = None
        else:
            # JPKI モード: シリアルが必要 (verify ボタンで取得済みのはず)。
            if not self.jpki_cert_serial:
                self.status.text = (
                    "「カードを確認...」ボタンでマイナンバーカードを確認してください"
                )
                return

        size_mm = float(self.size_input.value or 18)
        memo = (self.memo_input.value or "").strip()
        try:
            if self.editing is None:
                if cert_type == CERT_TYPE_PKCS12:
                    self.app.store.add(
                        name=name,
                        size_mm=size_mm,
                        memo=memo,
                        image_src=self.image_path,
                        cert_src=self.cert_path,
                        cert_type=CERT_TYPE_PKCS12,
                    )
                else:
                    self.app.store.add(
                        name=name,
                        size_mm=size_mm,
                        memo=memo,
                        image_src=self.image_path,
                        cert_type=CERT_TYPE_JPKI,
                        jpki_cert_serial=self.jpki_cert_serial,
                        jpki_cert_subject_cn=self.jpki_cert_subject_cn,
                    )
            else:
                update_kwargs: dict = dict(
                    name=name,
                    size_mm=size_mm,
                    memo=memo,
                    image_src=self.image_path,
                )
                if cert_type != self.editing.cert_type:
                    # 証明書種別が変わったときだけ store に種別変更を伝える。
                    update_kwargs["cert_type"] = cert_type
                if cert_type == CERT_TYPE_PKCS12:
                    if self.cert_path is not None:
                        update_kwargs["cert_src"] = self.cert_path
                else:
                    if self.jpki_reverified:
                        update_kwargs["jpki_cert_serial"] = self.jpki_cert_serial
                        update_kwargs["jpki_cert_subject_cn"] = (
                            self.jpki_cert_subject_cn
                        )
                self.app.store.update(self.editing.id, **update_kwargs)
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
