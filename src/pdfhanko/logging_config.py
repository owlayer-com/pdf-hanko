"""アプリ全体のロギング設定。

ファイル ``~/Library/Logs/PdfHanko/pdfhanko.log`` に WARNING 以上を書き出し、
未捕捉例外をハンドラ経由でファイルに記録する。ユーザーがバグ報告を行う際の
1 次情報として利用する想定。

Briefcase の Mac バンドル経由で起動された場合と、``uv run python -m pdfhanko``
の場合の両方で動作する。
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path.home() / "Library" / "Logs" / "PdfHanko"
"""ログ出力先ディレクトリ。macOS の Console.app からも閲覧可能。"""

LOG_FILE_NAME = "pdfhanko.log"
"""ログファイル名。ローテーションすると ``pdfhanko.log.1`` 等が並ぶ。"""

MAX_BYTES = 1_000_000
"""1 ファイルあたりの最大サイズ (約 1 MB)。これを超えたらローテーション。"""

BACKUP_COUNT = 3
"""保持する世代数。"""

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def setup_logging(level: int = logging.INFO) -> None:
    """アプリ起動時に 1 回だけ呼ぶロギング初期化処理。

    Args:
        level: アプリ自身のロガーで採用するレベル。デフォルトは INFO。

    Side Effects:
        - ``LOG_DIR`` を作成（存在しない場合）。
        - ルートロガーに :class:`RotatingFileHandler` を 1 つ追加。
        - ``pdfhanko`` 配下のロガーを ``level`` に設定。
        - PyHanko / pypdfium2 など外部ライブラリの logger は WARNING 以上に
          抑えてログファイルが膨らむのを防ぐ。
        - 未捕捉例外を ``sys.excepthook`` 経由で記録するようにする。
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / LOG_FILE_NAME

    handler = RotatingFileHandler(
        log_path,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    handler.setLevel(logging.WARNING)

    root_logger = logging.getLogger()
    # 既に同種のハンドラが付いている場合は重複追加しない (再 import 対策)
    if not any(isinstance(h, RotatingFileHandler) for h in root_logger.handlers):
        root_logger.addHandler(handler)
    # ルートは WARNING ベースにしておき、アプリ自身は別途 INFO に上げる
    root_logger.setLevel(logging.WARNING)

    logging.getLogger("pdfhanko").setLevel(level)

    # 外部ライブラリの logger は WARNING 以上に抑える
    # PyHanko の DEBUG/INFO は冗長で、本アプリでは追跡対象外
    for noisy in ("pyhanko", "pyhanko_certvalidator", "asyncio", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    sys.excepthook = _log_uncaught_exception


def _log_uncaught_exception(exc_type, exc_value, exc_traceback) -> None:
    """``sys.excepthook`` にセットする未捕捉例外ハンドラ。

    KeyboardInterrupt は通常の終了と区別するためログに残さず再送する。
    それ以外は CRITICAL レベルでスタックトレースつきで記録する。
    """
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logging.getLogger("pdfhanko").critical(
        "Uncaught exception",
        exc_info=(exc_type, exc_value, exc_traceback),
    )
