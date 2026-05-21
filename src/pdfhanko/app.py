"""アプリケーション本体のエントリポイント。

:class:`PdfHankoApp` が Toga の :class:`toga.App` を継承し、起動時に
:class:`pdfhanko.storage.HankoStore` を初期化してメインウィンドウを表示する。
"""
from __future__ import annotations

import toga

from .storage import HankoStore
from .windows.main_window import MainWindow


class PdfHankoApp(toga.App):
    """PDF Hanko アプリケーション。

    Attributes:
        store: ハンコ永続化ストア。``startup`` 内で初期化される。
    """

    store: HankoStore

    def startup(self) -> None:
        """Toga フレームワークから呼ばれる起動フック。

        ハンコストアを読み込み、メインウィンドウを構築して表示する。
        """
        self.store = HankoStore()
        self.store.load()

        self.main_window_obj = MainWindow(self)
        self.main_window = self.main_window_obj.window
        self.main_window.show()


def main() -> PdfHankoApp:
    """:class:`PdfHankoApp` を生成して返すファクトリ関数。

    Briefcase と ``python -m pdfhanko`` の両方から共通のエントリポイント
    として利用される。

    Returns:
        生成された :class:`PdfHankoApp` インスタンス。
    """
    # app_id は pyproject.toml [tool.briefcase] の bundle + app_name と一致させる
    return PdfHankoApp(
        formal_name="PDF Hanko",
        app_id="com.owlayer.pdfhanko",
        app_name="pdfhanko",
    )
