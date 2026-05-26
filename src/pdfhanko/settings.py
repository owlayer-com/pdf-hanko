"""アプリケーション設定の永続化レイヤ。

保存先::

    ~/Library/Application Support/PdfHanko/settings.json

ハンコ群 (:mod:`pdfhanko.storage`) とはライフサイクルが別なので、
:class:`HankoStore` には同居させず独立した小さなクラスとして扱う。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .storage import app_data_dir

SETTINGS_FILE_NAME = "settings.json"
"""設定インデックスファイル名。"""


@dataclass(slots=True)
class AppSettings:
    """ユーザー設定をディスクに永続化する小さなリポジトリ。

    Attributes:
        base_dir: 永続化のルートディレクトリ。デフォルトは
            :func:`pdfhanko.storage.app_data_dir`。
        show_field: ``True`` のとき、PDF ビューアの下に pyHanko CLI の
            ``--field`` 引数文字列を表示する。
    """

    base_dir: Path = field(default_factory=app_data_dir)
    show_field: bool = False

    @property
    def path(self) -> Path:
        """設定ファイル ``settings.json`` の絶対パス。"""
        return self.base_dir / SETTINGS_FILE_NAME

    def load(self) -> None:
        """設定ファイルを読み込み、自身の属性を更新する。

        ファイルが存在しない、または JSON として壊れている場合は何も
        変更せず既定値を維持する。未知のキーは無視し、欠落しているキーは
        既定値が使われる。
        """
        self.base_dir.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(data, dict):
            return
        self.show_field = bool(data.get("show_field", self.show_field))

    def save(self) -> None:
        """現在の設定値を JSON で書き出す。"""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        payload = {"show_field": self.show_field}
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
