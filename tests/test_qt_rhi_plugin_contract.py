"""The Qt Quick RHI viewport plugin must be pinned to the Qt PySide6 ships.

The Mesh Editor viewport is moving from an embedded child window to a node
inside Qt Quick's scene graph. That node calls QRhi, which lives in Qt's
GuiPrivate module, and Qt's own build system says what that costs:

    This project is using headers of the GuiPrivate module and will therefore be
    tied to this specific Qt module build version. Running this project against
    other versions of the Qt modules may crash at any arbitrary point.

So the plugin is only valid against the exact Qt inside the installed PySide6
wheel. A mismatch does not fail loudly, it corrupts at some later arbitrary
point, which is the kind of thing that has to be caught by a gate rather than by
a person. These tests hold the pin in place; the ones that need a built plugin
skip when it has not been built, so the suite stays runnable without a C++
toolchain.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "native" / "cdmw_qt_rhi"
BUILD_QML = PLUGIN_DIR / "build" / "qml"
VENDOR_ROOT = ROOT / "third_party" / "qt"
VENDOR_SCRIPT = ROOT / "scripts" / "vendor_qt_sdk.py"
BUILD_SCRIPT = ROOT / "scripts" / "build_qt_rhi_plugin.ps1"


def _pyside_qt_version() -> str:
    from PySide6 import QtCore

    return QtCore.qVersion()


def test_the_vendoring_and_build_entry_points_exist() -> None:
    """Without these the pin is a comment rather than a mechanism."""

    assert VENDOR_SCRIPT.is_file(), "scripts/vendor_qt_sdk.py is missing"
    assert BUILD_SCRIPT.is_file(), "scripts/build_qt_rhi_plugin.ps1 is missing"
    assert (PLUGIN_DIR / "CMakeLists.txt").is_file()
    assert (PLUGIN_DIR / "rhitriangle.cpp").is_file()


def test_the_build_refuses_a_qt_that_does_not_match_pyside() -> None:
    """The guard has to be in the build, not only in the wrapper script."""

    cmake = (PLUGIN_DIR / "CMakeLists.txt").read_text(encoding="utf-8")
    assert "CDMW_EXPECTED_QT_VERSION" in cmake
    assert "FATAL_ERROR" in cmake, (
        "a Qt version mismatch must fail the build; a warning would be read "
        "past and the crash it causes appears somewhere else entirely"
    )


def test_the_vendored_qt_is_not_committed() -> None:
    """It is ~2 GB and reproducible from the version PySide6 already pins."""

    ignored = subprocess.run(
        ["git", "check-ignore", "third_party/qt/x"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert ignored.returncode == 0, (
        "third_party/qt must be git-ignored; a vendored Qt SDK does not belong "
        "in the history"
    )


@pytest.mark.skipif(not VENDOR_ROOT.is_dir(), reason="Qt SDK not vendored on this machine")
def test_the_vendored_qt_matches_pyside() -> None:
    versions = [p.name for p in VENDOR_ROOT.iterdir() if p.is_dir() and p.name[0].isdigit()]
    if not versions:
        pytest.skip("no vendored Qt versions present")
    assert _pyside_qt_version() in versions, (
        f"PySide6 ships Qt {_pyside_qt_version()} but only {versions} are "
        "vendored; the plugin would be built against the wrong Qt"
    )


@pytest.mark.skipif(not VENDOR_ROOT.is_dir(), reason="Qt SDK not vendored on this machine")
def test_the_vendor_manifest_records_verified_hashes() -> None:
    """Every archive is checked against the sha256 Qt publishes beside it."""

    manifests = list(VENDOR_ROOT.glob("*/vendor-manifest.json"))
    if not manifests:
        pytest.skip("no vendor manifest present")
    payload = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert payload["archives"], "manifest records no archives"
    unverified = [
        a["archive"]
        for a in payload["archives"]
        if not a.get("sha256_verified_against_publisher")
    ]
    assert not unverified, f"archives vendored without a verified hash: {unverified}"


@pytest.mark.skipif(not (BUILD_QML / "CdmwQtRhi").is_dir(), reason="plugin not built")
def test_the_built_plugin_loads_renders_and_exits() -> None:
    """The whole point: it draws, and it lets the process go.

    The pure-Python QQuickRhiItem rendered correctly and then hung forever,
    which is what sent this to C++ in the first place. A renderer that stops the
    workbench from closing is worse than the flicker it was meant to fix.
    """

    harness = ROOT / "tests" / "data" / "qt_rhi_plugin_probe.py"
    if not harness.is_file():
        pytest.skip("probe harness not present")

    # Let Qt choose a real platform where there is one. The offscreen plugin has
    # no surface to present to, so it can prove loading and teardown but never
    # rendering.
    env = dict(os.environ)
    env.pop("QT_QPA_PLATFORM", None)

    result = subprocess.run(
        [sys.executable, "-u", str(harness), str(BUILD_QML)],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    # The timeout above is the real assertion for teardown: the pure-Python
    # renderer never returned from app.exec() at all.
    assert result.returncode == 0, (
        f"probe failed ({result.returncode}):\n{result.stdout}\n{result.stderr}"
    )
    assert "loaded=yes" in result.stdout, (
        f"the QML engine rejected the plugin:\n{result.stdout}\n{result.stderr}"
    )

    frames = int(result.stdout.split("frames=")[1].split()[0])
    platform = result.stdout.split("platform=")[1].strip()
    if platform == "offscreen":
        pytest.skip("offscreen platform has no surface; load and exit verified")
    assert frames > 0, f"the plugin loaded but never rendered:\n{result.stdout}"
