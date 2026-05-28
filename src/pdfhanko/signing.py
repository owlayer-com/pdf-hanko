"""PyHanko による PDF 電子署名のラッパ。

本モジュールは Toga (asyncio イベントループ) から呼び出される前提で書かれており、
すべての署名処理に async API を使用する。同期 API は内部で ``asyncio.run()`` を
呼ぶため、既存ループ内ではネストエラーになる。
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from contextlib import contextmanager
from pathlib import Path

from asn1crypto import algos as asn1_algos
from asn1crypto import x509 as asn1_x509
from pyhanko import stamp
from pyhanko.pdf_utils import images, layout
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.sign import fields, signers


class BadPasswordError(Exception):
    """PKCS#12 の復号に失敗したことを示す例外。

    パスワード誤りまたは破損ファイル時に送出される。
    """


class JpkiCertMismatchError(Exception):
    """マイナンバーカードの証明書シリアルが登録時と一致しない。"""


@contextmanager
def _suppress_pyhanko_logging():
    """PyHanko の logger を一時的に無効化するコンテキストマネージャ。

    PyHanko はパスワード誤りなどで ``logger.error(..., exc_info=True)`` を
    呼び、stderr に traceback を出力する。エンドユーザー向けには不要な
    出力のため、PKCS#12 復号処理を本コンテキスト内で囲んで抑止する。
    """
    logger = logging.getLogger("pyhanko")
    old_level = logger.level
    old_disabled = logger.disabled
    logger.setLevel(logging.CRITICAL + 1)
    logger.disabled = True
    try:
        yield
    finally:
        logger.setLevel(old_level)
        logger.disabled = old_disabled


def load_pkcs12_signer(p12_file: Path, password: bytes) -> signers.SimpleSigner:
    """PKCS#12 ファイルを復号して PyHanko の SimpleSigner を返す。

    Args:
        p12_file: ``.p12`` / ``.pfx`` 形式の証明書ファイルのパス。
        password: 復号用パスワード (バイト列)。呼び出し側は使用後に参照を
            クリアすること。

    Returns:
        生成された :class:`pyhanko.sign.signers.SimpleSigner` インスタンス。

    Raises:
        BadPasswordError: パスワード誤り、または PKCS#12 ファイルが
            読み取れない場合。
    """
    with _suppress_pyhanko_logging():
        try:
            signer = signers.SimpleSigner.load_pkcs12(
                pfx_file=str(p12_file), passphrase=password,
            )
        except (ValueError, OSError) as e:
            raise BadPasswordError(str(e)) from None
    if signer is None:
        raise BadPasswordError("証明書を復号できませんでした（パスワード誤りの可能性）")
    return signer


class JpkiSigner(signers.Signer):
    """マイナンバーカードを使った PyHanko Signer 実装。

    署名用秘密鍵はカードから出ない。``async_sign_raw`` で要求されたデータを
    SHA-256 でハッシュし、DigestInfo を組み立ててカードに COMPUTE DIGITAL
    SIGNATURE APDU を発行することで生 RSA 署名値を得る。

    本 Signer は **カードセッションを内部で保持する**。署名処理が終わったら
    必ず :meth:`close` を呼び出してリーダー接続を解放すること。
    """

    def __init__(
        self,
        cert: asn1_x509.Certificate,
        session,
    ):
        """
        Args:
            cert: カードから読み出した署名用電子証明書 (asn1crypto)。
            session: 認証済みの :class:`pdfhanko.jpki.JpkiSession`。署名処理
                完了まで生存している必要がある。
        """
        super().__init__(
            signing_cert=cert,
            signature_mechanism=asn1_algos.SignedDigestAlgorithm(
                {"algorithm": "rsassa_pkcs1v15"},
            ),
        )
        self._session = session
        # 鍵長 (bit) はプレースホルダ生成 (dry_run) のサイズ算出に必要。
        # JPKI の RSA 鍵長は現行カードで 2048 bit (256 byte)。
        self._key_size_bytes = (cert.public_key.bit_size + 7) // 8

    async def async_sign_raw(
        self, data: bytes, digest_algorithm: str, dry_run: bool = False,
    ) -> bytes:
        if dry_run:
            # PyHanko は dry_run で署名サイズを見積もるためにこのメソッドを
            # 1 回目に呼ぶ。カードアクセスせず、鍵長と同じバイト数のダミーを返す。
            return b"\x00" * self._key_size_bytes

        digest = hashlib.new(digest_algorithm.replace("-", ""))
        digest.update(data)
        hash_value = digest.digest()

        digest_info = asn1_algos.DigestInfo(
            {
                "digest_algorithm": asn1_algos.DigestAlgorithm(
                    {"algorithm": digest_algorithm},
                ),
                "digest": hash_value,
            },
        ).dump()
        return self._session.compute_signature(digest_info)

    def close(self) -> None:
        """カードセッションを解放する。冪等。"""
        if self._session is not None:
            self._session.close()
            self._session = None


def load_jpki_signer(
    pin: bytes,
    expected_serial: str | None = None,
) -> JpkiSigner:
    """マイナンバーカードを認証して :class:`JpkiSigner` を生成する。

    内部でカードリーダー検出 → 署名用 AP 選択 → VERIFY PIN → 証明書読み出し
    まで行い、その時点でカードセッションを開いたままの Signer を返す。
    呼び出し側は使用後に :meth:`JpkiSigner.close` を呼ぶこと。

    Args:
        pin: 署名用 PIN (6〜16 桁英数字、ASCII バイト列)。
        expected_serial: 登録時に保存した証明書シリアル番号 (16 進大文字)。
            ``None`` のとき同一カード検証を行わない。

    Returns:
        認証済みの :class:`JpkiSigner`。

    Raises:
        pdfhanko.jpki.CardNotFoundError: リーダーまたはカード未検出。
        pdfhanko.jpki.JpkiPinError: PIN 誤り。残回数を保持。
        pdfhanko.jpki.JpkiCardLockedError: PIN ロック済み。
        JpkiCertMismatchError: 登録時とカードが異なる。
    """
    # jpki モジュールは pyscard に依存するため遅延 import する。
    from . import jpki as jpki_mod

    session = jpki_mod.JpkiSession()
    try:
        session.select_signature_ap()
        session.verify_signature_pin(pin)
        cert_der = session.read_signature_certificate()
        cert = asn1_x509.Certificate.load(cert_der)

        if expected_serial is not None:
            actual_serial = format(cert.serial_number, "X")
            if actual_serial != expected_serial.upper():
                raise JpkiCertMismatchError(
                    "登録時のカードと一致しません "
                    f"(expected={expected_serial}, actual={actual_serial})",
                )

        return JpkiSigner(cert=cert, session=session)
    except BaseException:
        session.close()
        raise


def _generate_field_name() -> str:
    """ユニークな署名フィールド名を生成する。

    既に署名済みの PDF に追加で押印する場合、PyHanko は既存フィールド名と
    衝突するとエラーを返す。``HankoSignature_<8 桁 hex>`` 形式で衝突
    確率を実質ゼロにする。

    Returns:
        ユニークなフィールド名文字列。
    """
    return f"HankoSignature_{uuid.uuid4().hex[:8]}"


async def sign_pdf_with_signer(
    src_pdf: Path,
    dst_pdf: Path,
    hanko_image: Path,
    signer: signers.Signer,
    page_index: int,
    box_pdf: tuple[int, int, int, int],
    field_name: str | None = None,
) -> None:
    """ロード済み signer を使って PDF に可視署名を 1 つ付与する。

    PDF / PAdES 仕様の incremental update を用いるため、既に署名済みの
    PDF にもさらに押印できる（甲乙押印、割印などのハンコ運用に対応）。

    ハイブリッド xref (PDF 1.4 と 1.5 の過渡期形式) を含む PDF も
    ``strict=False`` で許容する。一部の PDF 生成ツールがこの形式を出力
    するため、エンドユーザーが遭遇する確率は無視できない。

    Args:
        src_pdf: 入力 PDF。
        dst_pdf: 出力 PDF。
        hanko_image: 印影 PNG (72 DPI 正規化済みを推奨)。
        signer: ロード済みの PyHanko Signer (PKCS#12 由来の SimpleSigner /
            JPKI 由来の :class:`JpkiSigner` のいずれか)。
        page_index: 押印するページ番号 (0 始まり)。
        box_pdf: PDF 仕様 (bottom-left 原点、pt) の署名矩形
            ``(x0, y0, x1, y1)``。
        field_name: 署名フィールド名。``None`` のときは
            :func:`_generate_field_name` で自動生成する。
    """
    if field_name is None:
        field_name = _generate_field_name()
    with open(src_pdf, "rb") as inf:
        w = IncrementalPdfFileWriter(inf, strict=False)
        fields.append_signature_field(
            w,
            sig_field_spec=fields.SigFieldSpec(
                field_name,
                box=box_pdf,
                on_page=page_index,
            ),
        )
        meta = signers.PdfSignatureMetadata(field_name=field_name)
        # PyHanko の BaseStampStyle.background_layout は既定で 5 pt の
        # uniform margin を持つため、何も指定しないと署名矩形より一回り
        # 小さく印影が描画されてしまう (24 mm 角 → 約 20 mm 角に縮小)。
        # 矩形いっぱいに描画するためマージンをゼロに指定する。
        bg_layout = layout.SimpleBoxLayoutRule(
            x_align=layout.AxisAlignment.ALIGN_MID,
            y_align=layout.AxisAlignment.ALIGN_MID,
            margins=layout.Margins.uniform(0),
        )
        # PyHanko の TextStampStyle.background_opacity の既定値は 0.6 (60%) で、
        # 印影画像をさらに薄く描画してしまう (元の PNG が既にアルファ付き透過
        # PNG であるため、二重に透明度が掛かる)。1.0 を指定して画像本来の
        # 濃度で描画する。
        stamp_style = stamp.TextStampStyle(
            stamp_text="",
            background=images.PdfImage(str(hanko_image)),
            background_layout=bg_layout,
            background_opacity=1.0,
            border_width=0,
        )
        pdf_signer = signers.PdfSigner(meta, signer=signer, stamp_style=stamp_style)
        with open(dst_pdf, "wb") as outf:
            await pdf_signer.async_sign_pdf(w, output=outf)
