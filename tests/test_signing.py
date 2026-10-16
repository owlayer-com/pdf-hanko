"""pdfhanko.signing.sign_pdf_with_signer の保存安全性に関するテスト。"""
from __future__ import annotations

import asyncio
import os
import socket
from pathlib import Path

import pytest
from asn1crypto import algos as asn1_algos
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, utils
from cryptography.hazmat.primitives.serialization import pkcs12
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign import signers
from pyhanko.sign.validation import validate_pdf_signature
from pyhanko_certvalidator import ValidationContext

from pdfhanko.signing import (
    JpkiSigner,
    SameFileError,
    load_pkcs12_signer,
    sign_pdf_with_signer,
)

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
    def _assert_signed(self, path: Path, signer: signers.SimpleSigner) -> None:
        with open(path, "rb") as f:
            sigs = PdfFileReader(f).embedded_signatures
            assert len(sigs) == 1
            # 自己署名証明書を信頼の起点として明示する (OS の信頼リストへの
            # フォールバックは pyhanko-certvalidator 0.32 で非推奨)。
            vc = ValidationContext(trust_roots=[signer.signing_cert], allow_fetching=False)
            status = validate_pdf_signature(sigs[0], vc)
            assert status.intact
            assert status.valid

    def test_signed_output_is_valid(
        self, sample_pdf: Path, hanko_png: Path, signer, tmp_path: Path,
    ) -> None:
        original = sample_pdf.read_bytes()
        dst = tmp_path / "out_signed.pdf"
        _sign(sample_pdf, dst, hanko_png, signer)
        self._assert_signed(dst, signer)
        assert sample_pdf.read_bytes() == original
        assert _leftover_temps(tmp_path) == []

    def test_overwrite_existing_other_file(
        self, sample_pdf: Path, hanko_png: Path, signer, tmp_path: Path,
    ) -> None:
        dst = tmp_path / "out_signed.pdf"
        dst.write_bytes(b"old content")
        _sign(sample_pdf, dst, hanko_png, signer)
        self._assert_signed(dst, signer)

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
        self._assert_signed(target, signer)


class _FakeCardSession:
    """マイナンバーカードの代わりに、PKCS#12 の秘密鍵で署名する偽セッション。

    実カードと同じく DigestInfo (DER) を受け取り、RSA PKCS#1 v1.5 の署名値を返す。
    """

    def __init__(self, private_key) -> None:
        self._key = private_key
        self.closed = False

    def compute_signature(self, digest_info_der: bytes) -> bytes:
        info = asn1_algos.DigestInfo.load(digest_info_der)
        assert info["digest_algorithm"]["algorithm"].native == "sha256"
        return self._key.sign(
            info["digest"].native, padding.PKCS1v15(), utils.Prehashed(hashes.SHA256()),
        )

    def close(self) -> None:
        self.closed = True


class TestJpkiSigner:
    """JpkiSigner (pyHanko の Signer を継承した独自実装) の署名経路のテスト。

    pyHanko の更新で Signer の API が変わった場合に検出するため、カードの
    代わりに偽セッションを使って PDF への署名と検証まで行う。
    """

    def test_sign_and_validate_without_network(
        self, sample_pdf: Path, hanko_png: Path, p12_file: Path, tmp_path: Path,
        monkeypatch,
    ) -> None:
        def _deny_network(*args, **kwargs):
            raise AssertionError(f"署名中にネットワーク接続が発生しました: {args!r}")

        key, _, _ = pkcs12.load_key_and_certificates(p12_file.read_bytes(), P12_PASSWORD)
        cert = load_pkcs12_signer(p12_file, P12_PASSWORD).signing_cert
        session = _FakeCardSession(key)
        jpki_signer = JpkiSigner(cert=cert, session=session)

        monkeypatch.setattr(socket.socket, "connect", _deny_network)
        monkeypatch.setattr(socket, "getaddrinfo", _deny_network)
        dst = tmp_path / "jpki_signed.pdf"
        _sign(sample_pdf, dst, hanko_png, jpki_signer)
        monkeypatch.undo()

        with open(dst, "rb") as f:
            sigs = PdfFileReader(f).embedded_signatures
            assert len(sigs) == 1
            vc = ValidationContext(trust_roots=[cert], allow_fetching=False)
            status = validate_pdf_signature(sigs[0], vc)
            assert status.intact
            assert status.valid

        jpki_signer.close()
        assert session.closed
