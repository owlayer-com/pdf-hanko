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
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

from .rendering import normalize_image_dpi

APP_DIR_NAME = "PdfHanko"
"""アプリ専用ディレクトリの名前。``~/Library/Application Support/`` 配下に置く。"""


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
    """

    id: str
    name: str
    size_mm: float
    memo: str
    image: str
    cert: str

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
        self.hankos = [Hanko(**item) for item in data]

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
        cert_src: Path,
    ) -> Hanko:
        """新規ハンコを登録する。

        印影画像は 72 DPI に正規化して保存し、証明書ファイルはそのままコピーする。

        Args:
            name: 表示名。
            size_mm: 印影実寸 (mm 角)。
            memo: 自由メモ。
            image_src: コピー元の印影画像ファイル。
            cert_src: コピー元の PKCS#12 証明書ファイル。

        Returns:
            登録された :class:`Hanko` インスタンス。
        """
        hanko_id = uuid.uuid4().hex
        rel_dir = Path("hankos") / hanko_id
        abs_dir = self.base_dir / rel_dir
        abs_dir.mkdir(parents=True, exist_ok=True)

        image_rel = rel_dir / "image.png"
        cert_rel = rel_dir / "cert.p12"
        normalize_image_dpi(image_src, self.base_dir / image_rel)
        shutil.copy2(cert_src, self.base_dir / cert_rel)

        hanko = Hanko(
            id=hanko_id,
            name=name,
            size_mm=size_mm,
            memo=memo,
            image=str(image_rel),
            cert=str(cert_rel),
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
    ) -> Hanko:
        """既存ハンコを部分的に更新する。

        ``None`` を渡したフィールドは変更されない。画像 / 証明書を新たに渡すと
        ディスク上のファイルが置き換えられる。

        Args:
            hanko_id: 更新対象のハンコ ID。
            name: 新しい表示名。
            size_mm: 新しい印影実寸 (mm 角)。
            memo: 新しいメモ。
            image_src: 新しい印影画像ファイル。
            cert_src: 新しい PKCS#12 証明書ファイル。

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
        if cert_src is not None:
            shutil.copy2(cert_src, self.base_dir / target.cert)

        self.save()
        return target

    def __iter__(self) -> Iterable[Hanko]:  # type: ignore[override]
        """登録済みハンコをイテレートする。"""
        return iter(self.hankos)
