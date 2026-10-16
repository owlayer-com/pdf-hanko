"""ハンコ（印影画像 + 証明書 + メタデータ）の永続化レイヤ。

保存先のディレクトリ構造::

    ~/Library/Application Support/PdfHanko/
        hankos.json                       メタデータインデックス
        hankos/<uuid>/image.png           72 DPI に正規化された印影画像
        hankos/<uuid>/cert.p12            PKCS#12 証明書ファイル

PKCS#12 のパスワードは保存しない (署名時に毎回入力させる)。

ディレクトリは ``0700``、ファイルは ``0600`` (所有者のみアクセス可) で
作成する。以前のバージョンで作成された広い権限のファイルは、
:meth:`HankoStore.load` の呼び出し時に修正する。

``hankos.json`` の内容は信頼しない。読み込み時に各エントリの ID・型・
パスを検証し、不正なエントリは読み込まない。ファイルの場所は保存された
``image`` / ``cert`` の値ではなく、検証済みの ID から毎回組み立てる
(:func:`hanko_dir`)。

確認と使用の間にファイルが差し替えられる競合 (TOCTOU) は完全には防いで
いない。``hankos/`` 以下は ``0700`` で所有者以外は書き込めないため、
差し替えには同じユーザー権限が必要であり、その攻撃者は本アプリを介さず
とも同じ操作ができる。本モジュールではシンボリックリンクの検出と保存
領域内であることの確認までを行う。
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import shutil
import stat
import uuid
from dataclasses import asdict, dataclass, field, fields as dc_fields
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .fileutil import (
    PRIVATE_FILE_MODE,
    UnsafePathError,
    atomic_write,
    copy_private_file,
    ensure_private_dir,
    fix_private_permissions,
)
from .limits import ResourceLimits
from .rendering import normalize_image_dpi

logger = logging.getLogger(__name__)

APP_DIR_NAME = "PdfHanko"
"""アプリ専用ディレクトリの名前。``~/Library/Application Support/`` 配下に置く。"""

CERT_TYPE_PKCS12 = "pkcs12"
"""``Hanko.cert_type`` の値: PKCS#12 (.p12/.pfx) ファイルベース。"""

CERT_TYPE_JPKI = "jpki"
"""``Hanko.cert_type`` の値: マイナンバーカード (JPKI 署名用電子証明書)。"""

HANKOS_DIR_NAME = "hankos"
IMAGE_FILE_NAME = "image.png"
CERT_FILE_NAME = "cert.p12"

_HANKO_ID_RE = re.compile(r"[0-9a-f]{32}")
"""ハンコ ID の形式 (``uuid.uuid4().hex``)。"""

_CERT_SERIAL_RE = re.compile(r"[0-9A-Fa-f]+")
"""JPKI 証明書シリアル番号の形式 (16 進)。"""


def app_data_dir() -> Path:
    """アプリ専用ディレクトリの絶対パスを返す。

    Returns:
        ``~/Library/Application Support/PdfHanko`` の :class:`Path`。
    """
    return Path.home() / "Library" / "Application Support" / APP_DIR_NAME


def is_valid_hanko_id(hanko_id: object) -> bool:
    """``hanko_id`` がハンコ ID の形式 (32 桁の小文字 16 進) か判定する。"""
    return isinstance(hanko_id, str) and _HANKO_ID_RE.fullmatch(hanko_id) is not None


def _image_rel(hanko_id: str) -> str:
    return f"{HANKOS_DIR_NAME}/{hanko_id}/{IMAGE_FILE_NAME}"


def _cert_rel(hanko_id: str) -> str:
    return f"{HANKOS_DIR_NAME}/{hanko_id}/{CERT_FILE_NAME}"


def _reject_symlink(path: Path) -> None:
    """``path`` がシンボリックリンクなら :class:`UnsafePathError` を送出する。

    存在しない場合は何もしない (作成前や削除済みのケース)。
    """
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return
    if stat.S_ISLNK(st.st_mode):
        raise UnsafePathError(f"シンボリックリンクは使用できません: {path}")


def hanko_dir(base: Path, hanko_id: str) -> Path:
    """検証済みのハンコ専用ディレクトリ ``<base>/hankos/<id>`` を返す。

    次をすべて確認する。``base`` 自身のシンボリックリンクは
    :func:`pdfhanko.fileutil.ensure_private_dir` と同じく許容する。

    - ``hanko_id`` が :func:`is_valid_hanko_id` を満たすこと。
    - ``hankos/`` と ``hankos/<id>/`` がシンボリックリンクでないこと。
    - 解決後のパスが ``base`` の解決後のパスの配下にあること。

    Args:
        base: アプリ専用ディレクトリ。
        hanko_id: ハンコ ID。

    Returns:
        ハンコ専用ディレクトリのパス (存在するとは限らない)。

    Raises:
        UnsafePathError: 上記の条件を満たさない場合。
    """
    if not is_valid_hanko_id(hanko_id):
        raise UnsafePathError(f"不正なハンコ ID です: {hanko_id!r}")
    hankos = base / HANKOS_DIR_NAME
    path = hankos / hanko_id
    _reject_symlink(hankos)
    _reject_symlink(path)
    if not path.resolve().is_relative_to(base.resolve()):
        raise UnsafePathError(f"保存領域の外を指しています: {path}")
    return path


def _hanko_file(base: Path, hanko_id: str, name: str) -> Path:
    """ハンコ専用ディレクトリ内のファイルパスを、検証したうえで返す。"""
    path = hanko_dir(base, hanko_id) / name
    _reject_symlink(path)
    return path


@dataclass(slots=True)
class Hanko:
    """1 個のハンコを表すデータクラス。

    Attributes:
        id: 内部識別子 (UUID hex)。
        name: 表示用のハンコ名 (ユーザー入力)。
        size_mm: 印影の実寸サイズ (mm 角)。
        memo: 自由メモ。
        image: 印影画像の相対パス (アプリ専用ディレクトリ基準)。後方互換の
            ため ``hankos.json`` に保存するが、ファイルアクセスには使わない
            (:meth:`image_path` は ``id`` からパスを組み立てる)。
        cert: 証明書ファイルの相対パス (アプリ専用ディレクトリ基準)。
            ``cert_type == "jpki"`` の場合は空文字。``image`` と同じく
            ファイルアクセスには使わない。
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

        Raises:
            UnsafePathError: ID が不正、またはパスの途中にシンボリック
                リンクがある場合。
        """
        return _hanko_file(base, self.id, IMAGE_FILE_NAME)

    def cert_path(self, base: Path) -> Path:
        """証明書ファイルの絶対パスを返す。

        Args:
            base: アプリ専用ディレクトリ。

        Returns:
            証明書ファイルの絶対パス。

        Raises:
            UnsafePathError: ID が不正、またはパスの途中にシンボリック
                リンクがある場合。
        """
        return _hanko_file(base, self.id, CERT_FILE_NAME)


def _validate_entry(item: Any) -> Hanko | None:
    """``hankos.json`` の 1 エントリを検証し、妥当なら :class:`Hanko` を返す。

    未知のフィールドは将来の追加に備えて無視する。欠落したフィールドは
    データクラスの既定値を使う (``id`` などの必須フィールドを除く)。

    Args:
        item: JSON から読み込んだ 1 エントリ。

    Returns:
        妥当なら :class:`Hanko`。不正なら ``None`` (理由は警告ログに残す)。
    """

    def reject(reason: str) -> None:
        hanko_id = item.get("id") if isinstance(item, dict) else None
        logger.warning("hankos.json の不正なエントリを読み込みません (id=%r): %s", hanko_id, reason)

    if not isinstance(item, dict):
        reject(f"オブジェクトではありません ({type(item).__name__})")
        return None

    known = {f.name for f in dc_fields(Hanko)}
    data = {k: v for k, v in item.items() if k in known}

    hanko_id = data.get("id")
    if not is_valid_hanko_id(hanko_id):
        reject("ID の形式が不正です")
        return None
    for key in ("name", "memo", "image", "cert"):
        if not isinstance(data.get(key), str):
            reject(f"{key} が文字列ではありません")
            return None
    size_mm = data.get("size_mm")
    if (
        isinstance(size_mm, bool)
        or not isinstance(size_mm, (int, float))
        or not math.isfinite(size_mm)
        or size_mm <= 0
    ):
        reject("size_mm が正の数ではありません")
        return None

    cert_type = data.get("cert_type", CERT_TYPE_PKCS12)
    serial = data.get("jpki_cert_serial")
    subject_cn = data.get("jpki_cert_subject_cn")
    if serial is not None and not (
        isinstance(serial, str) and _CERT_SERIAL_RE.fullmatch(serial)
    ):
        reject("jpki_cert_serial が 16 進の文字列ではありません")
        return None
    if subject_cn is not None and not isinstance(subject_cn, str):
        reject("jpki_cert_subject_cn が文字列ではありません")
        return None

    if data["image"] != _image_rel(hanko_id):
        reject("image のパスが想定と異なります")
        return None
    if cert_type == CERT_TYPE_PKCS12:
        expected_cert = _cert_rel(hanko_id)
    elif cert_type == CERT_TYPE_JPKI:
        expected_cert = ""
        if serial is None:
            # シリアルが無いと署名時の同一カード検証ができないため拒否する。
            reject("cert_type='jpki' なのに jpki_cert_serial がありません")
            return None
    else:
        reject(f"未知の cert_type です: {cert_type!r}")
        return None
    if data["cert"] != expected_cert:
        reject("cert のパスが想定と異なります")
        return None

    data["size_mm"] = float(size_mm)
    data["cert_type"] = cert_type
    return Hanko(**data)


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
    load_problems: list[str] = field(default_factory=list)
    """直近の :meth:`load` で見つかった問題 (UI 通知用の文言)。"""
    _needs_backup: bool = field(default=False, repr=False)
    """``hankos.json`` に問題があり、次回 :meth:`save` の前に元ファイルを
    退避する必要があるか。"""

    @property
    def index_path(self) -> Path:
        """メタデータインデックスファイル ``hankos.json`` のパス。"""
        return self.base_dir / "hankos.json"

    def load(self) -> None:
        """インデックスファイルを読み込み、:attr:`hankos` を再構築する。

        ``base_dir`` が存在しない場合は作成する。インデックスが
        存在しない場合は空リストになる。

        以前のバージョンで作成されたファイルの権限 (``0755`` / ``0644`` 等) を
        毎回確認し、所有者のみに狭める。バックアップからの復元などで権限が
        広がった場合も次回起動時に修正される。

        各エントリは :func:`_validate_entry` で検証し、不正なもの、ID が
        重複するもの、ハンコ専用ディレクトリやファイルがシンボリックリンク
        のものは読み込まない。JSON として壊れている場合は空リストとして
        扱う。いずれの場合も例外は送出せず、:attr:`load_problems` に記録する。
        問題があった場合、元の ``hankos.json`` は次回 :meth:`save` の前に
        退避し、上書きで失われないようにする。
        """
        ensure_private_dir(self.base_dir, allow_symlink=True)
        fix_private_permissions(self.base_dir)
        self.hankos = []
        self.load_problems = []
        self._needs_backup = False
        if not self.index_path.exists():
            return
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
            logger.warning("hankos.json を読み込めません: %s", e)
            self._record_problem("ハンコ一覧ファイル (hankos.json) が壊れているため読み込めませんでした。")
            return
        if not isinstance(data, list):
            logger.warning("hankos.json の形式が不正です (トップレベルが %s)", type(data).__name__)
            self._record_problem("ハンコ一覧ファイル (hankos.json) の形式が不正なため読み込めませんでした。")
            return

        seen: set[str] = set()
        skipped = 0
        for item in data:
            hanko = _validate_entry(item)
            if hanko is not None and hanko.id in seen:
                logger.warning("hankos.json の重複した ID を読み込みません: %s", hanko.id)
                hanko = None
            if hanko is not None:
                try:
                    hanko.image_path(self.base_dir)
                    if hanko.cert_type == CERT_TYPE_PKCS12:
                        hanko.cert_path(self.base_dir)
                except UnsafePathError as e:
                    logger.warning("ハンコを読み込みません (id=%s): %s", hanko.id, e)
                    hanko = None
            if hanko is None:
                skipped += 1
                continue
            seen.add(hanko.id)
            self.hankos.append(hanko)
        if skipped:
            self._record_problem(
                f"ハンコ一覧ファイル (hankos.json) の {skipped} 件を、内容が不正なため読み込みませんでした。",
            )

    def _record_problem(self, message: str) -> None:
        self.load_problems.append(message)
        self._needs_backup = True

    def _backup_index(self) -> Path | None:
        """問題のあった ``hankos.json`` を ``hankos.json.<日時>.bak`` に退避する。"""
        if not self.index_path.exists():
            return None
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = self.index_path.with_name(f"{self.index_path.name}.{stamp}.bak")
        n = 1
        while backup.exists():
            backup = self.index_path.with_name(f"{self.index_path.name}.{stamp}-{n}.bak")
            n += 1
        os.replace(self.index_path, backup)
        logger.warning("問題のあった hankos.json を退避しました: %s", backup)
        return backup

    def save(self) -> None:
        """現在の :attr:`hankos` をインデックスファイルに書き出す。

        直近の :meth:`load` で問題が見つかっていた場合は、上書きの前に元の
        ``hankos.json`` を退避する (読み込まなかったエントリを失わないため)。
        """
        ensure_private_dir(self.base_dir, allow_symlink=True)
        if self._needs_backup:
            self._backup_index()
            self._needs_backup = False
        payload = json.dumps([asdict(h) for h in self.hankos], ensure_ascii=False, indent=2)
        with atomic_write(self.index_path, mode=PRIVATE_FILE_MODE) as f:
            f.write(payload.encode("utf-8"))

    def _ensure_hanko_dir(self, hanko_id: str) -> Path:
        """ハンコ専用ディレクトリ ``hankos/<id>/`` を ``0700`` で用意する。

        Args:
            hanko_id: ハンコ ID。

        Returns:
            ハンコ専用ディレクトリの絶対パス。
        """
        ensure_private_dir(self.base_dir, allow_symlink=True)
        ensure_private_dir(self.base_dir / HANKOS_DIR_NAME)
        abs_dir = hanko_dir(self.base_dir, hanko_id)
        ensure_private_dir(abs_dir)
        return abs_dir

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
        limits: ResourceLimits | None = None,
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
            limits: 印影画像の処理量の上限。``None`` のときは既定値。

        Returns:
            登録された :class:`Hanko` インスタンス。

        Raises:
            pdfhanko.limits.ResourceLimitError: 印影画像が上限を超える場合。
        """
        hanko_id = uuid.uuid4().hex
        abs_dir = self._ensure_hanko_dir(hanko_id)

        try:
            normalize_image_dpi(
                image_src, abs_dir / IMAGE_FILE_NAME, mode=PRIVATE_FILE_MODE, limits=limits,
            )
        except BaseException:
            # 作成したばかりの空ディレクトリを残さない。
            shutil.rmtree(abs_dir, ignore_errors=True)
            raise

        cert_rel_str = ""
        if cert_type == CERT_TYPE_PKCS12:
            if cert_src is None:
                raise ValueError("cert_type='pkcs12' のとき cert_src は必須です")
            copy_private_file(cert_src, abs_dir / CERT_FILE_NAME)
            cert_rel_str = _cert_rel(hanko_id)
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
            image=_image_rel(hanko_id),
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

        ディレクトリの削除前に :func:`hanko_dir` でパスを検証する。
        ``shutil.rmtree`` は macOS ではシンボリックリンク攻撃に耐性のある
        実装 (``rmtree.avoids_symlink_attacks``) が使われ、リンク先は削除しない。

        Args:
            hanko_id: 削除対象のハンコ ID。

        Raises:
            UnsafePathError: ハンコ専用ディレクトリのパスが不正な場合。
                インデックスもディスクも変更しない。
        """
        target = next((h for h in self.hankos if h.id == hanko_id), None)
        if target is None:
            return
        abs_dir = hanko_dir(self.base_dir, hanko_id)
        self.hankos = [h for h in self.hankos if h.id != hanko_id]
        shutil.rmtree(abs_dir, ignore_errors=True)
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
        limits: ResourceLimits | None = None,
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
            limits: 印影画像の処理量の上限。``None`` のときは既定値。

        Returns:
            更新後の :class:`Hanko` インスタンス。

        Raises:
            KeyError: ``hanko_id`` に対応するハンコが存在しない場合。
        """
        target = next((h for h in self.hankos if h.id == hanko_id), None)
        if target is None:
            raise KeyError(hanko_id)

        # 画像は上限超過で失敗し得るため、他の項目を書き換える前に処理する。
        if image_src is not None:
            abs_dir = self._ensure_hanko_dir(target.id)
            normalize_image_dpi(
                image_src, abs_dir / IMAGE_FILE_NAME, mode=PRIVATE_FILE_MODE, limits=limits,
            )
        if name is not None:
            target.name = name
        if size_mm is not None:
            target.size_mm = size_mm
        if memo is not None:
            target.memo = memo

        new_cert_type = cert_type if cert_type is not None else target.cert_type
        if new_cert_type == CERT_TYPE_PKCS12:
            if cert_src is not None or cert_type is not None:
                # 渡された .p12 をハンコ専用ディレクトリにコピーし cert パスを更新する。
                if cert_src is None:
                    raise ValueError(
                        "cert_type='pkcs12' への切替時は cert_src が必須です",
                    )
                abs_dir = self._ensure_hanko_dir(target.id)
                copy_private_file(cert_src, abs_dir / CERT_FILE_NAME)
                target.cert = _cert_rel(target.id)
            target.cert_type = CERT_TYPE_PKCS12
            target.jpki_cert_serial = None
            target.jpki_cert_subject_cn = None
        elif new_cert_type == CERT_TYPE_JPKI:
            if cert_type is not None:
                # 旧 .p12 をディスクから削除し cert パスを空にする。
                if target.cert:
                    target.cert_path(self.base_dir).unlink(missing_ok=True)
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
