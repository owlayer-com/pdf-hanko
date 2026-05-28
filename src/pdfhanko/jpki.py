"""マイナンバーカード（公的個人認証 JPKI）への APDU 通信ラッパ。

pyscard を介して PC/SC でカードと通信し、JPKI 署名用 AP に対する以下の
操作を提供する:

- 署名用 PIN 残回数の取得（PIN を消費せず）
- 署名用 PIN の認証
- 署名用電子証明書の読み出し
- COMPUTE DIGITAL SIGNATURE による RSA PKCS#1 v1.5 署名

APDU バイト列の出典は以下の通り。**マイナンバーカードは署名用 PIN を
5 回連続で誤入力すると失効し、市区町村窓口での解除が必要になる**ため、
PIN 送信前は必ず残回数を確認すること。

参考実装/仕様:
    - jpki/myna (MIT/Apache, https://github.com/jpki/myna)
      の ``src/reader.rs`` / ``src/jpki.rs``。本モジュールは同実装の
      APDU 構造に準拠する。
    - 晴耕雨読「マイナンバーカードと APDU で通信して署名データ作成」
      https://tex2e.github.io/blog/protocol/jpki-mynumbercard-with-apdu
"""
from __future__ import annotations

import logging
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from smartcard.CardConnection import CardConnection

log = logging.getLogger(__name__)

# ---- APDU 定数 ----

#: 署名用 JPKI-AP の AID（10 バイト）
AID_JPKI = bytes.fromhex("D392F00026010000 0001".replace(" ", ""))

#: 署名用電子証明書を格納する EF の File ID
EF_SIGN_CERT = bytes.fromhex("0001")

#: 署名用 PIN を扱う EF の File ID
EF_SIGN_PIN = bytes.fromhex("001B")

#: 署名用秘密鍵を扱う EF の File ID（COMPUTE DIGITAL SIGNATURE 対象）
EF_SIGN_KEY = bytes.fromhex("001A")

#: SW=0x9000 = 正常終了
SW_SUCCESS = 0x9000

#: SW1=0x63 = 認証失敗（SW2 下位 4bit が残回数）。SW=0x6983 はロック。
SW1_AUTH_FAILED = 0x63
SW_LOCKED = 0x6983


# ---- 例外型 ----


class JpkiError(Exception):
    """JPKI 操作で発生した汎用エラー。"""


class CardNotFoundError(JpkiError):
    """カードリーダーが見つからない、またはカードが挿入されていない。"""


class JpkiCardLockedError(JpkiError):
    """署名用 PIN がロック状態（5 回失敗で失効済み）。"""


class JpkiPinError(JpkiError):
    """PIN 認証に失敗した。

    Attributes:
        attempts_remaining: 失敗後の残り試行回数。0 ならロック。
    """

    def __init__(self, attempts_remaining: int):
        self.attempts_remaining = attempts_remaining
        super().__init__(
            f"PIN が誤っています（残り {attempts_remaining} 回）"
            if attempts_remaining > 0
            else "PIN がロックされました"
        )


@dataclass(frozen=True)
class ApduResponse:
    """APDU レスポンス。"""

    data: bytes
    sw1: int
    sw2: int

    @property
    def sw(self) -> int:
        return (self.sw1 << 8) | self.sw2


# ---- リーダー検出 ----


def list_readers() -> list[str]:
    """接続中のカードリーダー名一覧を返す。

    Returns:
        リーダー表示名のリスト。0 件の場合は空リスト。
    """
    from smartcard.System import readers as _readers

    return [str(r) for r in _readers()]


# ---- セッション ----


class JpkiSession(AbstractContextManager):
    """1 回のカード接続を表す context manager。

    使用例::

        with JpkiSession() as sess:
            sess.select_signature_ap()
            remaining = sess.get_pin_attempts_remaining()
            if remaining <= 2:
                ...警告...
            sess.verify_pin(b"ABCD1234")
            cert_der = sess.read_signature_certificate()
            sig = sess.compute_signature(digest_info_der)
    """

    def __init__(self, reader_name: str | None = None):
        """カードに接続する。

        Args:
            reader_name: 使用するリーダー名。``None`` のとき最初に発見した
                リーダーを使う。
        """
        from smartcard.System import readers as _readers
        from smartcard.Exceptions import NoCardException, CardConnectionException

        all_readers = _readers()
        if not all_readers:
            raise CardNotFoundError("カードリーダーが見つかりません")

        if reader_name is None:
            target = all_readers[0]
        else:
            target = next((r for r in all_readers if str(r) == reader_name), None)
            if target is None:
                raise CardNotFoundError(f"リーダー '{reader_name}' が見つかりません")

        self._connection: CardConnection = target.createConnection()
        try:
            self._connection.connect()
        except (NoCardException, CardConnectionException) as e:
            raise CardNotFoundError(f"カードに接続できません: {e}") from e

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        """カード接続を解放する。冪等。"""
        try:
            self._connection.disconnect()
        except Exception:
            pass

    # ---- 低レベル APDU 発行 ----

    def _transmit(self, apdu: bytes) -> ApduResponse:
        """生 APDU を送信して ``ApduResponse`` で返す。"""
        data, sw1, sw2 = self._connection.transmit(list(apdu))
        return ApduResponse(bytes(data), sw1, sw2)

    # ---- 中レベル APDU（jpki/myna の case3/case2/case1/case4 と対応）----

    def _select_df_by_aid(self, aid: bytes) -> None:
        """DF（アプリケーション）を AID で選択する。

        APDU: ``00 A4 04 0C Lc <AID>``
        """
        apdu = bytes([0x00, 0xA4, 0x04, 0x0C, len(aid)]) + aid
        res = self._transmit(apdu)
        if res.sw != SW_SUCCESS:
            raise JpkiError(f"SELECT DF AID 失敗: SW={res.sw:04X}")

    def _select_ef(self, fid: bytes) -> None:
        """カレント DF 配下の EF を File ID で選択する。

        APDU: ``00 A4 02 0C 02 <FID>``
        """
        if len(fid) != 2:
            raise ValueError("EF File ID は 2 バイト必須")
        apdu = bytes([0x00, 0xA4, 0x02, 0x0C, 0x02]) + fid
        res = self._transmit(apdu)
        if res.sw != SW_SUCCESS:
            raise JpkiError(f"SELECT EF {fid.hex()} 失敗: SW={res.sw:04X}")

    def _read_binary(self, offset: int, length: int) -> bytes:
        """カレント EF を offset から length バイト読む。

        APDU: ``00 B0 <offset_hi> <offset_lo> <Le>``。
        Le=0 は 256 バイトを意味する。
        """
        result = bytearray()
        pos = offset
        end = offset + length
        while pos < end:
            remaining = end - pos
            le = 0 if remaining > 0xFF else remaining
            p1 = (pos >> 8) & 0xFF
            p2 = pos & 0xFF
            apdu = bytes([0x00, 0xB0, p1, p2, le])
            res = self._transmit(apdu)
            if res.sw != SW_SUCCESS:
                raise JpkiError(
                    f"READ BINARY 失敗 offset={pos} SW={res.sw:04X}"
                )
            if not res.data:
                break
            result.extend(res.data)
            pos += len(res.data)
        return bytes(result)

    def _read_binary_all(self) -> bytes:
        """BER の長さフィールドを解析してカレント EF を全部読む。

        jpki/myna の ``read_binary_all`` 相当。先頭 7 バイト（BER tag+length
        部分の最大長）を読み、長さフィールドを解析してから残りを読む。
        """
        head = self._read_binary(0, 7)
        body_len = _parse_ber_remaining_length(head)
        if body_len <= 0:
            return head
        body = self._read_binary(7, body_len)
        return head + body

    # ---- 高レベル操作 ----

    def select_signature_ap(self) -> None:
        """署名用 JPKI-AP を選択する。"""
        self._select_df_by_aid(AID_JPKI)

    def get_pin_attempts_remaining(self) -> int:
        """署名用 PIN の残り試行回数を取得する（PIN を消費しない）。

        APDU: ``00 20 00 80``（データなし）。SW1=0x63 のとき SW2 下位 4bit が
        残回数。jpki/myna の ``read_pin`` 相当。

        Returns:
            残り回数（0 ならロック済み）。

        Raises:
            JpkiError: 想定外の SW1SW2 を返した場合。
        """
        self._select_ef(EF_SIGN_PIN)
        apdu = bytes([0x00, 0x20, 0x00, 0x80])
        res = self._transmit(apdu)
        if res.sw1 == SW1_AUTH_FAILED:
            return res.sw2 & 0x0F
        if res.sw == SW_LOCKED:
            return 0
        raise JpkiError(
            f"PIN 残回数取得で想定外の SW: {res.sw:04X}"
        )

    def verify_signature_pin(self, pin: bytes) -> None:
        """署名用 PIN を認証する。

        マイナンバーカードの署名用 PIN は **6〜16 桁の英数字**で、英字は
        大文字として扱われる。本メソッドは PIN を**大文字に正規化してから
        送信**する（呼び出し側で正規化済みの場合も冪等）。

        APDU: ``00 20 00 80 Lc <PIN>``

        Args:
            pin: PIN バイト列（ASCII）。

        Raises:
            JpkiPinError: PIN 誤り。残回数を保持。
            JpkiCardLockedError: PIN ロック済み。
            JpkiError: その他のエラー。
        """
        self._select_ef(EF_SIGN_PIN)
        normalized = pin.upper()
        apdu = bytes([0x00, 0x20, 0x00, 0x80, len(normalized)]) + normalized
        res = self._transmit(apdu)
        if res.sw == SW_SUCCESS:
            return
        if res.sw == SW_LOCKED:
            raise JpkiCardLockedError("署名用 PIN がロックされています")
        if res.sw1 == SW1_AUTH_FAILED:
            remaining = res.sw2 & 0x0F
            if remaining == 0:
                raise JpkiCardLockedError("署名用 PIN がロックされました")
            raise JpkiPinError(remaining)
        raise JpkiError(f"VERIFY PIN 失敗: SW={res.sw:04X}")

    def read_signature_certificate(self) -> bytes:
        """署名用電子証明書を DER バイト列で読み出す。

        署名用証明書 EF は VERIFY PIN による認証後にアクセス可能。
        ``verify_signature_pin`` を先に呼ぶこと。

        Returns:
            証明書 DER バイト列（X.509）。
        """
        self._select_ef(EF_SIGN_CERT)
        return self._read_binary_all()

    def compute_signature(self, digest_info_der: bytes) -> bytes:
        """カード内 RSA 秘密鍵で署名する。

        入力は **DigestInfo（DER エンコード ASN.1）**で、カード側が RSA
        PKCS#1 v1.5 で署名する。SHA-256 を使う場合は呼び出し側で 32 バイト
        ハッシュ + DigestInfo 構築まで済ませて渡す。

        APDU: ``80 2A 00 80 Lc <DigestInfo> 00``（case 4: 入力+出力）

        Args:
            digest_info_der: DigestInfo の DER エンコード。

        Returns:
            RSA 署名値（鍵長と同じバイト数、典型 256 バイト）。
        """
        self._select_ef(EF_SIGN_KEY)
        apdu = (
            bytes([0x80, 0x2A, 0x00, 0x80, len(digest_info_der)])
            + digest_info_der
            + bytes([0x00])
        )
        res = self._transmit(apdu)
        if res.sw != SW_SUCCESS:
            raise JpkiError(f"COMPUTE DIGITAL SIGNATURE 失敗: SW={res.sw:04X}")
        return res.data


# ---- BER 長さ解析（read_binary_all 用）----


def _parse_ber_remaining_length(head: bytes) -> int:
    """BER 形式の先頭バイト列から、tag+length を除いた残りデータ長を返す。

    マイナンバーカードの証明書 EF は最上位タグが SEQUENCE (0x30) で
    始まる X.509 DER。先頭バイト目はタグ、2 バイト目以降が長さフィールド。

    長さフィールドの形式（X.690）:
        - 0x00〜0x7F: 短形式、その値が長さそのもの
        - 0x81 NN: 1 バイト長
        - 0x82 NN NN: 2 バイト長
        - 0x83 NN NN NN: 3 バイト長

    Args:
        head: 先頭バイト列（7 バイト推奨）。

    Returns:
        tag + length ヘッダの **後ろ**に続くデータ部のバイト数。
        head に既に一部含まれている場合も、それを差し引いた残りを返す。
    """
    if len(head) < 2:
        return 0
    # head[0] = tag, head[1] = length byte
    lb = head[1]
    if lb < 0x80:
        body_len = lb
        header_len = 2
    else:
        n = lb & 0x7F
        if len(head) < 2 + n:
            return 0
        body_len = int.from_bytes(head[2:2 + n], "big")
        header_len = 2 + n
    total = header_len + body_len
    already_read = len(head)
    return max(0, total - already_read)


# ---- CLI probe ----


def _probe(verify_pin: bool = False, pin: str | None = None) -> None:
    """デバッグ用 CLI エントリ。

    ``python -m pdfhanko.jpki`` で実行できる。デフォルトでは PIN を送らず、
    リーダー検出と AP 選択、PIN 残回数取得のみを行う（PIN を消費しない安全な
    確認モード）。``--verify-pin PIN`` を渡すと VERIFY と証明書読み出しまで
    行う。
    """
    print("=== JPKI Probe ===")
    rs = list_readers()
    if not rs:
        print("リーダーが見つかりません")
        return
    print(f"検出リーダー: {rs}")

    try:
        sess_ctx = JpkiSession()
    except CardNotFoundError as e:
        print(f"カード未挿入: {e}")
        return

    with sess_ctx as sess:
        print("カード接続: OK")
        sess.select_signature_ap()
        print("署名用 AP 選択: OK")
        remaining = sess.get_pin_attempts_remaining()
        print(f"署名用 PIN 残回数: {remaining}")
        if not verify_pin:
            print("(PIN 送信は --verify-pin で明示指定が必要)")
            return
        if pin is None:
            print("ERROR: --verify-pin 指定時は PIN が必要")
            return
        if remaining <= 2:
            print(f"WARNING: 残 {remaining} 回。続行しますか？ Ctrl+C で中断")
            input("Enter で続行: ")
        sess.verify_signature_pin(pin.encode("ascii"))
        print("VERIFY PIN: OK")
        cert_der = sess.read_signature_certificate()
        print(f"証明書 DER 読み出し: {len(cert_der)} bytes")
        print(f"先頭 32 バイト: {cert_der[:32].hex()}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="JPKI APDU probe (dry-run by default)")
    parser.add_argument(
        "--verify-pin",
        action="store_true",
        help="PIN を実際に送信して認証＋証明書読み出しまで行う（PIN 試行回数を消費する）",
    )
    parser.add_argument("--pin", type=str, default=None, help="署名用 PIN（6〜16 桁英数字）")
    args = parser.parse_args()
    _probe(verify_pin=args.verify_pin, pin=args.pin)
