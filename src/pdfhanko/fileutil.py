"""ファイル操作の安全化ユーティリティ。

保存先へ直接書き込むと、書き込み途中の失敗で不完全なファイルが残ったり、
入力と同一のファイルを保存先にした場合に入力が切り詰められたりする。
本モジュールは「同一ファイル判定」と「一時ファイル経由の原子的な置換」を
提供し、これらを防ぐ。
"""
from __future__ import annotations

import os
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator


def is_same_file(a: Path, b: Path) -> bool:
    """2 つのパスがファイルシステム上の同一ファイルを指すか判定する。

    ``os.path.samefile`` (st_dev / st_ino の比較) を使うため、パス文字列が
    異なるハードリンクやシンボリックリンク経由の同一ファイルも検出できる。

    Args:
        a: 比較対象のパス。
        b: 比較対象のパス。

    Returns:
        同一ファイルなら ``True``。どちらかが存在しない場合は ``False``。
    """
    try:
        return os.path.samefile(a, b)
    except FileNotFoundError:
        return False


def _current_umask() -> int:
    """プロセスの現在の umask を返す (値は変更しない)。"""
    mask = os.umask(0)
    os.umask(mask)
    return mask


@contextmanager
def atomic_write(dst: Path, mode: int | None = None) -> Iterator[BinaryIO]:
    """一時ファイルに書き込み、成功時のみ ``dst`` を置き換える。

    一時ファイルは置換先と同じディレクトリに ``mkstemp`` (``O_EXCL``、
    ``0600``) で作成し、ブロックを正常に抜けたら ``fsync`` → 権限設定 →
    ``os.replace`` の順に確定する。ブロック内で例外が発生した場合は一時
    ファイルを削除し、既存の ``dst`` には触れない。

    ``dst`` がシンボリックリンクの場合はリンク先を置換対象とし、リンク
    自体は通常ファイルで置き換えない。

    Args:
        dst: 最終的な保存先。
        mode: 確定後のファイル権限。``None`` のときは既存の ``dst`` の権限を
            引き継ぎ、``dst`` が存在しなければ ``0o666 & ~umask`` とする。

    Yields:
        書き込み用のバイナリファイルオブジェクト。
    """
    target = Path(os.path.realpath(dst))
    if mode is None:
        try:
            mode = stat.S_IMODE(os.stat(target).st_mode)
        except FileNotFoundError:
            mode = 0o666 & ~_current_umask()

    fd, tmp_name = tempfile.mkstemp(
        dir=target.parent, prefix=".pdfhanko-", suffix=".tmp",
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            yield f
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
