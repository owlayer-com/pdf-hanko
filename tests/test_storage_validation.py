"""HankoStore の hankos.json 検証とパス検証に関するテスト。"""
from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import pytest

from pdfhanko.fileutil import UnsafePathError
from pdfhanko.storage import CERT_TYPE_JPKI, HankoStore, hanko_dir


def _entry(hanko_id: str | None = None, **overrides) -> dict:
    """v0.3.0 が書き出す形式の正常な PKCS#12 エントリを返す。"""
    hanko_id = hanko_id or uuid.uuid4().hex
    entry = {
        "id": hanko_id,
        "name": "テスト",
        "size_mm": 24.0,
        "memo": "",
        "image": f"hankos/{hanko_id}/image.png",
        "cert": f"hankos/{hanko_id}/cert.p12",
        "cert_type": "pkcs12",
        "jpki_cert_serial": None,
        "jpki_cert_subject_cn": None,
    }
    entry.update(overrides)
    return entry


def _jpki_entry(hanko_id: str | None = None, **overrides) -> dict:
    hanko_id = hanko_id or uuid.uuid4().hex
    entry = _entry(
        hanko_id,
        cert="",
        cert_type="jpki",
        jpki_cert_serial="1A2B3C",
        jpki_cert_subject_cn="山田 太郎",
    )
    entry.update(overrides)
    return entry


@pytest.fixture
def base_dir(tmp_path: Path) -> Path:
    base = tmp_path / "PdfHanko"
    base.mkdir()
    return base


def _write_index(base: Path, data) -> Path:
    path = base / "hankos.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def _load(base: Path) -> HankoStore:
    store = HankoStore(base_dir=base)
    store.load()
    return store


class TestValidEntries:
    def test_v030_format_is_loaded(self, base_dir: Path) -> None:
        entries = [_entry(), _jpki_entry()]
        _write_index(base_dir, entries)
        store = _load(base_dir)
        assert [h.id for h in store.hankos] == [e["id"] for e in entries]
        assert store.load_problems == []

    def test_v02_format_without_cert_type(self, base_dir: Path) -> None:
        entry = _entry()
        for key in ("cert_type", "jpki_cert_serial", "jpki_cert_subject_cn"):
            del entry[key]
        _write_index(base_dir, [entry])
        store = _load(base_dir)
        assert len(store.hankos) == 1
        assert store.hankos[0].cert_type == "pkcs12"

    def test_unknown_fields_are_ignored(self, base_dir: Path) -> None:
        _write_index(base_dir, [_entry(future_field="x")])
        assert len(_load(base_dir).hankos) == 1

    def test_integer_size_is_accepted(self, base_dir: Path) -> None:
        _write_index(base_dir, [_entry(size_mm=24)])
        store = _load(base_dir)
        assert store.hankos[0].size_mm == 24.0

    def test_paths_are_built_from_id(self, base_dir: Path) -> None:
        entry = _entry()
        _write_index(base_dir, [entry])
        hanko = _load(base_dir).hankos[0]
        assert hanko.image_path(base_dir) == base_dir / "hankos" / entry["id"] / "image.png"
        assert hanko.cert_path(base_dir) == base_dir / "hankos" / entry["id"] / "cert.p12"


class TestInvalidEntries:
    @pytest.mark.parametrize(
        "bad_id",
        ["../../tmp/x", "/etc", "abc", "0" * 31, "0" * 33, "G" * 32, "A" * 32, 123, None],
    )
    def test_bad_id(self, base_dir: Path, bad_id) -> None:
        good = _entry()
        bad = _entry()
        bad["id"] = bad_id
        _write_index(base_dir, [bad, good])
        store = _load(base_dir)
        assert [h.id for h in store.hankos] == [good["id"]]
        assert len(store.load_problems) == 1

    @pytest.mark.parametrize("bad_image", ["/etc/passwd", "../x", "hankos/other/image.png", 1])
    def test_bad_image_path(self, base_dir: Path, bad_image) -> None:
        _write_index(base_dir, [_entry(image=bad_image)])
        assert _load(base_dir).hankos == []

    @pytest.mark.parametrize("bad_cert", ["/etc/passwd", "../x.p12", ""])
    def test_bad_cert_path(self, base_dir: Path, bad_cert) -> None:
        _write_index(base_dir, [_entry(cert=bad_cert)])
        assert _load(base_dir).hankos == []

    def test_jpki_with_cert_path(self, base_dir: Path) -> None:
        hanko_id = uuid.uuid4().hex
        _write_index(base_dir, [_jpki_entry(hanko_id, cert=f"hankos/{hanko_id}/cert.p12")])
        assert _load(base_dir).hankos == []

    def test_jpki_without_serial(self, base_dir: Path) -> None:
        _write_index(base_dir, [_jpki_entry(jpki_cert_serial=None)])
        assert _load(base_dir).hankos == []

    @pytest.mark.parametrize(
        "overrides",
        [
            {"size_mm": "abc"},
            {"size_mm": True},
            {"size_mm": 0},
            {"size_mm": -1},
            {"size_mm": float("inf")},
            {"name": None},
            {"memo": 1},
            {"cert_type": "pkcs11"},
            {"jpki_cert_serial": "XYZ"},
            {"jpki_cert_subject_cn": 1},
        ],
    )
    def test_bad_types(self, base_dir: Path, overrides: dict) -> None:
        # inf は json.dumps で Infinity として書き出され、json.loads で読める。
        _write_index(base_dir, [_entry(**overrides)])
        assert _load(base_dir).hankos == []

    def test_missing_required_field(self, base_dir: Path) -> None:
        entry = _entry()
        del entry["name"]
        _write_index(base_dir, [entry])
        assert _load(base_dir).hankos == []

    def test_non_object_entry(self, base_dir: Path) -> None:
        good = _entry()
        _write_index(base_dir, ["string", 1, None, good])
        store = _load(base_dir)
        assert [h.id for h in store.hankos] == [good["id"]]

    def test_duplicate_id(self, base_dir: Path) -> None:
        entry = _entry()
        _write_index(base_dir, [entry, dict(entry, name="重複")])
        store = _load(base_dir)
        assert [h.name for h in store.hankos] == ["テスト"]
        assert store.load_problems

    def test_symlinked_hanko_dir_is_skipped(self, base_dir: Path, tmp_path: Path) -> None:
        entry = _entry()
        outside = tmp_path / "outside"
        outside.mkdir()
        (base_dir / "hankos").mkdir()
        (base_dir / "hankos" / entry["id"]).symlink_to(outside)
        _write_index(base_dir, [entry])
        assert _load(base_dir).hankos == []

    def test_symlinked_cert_file_is_skipped(self, base_dir: Path, tmp_path: Path) -> None:
        entry = _entry()
        secret = tmp_path / "secret.txt"
        secret.write_text("secret")
        d = base_dir / "hankos" / entry["id"]
        d.mkdir(parents=True)
        (d / "cert.p12").symlink_to(secret)
        _write_index(base_dir, [entry])
        assert _load(base_dir).hankos == []


class TestBrokenIndex:
    @pytest.mark.parametrize("content", ["{not json", '{"a": 1}', '"text"', "\udcff"])
    def test_broken_index_does_not_raise(self, base_dir: Path, content: str) -> None:
        path = base_dir / "hankos.json"
        path.write_bytes(content.encode("utf-8", "surrogateescape"))
        store = _load(base_dir)
        assert store.hankos == []
        assert store.load_problems
        # 読み込むだけでは元ファイルを変更しない。
        assert path.read_bytes() == content.encode("utf-8", "surrogateescape")

    def test_save_backs_up_broken_index(
        self, base_dir: Path, hanko_png: Path, p12_file: Path,
    ) -> None:
        path = base_dir / "hankos.json"
        path.write_text("{not json", encoding="utf-8")
        store = _load(base_dir)
        store.add("新規", 24.0, "", hanko_png, p12_file)

        backups = list(base_dir.glob("hankos.json.*.bak"))
        assert len(backups) == 1
        assert backups[0].read_text(encoding="utf-8") == "{not json"
        assert len(json.loads(path.read_text(encoding="utf-8"))) == 1

        # 退避は 1 回だけ。以降の保存では増えない。
        store.add("新規 2", 24.0, "", hanko_png, p12_file)
        assert len(list(base_dir.glob("hankos.json.*.bak"))) == 1

    def test_save_backs_up_when_entries_were_skipped(
        self, base_dir: Path, hanko_png: Path, p12_file: Path,
    ) -> None:
        bad = _entry(image="/etc/passwd")
        _write_index(base_dir, [bad])
        store = _load(base_dir)
        store.add("新規", 24.0, "", hanko_png, p12_file)
        backups = list(base_dir.glob("hankos.json.*.bak"))
        assert len(backups) == 1
        assert json.loads(backups[0].read_text(encoding="utf-8")) == [bad]

    def test_no_backup_when_index_is_valid(
        self, base_dir: Path, hanko_png: Path, p12_file: Path,
    ) -> None:
        _write_index(base_dir, [])
        store = _load(base_dir)
        store.add("新規", 24.0, "", hanko_png, p12_file)
        assert list(base_dir.glob("hankos.json.*.bak")) == []


class TestHankoDir:
    def test_rejects_bad_id(self, base_dir: Path) -> None:
        with pytest.raises(UnsafePathError):
            hanko_dir(base_dir, "../x")

    def test_rejects_symlinked_hankos(self, base_dir: Path, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        (base_dir / "hankos").symlink_to(outside)
        with pytest.raises(UnsafePathError):
            hanko_dir(base_dir, uuid.uuid4().hex)

    def test_allows_symlinked_base(self, tmp_path: Path) -> None:
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "PdfHanko"
        link.symlink_to(real)
        hanko_id = uuid.uuid4().hex
        assert hanko_dir(link, hanko_id) == link / "hankos" / hanko_id


class TestRemove:
    def test_rmtree_is_symlink_safe(self) -> None:
        assert shutil.rmtree.avoids_symlink_attacks

    def test_remove_deletes_hanko_dir(
        self, base_dir: Path, hanko_png: Path, p12_file: Path,
    ) -> None:
        store = _load(base_dir)
        hanko = store.add("テスト", 24.0, "", hanko_png, p12_file)
        store.remove(hanko.id)
        assert not (base_dir / "hankos" / hanko.id).exists()
        assert _load(base_dir).hankos == []

    def test_remove_does_not_follow_symlinked_dir(
        self, base_dir: Path, hanko_png: Path, p12_file: Path, tmp_path: Path,
    ) -> None:
        store = _load(base_dir)
        hanko = store.add("テスト", 24.0, "", hanko_png, p12_file)

        # 読み込み後にハンコ専用ディレクトリが外部へのリンクに差し替えられた。
        outside = tmp_path / "outside"
        outside.mkdir()
        victim = outside / "important.txt"
        victim.write_text("keep")
        d = base_dir / "hankos" / hanko.id
        shutil.rmtree(d)
        d.symlink_to(outside)

        with pytest.raises(UnsafePathError):
            store.remove(hanko.id)
        assert victim.read_text() == "keep"
        assert [h.id for h in _load(base_dir).hankos] == []  # リンクのため読み込まれない
        assert [h.id for h in store.hankos] == [hanko.id]  # メモリ上も変更しない


class TestUpdate:
    def test_switch_to_jpki_removes_cert(
        self, base_dir: Path, hanko_png: Path, p12_file: Path,
    ) -> None:
        store = _load(base_dir)
        hanko = store.add("テスト", 24.0, "", hanko_png, p12_file)
        cert = base_dir / "hankos" / hanko.id / "cert.p12"
        assert cert.exists()
        store.update(hanko.id, cert_type=CERT_TYPE_JPKI, jpki_cert_serial="ABCDEF")
        assert not cert.exists()
        reloaded = _load(base_dir)
        assert reloaded.hankos[0].cert_type == CERT_TYPE_JPKI
        assert reloaded.load_problems == []
