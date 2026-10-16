"""処理量の上限 (pdfhanko.limits / rendering / settings) のテスト。"""
from __future__ import annotations

import json
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from PIL import Image

from pdfhanko.limits import (
    LIMIT_SPECS,
    MB,
    ResourceLimitError,
    ResourceLimits,
)
from pdfhanko.rendering import (
    check_image_file,
    check_pdf_file,
    check_pdf_pages,
    normalize_image_dpi,
    render_page,
)
from pdfhanko.settings import AppSettings
from pdfhanko.storage import HankoStore


def _make_pdf(path: Path, width_pt: float, height_pt: float, pages: int = 1) -> Path:
    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(width_pt, height_pt)
    doc.save(path)
    doc.close()
    return path


def _render_first_page(path: Path, **kwargs):
    doc = pdfium.PdfDocument(path)
    try:
        return render_page(doc[0], **kwargs)
    finally:
        doc.close()


class TestResourceLimits:
    def test_defaults_match_specs(self) -> None:
        limits = ResourceLimits()
        for spec in LIMIT_SPECS:
            assert getattr(limits, spec.key) == spec.default

    def test_values_above_recommended_are_kept(self) -> None:
        limits = ResourceLimits.from_dict({"render_megapixels": 1000, "pdf_file_mb": 99999})
        assert limits.render_megapixels == 1000
        assert limits.pdf_file_mb == 99999

    @pytest.mark.parametrize("bad", [0, -1, 1.5, "100", True, False, None, [], {}])
    def test_invalid_values_fall_back_to_default(self, bad) -> None:
        limits = ResourceLimits.from_dict({"pdf_pages": bad})
        assert limits.pdf_pages == ResourceLimits().pdf_pages

    def test_integral_float_is_accepted(self) -> None:
        assert ResourceLimits.from_dict({"pdf_pages": 300.0}).pdf_pages == 300

    def test_minimum_is_one(self) -> None:
        assert ResourceLimits.from_dict({"pdf_pages": 1}).pdf_pages == 1

    def test_unknown_keys_and_missing_keys(self) -> None:
        limits = ResourceLimits.from_dict({"unknown": 1, "image_file_mb": 5})
        assert limits.image_file_mb == 5
        assert limits.pdf_pages == ResourceLimits().pdf_pages

    @pytest.mark.parametrize("bad", [None, "text", 1, []])
    def test_non_dict(self, bad) -> None:
        assert ResourceLimits.from_dict(bad) == ResourceLimits()

    def test_round_trip(self) -> None:
        limits = ResourceLimits(pdf_file_mb=10, render_megapixels=300)
        assert ResourceLimits.from_dict(limits.to_dict()) == limits

    def test_exceeds_recommended(self) -> None:
        assert ResourceLimits().exceeds_recommended() == []
        limits = ResourceLimits(render_megapixels=151, image_megapixels=178)
        assert limits.exceeds_recommended() == ["render_megapixels"]

    def test_error_message(self) -> None:
        e = ResourceLimitError("render_megapixels", 207.4, 40)
        assert "1 ページの描画サイズ" in str(e)
        assert "207.4 M px" in str(e)
        assert "40 M px" in str(e)
        assert "⌘," in str(e)


class TestPdfChecks:
    def test_file_size(self, sample_pdf: Path) -> None:
        check_pdf_file(sample_pdf)

    def test_file_size_exceeded(self, tmp_path: Path) -> None:
        big = tmp_path / "big.pdf"
        with open(big, "wb") as f:
            f.truncate(2 * MB + 1)
        with pytest.raises(ResourceLimitError) as exc:
            check_pdf_file(big, ResourceLimits(pdf_file_mb=2))
        assert exc.value.key == "pdf_file_mb"

    def test_file_size_exactly_at_limit(self, tmp_path: Path) -> None:
        f_path = tmp_path / "exact.pdf"
        with open(f_path, "wb") as f:
            f.truncate(2 * MB)
        check_pdf_file(f_path, ResourceLimits(pdf_file_mb=2))

    def test_pages(self) -> None:
        check_pdf_pages(10, ResourceLimits(pdf_pages=10))
        with pytest.raises(ResourceLimitError):
            check_pdf_pages(11, ResourceLimits(pdf_pages=10))


class TestRenderPage:
    def test_a4_is_rendered(self, sample_pdf: Path) -> None:
        rendered = _render_first_page(sample_pdf)
        assert (rendered.width_px, rendered.height_px) == (595, 842)

    def test_huge_page_is_rejected(self, tmp_path: Path) -> None:
        # 14,400 pt 四方 = 約 207 M px (既定の上限 40 M px を超える)
        pdf = _make_pdf(tmp_path / "huge.pdf", 14400, 14400)
        with pytest.raises(ResourceLimitError) as exc:
            _render_first_page(pdf)
        assert exc.value.key == "render_megapixels"
        assert exc.value.actual == pytest.approx(207.36)

    def test_scale_is_considered(self, sample_pdf: Path) -> None:
        # A4 は 1.0 倍で約 0.5 M px、3.0 倍で約 4.5 M px。
        _render_first_page(sample_pdf, scale=1.0, limits=ResourceLimits(render_megapixels=1))
        with pytest.raises(ResourceLimitError):
            _render_first_page(sample_pdf, scale=3.0, limits=ResourceLimits(render_megapixels=1))

    def test_limit_from_settings(self, sample_pdf: Path, tmp_path: Path) -> None:
        base = tmp_path / "PdfHanko"
        base.mkdir()
        (base / "settings.json").write_text(json.dumps({"limits": {"render_megapixels": 1}}))
        settings = AppSettings(base_dir=base)
        settings.load()
        with pytest.raises(ResourceLimitError):
            _render_first_page(sample_pdf, scale=2.0, limits=settings.limits)


@pytest.fixture
def huge_png(tmp_path: Path) -> Path:
    """10,000 × 10,000 の単色 PNG (高圧縮で数百 KB 程度)。"""
    path = tmp_path / "huge.png"
    Image.new("L", (10_000, 10_000), 255).save(path, optimize=True)
    return path


class TestImageLimits:
    def test_huge_image_is_rejected(self, huge_png: Path, tmp_path: Path) -> None:
        dst = tmp_path / "out.png"
        with pytest.raises(ResourceLimitError) as exc:
            normalize_image_dpi(huge_png, dst)
        assert exc.value.key == "image_megapixels"
        assert not dst.exists()
        assert list(tmp_path.glob(".pdfhanko-*.tmp")) == []

    def test_check_image_file(self, huge_png: Path, hanko_png: Path) -> None:
        check_image_file(hanko_png)
        with pytest.raises(ResourceLimitError):
            check_image_file(huge_png)

    def test_image_file_size(self, hanko_png: Path, tmp_path: Path) -> None:
        with pytest.raises(ResourceLimitError) as exc:
            # 1 MB 未満のファイルでも、上限を 0 に近づけると拒否されることを
            # 確かめるため、ファイルを 1 MB 超に水増しする。
            padded = tmp_path / "padded.png"
            padded.write_bytes(hanko_png.read_bytes() + b"\0" * (MB + 1))
            check_image_file(padded, ResourceLimits(image_file_mb=1))
        assert exc.value.key == "image_file_mb"

    def test_raise_above_pillow_default(self, tmp_path: Path) -> None:
        """設定を上げれば、Pillow 標準の上限を超える画像も処理できる。"""
        old = Image.MAX_IMAGE_PIXELS
        Image.MAX_IMAGE_PIXELS = 1000  # Pillow 標準の上限を小さくして再現する
        try:
            src = tmp_path / "src.png"
            Image.new("L", (100, 100), 255).save(src)  # 10,000 px > 2 × 1,000
            dst = tmp_path / "out.png"
            normalize_image_dpi(src, dst, limits=ResourceLimits(image_megapixels=1))
            assert dst.exists()
            assert Image.MAX_IMAGE_PIXELS == 1000  # 元の値に戻っている
        finally:
            Image.MAX_IMAGE_PIXELS = old

    def test_store_add_rejects_and_cleans_up(
        self, huge_png: Path, p12_file: Path, tmp_path: Path,
    ) -> None:
        base = tmp_path / "PdfHanko"
        store = HankoStore(base_dir=base)
        store.load()
        with pytest.raises(ResourceLimitError):
            store.add("テスト", 24.0, "", huge_png, p12_file)
        assert store.hankos == []
        assert list((base / "hankos").iterdir()) == []

    def test_store_update_rejects_without_changes(
        self, huge_png: Path, hanko_png: Path, p12_file: Path, tmp_path: Path,
    ) -> None:
        store = HankoStore(base_dir=tmp_path / "PdfHanko")
        store.load()
        hanko = store.add("元の名前", 24.0, "", hanko_png, p12_file)
        with pytest.raises(ResourceLimitError):
            store.update(hanko.id, name="新しい名前", image_src=huge_png)
        assert store.hankos[0].name == "元の名前"


class TestSettingsPersistence:
    def test_limits_survive_show_field_toggle(self, tmp_path: Path) -> None:
        base = tmp_path / "PdfHanko"
        base.mkdir()
        (base / "settings.json").write_text(
            json.dumps({"show_field": False, "limits": {"pdf_pages": 123}}),
        )
        settings = AppSettings(base_dir=base)
        settings.load()
        settings.show_field = True
        settings.save()

        reloaded = AppSettings(base_dir=base)
        reloaded.load()
        assert reloaded.show_field is True
        assert reloaded.limits.pdf_pages == 123

    def test_save_writes_all_limit_keys(self, tmp_path: Path) -> None:
        settings = AppSettings(base_dir=tmp_path / "PdfHanko")
        settings.load()
        settings.save()
        data = json.loads(settings.path.read_text())
        assert set(data["limits"]) == {spec.key for spec in LIMIT_SPECS}

    def test_legacy_settings_without_limits(self, tmp_path: Path) -> None:
        base = tmp_path / "PdfHanko"
        base.mkdir()
        (base / "settings.json").write_text(json.dumps({"show_field": True}))
        settings = AppSettings(base_dir=base)
        settings.load()
        assert settings.limits == ResourceLimits()
