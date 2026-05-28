"""ハンコ（印影画像 + 証明書 + メタデータ）の永続化レイヤ。

保存先のディレクトリ構造::

    ~/Library/Application Support/PdfHanko/
        hankos.json                       メタデータインデックス
        hankos/<uuid>/image.png           72 DPI に正規化された印影画像
        hankos/<uuid>/cert.p12            PKCS#12 証明書ファイル

PKCS#12 のパスワードは保存しない (署名時に毎回入力させる)。
"""
from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import asdict, dataclass, field, fields as dc_fields
from pathlib import Path
from typing import Iterable

from .rendering import normalize_image_dpi

APP_DIR_NAME = "PdfHanko"
"""アプリ専用ディレクトリの名前。``~/Library/Application Support/`` 配下に置く。"""

CERT_TYPE_PKCS12 = "pkcs12"
"""``Hanko.cert_type`` の値: PKCS#12 (.p12/.pfx) ファイルベース。"""

CERT_TYPE_JPKI = "jpki"
"""``Hanko.cert_type`` の値: マイナンバーカード (JPKI 署名用電子証明書)。"""


def app_data_dir() -> Path:
    """アプリ専用ディレクトリの絶対パスを返す。

    Returns:
        ``~/Library/Application Support/PdfHanko`` の :class:`Path`。
    """
    return Path.home() / "Library" / "Application Support" / APP_DIR_NAME


@dataclass(slots=True)
class Hanko:
    """1 個のハンコを表すデータクラス。

    Attributes:
        id: 内部識別子 (UUID hex)。
        name: 表示用のハンコ名 (ユーザー入力)。
        size_mm: 印影の実寸サイズ (mm 角)。
        memo: 自由メモ。
        image: 印影画像の相対パス (アプリ専用ディレクトリ基準)。
        cert: 証明書ファイルの相対パス (アプリ専用ディレクトリ基準)。
            ``cert_type == "jpki"`` の場合は空文字。
        cert_type: 証明書ソース種別。``"pkcs12"`` (デフォルト) または
            ``"jpki"`` (マイナンバーカード)。
        jpki_cert_serial: ``cert_type == "jpki"`` のとき、登録時にカードから
            読み出した署名用証明書のシリアル番号 (16 進大文字)。署名時に
            同一カード検証に使う。
        jpki_cert_subject_cn: ``cert_type == "jpki"`` のとき、登録時の
            証明書 Subject の Common Name (氏名)。UI 表示用。
    """

    id: str
    name: str
    size_mm: float
    memo: str
    image: str
    cert: str
    cert_type: str = CERT_TYPE_PKCS12
    jpki_cert_serial: str | None = None
    jpki_cert_subject_cn: str | None = None

    def image_path(self, base: Path) -> Path:
        """印影画像の絶対パスを返す。

        Args:
            base: アプリ専用ディレクトリ。

        Returns:
            印影画像ファイルの絶対パス。
        """
        return base / self.image

    def cert_path(self, base: Path) -> Path:
        """証明書ファイルの絶対パスを返す。

        Args:
            base: アプリ専用ディレクトリ。

        Returns:
            証明書ファイルの絶対パス。
        """
        return base / self.cert


@dataclass(slots=True)
class HankoStore:
    """ハンコ群をディスクに永続化するリポジトリ。

    Attributes:
        base_dir: 永続化のルートディレクトリ。デフォルトは
            :func:`app_data_dir`。
        hankos: メモリ上に保持しているハンコ一覧。
    """

    base_dir: Path = field(default_factory=app_data_dir)
    hankos: list[Hanko] = field(default_factory=list)

    @property
    def index_path(self) -> Path:
        """メタデータインデックスファイル ``hankos.json`` のパス。"""
        return self.base_dir / "hankos.json"

    def load(self) -> None:
        """インデックスファイルを読み込み、:attr:`hankos` を再構築する。

        ``base_dir`` が存在しない場合は作成する。インデックスが
        存在しない場合は空リストになる。
        """
        self.base_dir.mkdir(parents=True, exist_ok=True)
        if not self.index_path.exists():
            self.hankos = []
            return
        data = json.loads(self.index_path.read_text(encoding="utf-8"))
        # 未知フィールドを無視して将来の追加に耐えるよう、既知フィールドのみ
        # を取り出して構築する。欠落フィールドはデータクラスのデフォルト値。
        known = {f.name for f in dc_fields(Hanko)}
        self.hankos = [
            Hanko(**{k: v for k, v in item.items() if k in known})
            for item in data
        ]

    def save(self) -> None:
        """現在の :attr:`hankos` をインデックスファイルに書き出す。"""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(
            json.dumps([asdict(h) for h in self.hankos], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add(
        self,
        name: str,
        size_mm: float,
        memo: str,
        image_src: Path,
        cert_src: Path | None = None,
        *,
        cert_type: str = CERT_TYPE_PKCS12,
        jpki_cert_serial: str | None = None,
        jpki_cert_subject_cn: str | None = None,
    ) -> Hanko:
        """新規ハンコを登録する。

        印影画像は 72 DPI に正規化して保存する。``cert_type == "pkcs12"`` の
        場合は ``cert_src`` の PKCS#12 ファイルをそのままコピーする。
        ``cert_type == "jpki"`` の場合は ``cert_src`` 不要で、カードから読み出
        した証明書シリアル等のメタデータのみ保存する。

        Args:
            name: 表示名。
            size_mm: 印影実寸 (mm 角)。
            memo: 自由メモ。
            image_src: コピー元の印影画像ファイル。
            cert_src: コピー元の PKCS#12 証明書ファイル。
                ``cert_type == "jpki"`` の場合は無視され ``None`` でよい。
            cert_type: 証明書ソース種別。``"pkcs12"`` または ``"jpki"``。
            jpki_cert_serial: ``cert_type == "jpki"`` 時の証明書シリアル番号
                (16 進大文字)。
            jpki_cert_subject_cn: ``cert_type == "jpki"`` 時の証明書 Subject CN。

        Returns:
            登録された :class:`Hanko` インスタンス。
        """
        hanko_id = uuid.uuid4().hex
        rel_dir = Path("hankos") / hanko_id
        abs_dir = self.base_dir / rel_dir
        abs_dir.mkdir(parents=True, exist_ok=True)

        image_rel = rel_dir / "image.png"
        normalize_image_dpi(image_src, self.base_dir / image_rel)

        cert_rel_str = ""
        if cert_type == CERT_TYPE_PKCS12:
            if cert_src is None:
                raise ValueError("cert_type='pkcs12' のとき cert_src は必須です")
            cert_rel = rel_dir / "cert.p12"
            shutil.copy2(cert_src, self.base_dir / cert_rel)
            cert_rel_str = str(cert_rel)
        elif cert_type == CERT_TYPE_JPKI:
            if jpki_cert_serial is None:
                raise ValueError(
                    "cert_type='jpki' のとき jpki_cert_serial は必須です",
                )
        else:
            raise ValueError(f"未知の cert_type: {cert_type!r}")

        hanko = Hanko(
            id=hanko_id,
            name=name,
            size_mm=size_mm,
            memo=memo,
            image=str(image_rel),
            cert=cert_rel_str,
            cert_type=cert_type,
            jpki_cert_serial=jpki_cert_serial,
            jpki_cert_subject_cn=jpki_cert_subject_cn,
        )
        self.hankos.append(hanko)
        self.save()
        return hanko

    def remove(self, hanko_id: str) -> None:
        """指定 ID のハンコをインデックスとディスクから削除する。

        該当 ID が存在しない場合は何もしない (安全)。

        Args:
            hanko_id: 削除対象のハンコ ID。
        """
        target = next((h for h in self.hankos if h.id == hanko_id), None)
        if target is None:
            return
        self.hankos = [h for h in self.hankos if h.id != hanko_id]
        shutil.rmtree(self.base_dir / "hankos" / hanko_id, ignore_errors=True)
        self.save()

    def update(
        self,
        hanko_id: str,
        *,
        name: str | None = None,
        size_mm: float | None = None,
        memo: str | None = None,
        image_src: Path | None = None,
        cert_src: Path | None = None,
        cert_type: str | None = None,
        jpki_cert_serial: str | None = None,
        jpki_cert_subject_cn: str | None = None,
    ) -> Hanko:
        """既存ハンコを部分的に更新する。

        ``None`` を渡したフィールドは変更されない。画像 / 証明書を新たに渡すと
        ディスク上のファイルが置き換えられる。``cert_type`` を切り替える場合
        (PKCS#12 ⇔ JPKI) は旧データを掃除しつつ新規データを書き込む。

        Args:
            hanko_id: 更新対象のハンコ ID。
            name: 新しい表示名。
            size_mm: 新しい印影実寸 (mm 角)。
            memo: 新しいメモ。
            image_src: 新しい印影画像ファイル。
            cert_src: 新しい PKCS#12 証明書ファイル
                (新 cert_type が ``"pkcs12"`` のときのみ意味を持つ)。
            cert_type: 新しい証明書ソース種別。
            jpki_cert_serial: 新 cert_type が ``"jpki"`` のときのシリアル。
            jpki_cert_subject_cn: 新 cert_type が ``"jpki"`` のとき Subject CN。

        Returns:
            更新後の :class:`Hanko` インスタンス。

        Raises:
            KeyError: ``hanko_id`` に対応するハンコが存在しない場合。
        """
        target = next((h for h in self.hankos if h.id == hanko_id), None)
        if target is None:
            raise KeyError(hanko_id)

        if name is not None:
            target.name = name
        if size_mm is not None:
            target.size_mm = size_mm
        if memo is not None:
            target.memo = memo
        if image_src is not None:
            normalize_image_dpi(image_src, self.base_dir / target.image)

        new_cert_type = cert_type if cert_type is not None else target.cert_type
        if new_cert_type == CERT_TYPE_PKCS12:
            if cert_src is not None or cert_type is not None:
                # 渡された .p12 をハンコ専用ディレクトリにコピーし cert パスを更新する。
                cert_rel = Path("hankos") / target.id / "cert.p12"
                abs_cert = self.base_dir / cert_rel
                abs_cert.parent.mkdir(parents=True, exist_ok=True)
                if cert_src is None:
                    raise ValueError(
                        "cert_type='pkcs12' への切替時は cert_src が必須です",
                    )
                shutil.copy2(cert_src, abs_cert)
                target.cert = str(cert_rel)
            target.cert_type = CERT_TYPE_PKCS12
            target.jpki_cert_serial = None
            target.jpki_cert_subject_cn = None
        elif new_cert_type == CERT_TYPE_JPKI:
            if cert_type is not None:
                # 旧 .p12 をディスクから削除し cert パスを空にする。
                if target.cert:
                    old_p12 = self.base_dir / target.cert
                    old_p12.unlink(missing_ok=True)
                target.cert = ""
            if jpki_cert_serial is not None:
                target.jpki_cert_serial = jpki_cert_serial
            if jpki_cert_subject_cn is not None:
                target.jpki_cert_subject_cn = jpki_cert_subject_cn
            if target.jpki_cert_serial is None:
                raise ValueError(
                    "cert_type='jpki' のとき jpki_cert_serial が必要です",
                )
            target.cert_type = CERT_TYPE_JPKI
        else:
            raise ValueError(f"未知の cert_type: {new_cert_type!r}")

        self.save()
        return target

    def __iter__(self) -> Iterable[Hanko]:  # type: ignore[override]
        """登録済みハンコをイテレートする。"""
        return iter(self.hankos)
