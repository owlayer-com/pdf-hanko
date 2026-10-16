"""設定画面 (処理量の上限)。

macOS 標準の「PDF Hanko」メニュー →「設定…」(``⌘,``) から開く。
PDF・画像の処理量の上限 (:mod:`pdfhanko.limits`) を変更する。

- 各項目に既定値と推奨上限を表示する。値はすべて
  :data:`pdfhanko.limits.LIMIT_SPECS` から作り、画面とコードでずれないようにする。
- 設定できる値に上限は設けない。推奨上限を超えた値は、その場で警告を表示し、
  保存時に確認ダイアログを 1 回出す (保存は止めない)。
"""
from __future__ import annotations

import asyncio
from decimal import Decimal

import toga
from toga.style.pack import COLUMN, ROW, Pack

from ..limits import LIMIT_SPECS, LimitSpec, ResourceLimits

WARN_COLOR = "#a33"
"""推奨上限を超えたときの警告文の色。"""


class _LimitRow:
    """上限 1 項目分の入力欄・説明・警告をまとめた行。"""

    def __init__(self, spec: LimitSpec, value: int, on_change) -> None:
        self.spec = spec
        self.input = toga.NumberInput(
            value=value, min=1, step=1, on_change=on_change, style=Pack(width=110),
        )
        self.warning = toga.Label("", style=Pack(margin=(2, 0, 0, 0), color=WARN_COLOR))
        self.box = toga.Box(
            style=Pack(direction=COLUMN, margin=(0, 0, 12, 0)),
            children=[
                toga.Box(
                    style=Pack(direction=ROW, align_items="center"),
                    children=[
                        toga.Label(spec.label, style=Pack(width=200)),
                        self.input,
                        toga.Label(spec.unit, style=Pack(margin=(0, 0, 0, 6))),
                    ],
                ),
                toga.Label(
                    f"既定値 {spec.format(spec.default)} ／ "
                    f"推奨上限 {spec.format(spec.recommended_max)}",
                    style=Pack(margin=(2, 0, 0, 0), color="#666"),
                ),
                self.warning,
            ],
        )

    def value(self) -> int | None:
        """入力値を整数で返す。空欄・1 未満・小数のときは ``None``。"""
        v = self.input.value
        if v is None:
            return None
        v = Decimal(v)
        if v < 1 or v != v.to_integral_value():
            return None
        return int(v)

    def update_warning(self) -> None:
        """入力値に応じて警告文を更新する。"""
        v = self.value()
        if v is None:
            self.warning.text = "1 以上の整数を入力してください。"
        elif v > self.spec.recommended_max:
            self.warning.text = f"⚠ 推奨上限を超えています。{self.spec.description}"
        else:
            self.warning.text = ""


async def edit_resource_limits(
    parent: toga.Window, current: ResourceLimits,
) -> ResourceLimits | None:
    """処理量の上限を編集するモーダルを表示する。

    Args:
        parent: 親ウィンドウ。
        current: 現在の上限。

    Returns:
        「保存」された新しい上限。キャンセルされた場合は ``None``。
    """
    loop = asyncio.get_event_loop()
    fut: asyncio.Future[ResourceLimits | None] = loop.create_future()
    modal = toga.Window(title="設定", size=(560, 620))

    status = toga.Label("", style=Pack(margin=(0, 0, 8, 0), color=WARN_COLOR))
    rows: list[_LimitRow] = []

    def _on_input_change(widget) -> None:
        for row in rows:
            if row.input is widget:
                row.update_warning()

    for spec in LIMIT_SPECS:
        rows.append(_LimitRow(spec, getattr(current, spec.key), _on_input_change))
    for row in rows:
        row.update_warning()

    def _resolve(value: ResourceLimits | None) -> None:
        if not fut.done():
            fut.set_result(value)
        modal.close()

    def _on_reset(widget) -> None:
        for row in rows:
            row.input.value = row.spec.default
            row.update_warning()
        status.text = ""

    async def _on_save(widget) -> None:
        values: dict[str, int] = {}
        for row in rows:
            v = row.value()
            if v is None:
                status.text = f"「{row.spec.label}」には 1 以上の整数を入力してください。"
                return
            values[row.spec.key] = v
        limits = ResourceLimits(**values)

        exceeded = [
            row.spec for row in rows if row.spec.key in limits.exceeds_recommended()
        ]
        if exceeded:
            lines = "\n".join(
                f"・{spec.label}: {spec.format(values[spec.key])}"
                f"（推奨上限 {spec.format(spec.recommended_max)}）"
                for spec in exceeded
            )
            ok = await modal.dialog(
                toga.ConfirmDialog(
                    "推奨上限を超えています",
                    f"次の項目が推奨上限を超えています。\n{lines}\n\n"
                    "大きすぎるファイルを開いたときに、メモリ不足でアプリが停止する"
                    "おそれがあります。このまま保存しますか？",
                )
            )
            if not ok:
                return
        _resolve(limits)

    def _on_cancel(widget) -> None:
        _resolve(None)

    def _on_close(window: toga.Window, **_) -> bool:
        if not fut.done():
            fut.set_result(None)
        return True

    modal.on_close = _on_close
    modal.content = toga.ScrollContainer(
        horizontal=False,
        content=toga.Box(
            style=Pack(direction=COLUMN, margin=16),
            children=[
                toga.Label("処理量の上限", style=Pack(font_weight="bold", margin=(0, 0, 4, 0))),
                toga.Label(
                    "大きすぎるファイルや悪意のある PDF で、アプリが固まったり\n"
                    "メモリを使い切ったりするのを防ぎます。",
                    style=Pack(margin=(0, 0, 16, 0), color="#444"),
                ),
                *[row.box for row in rows],
                status,
                toga.Box(
                    style=Pack(direction=ROW, margin=(8, 0, 0, 0)),
                    children=[
                        toga.Button("既定値に戻す", on_press=_on_reset, style=Pack(margin=4)),
                        toga.Box(style=Pack(flex=1)),
                        toga.Button("キャンセル", on_press=_on_cancel, style=Pack(margin=4)),
                        toga.Button("保存", on_press=_on_save, style=Pack(margin=4)),
                    ],
                ),
            ],
        ),
    )
    parent.app.windows.add(modal)
    modal.show()
    return await fut
