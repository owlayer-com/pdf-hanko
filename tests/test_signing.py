"""pdfhanko.signing.sign_pdf_with_signer の保存安全性に関するテスト。"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign import signers
from pyhanko.sign.validation import validate_pdf_signature
from pyhanko_certvalidator import ValidationContext

from pdfhanko.signing import SameFileError, load_pkcs12_signer, sign_pdf_with_signer

from .conftest import P12_PASSWORD

BOX = (100, 100, 168, 168)


class _FailingSigner(signers.SimpleSigner):
    """本署名の段階で例外を送出する Signer (失敗時の後始末確認用)。"""

    async def async_sign_raw(self, data, digest_algorithm, dry_run=False):
        if dry_run:
            return await super().async_sign_raw(data, digest_algorithm, dry_run=True)
        raise RuntimeError("署名失敗のシミュレーション")


def _sign(src: Path, dst: Path, hanko: Path, signer: signers.Signer) -> None:
    asyncio.run(
        sign_pdf_with_signer(
            src_pdf=src,
            dst_pdf=dst,
            hanko_image=hanko,
            signer=signer,
            page_index=0,
            box_pdf=BOX,
        ),
    )


@pytest.fixture
def signer(p12_file: Path) -> signers.SimpleSigner:
    return load_pkcs12_signer(p12_file, P12_PASSWORD)


@pytest.fixture
def failing_signer(signer: signers.SimpleSigner) -> _FailingSigner:
    return _FailingSigner(
        signing_cert=signer.signing_cert,
        signing_key=signer.signing_key,
        cert_registry=signer.cert_registry,
    )


def _leftover_temps(directory: Path) -> list[Path]:
    return list(directory.glob(".pdfhanko-*.tmp"))


class TestSameFileRejected:
    def test_same_path(self, sample_pdf: Path, hanko_png: Path, signer) -> None:
        original = sample_pdf.read_bytes()
        with pytest.raises(SameFileError):
            _sign(sample_pdf, sample_pdf, hanko_png, signer)
        assert sample_pdf.read_bytes() == original

    def test_hardlink(self, sample_pdf: Path, hanko_png: Path, signer, tmp_path: Path) -> None:
        original = sample_pdf.read_bytes()
        dst = tmp_path / "hardlink.pdf"
        os.link(sample_pdf, dst)
        with pytest.raises(SameFileError):
            _sign(sample_pdf, dst, hanko_png, signer)
        assert sample_pdf.read_bytes() == original

    def test_symlink(self, sample_pdf: Path, hanko_png: Path, signer, tmp_path: Path) -> None:
        original = sample_pdf.read_bytes()
        dst = tmp_path / "symlink.pdf"
        dst.symlink_to(sample_pdf)
        with pytest.raises(SameFileError):
            _sign(sample_pdf, dst, hanko_png, signer)
        assert sample_pdf.read_bytes() == original
        assert dst.is_symlink()


class TestSigningFailure:
    def test_no_output_created(
        self, sample_pdf: Path, hanko_png: Path, failing_signer, tmp_path: Path,
    ) -> None:
        dst = tmp_path / "out.pdf"
        with pytest.raises(RuntimeError):
            _sign(sample_pdf, dst, hanko_png, failing_signer)
        assert not dst.exists()
        assert _leftover_temps(tmp_path) == []

    def test_existing_output_untouched(
        self, sample_pdf: Path, hanko_png: Path, failing_signer, tmp_path: Path,
    ) -> None:
        dst = tmp_path / "out.pdf"
        dst.write_bytes(b"existing")
        with pytest.raises(RuntimeError):
            _sign(sample_pdf, dst, hanko_png, failing_signer)
        assert dst.read_bytes() == b"existing"
        assert _leftover_temps(tmp_path) == []


class TestSigningSuccess:
    def _assert_signed(self, path: Path) -> None:
        with open(path, "rb") as f:
            sigs = PdfFileReader(f).embedded_signatures
            assert len(sigs) == 1
            # 自己署名のため信頼性 (valid) は問わず、改ざんがないことだけ確認する。
            status = validate_pdf_signature(sigs[0], ValidationContext(allow_fetching=False))
            assert status.intact

    def test_signed_output_is_valid(
        self, sample_pdf: Path, hanko_png: Path, signer, tmp_path: Path,
    ) -> None:
        original = sample_pdf.read_bytes()
        dst = tmp_path / "out_signed.pdf"
        _sign(sample_pdf, dst, hanko_png, signer)
        self._assert_signed(dst)
        assert sample_pdf.read_bytes() == original
        assert _leftover_temps(tmp_path) == []

    def test_overwrite_existing_other_file(
        self, sample_pdf: Path, hanko_png: Path, signer, tmp_path: Path,
    ) -> None:
        dst = tmp_path / "out_signed.pdf"
        dst.write_bytes(b"old content")
        _sign(sample_pdf, dst, hanko_png, signer)
        self._assert_signed(dst)

    def test_symlink_destination(
        self, sample_pdf: Path, hanko_png: Path, signer, tmp_path: Path,
    ) -> None:
        target_dir = tmp_path / "real"
        target_dir.mkdir()
        target = target_dir / "target.pdf"
        target.write_bytes(b"old content")
        link = tmp_path / "link.pdf"
        link.symlink_to(target)

        _sign(sample_pdf, link, hanko_png, signer)

        assert link.is_symlink()
        self._assert_signed(target)
