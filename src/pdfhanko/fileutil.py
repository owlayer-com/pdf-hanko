"""ファイル操作の安全化ユーティリティ。

保存先へ直接書き込むと、書き込み途中の失敗で不完全なファイルが残ったり、
入力と同一のファイルを保存先にした場合に入力が切り詰められたりする。
本モジュールは「同一ファイル判定」と「一時ファイル経由の原子的な置換」を
提供し、これらを防ぐ。

また、PKCS#12 などの機微なデータを置くアプリ専用ディレクトリについて、
所有者のみがアクセスできる権限 (ディレクトリ ``0700``、ファイル ``0600``)
での作成・複製と、既存ファイルの権限修正を提供する。
"""
from __future__ import annotations

import logging
import os
import shutil
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator

logger = logging.getLogger(__name__)

PRIVATE_DIR_MODE = 0o700
"""アプリ専用ディレクトリの権限 (所有者のみ読み書き・移動可)。"""

PRIVATE_FILE_MODE = 0o600
"""アプリ専用ファイルの権限 (所有者のみ読み書き可)。"""


class UnsafePathError(OSError):
    """アプリ専用領域として扱えないパス (シンボリックリンク等) を示す例外。"""


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


_warned_symlink_dirs: set[str] = set()
"""シンボリックリンクの警告を出したパス。保存のたびに警告が重複しないよう、
プロセス内で 1 パスにつき 1 回だけ出す。"""


def ensure_private_dir(path: Path, *, allow_symlink: bool = False) -> None:
    """所有者のみアクセスできるディレクトリを用意する。

    存在しなければ作成し、権限を ``0700`` に設定する。``mkdir`` の mode は
    umask の影響を受けるため、作成後に ``chmod`` で明示的に設定する。
    途中の親ディレクトリも必要に応じて作成するが、権限を設定するのは
    ``path`` 自身のみ (呼び出し側で階層ごとに呼ぶ)。

    Args:
        path: 用意するディレクトリ。
        allow_symlink: ``True`` のとき、``path`` がディレクトリへの
            シンボリックリンクであれば警告ログを残してリンク先を使う
            (リンク先の権限を ``0700`` に設定する)。以前のバージョンで
            ``PdfHanko/`` やログフォルダを別の場所へのリンクにしていた
            利用者との互換性のため、最上位のフォルダでのみ使う。

    Raises:
        UnsafePathError: ``path`` がシンボリックリンク (``allow_symlink``
            が ``False``、またはリンク切れの場合)、またはディレクトリ以外の
            場合。
    """
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        path.mkdir(mode=PRIVATE_DIR_MODE, parents=True, exist_ok=True)
        st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode):
        if not allow_symlink:
            raise UnsafePathError(
                f"シンボリックリンクはアプリ専用ディレクトリに使えません: {path}",
            )
        try:
            st = os.stat(path)
        except FileNotFoundError:
            raise UnsafePathError(f"リンク先が存在しません: {path}") from None
        key = str(path)
        if key not in _warned_symlink_dirs:
            _warned_symlink_dirs.add(key)
            logger.warning(
                "アプリ専用フォルダがシンボリックリンクです。リンク先をそのまま使用します: "
                "%s -> %s",
                path, os.path.realpath(path),
            )
    if not stat.S_ISDIR(st.st_mode):
        raise UnsafePathError(f"ディレクトリではありません: {path}")
    if stat.S_IMODE(st.st_mode) != PRIVATE_DIR_MODE:
        os.chmod(path, PRIVATE_DIR_MODE)


def copy_private_file(src: Path, dst: Path) -> None:
    """ファイルの内容だけを ``0600`` の新しいファイルとして複製する。

    ``shutil.copy2`` と異なり、コピー元の権限・拡張属性 (quarantine 等)・
    ACL は引き継がない。書き込みは :func:`atomic_write` 経由で行う。

    Args:
        src: コピー元。
        dst: コピー先。
    """
    with open(src, "rb") as inf, atomic_write(dst, mode=PRIVATE_FILE_MODE) as outf:
        shutil.copyfileobj(inf, outf)


def fix_private_permissions(root: Path) -> int:
    """``root`` 配下の権限を所有者のみに狭める (既存環境の移行用)。

    以前のバージョンは umask 任せ (``0755`` / ``0644``) やコピー元の権限を
    引き継いでファイルを作成していたため、起動時に本関数で修正する。

    - ディレクトリはグループ・その他の権限を外す (``0755`` → ``0700``)。
    - ファイルはグループ・その他の権限と所有者の実行権限を外す
      (``0644`` → ``0600``、``0700`` → ``0600``)。
    - 権限を広げる変更は行わない (``0400`` は ``0400`` のまま)。
    - シンボリックリンクと、自分が所有していないファイルは変更せず、
      警告ログを残す。
    - ``chmod`` に失敗しても例外は送出せず、警告ログを残して続行する。

    ``root`` 自身がシンボリックリンクの場合はリンク先を走査する
    (:func:`ensure_private_dir` の ``allow_symlink`` と対応)。

    Args:
        root: 走査するディレクトリ。存在しなければ何もしない。

    Returns:
        権限を変更したエントリ数。
    """
    if root.is_symlink():
        root = Path(os.path.realpath(root))
    if not root.is_dir():
        return 0

    uid = os.getuid()
    changed = 0

    def _fix(path: Path, is_dir: bool) -> None:
        nonlocal changed
        try:
            st = os.lstat(path)
        except OSError as e:
            logger.warning("権限を確認できません: %s (%s)", path, e)
            return
        if stat.S_ISLNK(st.st_mode):
            logger.warning("シンボリックリンクのため権限を変更しません: %s", path)
            return
        if st.st_uid != uid:
            logger.warning("所有者が異なるため権限を変更しません: %s", path)
            return
        current = stat.S_IMODE(st.st_mode)
        strip = 0o077 if is_dir else 0o177
        desired = current & ~strip
        if desired == current:
            return
        try:
            os.chmod(path, desired)
        except OSError as e:
            logger.warning("権限を変更できません: %s (%s)", path, e)
            return
        changed += 1

    def _on_walk_error(e: OSError) -> None:
        logger.warning("ディレクトリを走査できません: %s", e)

    _fix(root, is_dir=True)
    for dirpath, dirnames, filenames in os.walk(root, onerror=_on_walk_error):
        base = Path(dirpath)
        # os.walk はシンボリックリンクのディレクトリを dirnames に含めるが
        # 辿らない (followlinks=False)。_fix 側で警告して変更しない。
        for name in dirnames:
            _fix(base / name, is_dir=True)
        for name in filenames:
            _fix(base / name, is_dir=False)

    if changed:
        logger.warning("アプリ専用データの権限を修正しました: %s (%d 件)", root, changed)
    return changed
