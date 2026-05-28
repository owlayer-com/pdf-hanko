"""マイナンバーカード署名用 PIN 入力モーダル。

PKCS#12 用の :mod:`pdfhanko.windows.password_dialog` と用途を分けている。
理由:

- マイナンバーカードの署名用 PIN は **6〜16 桁英数字**という具体的な制約を持つ。
- 5 回失敗で失効するため、残回数を画面に常時表示してユーザーに警告する必要がある。
- PKCS#12 用ダイアログには無い「カード検出待ち」「リーダー名表示」などの
  付帯情報を載せたい。
"""
from __future__ import annotations

import asyncio

import toga
from toga.style.pack import COLUMN, ROW, Pack

# 残り回数がこの値以下になったら警告色で強調する閾値。
WARN_THRESHOLD = 2


async def prompt_jpki_pin(
    parent: toga.Window,
    message: str,
    attempts_remaining: int | None = None,
) -> str | None:
    """マイナンバーカード署名用 PIN 入力モーダルを表示する。

    Args:
        parent: 親ウィンドウ。
        message: 入力欄の上に表示する案内文 (例: ハンコ名や用途)。
        attempts_remaining: 入力試行前のカード側残回数。``None`` で非表示。
            ``WARN_THRESHOLD`` 以下のとき警告色で強調。

    Returns:
        入力された PIN 文字列。キャンセルされた場合は ``None``。
    """
    loop = asyncio.get_event_loop()
    fut: asyncio.Future[str | None] = loop.create_future()
    modal = toga.Window(title="マイナンバーカード PIN 入力", size=(460, 240))

    status = toga.Label("", style=Pack(margin=(0, 8), color="#a33"))

    def _resolve(value: str | None) -> None:
        if not fut.done():
            fut.set_result(value)
        modal.close()

    def _ok(widget) -> None:
        v = (input_widget.value or "").strip()
        if not v:
            status.text = "PIN を入力してください"
            return
        if not (6 <= len(v) <= 16):
            status.text = "PIN は 6〜16 桁です"
            return
        if not v.isascii() or not v.replace(" ", "").isalnum():
            status.text = "PIN は英数字のみ使用できます"
            return
        _resolve(v)

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

    children: list[toga.Widget] = [
        toga.Label(message, style=Pack(margin=(0, 0, 8, 0))),
    ]
    if attempts_remaining is not None:
        warn = attempts_remaining <= WARN_THRESHOLD
        attempts_label = toga.Label(
            f"署名用 PIN の残り試行回数: {attempts_remaining} 回"
            + ("（残り少ないため、慎重に入力してください）" if warn else ""),
            style=Pack(
                margin=(0, 0, 8, 0),
                color="#a33" if warn else "#444",
            ),
        )
        children.append(attempts_label)

    children.extend(
        [
            input_widget,
            toga.Label(
                "署名用パスワードは 6〜16 桁の英数字です。"
                "英字は大文字小文字どちらでも構いません。",
                style=Pack(margin=(0, 8), color="#666"),
            ),
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

    modal.on_close = _on_close
    modal.content = toga.Box(
        style=Pack(direction=COLUMN, margin=12),
        children=children,
    )
    parent.app.windows.add(modal)
    modal.show()
    return await fut
