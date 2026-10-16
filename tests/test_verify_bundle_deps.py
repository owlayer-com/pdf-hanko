"""scripts/verify_bundle_deps.py のテスト。"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "verify_bundle_deps", ROOT / "scripts" / "verify_bundle_deps.py",
)
vbd = importlib.util.module_from_spec(_spec)
sys.modules["verify_bundle_deps"] = vbd
_spec.loader.exec_module(vbd)


LOCK = """
version = 1

[[package]]
name = "idna"
version = "3.15"

[[package]]
name = "charset-normalizer"
version = "3.4.7"

[[package]]
name = "multi"
version = "1.0"

[[package]]
name = "multi"
version = "2.0"

[[package]]
name = "pdfhanko"
source = { editable = "." }
"""


def _dist(app_packages: Path, dirname: str, name: str, version: str) -> None:
    d = app_packages / f"{dirname}.dist-info"
    d.mkdir(parents=True)
    (d / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n\nbody\n",
        encoding="utf-8",
    )


@pytest.fixture
def project(tmp_path: Path) -> dict[str, Path]:
    lock = tmp_path / "uv.lock"
    lock.write_text(LOCK, encoding="utf-8")
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "pdfhanko"\nversion = "9.9.9"\n', encoding="utf-8")
    bundle = tmp_path / "build"
    shipped = bundle / "PDF Hanko.app" / "Contents" / "Resources" / "app_packages"
    arm = bundle / "app_packages.arm64"
    for d in (shipped, arm):
        _dist(d, "idna-3.15", "idna", "3.15")
        # dist-info のディレクトリ名と METADATA の表記ゆれ (_ と -) を吸収できること
        _dist(d, "charset_normalizer-3.4.7", "charset_normalizer", "3.4.7")
        _dist(d, "multi-2.0", "Multi", "2.0")
    (shipped / "idna").mkdir()
    (shipped / "idna" / "__init__.py").write_text("x = 1\n")
    return {"lock": lock, "pyproject": pyproject, "bundle": bundle, "shipped": shipped, "arm": arm}


def _run(project: dict[str, Path], *extra: str) -> int:
    return vbd.main([
        "--lock", str(project["lock"]),
        "--bundle", str(project["bundle"]),
        "--pyproject", str(project["pyproject"]),
        *extra,
    ])


def test_matching_bundle_passes(project) -> None:
    assert _run(project) == 0


def test_version_mismatch_fails(project, capsys) -> None:
    (project["arm"] / "idna-3.15.dist-info").rename(project["arm"] / "idna-3.16.dist-info")
    (project["arm"] / "idna-3.16.dist-info" / "METADATA").write_text(
        "Name: idna\nVersion: 3.16\n", encoding="utf-8",
    )
    assert _run(project) == 1
    err = capsys.readouterr().err
    assert "app_packages.arm64: idna==3.16 (uv.lock: 3.15)" in err


def test_package_missing_from_lock_fails(project, capsys) -> None:
    _dist(project["shipped"], "extra-1.0", "extra", "1.0")
    assert _run(project) == 1
    assert "extra==1.0 は uv.lock にありません" in capsys.readouterr().err


def test_missing_bundle(tmp_path: Path, project) -> None:
    assert vbd.main(["--lock", str(project["lock"]), "--bundle", str(tmp_path / "none")]) == 2


def test_manifest(project, tmp_path: Path) -> None:
    out = tmp_path / "dist" / "manifest.json"
    assert _run(project, "--manifest", str(out)) == 0
    manifest = json.loads(out.read_text(encoding="utf-8"))
    assert manifest["app_version"] == "9.9.9"
    assert {p["name"] for p in manifest["packages"]} == {"idna", "charset-normalizer", "multi"}
    by_path = {f["path"]: f for f in manifest["files"]}
    assert by_path["idna/__init__.py"]["sha256"] == hashlib.sha256(b"x = 1\n").hexdigest()
    assert by_path["idna/__init__.py"]["size"] == 6
    assert len(manifest["uv_lock_sha256"]) == 64


def test_manifest_not_written_on_mismatch(project, tmp_path: Path) -> None:
    _dist(project["shipped"], "extra-1.0", "extra", "1.0")
    out = tmp_path / "manifest.json"
    assert _run(project, "--manifest", str(out)) == 1
    assert not out.exists()


def test_constraints_file_matches_lock() -> None:
    """constraints-macos.txt が uv.lock から生成した内容と一致していること。"""
    constraints = (ROOT / "constraints-macos.txt").read_text(encoding="utf-8")
    locked = vbd.load_locked_versions(ROOT / "uv.lock")
    pins = [
        line.split(";")[0].strip()
        for line in constraints.splitlines()
        if line and not line.startswith((" ", "#"))
    ]
    assert pins, "constraints-macos.txt が空です"
    for pin in pins:
        name, version = pin.split("==")
        assert version in locked[vbd.normalize_name(name)], pin
    assert "std-nslog==" in constraints
