"""pdfhanko.fileutil のテスト。"""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from pdfhanko.fileutil import atomic_write, is_same_file


def _leftover_temps(directory: Path) -> list[Path]:
    return list(directory.glob(".pdfhanko-*.tmp"))


class TestIsSameFile:
    def test_same_path(self, tmp_path: Path) -> None:
        a = tmp_path / "a.pdf"
        a.write_bytes(b"x")
        assert is_same_file(a, a)

    def test_hardlink(self, tmp_path: Path) -> None:
        a = tmp_path / "a.pdf"
        a.write_bytes(b"x")
        b = tmp_path / "b.pdf"
        os.link(a, b)
        assert is_same_file(a, b)

    def test_symlink(self, tmp_path: Path) -> None:
        a = tmp_path / "a.pdf"
        a.write_bytes(b"x")
        b = tmp_path / "b.pdf"
        b.symlink_to(a)
        assert is_same_file(a, b)

    def test_relative_path_variant(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        a = tmp_path / "a.pdf"
        a.write_bytes(b"x")
        assert is_same_file(a, sub / ".." / "a.pdf")

    def test_different_files(self, tmp_path: Path) -> None:
        a = tmp_path / "a.pdf"
        b = tmp_path / "b.pdf"
        a.write_bytes(b"x")
        b.write_bytes(b"x")
        assert not is_same_file(a, b)

    def test_missing_destination(self, tmp_path: Path) -> None:
        a = tmp_path / "a.pdf"
        a.write_bytes(b"x")
        assert not is_same_file(a, tmp_path / "missing.pdf")


class TestAtomicWrite:
    def test_creates_new_file(self, tmp_path: Path) -> None:
        dst = tmp_path / "out.pdf"
        with atomic_write(dst) as f:
            f.write(b"hello")
        assert dst.read_bytes() == b"hello"
        assert _leftover_temps(tmp_path) == []

    def test_new_file_mode_follows_umask(self, tmp_path: Path) -> None:
        old = os.umask(0o027)
        try:
            dst = tmp_path / "out.pdf"
            with atomic_write(dst) as f:
                f.write(b"x")
        finally:
            os.umask(old)
        assert stat.S_IMODE(dst.stat().st_mode) == 0o640

    def test_keeps_existing_mode(self, tmp_path: Path) -> None:
        dst = tmp_path / "out.pdf"
        dst.write_bytes(b"old")
        dst.chmod(0o604)
        with atomic_write(dst) as f:
            f.write(b"new")
        assert dst.read_bytes() == b"new"
        assert stat.S_IMODE(dst.stat().st_mode) == 0o604

    def test_explicit_mode(self, tmp_path: Path) -> None:
        dst = tmp_path / "out.pdf"
        with atomic_write(dst, mode=0o600) as f:
            f.write(b"x")
        assert stat.S_IMODE(dst.stat().st_mode) == 0o600

    def test_failure_keeps_existing_file(self, tmp_path: Path) -> None:
        dst = tmp_path / "out.pdf"
        dst.write_bytes(b"original")
        with pytest.raises(RuntimeError):
            with atomic_write(dst) as f:
                f.write(b"partial")
                raise RuntimeError("boom")
        assert dst.read_bytes() == b"original"
        assert _leftover_temps(tmp_path) == []

    def test_failure_creates_nothing(self, tmp_path: Path) -> None:
        dst = tmp_path / "out.pdf"
        with pytest.raises(RuntimeError):
            with atomic_write(dst) as f:
                f.write(b"partial")
                raise RuntimeError("boom")
        assert not dst.exists()
        assert _leftover_temps(tmp_path) == []

    def test_symlink_destination_updates_target(self, tmp_path: Path) -> None:
        real_dir = tmp_path / "real"
        real_dir.mkdir()
        target = real_dir / "target.pdf"
        target.write_bytes(b"old")
        link = tmp_path / "link.pdf"
        link.symlink_to(target)

        with atomic_write(link) as f:
            f.write(b"new")

        assert link.is_symlink()
        assert target.read_bytes() == b"new"
        # 一時ファイルはリンク先と同じディレクトリに作られ、残らない。
        assert _leftover_temps(real_dir) == []
        assert _leftover_temps(tmp_path) == []
