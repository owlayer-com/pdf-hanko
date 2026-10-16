"""Briefcase のビルド成果物に同梱された依存パッケージを uv.lock と照合する。

リリース前に ``briefcase build macOS`` の後で実行し、配布物に入るパッケージの
バージョンがソースの ``uv.lock`` と一致することを確認する。

照合対象 (存在するものすべて):

- ``<bundle>/<アプリ>.app/Contents/Resources/app_packages`` (実際に配布される)
- ``<bundle>/app_packages.arm64`` / ``app_packages.x86_64`` (ユニバーサル
  ビルドの各アーキテクチャのインストール結果)

不一致 (lock にないパッケージ、またはバージョン違い) があれば一覧を出して
終了コード 1 で終わる。``--manifest`` を指定すると、配布される
``app_packages`` のパッケージ一覧と全ファイルの SHA-256 を JSON で書き出す。

使い方::

    uv run python scripts/verify_bundle_deps.py
    uv run python scripts/verify_bundle_deps.py --manifest dist/bundle-manifest-0.3.1.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from email.parser import HeaderParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOCK = ROOT / "uv.lock"
DEFAULT_BUNDLE = ROOT / "build" / "pdfhanko" / "macos" / "app"
DEFAULT_PYPROJECT = ROOT / "pyproject.toml"


def normalize_name(name: str) -> str:
    """PEP 503 に従ってパッケージ名を正規化する (``Foo_Bar`` → ``foo-bar``)。"""
    return re.sub(r"[-_.]+", "-", name).lower()


@dataclass(frozen=True)
class InstalledPackage:
    name: str
    version: str
    dist_info: Path


@dataclass(frozen=True)
class Mismatch:
    location: str
    name: str
    version: str
    locked_versions: tuple[str, ...]

    def describe(self) -> str:
        if not self.locked_versions:
            return f"{self.location}: {self.name}=={self.version} は uv.lock にありません"
        locked = ", ".join(self.locked_versions)
        return f"{self.location}: {self.name}=={self.version} (uv.lock: {locked})"


def load_locked_versions(lock_path: Path) -> dict[str, set[str]]:
    """uv.lock からパッケージ名 → バージョン集合を作る。

    環境マーカーによって同じパッケージが複数バージョン登録されることが
    あるため、集合で持つ。
    """
    with lock_path.open("rb") as f:
        lock = tomllib.load(f)
    versions: dict[str, set[str]] = {}
    for pkg in lock.get("package", []):
        if "version" not in pkg:
            continue
        versions.setdefault(normalize_name(pkg["name"]), set()).add(pkg["version"])
    return versions


def find_installed_packages(app_packages: Path) -> list[InstalledPackage]:
    """``app_packages`` 内の ``*.dist-info/METADATA`` からパッケージ一覧を作る。"""
    packages = []
    for dist_info in sorted(app_packages.glob("*.dist-info")):
        metadata = dist_info / "METADATA"
        if not metadata.is_file():
            continue
        headers = HeaderParser().parsestr(metadata.read_text(encoding="utf-8", errors="replace"))
        name, version = headers.get("Name"), headers.get("Version")
        if not name or not version:
            continue
        packages.append(InstalledPackage(normalize_name(name), version, dist_info))
    return packages


def find_app_packages_dirs(bundle: Path) -> dict[str, Path]:
    """照合対象の ``app_packages`` ディレクトリを探す (表示名 → パス)。"""
    dirs: dict[str, Path] = {}
    for app in sorted(bundle.glob("*.app")):
        shipped = app / "Contents" / "Resources" / "app_packages"
        if shipped.is_dir():
            dirs[f"{app.name} (配布物)"] = shipped
    for arch_dir in sorted(bundle.glob("app_packages.*")):
        if arch_dir.is_dir():
            dirs[arch_dir.name] = arch_dir
    return dirs


def check(app_packages_dirs: dict[str, Path], locked: dict[str, set[str]]) -> list[Mismatch]:
    """各 ``app_packages`` のパッケージを uv.lock と照合し、不一致を返す。"""
    mismatches = []
    for location, path in app_packages_dirs.items():
        for pkg in find_installed_packages(path):
            versions = locked.get(pkg.name, set())
            if pkg.version not in versions:
                mismatches.append(
                    Mismatch(location, pkg.name, pkg.version, tuple(sorted(versions))),
                )
    return mismatches


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(app_packages: Path, lock_path: Path, pyproject: Path) -> dict:
    """配布される ``app_packages`` のパッケージ一覧と全ファイルの SHA-256 を作る。

    ハッシュは dist-info の ``RECORD`` ではなく、実際のファイルから計算する。
    """
    with pyproject.open("rb") as f:
        app_version = tomllib.load(f).get("project", {}).get("version")
    files = [
        {
            "path": p.relative_to(app_packages).as_posix(),
            "size": p.stat().st_size,
            "sha256": sha256_file(p),
        }
        for p in sorted(app_packages.rglob("*"))
        if p.is_file() and not p.is_symlink()
    ]
    return {
        "app_version": app_version,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "uv_lock_sha256": sha256_file(lock_path),
        "packages": [
            {"name": pkg.name, "version": pkg.version}
            for pkg in find_installed_packages(app_packages)
        ],
        "files": files,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK, help="uv.lock のパス")
    parser.add_argument(
        "--bundle", type=Path, default=DEFAULT_BUNDLE,
        help="Briefcase の macOS ビルドディレクトリ (build/pdfhanko/macos/app)",
    )
    parser.add_argument("--pyproject", type=Path, default=DEFAULT_PYPROJECT, help=argparse.SUPPRESS)
    parser.add_argument("--manifest", type=Path, help="同梱物のマニフェスト (JSON) の出力先")
    args = parser.parse_args(argv)

    dirs = find_app_packages_dirs(args.bundle)
    if not dirs:
        print(f"ERROR: app_packages が見つかりません: {args.bundle}", file=sys.stderr)
        return 2

    locked = load_locked_versions(args.lock)
    for location, path in dirs.items():
        print(f"照合: {location}: {len(find_installed_packages(path))} パッケージ")
    mismatches = check(dirs, locked)
    sys.stdout.flush()
    if mismatches:
        print(f"\nNG: uv.lock と一致しないパッケージが {len(mismatches)} 件あります", file=sys.stderr)
        for m in mismatches:
            print(f"  - {m.describe()}", file=sys.stderr)
        return 1
    print("OK: すべての同梱パッケージが uv.lock と一致しました")

    if args.manifest:
        shipped = next((p for loc, p in dirs.items() if loc.endswith("(配布物)")), None)
        if shipped is None:
            print("ERROR: 配布物の app_packages が見つからないためマニフェストを作れません", file=sys.stderr)
            return 2
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest = build_manifest(shipped, args.lock, args.pyproject)
        args.manifest.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        print(
            f"マニフェスト: {args.manifest} "
            f"({len(manifest['packages'])} パッケージ, {len(manifest['files'])} ファイル)",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
