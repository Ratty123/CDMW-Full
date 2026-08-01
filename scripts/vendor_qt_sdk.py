"""Fetch the Qt SDK that matches the Qt PySide6 already ships.

The Mesh Editor viewport is moving to a C++ ``QQuickRhiItem`` so the 3D renderer
can be a node inside Qt Quick's scene graph. That item calls QRhi, which lives
in Qt's ``GuiPrivate`` module, and Qt excludes private modules from its binary
compatibility promise -- its own build system says so out loud:

    This project is using headers of the GuiPrivate module and will therefore be
    tied to this specific Qt module build version. Running this project against
    other versions of the Qt modules may crash at any arbitrary point.

So the plugin must be compiled against exactly the Qt that will load it, which
is the Qt inside the installed PySide6 wheel, and that pairing has to be
reproducible on every machine and in CI rather than something a developer sets
up by hand.

``aqtinstall`` cannot do this job. From Qt 6.10 the repository moved to a nested
per-toolchain layout (``qt6_6111/qt6_6111_msvc2022_64/``) and stopped publishing
the ``Updates.xml.sha256`` sidecar that aqt insists on; aqt 3.3.0, the current
release, builds ``qt6_6111/qt6_6111/`` and fails before it downloads anything.

Only the *index* sidecar went away. Every archive still publishes its own
``.sha256`` beside it, which is what this script verifies against -- a stronger
check than the SHA-1 in ``Updates.xml``, which covers package metadata rather
than the archive you actually download.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DEST = REPO_ROOT / "third_party" / "qt"
QT_REPO = "https://download.qt.io/online/qtsdkrepository"
# qtbase carries QtCore/QtGui (and the versioned rhi/qrhi.h); qtdeclarative
# carries QtQuick and QQuickRhiItem; qtshadertools carries qsb, which the plugin
# build runs to compile its shaders.
REQUIRED_ARCHIVES = ("qtbase", "qtdeclarative", "qtshadertools")
USER_AGENT = "cdmw-vendor-qt-sdk"


class VendorError(RuntimeError):
    """Anything that should stop the vendoring with a readable message."""


@dataclass(frozen=True)
class Archive:
    package: str
    version: str
    name: str
    sha1: str

    @property
    def url_suffix(self) -> str:
        # Qt concatenates the package version directly onto the archive name.
        return f"{self.package}/{self.version}{self.name}"


def detect_pyside_qt_version(python: str | None = None) -> str:
    """Ask the interpreter that will run the app which Qt it bundles."""

    executable = python or sys.executable
    try:
        out = subprocess.run(
            [executable, "-c", "from PySide6 import QtCore; print(QtCore.qVersion())"],
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise VendorError(f"Could not ask {executable} for its Qt version: {exc}") from exc
    version = out.stdout.strip()
    if not version:
        raise VendorError(f"{executable} reported no Qt version")
    return version


def toolchain_folder_suffix(arch: str) -> str:
    """The directory name Qt uses for a toolchain, which is not the arch id.

    The published architecture is ``win64_msvc2022_64`` but the directory is
    ``qt6_6111_msvc2022_64``: the platform-width prefix is dropped. Package names
    *inside* Updates.xml keep the full id, so only the path needs this.
    """

    for prefix in ("win64_", "win32_"):
        if arch.startswith(prefix):
            return arch[len(prefix) :]
    return arch


def repository_url(qt_version: str, host: str, target: str, arch: str) -> str:
    """The nested per-toolchain directory Qt has used since 6.10."""

    flat = qt_version.replace(".", "")
    folder = f"qt6_{flat}"
    return f"{QT_REPO}/{host}/{target}/{folder}/{folder}_{toolchain_folder_suffix(arch)}/"


def _get(url: str, timeout: int = 120) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return response.read()


def read_updates_xml(base_url: str) -> ET.Element:
    try:
        payload = _get(base_url + "Updates.xml")
    except Exception as exc:  # urllib raises a wide family
        raise VendorError(
            f"Could not read {base_url}Updates.xml -- if this 404s, Qt has "
            f"changed its repository layout again: {exc}"
        ) from exc
    return ET.fromstring(payload)


def select_archives(root: ET.Element, arch: str) -> list[Archive]:
    """Pick the smallest set of archives that can build the plugin."""

    found: list[Archive] = []
    for package in root.findall("PackageUpdate"):
        name = (package.findtext("Name") or "").strip()
        if not name.endswith(arch) or "debug" in name:
            continue
        version = (package.findtext("Version") or "").strip()
        sha1 = (package.findtext("SHA1") or "").strip()
        archives = (package.findtext("DownloadableArchives") or "").strip()
        for entry in (a.strip() for a in archives.split(",") if a.strip()):
            if any(entry.startswith(wanted + "-") for wanted in REQUIRED_ARCHIVES):
                found.append(Archive(name, version, entry, sha1))
    missing = [
        wanted
        for wanted in REQUIRED_ARCHIVES
        if not any(a.name.startswith(wanted + "-") for a in found)
    ]
    if missing:
        raise VendorError(
            "Qt's package index did not offer " + ", ".join(missing) + " for this "
            "architecture; the plugin cannot be built against it."
        )
    return found


def download(base_url: str, archive: Archive, cache: Path) -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / archive.name
    if target.is_file():
        print(f"  cached  {archive.name}")
        return target
    url = base_url + archive.url_suffix
    print(f"  fetch   {archive.name}")
    payload = _get(url, timeout=900)
    target.write_bytes(payload)
    return target


def published_sha256(base_url: str, archive: Archive) -> str:
    """The hash Qt publishes beside the archive itself."""

    try:
        return _get(base_url + archive.url_suffix + ".sha256", timeout=120).decode().split()[0]
    except Exception:  # the sidecar is the check, not the download
        return ""


def verify(path: Path, expected_sha256: str) -> tuple[bool, str]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return bool(expected_sha256) and digest.lower() == expected_sha256.lower(), digest


def extract(archive_path: Path, dest: Path) -> None:
    try:
        import py7zr
    except ImportError as exc:
        raise VendorError(
            "py7zr is required to unpack the Qt archives: pip install py7zr"
        ) from exc
    with py7zr.SevenZipFile(archive_path, mode="r") as bundle:
        bundle.extractall(path=dest)


def vendor(
    qt_version: str,
    dest: Path,
    host: str,
    target: str,
    arch: str,
    keep_cache: bool,
) -> Path:
    base_url = repository_url(qt_version, host, target, arch)
    print(f"Qt {qt_version} ({arch})")
    print(f"  index   {base_url}Updates.xml")
    archives = select_archives(read_updates_xml(base_url), arch)

    cache = dest / ".cache" / qt_version
    staging = dest / ".staging" / qt_version
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)

    manifest: list[dict[str, object]] = []
    for archive in archives:
        path = download(base_url, archive, cache)
        expected = published_sha256(base_url, archive)
        ok, digest = verify(path, expected)
        if expected and not ok:
            raise VendorError(
                f"{archive.name} does not match the sha256 Qt publishes for it "
                f"(got {digest}, expected {expected}). Refusing to vendor it."
            )
        print(f"  {'verified' if ok else 'NO HASH '} {archive.name}")
        extract(path, staging)
        manifest.append(
            {
                "package": archive.package,
                "archive": archive.name,
                "package_version": archive.version,
                "sha256": digest,
                "sha256_verified_against_publisher": ok,
            }
        )

    # The archives unpack straight to the prefix root: bin/, include/, lib/, qml/.
    if not (staging / "include").is_dir() or not (staging / "lib").is_dir():
        raise VendorError(
            f"Expected a Qt prefix (include/, lib/) in {staging}; layout changed."
        )
    final = dest / qt_version / arch
    if final.exists():
        shutil.rmtree(final)
    final.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(staging), str(final))
    shutil.rmtree(dest / ".staging", ignore_errors=True)
    if not keep_cache:
        shutil.rmtree(cache, ignore_errors=True)

    (dest / qt_version / "vendor-manifest.json").write_text(
        json.dumps(
            {
                "qt_version": qt_version,
                "architecture": arch,
                "host": host,
                "target": target,
                "source": base_url,
                "archives": manifest,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return final


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--qt-version",
        default="",
        help="Qt version to vendor. Defaults to the Qt that PySide6 bundles.",
    )
    parser.add_argument("--python", default="", help="Interpreter whose PySide6 to match.")
    parser.add_argument("--dest", default=str(DEFAULT_DEST), type=str)
    parser.add_argument("--host", default="windows_x86")
    parser.add_argument("--target", default="desktop")
    parser.add_argument("--arch", default="win64_msvc2022_64")
    parser.add_argument("--keep-cache", action="store_true")
    parser.add_argument(
        "--print-prefix",
        action="store_true",
        help="Print the CMAKE_PREFIX_PATH for an existing vendored Qt and exit.",
    )
    args = parser.parse_args(argv)

    try:
        qt_version = args.qt_version or detect_pyside_qt_version(args.python or None)
        dest = Path(args.dest).resolve()
        prefix = dest / qt_version / args.arch
        if args.print_prefix:
            if not prefix.is_dir():
                raise VendorError(f"No vendored Qt at {prefix}; run this script first.")
            print(prefix)
            return 0
        if prefix.is_dir():
            print(f"Qt {qt_version} already vendored at {prefix}")
            return 0
        final = vendor(
            qt_version, dest, args.host, args.target, args.arch, args.keep_cache
        )
        print(f"Vendored Qt {qt_version} -> {final}")
        return 0
    except VendorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
