"""アプリケーション本体のエントリポイント。

:class:`PdfHankoApp` が Toga の :class:`toga.App` を継承し、起動時に
:class:`pdfhanko.storage.HankoStore` を初期化してメインウィンドウを表示する。
"""
from __future__ import annotations

import asyncio
import logging
import webbrowser

import toga

from . import __version__
from .logging_config import LOG_DIR, setup_logging
from .settings import AppSettings
from .storage import HankoStore
from .windows.main_window import MainWindow

SHOW_FIELD_MENU_LABEL = "pyHanko --field 表示"
"""「表示」メニューに置く --field トグル項目のベースラベル。"""

CHECK_MARK_PREFIX = "✓ "
"""ON 状態を示すラベル先頭の印。Toga には標準のチェック式メニューが無いため
ラベル先頭文字を切り替えて代用する。"""


def _disable_window_tabbing() -> None:
    """macOS の View メニューに自動挿入される『Show Tab Bar』を抑制する。

    Cocoa は ``NSWindow.allowsAutomaticWindowTabbing`` が True (既定) のとき
    View メニューに『Show Tab Bar』『New Tab』等を勝手に挿入する。本アプリは
    ウィンドウタブを使わないため、メインウィンドウを構築する前に False に
    切り替えて挿入自体を止める。

    macOS 以外 (rubicon-objc が無い・NSWindow が無い) の環境では何もしない。
    """
    try:
        from rubicon.objc import ObjCClass

        NSWindow = ObjCClass("NSWindow")
        NSWindow.setAllowsAutomaticWindowTabbing_(False)
    except Exception:
        logger.debug("Window tabbing 抑制に失敗 (非 macOS 環境とみなす)", exc_info=True)

logger = logging.getLogger(__name__)

REPOSITORY_URL = "https://github.com/owlayer-com/pdf-hanko"
"""GitHub リポジトリ URL。About ダイアログやヘルプ動線で使用する。"""

HELP_URL = REPOSITORY_URL + "#readme"
"""ヘルプメニューから開く URL。README の使い方セクションを指す。"""


def _build_about_message() -> str:
    """About ダイアログに表示するメッセージを生成する。

    Returns:
        多行テキスト形式の About 情報。アプリ名・バージョン・著作権・主要
        OSS ライブラリの帰属を含む。
    """
    return (
        f"PDF Hanko v{__version__}\n\n"
        "日本のハンコ文化に特化した、macOS 向け PDF 電子署名アプリ。\n"
        "あらかじめ登録した印影画像と PKCS#12 証明書を用いて、PDF に\n"
        "見た目のハンコと PAdES 準拠の電子署名を同時に付与します。\n\n"
        "Copyright (c) 2026 owlayer-com\n"
        "Licensed under the MIT License.\n\n"
        f"ソースコード: {REPOSITORY_URL}\n\n"
        "本アプリは以下のオープンソースライブラリを利用しています:\n"
        "  • PyHanko (MIT)\n"
        "  • pypdfium2 (Apache 2.0 / BSD-3) / PDFium (BSD-3)\n"
        "  • Toga / BeeWare (BSD-3)\n"
        "  • Pillow (HPND)\n"
        "  • cryptography (Apache 2.0 / BSD)\n\n"
        "ライセンス全文は同梱の NOTICE.md を参照してください。"
    )


class PdfHankoApp(toga.App):
    """PDF Hanko アプリケーション。

    Attributes:
        store: ハンコ永続化ストア。``startup`` 内で初期化される。
        main_window_obj: メインウィンドウのラッパインスタンス。
    """

    store: HankoStore
    settings: AppSettings
    main_window_obj: MainWindow

    def startup(self) -> None:
        """Toga フレームワークから呼ばれる起動フック。

        ハンコストアと設定を読み込み、メインウィンドウを構築して表示する。
        About コマンドのアクションを差し替え、アプリ固有のダイアログを出す。
        """
        # MainWindow 生成前に呼ぶ必要がある。View メニューへの『Show Tab Bar』
        # 自動挿入を抑制する (Cocoa の NSWindow が tabbing を有効にしている時に
        # 自動で項目を追加する挙動)。
        _disable_window_tabbing()

        self.store = HankoStore()
        self.store.load()
        self.settings = AppSettings()
        self.settings.load()

        self.main_window_obj = MainWindow(self)
        self.main_window = self.main_window_obj.window
        self.main_window.show()

        # macOS の標準 "About PDF Hanko" メニュー項目を、自前の
        # ダイアログでオーバーライドする。Toga が自動で挿入する Command の
        # action だけを差し替える形。
        try:
            self.commands[toga.Command.ABOUT].action = self._on_about
        except KeyError:
            # ABOUT コマンドが定義されていないプラットフォームでは無視
            pass

        # 「ヘルプ」メニューに GitHub の README を開く項目を追加する。
        # macOS では Help メニュー配下に自動配置される。
        self.commands.add(
            toga.Command(
                self._on_open_help,
                text="PDF Hanko ヘルプ",
                tooltip="GitHub の README を既定ブラウザで開く",
                group=toga.Group.HELP,
            )
        )

        # 「表示」メニューに pyHanko CLI 引数表示のトグルを追加する。
        self._show_field_command = toga.Command(
            self._on_toggle_show_field,
            text=self._show_field_menu_text(self.settings.show_field),
            tooltip="押印位置を pyHanko CLI の --field 引数形式で表示する",
            group=toga.Group.VIEW,
        )
        self.commands.add(self._show_field_command)

    def _on_about(self, widget) -> None:
        """About ダイアログを表示する (同期ハンドラ)。

        Toga の Command action は同期関数として呼ばれるため、async な
        ``self.dialog()`` は ``asyncio.create_task`` でスケジュールする。
        """
        asyncio.create_task(
            self.dialog(toga.InfoDialog("PDF Hanko について", _build_about_message()))
        )

    def _on_open_help(self, widget) -> None:
        """ヘルプメニュー押下時のハンドラ。既定ブラウザで README を開く。"""
        try:
            webbrowser.open(HELP_URL)
        except Exception:
            logger.exception("ヘルプ URL を開けませんでした: %s", HELP_URL)

    @staticmethod
    def _show_field_menu_text(enabled: bool) -> str:
        """--field 表示メニューのラベル文字列を返す。

        Toga の :class:`toga.Command` には標準のチェック表示が無いため、
        ON 時にはラベル先頭に :data:`CHECK_MARK_PREFIX` を付ける。
        """
        return (CHECK_MARK_PREFIX if enabled else "") + SHOW_FIELD_MENU_LABEL

    def _on_toggle_show_field(self, widget) -> None:
        """「表示」メニューの --field 表示トグル押下時のハンドラ。

        設定値を反転し、永続化したうえで PdfView の表示状態を更新する。
        """
        self.settings.show_field = not self.settings.show_field
        self.settings.save()
        label = self._show_field_menu_text(self.settings.show_field)
        self._show_field_command.text = label
        self._apply_show_field_menu_title(label)
        self.main_window_obj.pdf_view.set_show_field(self.settings.show_field)

    def _apply_show_field_menu_title(self, label: str) -> None:
        """ネイティブ NSMenuItem のタイトルを直接書き換える。

        Toga の :class:`toga.Command` は ``text`` を単なる属性として保持しており、
        書き換えても Cocoa 側の ``NSMenuItem`` の title には反映されない。
        rubicon-objc 経由で ``setTitle_`` を呼んで動的に同期する。

        Args:
            label: 新しいメニューラベル。
        """
        impl = getattr(self._show_field_command, "_impl", None)
        natives = getattr(impl, "native", None) if impl is not None else None
        if not natives:
            return
        for native in natives:
            setter = getattr(native, "setTitle_", None)
            if setter is None:
                continue
            try:
                setter(label)
            except Exception:
                logger.exception("メニューラベルの更新に失敗しました")

    def on_exit(self) -> bool:
        """アプリ終了直前のフック。ネイティブリソースを明示的に解放する。

        Toga / rubicon-objc は Cocoa 側の autorelease pool が drain される際に
        Python コールバック (deallocator) を呼び戻す。Python インタープリタが
        先に shutdown 済みだとここで segfault することがあるため、可能な限り
        終了前に Python 側から native ハンドル (pypdfium2 の PdfDocument 等) を
        明示 close しておく。

        Returns:
            True を返すと終了を許可する。クリーンアップに失敗しても終了を
            止めないよう、例外は内部で握りつぶす。
        """
        try:
            self.main_window_obj.cleanup()
        except Exception:
            pass
        return True


def main() -> PdfHankoApp:
    """:class:`PdfHankoApp` を生成して返すファクトリ関数。

    Briefcase と ``python -m pdfhanko`` の両方から共通のエントリポイント
    として利用される。ロギングは Toga が起動する前に初期化する。

    Returns:
        生成された :class:`PdfHankoApp` インスタンス。
    """
    setup_logging()
    logger.info("PDF Hanko v%s starting (log dir: %s)", __version__, LOG_DIR)
    return PdfHankoApp(
        formal_name="PDF Hanko",
        app_id="com.owlayer.pdfhanko",
        app_name="pdfhanko",
        version=__version__,
    )
