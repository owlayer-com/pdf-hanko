"""PDF・画像の処理量の上限。

巨大なページや高圧縮の PDF・画像によって、メモリを使い切ったり UI が
固まったりするのを防ぐため、ファイルサイズ・ページ数・ピクセル数に上限を
設ける。上限値はユーザーが設定画面 (``settings.json``) から変更できる。

- 設定できる値に上限は設けない。最終的な値はユーザーが決める。
  :attr:`LimitSpec.recommended_max` は設定画面で警告を出すための目安。
- 最小値は 1。0 以下ではどのファイルも開けなくなるため。

:mod:`pdfhanko.rendering` と :mod:`pdfhanko.settings` の両方から使うため、
循環 import を避けて独立したモジュールにしている。
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger(__name__)

MB = 1024 * 1024
"""設定値の ``MB`` を bytes に換算する係数。"""

MEGAPIXEL = 1_000_000
"""設定値の ``M px`` を pixel 数に換算する係数。"""

SETTINGS_HINT = "上限は「設定」（⌘,）から変更できます。"
"""上限超過のエラーメッセージに添える案内文。"""


@dataclass(frozen=True, slots=True)
class LimitSpec:
    """上限 1 項目の定義。設定画面とエラーメッセージはこの定義から作る。

    Attributes:
        key: ``settings.json`` の ``limits`` 内のキー。
        label: 表示名。
        unit: 表示用の単位。
        default: 既定値。
        recommended_max: 推奨上限。超えても保存できるが警告を出す。
        description: 設定画面に出す補足 (推奨上限を超えたときの影響)。
    """

    key: str
    label: str
    unit: str
    default: int
    recommended_max: int
    description: str

    def format(self, value: float) -> str:
        """``value`` を単位付きの表示用文字列にする (例: ``"1,024 MB"``)。"""
        if float(value).is_integer():
            text = f"{int(value):,}"
        else:
            text = f"{value:,.1f}"
        return f"{text} {self.unit}"


LIMIT_SPECS: tuple[LimitSpec, ...] = (
    LimitSpec(
        key="pdf_file_mb",
        label="PDF のファイルサイズ",
        unit="MB",
        default=200,
        recommended_max=1024,
        description="署名時にファイル全体を読み込むため、大きいほどメモリを使います。",
    ),
    LimitSpec(
        key="pdf_pages",
        label="PDF のページ数",
        unit="ページ",
        default=5000,
        recommended_max=20000,
        description="ページ数が極端に多い PDF は、読み込みに時間がかかります。",
    ),
    LimitSpec(
        key="render_megapixels",
        label="1 ページの描画サイズ",
        unit="M px",
        default=40,
        recommended_max=150,
        description="大きいほど描画時のメモリを使います（150 M px で約 2 GB）。",
    ),
    LimitSpec(
        key="image_file_mb",
        label="印影画像のファイルサイズ",
        unit="MB",
        default=30,
        recommended_max=200,
        description="印影画像の登録時に読み込むファイルの大きさです。",
    ),
    LimitSpec(
        key="image_megapixels",
        label="印影画像のピクセル数",
        unit="M px",
        default=50,
        recommended_max=178,
        description="大きいほど登録時のメモリを使います。",
    ),
)
"""上限項目の一覧 (設定画面の表示順)。"""

SPECS_BY_KEY: dict[str, LimitSpec] = {spec.key: spec for spec in LIMIT_SPECS}


class ResourceLimitError(ValueError):
    """処理量の上限を超えたことを示す例外。

    Attributes:
        key: 超えた上限の設定キー (``LIMIT_SPECS`` のいずれか)。
        actual: 実際の値 (設定値と同じ単位)。不明な場合は ``None``。
        limit: 上限値 (設定値と同じ単位)。
    """

    def __init__(self, key: str, actual: float | None, limit: int, message: str | None = None):
        self.key = key
        self.actual = actual
        self.limit = limit
        if message is None:
            spec = SPECS_BY_KEY[key]
            detail = f"上限 {spec.format(limit)}"
            if actual is not None:
                detail = f"{spec.format(actual)}、{detail}"
            message = f"{spec.label}が上限を超えています（{detail}）。\n{SETTINGS_HINT}"
        super().__init__(message)

    @classmethod
    def out_of_memory(cls, key: str, limit: int) -> ResourceLimitError:
        """上限内でもメモリを確保できなかった場合の例外を作る。"""
        spec = SPECS_BY_KEY[key]
        return cls(
            key,
            None,
            limit,
            message=(
                "メモリが不足しているため処理できませんでした。\n"
                f"「{spec.label}」の上限（現在 {spec.format(limit)}）を下げると、"
                f"同じ状況を事前に防げます。{SETTINGS_HINT}"
            ),
        )


def _coerce_limit(key: str, value: Any, default: int) -> int:
    """設定値を検証し、不正なら既定値を返す (警告ログを残す)。

    整数 (または整数値の float) で 1 以上なら有効。``bool`` は不正とする。
    上限側の丸めは行わない。
    """
    if isinstance(value, bool):
        valid = False
    elif isinstance(value, int):
        valid = value >= 1
    elif isinstance(value, float) and value.is_integer():
        valid = value >= 1
        value = int(value)
    else:
        valid = False
    if not valid:
        logger.warning("設定 limits.%s の値が不正なため既定値 %d を使います: %r", key, default, value)
        return default
    return int(value)


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    """処理量の上限値 (各属性の単位は :data:`LIMIT_SPECS` を参照)。"""

    pdf_file_mb: int = SPECS_BY_KEY["pdf_file_mb"].default
    pdf_pages: int = SPECS_BY_KEY["pdf_pages"].default
    render_megapixels: int = SPECS_BY_KEY["render_megapixels"].default
    image_file_mb: int = SPECS_BY_KEY["image_file_mb"].default
    image_megapixels: int = SPECS_BY_KEY["image_megapixels"].default

    @classmethod
    def from_dict(cls, data: Any) -> ResourceLimits:
        """``settings.json`` の ``limits`` から構築する。

        キーが欠けている項目は既定値を使う。整数でない値・``bool``・1 未満の
        値は既定値に戻し、警告ログを残す。未知のキーは無視する。

        Args:
            data: ``limits`` の値。dict 以外なら全項目を既定値にする。
        """
        if data is None:
            data = {}
        if not isinstance(data, dict):
            logger.warning("設定 limits の形式が不正なため既定値を使います: %r", data)
            data = {}
        values = {
            spec.key: _coerce_limit(spec.key, data[spec.key], spec.default)
            for spec in LIMIT_SPECS
            if spec.key in data
        }
        return cls(**values)

    def to_dict(self) -> dict[str, int]:
        """``settings.json`` に書き出す dict を返す。"""
        return asdict(self)

    def exceeds_recommended(self) -> list[str]:
        """推奨上限を超えている項目のキーを返す (設定画面の警告用)。"""
        return [
            spec.key
            for spec in LIMIT_SPECS
            if getattr(self, spec.key) > spec.recommended_max
        ]

    @property
    def pdf_file_bytes(self) -> int:
        return self.pdf_file_mb * MB

    @property
    def render_pixels(self) -> int:
        return self.render_megapixels * MEGAPIXEL

    @property
    def image_file_bytes(self) -> int:
        return self.image_file_mb * MB

    @property
    def image_pixels(self) -> int:
        return self.image_megapixels * MEGAPIXEL
