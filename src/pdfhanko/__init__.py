"""PDF Hanko - 日本のハンコ文化に特化した macOS 向け PDF 電子署名アプリ。

バージョンは pyproject.toml の `[project]` セクションを source of truth とし、
インストール済みパッケージのメタデータから取得する。開発時 (editable
install) でもパッケージング後の .app バンドルでも一貫した値が得られる。
"""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    __version__: str = _pkg_version("pdfhanko")
except PackageNotFoundError:
    # パッケージとしてインストールされていない場合のフォールバック
    __version__ = "0.0.0+unknown"
