"""テスト共通の fixture。

テスト用の PDF・PKCS#12・印影画像は ``tmp_path`` 上に毎回生成し、
リポジトリにバイナリを置かない。生成処理は ``poc/`` の各スクリプトと同等。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from PIL import Image, ImageDraw

P12_PASSWORD = b"test1234"


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    """A4 縦 1 ページの空 PDF を生成する。"""
    path = tmp_path / "sample.pdf"
    doc = pdfium.PdfDocument.new()
    doc.new_page(595, 842)
    doc.save(path)
    doc.close()
    return path


@pytest.fixture(scope="session")
def p12_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """自己署名証明書入りの PKCS#12 を生成する (パスワード ``P12_PASSWORD``)。

    RSA 鍵生成が重いため session 単位で 1 回だけ作る。
    """
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "JP"),
        x509.NameAttribute(NameOID.COMMON_NAME, "PdfHanko Test"),
    ])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    path = tmp_path_factory.mktemp("cert") / "test.p12"
    path.write_bytes(
        pkcs12.serialize_key_and_certificates(
            name=b"pdf-hanko-test",
            key=key,
            cert=cert,
            cas=None,
            encryption_algorithm=serialization.BestAvailableEncryption(P12_PASSWORD),
        ),
    )
    return path


@pytest.fixture
def hanko_png(tmp_path: Path) -> Path:
    """赤い丸の印影画像 (透過 PNG) を生成する。"""
    path = tmp_path / "hanko.png"
    img = Image.new("RGBA", (200, 200), (255, 255, 255, 0))
    ImageDraw.Draw(img).ellipse((10, 10, 190, 190), outline=(200, 30, 30, 255), width=8)
    img.save(path)
    return path
