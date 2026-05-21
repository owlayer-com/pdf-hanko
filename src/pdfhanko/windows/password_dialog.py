"""PKCS#12 復号用のパスワード入力モーダル。

Toga の標準ダイアログ群には PasswordInput 付きのものが無いため、
自前で簡易モーダルを構築している。
"""
from __future__ import annotations

import asyncio

import toga
from toga.style.pack import COLUMN, ROW, Pack


async def prompt_password(parent: toga.Window, message: str) -> str | None:
    """パスワード入力モーダルを表示し、入力された文字列を返す。

    OK ボタン押下 / Enter キー押下 / キャンセル / ウィンドウクローズに対応する。
    入力値はメモリ上のみで扱う。呼び出し側は使い終わったら参照をクリアする
    こと。

    Args:
        parent: モーダルを所属させる親ウィンドウ。
        message: 入力欄の上に表示する案内文。

    Returns:
        入力されたパスワード文字列。キャンセルされた場合は ``None``。
    """
    loop = asyncio.get_event_loop()
    fut: asyncio.Future[str | None] = loop.create_future()
    modal = toga.Window(title="パスワード入力", size=(420, 180))

    status = toga.Label("", style=Pack(margin=(0, 8), color="#a33"))

    def _resolve(value: str | None) -> None:
        if not fut.done():
            fut.set_result(value)
        modal.close()

    def _ok(widget) -> None:
        if not input_widget.value:
            status.text = "パスワードを入力してください"
            return
        _resolve(input_widget.value)

    def _cancel(widget: toga.Button) -> None:
        _resolve(None)

    def _on_close(window: toga.Window, **_) -> bool:
        if not fut.done():
            fut.set_result(None)
        return True

    input_widget = toga.PasswordInput(
        on_confirm=_ok,
        style=Pack(flex=1, margin=8),
    )

    modal.on_close = _on_close
    modal.content = toga.Box(
        style=Pack(direction=COLUMN, margin=12),
        children=[
            toga.Label(message, style=Pack(margin=(0, 0, 8, 0))),
            input_widget,
            status,
            toga.Box(
                style=Pack(direction=ROW, margin_top=8),
                children=[
                    toga.Button("キャンセル", on_press=_cancel, style=Pack(margin=4)),
                    toga.Button("OK", on_press=_ok, style=Pack(margin=4)),
                ],
            ),
        ],
    )
    parent.app.windows.add(modal)
    modal.show()
    return await fut
