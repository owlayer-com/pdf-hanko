"""署名用 PIN の検証 (pdfhanko.jpki) のテスト。

実カードには触れず、``JpkiSession._transmit`` を差し替えて送信内容を確認する。
"""
from __future__ import annotations

import pytest

from pdfhanko import jpki
from pdfhanko.jpki import (
    ApduResponse,
    InvalidPinFormatError,
    JpkiSession,
    normalize_signature_pin,
)
from pdfhanko.signing import load_jpki_signer

OK = ApduResponse(b"", 0x90, 0x00)


class _FakeSession(JpkiSession):
    """カードに接続せず、送信した APDU を記録するセッション。"""

    def __init__(self, reader_name=None):
        self.sent: list[bytes] = []
        self.closed = False

    def _transmit(self, apdu: bytes) -> ApduResponse:
        self.sent.append(apdu)
        return OK

    def select_signature_ap(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


class TestNormalizeSignaturePin:
    @pytest.mark.parametrize(
        ("pin", "expected"),
        [
            ("abc123", b"ABC123"),
            ("ABCdef123456", b"ABCDEF123456"),
            ("123456", b"123456"),
            ("A" * 16, b"A" * 16),
            (b"abc123", b"ABC123"),
        ],
    )
    def test_valid(self, pin, expected) -> None:
        assert normalize_signature_pin(pin) == expected

    @pytest.mark.parametrize(
        ("pin", "message"),
        [
            ("", "入力してください"),
            (b"", "入力してください"),
            ("1234 56", "空白"),
            (" 123456", "空白"),
            ("123456 ", "空白"),
            ("123456\t", "空白"),
            ("12345　66", "空白"),  # 全角スペース
            (b"1234 56", "空白"),
            ("１２３４５６", "半角英数字"),  # 全角数字 (str.isalnum() は True)
            ("abc-123", "半角英数字"),
            ("ａｂｃ123", "半角英数字"),
            (b"abc\xff23", "半角英数字"),
            ("12345", "6〜16 桁"),
            ("A" * 17, "6〜16 桁"),
        ],
    )
    def test_invalid(self, pin, message) -> None:
        with pytest.raises(InvalidPinFormatError) as exc:
            normalize_signature_pin(pin)
        assert message in str(exc.value)


class TestVerifySignaturePin:
    def test_valid_pin_is_sent_in_uppercase(self) -> None:
        sess = _FakeSession()
        sess.verify_signature_pin(b"abc123")
        verify_apdu = sess.sent[-1]
        assert verify_apdu == bytes([0x00, 0x20, 0x00, 0x80, 6]) + b"ABC123"

    @pytest.mark.parametrize("pin", [b"1234 56", b"12345", "１２３４５６".encode(), b"abc-123"])
    def test_invalid_pin_is_never_sent(self, pin: bytes) -> None:
        sess = _FakeSession()
        with pytest.raises(InvalidPinFormatError):
            sess.verify_signature_pin(pin)
        assert sess.sent == []

    def test_load_jpki_signer_does_not_send_invalid_pin(self, monkeypatch) -> None:
        created: list[_FakeSession] = []

        def factory(*args, **kwargs):
            s = _FakeSession()
            created.append(s)
            return s

        monkeypatch.setattr(jpki, "JpkiSession", factory)
        with pytest.raises(InvalidPinFormatError):
            load_jpki_signer(b"1234 56")
        assert created[0].sent == []
        assert created[0].closed


class TestProbeCli:
    def test_pin_argument_is_removed(self) -> None:
        """--pin 引数は廃止され、PIN はコマンドラインで受け付けない。"""
        import inspect

        assert "pin" not in inspect.signature(jpki._probe).parameters
        source = inspect.getsource(jpki)
        assert '"--pin"' not in source
