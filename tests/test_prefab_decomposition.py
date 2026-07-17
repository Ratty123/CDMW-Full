from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from cdmw.core import prefab_corpus, prefab_json
from tests.architecture_limits import DEFAULT_OWNER_FILE_LINE_LIMIT


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "cdmw" / "core"


def _lp(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return len(encoded).to_bytes(4, "little") + encoded


def _payload() -> bytes:
    return (
        b"\xff\xff\x04\x00"
        + _lp("_attachedSocketName")
        + _lp("IndexedStringA")
        + b"\x01\x00\x01\x00\x10\x00\x00\x00"
        + b"\x00" * 16
        + _lp("Spine2_B_Socket")
        + _lp("character/model/test.pac")
    )


def _normalized(value: object) -> object:
    if isinstance(value, dict):
        return {key: _normalized(item) for key, item in value.items() if key != "elapsed_ms"}
    if isinstance(value, list):
        return [_normalized(item) for item in value]
    return value


def _digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def test_prefab_owner_modules_obey_new_size_limits() -> None:
    owners = sorted(CORE.glob("prefab_corpus_*.py")) + sorted(CORE.glob("prefab_json_*.py"))
    assert owners
    for path in owners:
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source)
        assert len(source.splitlines()) <= DEFAULT_OWNER_FILE_LINE_LIMIT, path
        functions = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        assert max((node.end_lineno - node.lineno + 1 for node in functions), default=0) <= 150, path
        assert not any(
            isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names)
            for node in ast.walk(tree)
        ), path


def test_prefab_facades_reexport_original_owner_objects() -> None:
    from cdmw.core.prefab_corpus_audit import audit_prefab_json_import_sample
    from cdmw.core.prefab_corpus_loading import build_prefab_json_import_corpus_report
    from cdmw.core.prefab_json_apply import apply_prefab_edit_document
    from cdmw.core.prefab_json_document import build_prefab_edit_document

    assert prefab_corpus.audit_prefab_json_import_sample is audit_prefab_json_import_sample
    assert prefab_corpus.build_prefab_json_import_corpus_report is build_prefab_json_import_corpus_report
    assert prefab_json.apply_prefab_edit_document is apply_prefab_edit_document
    assert prefab_json.build_prefab_edit_document is build_prefab_edit_document


def test_prefab_normalized_document_and_corpus_goldens(tmp_path: Path) -> None:
    payload = _payload()
    virtual_path = "character/prefab/test.prefab"
    document = prefab_json.build_prefab_edit_document(payload, virtual_path)
    audit = prefab_corpus.audit_prefab_json_import_sample(payload, virtual_path)
    loose_path = tmp_path / "test.prefab"
    loose_path.write_bytes(payload)
    report = prefab_corpus.build_prefab_json_import_corpus_report([loose_path])
    normalized_report = _normalized(report)
    assert isinstance(normalized_report, dict)
    normalized_report["source_paths"] = ["<source>"]

    assert _digest(document) == "b7e859d98c5174b5dd67b53e61081a44154f677b559d73047bb63a645f20d357"
    assert _digest(_normalized(audit)) == "4546dbb135ee02071c47cf86b639e6201a1b9a5e8adcd4f5c3dd3d06d5596767"
    assert _digest(normalized_report) == "b1968e2655c88848439eb8cca7f4d4a50204a08ac257996f616f279cd67e4380"


def test_prefab_owner_first_import_order_keeps_identity() -> None:
    scripts = (
        "from cdmw.core.prefab_corpus_audit import audit_prefab_json_import_sample as owner; "
        "from cdmw.core.prefab_corpus import audit_prefab_json_import_sample as facade; assert owner is facade",
        "from cdmw.core.prefab_json_apply import apply_prefab_edit_document as owner; "
        "from cdmw.core.prefab_json import apply_prefab_edit_document as facade; assert owner is facade",
    )
    for script in scripts:
        subprocess.run([sys.executable, "-c", script], cwd=ROOT, check=True)
