"""PyHanko による PDF 電子署名のラッパ。

本モジュールは Toga (asyncio イベントループ) から呼び出される前提で書かれており、
すべての署名処理に async API を使用する。同期 API は内部で ``asyncio.run()`` を
呼ぶため、既存ループ内ではネストエラーになる。
"""
from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from pathlib import Path

from pyhanko import stamp
from pyhanko.pdf_utils import images
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.sign import fields, signers


class BadPasswordError(Exception):
    """PKCS#12 の復号に失敗したことを示す例外。

    パスワード誤りまたは破損ファイル時に送出される。
    """


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
    signer: signers.SimpleSigner,
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
        signer: PKCS#12 から生成済みの SimpleSigner。
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
        stamp_style = stamp.TextStampStyle(
            stamp_text="",
            background=images.PdfImage(str(hanko_image)),
            border_width=0,
        )
        pdf_signer = signers.PdfSigner(meta, signer=signer, stamp_style=stamp_style)
        with open(dst_pdf, "wb") as outf:
            await pdf_signer.async_sign_pdf(w, output=outf)
