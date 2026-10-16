"""pdfhanko.fileutil のテスト。"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from pdfhanko.fileutil import (
    UnsafePathError,
    atomic_write,
    copy_private_file,
    ensure_private_dir,
    fix_private_permissions,
    is_same_file,
)


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


def _mode(path: Path) -> int:
    return stat.S_IMODE(os.lstat(path).st_mode)


@pytest.fixture
def umask_022():
    old = os.umask(0o022)
    try:
        yield
    finally:
        os.umask(old)


class TestEnsurePrivateDir:
    def test_creates_with_0700(self, tmp_path: Path, umask_022) -> None:
        d = tmp_path / "app"
        ensure_private_dir(d)
        assert d.is_dir()
        assert _mode(d) == 0o700

    def test_tightens_existing(self, tmp_path: Path) -> None:
        d = tmp_path / "app"
        d.mkdir()
        d.chmod(0o755)
        ensure_private_dir(d)
        assert _mode(d) == 0o700

    def test_rejects_symlink(self, tmp_path: Path) -> None:
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        link.symlink_to(real)
        with pytest.raises(UnsafePathError):
            ensure_private_dir(link)

    def test_rejects_regular_file(self, tmp_path: Path) -> None:
        f = tmp_path / "file"
        f.write_bytes(b"x")
        with pytest.raises(UnsafePathError):
            ensure_private_dir(f)

    def test_allow_symlink_warns_and_uses_target(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    ) -> None:
        real = tmp_path / "real"
        real.mkdir()
        real.chmod(0o755)
        link = tmp_path / "link"
        link.symlink_to(real)

        with caplog.at_level("WARNING", logger="pdfhanko.fileutil"):
            ensure_private_dir(link, allow_symlink=True)
            # 2 回目は警告を重複させない。
            ensure_private_dir(link, allow_symlink=True)

        assert link.is_symlink()
        assert _mode(real) == 0o700
        warnings = [r for r in caplog.records if "シンボリックリンク" in r.getMessage()]
        assert len(warnings) == 1

    def test_allow_symlink_rejects_dangling(self, tmp_path: Path) -> None:
        link = tmp_path / "link"
        link.symlink_to(tmp_path / "missing")
        with pytest.raises(UnsafePathError):
            ensure_private_dir(link, allow_symlink=True)

    def test_allow_symlink_rejects_link_to_file(self, tmp_path: Path) -> None:
        f = tmp_path / "file"
        f.write_bytes(b"x")
        link = tmp_path / "link"
        link.symlink_to(f)
        with pytest.raises(UnsafePathError):
            ensure_private_dir(link, allow_symlink=True)


class TestCopyPrivateFile:
    def test_content_and_mode(self, tmp_path: Path, umask_022) -> None:
        src = tmp_path / "src.p12"
        src.write_bytes(b"secret")
        src.chmod(0o755)
        dst = tmp_path / "dst.p12"
        copy_private_file(src, dst)
        assert dst.read_bytes() == b"secret"
        assert _mode(dst) == 0o600

    @pytest.mark.skipif(
        sys.platform != "darwin" or shutil.which("xattr") is None,
        reason="macOS の xattr コマンドが必要",
    )
    def test_does_not_copy_quarantine(self, tmp_path: Path) -> None:
        src = tmp_path / "src.p12"
        src.write_bytes(b"secret")
        subprocess.run(
            ["xattr", "-w", "com.apple.quarantine", "0081;00000000;Test;", str(src)],
            check=True,
        )
        dst = tmp_path / "dst.p12"
        copy_private_file(src, dst)
        attrs = subprocess.run(
            ["xattr", str(dst)], check=True, capture_output=True, text=True,
        ).stdout
        assert "com.apple.quarantine" not in attrs


class TestFixPrivatePermissions:
    def _make_legacy_tree(self, root: Path) -> dict[str, Path]:
        """v0.3.0 相当の広い権限のツリーを作る。"""
        hanko_dir = root / "hankos" / ("0" * 32)
        hanko_dir.mkdir(parents=True)
        paths = {
            "root": root,
            "hankos": root / "hankos",
            "hanko_dir": hanko_dir,
            "index": root / "hankos.json",
            "cert_644": hanko_dir / "cert.p12",
            "cert_700": root / "hankos" / "other.p12",
            "readonly": root / "readonly.txt",
        }
        for key in ("index", "cert_644", "cert_700", "readonly"):
            paths[key].write_bytes(b"x")
        for key in ("root", "hankos", "hanko_dir"):
            paths[key].chmod(0o755)
        paths["index"].chmod(0o644)
        paths["cert_644"].chmod(0o644)
        paths["cert_700"].chmod(0o700)
        paths["readonly"].chmod(0o400)
        return paths

    def test_tightens_legacy_tree(self, tmp_path: Path) -> None:
        paths = self._make_legacy_tree(tmp_path / "PdfHanko")
        changed = fix_private_permissions(paths["root"])
        assert changed == 6
        for key in ("root", "hankos", "hanko_dir"):
            assert _mode(paths[key]) == 0o700, key
        for key in ("index", "cert_644", "cert_700"):
            assert _mode(paths[key]) == 0o600, key
        # 権限を広げる変更はしない。
        assert _mode(paths["readonly"]) == 0o400

    def test_idempotent(self, tmp_path: Path) -> None:
        paths = self._make_legacy_tree(tmp_path / "PdfHanko")
        fix_private_permissions(paths["root"])
        assert fix_private_permissions(paths["root"]) == 0

    def test_does_not_follow_symlinks(self, tmp_path: Path) -> None:
        root = tmp_path / "PdfHanko"
        root.mkdir(mode=0o700)
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        outside_dir.chmod(0o755)
        outside_file = outside_dir / "file.txt"
        outside_file.write_bytes(b"x")
        outside_file.chmod(0o644)
        (root / "link_dir").symlink_to(outside_dir)
        (root / "link_file").symlink_to(outside_file)

        fix_private_permissions(root)

        assert _mode(outside_dir) == 0o755
        assert _mode(outside_file) == 0o644

    def test_symlink_root_fixes_target(self, tmp_path: Path) -> None:
        real = tmp_path / "real"
        real.mkdir()
        real.chmod(0o755)
        (real / "hankos.json").write_bytes(b"[]")
        (real / "hankos.json").chmod(0o644)
        link = tmp_path / "PdfHanko"
        link.symlink_to(real)

        assert fix_private_permissions(link) == 2
        assert _mode(real) == 0o700
        assert _mode(real / "hankos.json") == 0o600

    def test_missing_root(self, tmp_path: Path) -> None:
        assert fix_private_permissions(tmp_path / "missing") == 0

    def test_chmod_failure_is_not_fatal(self, tmp_path: Path, monkeypatch) -> None:
        root = tmp_path / "PdfHanko"
        root.mkdir()
        root.chmod(0o755)

        def _deny(*args, **kwargs):
            raise PermissionError("denied")

        monkeypatch.setattr(os, "chmod", _deny)
        assert fix_private_permissions(root) == 0
