"""HankoStore / AppSettings / ログのファイル権限に関するテスト。"""
from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

import pytest

from pdfhanko.fileutil import UnsafePathError
from pdfhanko.logging_config import PrivateRotatingFileHandler
from pdfhanko.settings import AppSettings
from pdfhanko.storage import CERT_TYPE_JPKI, HankoStore


def _mode(path: Path) -> int:
    return stat.S_IMODE(os.lstat(path).st_mode)


@pytest.fixture(autouse=True)
def umask_022():
    """macOS の既定と同じ umask で、権限が明示的に設定されることを確認する。"""
    old = os.umask(0o022)
    try:
        yield
    finally:
        os.umask(old)


@pytest.fixture
def base_dir(tmp_path: Path) -> Path:
    return tmp_path / "PdfHanko"


def _assert_private_tree(base: Path) -> None:
    for dirpath, dirnames, filenames in os.walk(base):
        assert _mode(Path(dirpath)) == 0o700, dirpath
        for name in filenames:
            assert _mode(Path(dirpath) / name) == 0o600, name


class TestHankoStore:
    def test_add_pkcs12(self, base_dir: Path, hanko_png: Path, p12_file: Path) -> None:
        p12_file.chmod(0o644)
        store = HankoStore(base_dir=base_dir)
        store.load()
        hanko = store.add("テスト", 24.0, "", hanko_png, p12_file)

        assert hanko.cert_path(base_dir).read_bytes() == p12_file.read_bytes()
        _assert_private_tree(base_dir)

    def test_add_jpki(self, base_dir: Path, hanko_png: Path) -> None:
        store = HankoStore(base_dir=base_dir)
        store.load()
        store.add(
            "カード", 24.0, "", hanko_png,
            cert_type=CERT_TYPE_JPKI, jpki_cert_serial="ABC123",
        )
        _assert_private_tree(base_dir)

    def test_update_cert_and_image(
        self, base_dir: Path, hanko_png: Path, p12_file: Path,
    ) -> None:
        store = HankoStore(base_dir=base_dir)
        store.load()
        hanko = store.add(
            "カード", 24.0, "", hanko_png,
            cert_type=CERT_TYPE_JPKI, jpki_cert_serial="ABC123",
        )
        p12_file.chmod(0o755)
        store.update(
            hanko.id, image_src=hanko_png, cert_src=p12_file, cert_type="pkcs12",
        )
        _assert_private_tree(base_dir)

    def test_load_migrates_legacy_permissions(
        self, base_dir: Path, hanko_png: Path, p12_file: Path,
    ) -> None:
        store = HankoStore(base_dir=base_dir)
        store.load()
        store.add("テスト", 24.0, "", hanko_png, p12_file)

        # v0.3.0 相当の権限に戻す。
        for dirpath, dirnames, filenames in os.walk(base_dir):
            Path(dirpath).chmod(0o755)
            for name in filenames:
                (Path(dirpath) / name).chmod(0o644)

        reloaded = HankoStore(base_dir=base_dir)
        reloaded.load()
        assert len(reloaded.hankos) == 1
        _assert_private_tree(base_dir)


    def test_symlinked_base_dir_is_allowed(
        self, tmp_path: Path, hanko_png: Path, p12_file: Path,
    ) -> None:
        real = tmp_path / "elsewhere"
        real.mkdir()
        link = tmp_path / "PdfHanko"
        link.symlink_to(real)

        store = HankoStore(base_dir=link)
        store.load()
        store.add("テスト", 24.0, "", hanko_png, p12_file)

        reloaded = HankoStore(base_dir=link)
        reloaded.load()
        assert len(reloaded.hankos) == 1
        assert link.is_symlink()
        _assert_private_tree(real)

    def test_symlinked_hanko_dir_is_rejected(
        self, base_dir: Path, tmp_path: Path, hanko_png: Path, p12_file: Path,
    ) -> None:
        store = HankoStore(base_dir=base_dir)
        store.load()
        outside = tmp_path / "outside"
        outside.mkdir()
        (base_dir / "hankos").symlink_to(outside)
        with pytest.raises(UnsafePathError):
            store.add("テスト", 24.0, "", hanko_png, p12_file)


class TestAppSettings:
    def test_save_is_private(self, base_dir: Path) -> None:
        settings = AppSettings(base_dir=base_dir)
        settings.load()
        settings.show_field = True
        settings.save()

        assert _mode(base_dir) == 0o700
        assert _mode(settings.path) == 0o600

        reloaded = AppSettings(base_dir=base_dir)
        reloaded.load()
        assert reloaded.show_field is True


class TestPrivateRotatingFileHandler:
    def test_log_files_are_private(self, tmp_path: Path) -> None:
        log_path = tmp_path / "pdfhanko.log"
        handler = PrivateRotatingFileHandler(
            log_path, maxBytes=200, backupCount=2, encoding="utf-8",
        )
        logger = logging.getLogger("pdfhanko.test.private_log")
        logger.propagate = False
        logger.addHandler(handler)
        try:
            for i in range(20):
                logger.warning("message %d %s", i, "x" * 40)
        finally:
            logger.removeHandler(handler)
            handler.close()

        files = sorted(tmp_path.glob("pdfhanko.log*"))
        # ローテーションが発生し、新しく作られたファイルも 0600 であること。
        assert len(files) >= 2
        for f in files:
            assert _mode(f) == 0o600, f.name
