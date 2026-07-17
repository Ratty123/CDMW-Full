from __future__ import annotations

import ast
import hashlib
import json
import struct
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from cdmw.core import archive_binary_preview
from cdmw.core import archive_binary_preview_analysis
from cdmw.core import archive_binary_preview_corpus
from cdmw.core.common import RunCancelled
from tests.architecture_limits import DEFAULT_OWNER_FILE_LINE_LIMIT


ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_GOLDEN_SHA256 = "fe70b32d78ff8befdb1ac3c85bf9c35640f0947a242874a92a33381bc6515085"
CORPUS_GOLDEN_SHA256 = "7b2d9e51675198cf2b36372e2434df1501f31362ab74b1cfb27383d82e804ca2"


def _decl(name: bytes, declared_type: bytes, descriptor: bytes) -> bytes:
    return struct.pack("<I", len(name)) + name + struct.pack("<I", len(declared_type)) + declared_type + descriptor


def _payload() -> bytes:
    return (
        b"\xff\xff\x04\x00"
        + _decl(b"_mass", b"float", bytes.fromhex("00 00 04 00 00 00 00 00"))
        + _decl(b"_isBreakable", b"bool", bytes.fromhex("00 00 01 00 20 00 00 00"))
        + b"character/model/test.pac\x00"
    )


def _digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def test_binary_preview_exports_keep_owner_identity() -> None:
    assert (
        archive_binary_preview.build_binary_sidecar_analysis_document
        is archive_binary_preview_analysis.build_binary_sidecar_analysis_document
    )
    assert (
        archive_binary_preview.build_binary_sidecar_analysis_json
        is archive_binary_preview_analysis.build_binary_sidecar_analysis_json
    )
    assert (
        archive_binary_preview.build_binary_sidecar_corpus_report
        is archive_binary_preview_corpus.build_binary_sidecar_corpus_report
    )
    assert (
        archive_binary_preview.build_binary_sidecar_corpus_json
        is archive_binary_preview_corpus.build_binary_sidecar_corpus_json
    )


def test_binary_preview_analysis_and_corpus_goldens_are_unchanged(tmp_path: Path) -> None:
    payload = _payload()
    document = archive_binary_preview.build_binary_sidecar_analysis_document(
        payload,
        "object/test.meshinfo",
        extension=".meshinfo",
    )
    (tmp_path / "a.meshinfo").write_bytes(payload)
    (tmp_path / "b.meshinfo").write_bytes(payload)
    report = archive_binary_preview.build_binary_sidecar_corpus_report(
        (tmp_path,), discovery_limit=10, detail_scan_limit=10
    )
    report["source_paths"] = ["<source>"]

    assert _digest(document) == ANALYSIS_GOLDEN_SHA256
    assert _digest(report) == CORPUS_GOLDEN_SHA256


def test_binary_preview_corpus_keeps_cancellation_and_progress(tmp_path: Path) -> None:
    (tmp_path / "sample.meshinfo").write_bytes(_payload())
    progress: list[tuple[int, int, str]] = []
    archive_binary_preview.build_binary_sidecar_corpus_report(
        (tmp_path,),
        progress_callback=lambda current, total, message: progress.append((current, total, message)),
    )
    assert progress[0] == (0, 1, "Discovered 1 binary sidecar file(s).")
    assert progress[-1] == (1, 1, "Binary sidecar corpus report complete.")

    stop_event = threading.Event()
    stop_event.set()
    with pytest.raises(RunCancelled):
        archive_binary_preview.build_binary_sidecar_corpus_report((tmp_path,), stop_event=stop_event)


def test_binary_preview_owner_modules_obey_new_size_limits() -> None:
    moved = {
        "build_binary_sidecar_analysis_document",
        "build_binary_sidecar_analysis_json",
        "build_binary_sidecar_corpus_report",
        "build_binary_sidecar_corpus_json",
        "_build_binary_sidecar_corpus_extension_report",
    }
    facade_path = ROOT / "cdmw" / "core" / "archive_binary_preview.py"
    facade_tree = ast.parse(facade_path.read_text(encoding="utf-8-sig"))
    definitions = {
        node.name
        for node in facade_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    assert definitions.isdisjoint(moved)
    assert len(facade_path.read_text(encoding="utf-8-sig").splitlines()) <= 3_177

    for name in ("archive_binary_preview_analysis.py", "archive_binary_preview_corpus.py"):
        path = ROOT / "cdmw" / "core" / name
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source)
        functions = [
            node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        assert len(source.splitlines()) <= DEFAULT_OWNER_FILE_LINE_LIMIT, path
        assert max((node.end_lineno - node.lineno + 1 for node in functions), default=0) <= 150, path


def test_binary_preview_owner_first_and_facade_first_imports_keep_identity() -> None:
    owner_first = (
        "import cdmw.core.archive_binary_preview_analysis as analysis; "
        "import cdmw.core.archive_binary_preview_corpus as corpus; "
        "import cdmw.core.archive_binary_preview as preview; "
        "import cdmw.core.archive as compat; "
    )
    facade_first = (
        "import cdmw.core.archive as compat; "
        "import cdmw.core.archive_binary_preview as preview; "
        "import cdmw.core.archive_binary_preview_corpus as corpus; "
        "import cdmw.core.archive_binary_preview_analysis as analysis; "
    )
    assertions = (
        "assert preview.build_binary_sidecar_analysis_document is analysis.build_binary_sidecar_analysis_document; "
        "assert compat.build_binary_sidecar_analysis_document is analysis.build_binary_sidecar_analysis_document; "
        "assert preview.build_binary_sidecar_corpus_report is corpus.build_binary_sidecar_corpus_report; "
        "assert compat.build_binary_sidecar_corpus_report is corpus.build_binary_sidecar_corpus_report"
    )
    for imports in (owner_first, facade_first):
        result = subprocess.run(
            [sys.executable, "-c", imports + assertions],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stderr or result.stdout
