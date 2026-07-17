from __future__ import annotations

import ast
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import struct

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QLineEdit, QPushButton, QTabWidget, QTreeWidget, QWidget

from cdmw.core.archive_hkx import build_hkx_editable_geometry_xml
from cdmw.models import ArchiveEntry
from cdmw.ui.archive_browser import hkx_editor_dialog
from cdmw.ui.archive_browser.hkx_editor_dialog_owners import DIALOG_STEPS
from tests.architecture_limits import DEFAULT_OWNER_FILE_LINE_LIMIT
from tests.test_hkx_preview import _tag_item, _tna1_payload


ROOT = Path(__file__).resolve().parents[1]
OWNER_ROOT = ROOT / "cdmw" / "ui" / "archive_browser"


def _box_hkx_document() -> str:
    type_names = b"hknpBoxShape\0\xff"
    records = (0x10000001).to_bytes(4, "little") + (0).to_bytes(4, "little") + (1).to_bytes(4, "little")
    payload = bytearray(192)
    for offset, value in (
        (0x30, 14), (0x38, 136), (0x3C, 8), (0x40, 224), (0x44, 6), (0x48, 312),
        (0x4C, 6), (0x50, 336), (0x54, 24), (0x58, 360), (0x5C, 24), (0x60, 448), (0x64, 8),
    ):
        struct.pack_into("<I", payload, offset, value)
    struct.pack_into("<f", payload, 0x68, 0.015)
    struct.pack_into("<f", payload, 0x6C, 0.008)
    for index, value in enumerate((1.0, 0.0, 0.0, 0.075, 0.0, 1.0, 0.0, 0.048, 0.0, 0.0, 1.0, 0.009, -4.5, 1.0, 6.25, 0.5)):
        struct.pack_into("<f", payload, 0x80 + index * 4, value)
    item_payload = b"\0" * 12 + records
    body = b"TAG0"
    body += _tag_item(b"SDKV", b"20240200")
    body += _tag_item(b"DATA", bytes(payload))
    body += _tag_item(b"TST1", type_names)
    body += _tag_item(b"TNA1", _tna1_payload(1), flags=0x40000000)
    body += _tag_item(b"TPAD", b"", flags=0)
    body += _tag_item(b"INDX", b"", flags=0x40000000)
    body += (8 + len(item_payload)).to_bytes(4, "big") + b"ITEM" + item_payload
    return build_hkx_editable_geometry_xml((len(body) + 4).to_bytes(4, "big") + body, "object/box.hkx")


def _dialog_fingerprint(dialog: QDialog) -> str:
    def tree_rows(tree: QTreeWidget) -> list[tuple[str, ...]]:
        rows: list[tuple[str, ...]] = []

        def visit(item) -> None:
            rows.append(tuple(item.text(column) for column in range(tree.columnCount())))
            for child_index in range(item.childCount()):
                visit(item.child(child_index))

        for row_index in range(tree.topLevelItemCount()):
            visit(tree.topLevelItem(row_index))
        return rows

    widgets = dialog.findChildren(QWidget)
    payload = {
        "types": sorted(Counter(type(widget).__name__ for widget in widgets).items()),
        "labels": sorted(widget.text() for widget in dialog.findChildren(QLabel)),
        "buttons": sorted(widget.text() for widget in dialog.findChildren(QPushButton)),
        "tabs": [tuple(widget.tabText(index) for index in range(widget.count())) for widget in dialog.findChildren(QTabWidget)],
        "trees": [
            {
                "headers": tuple(tree.headerItem().text(index) for index in range(tree.columnCount())),
                "rows": tree_rows(tree),
            }
            for tree in dialog.findChildren(QTreeWidget)
        ],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def test_hkx_editor_facade_forwards_current_module_seams(monkeypatch) -> None:
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(hkx_editor_dialog, "run_hkx_editor_dialog", lambda *args: calls.append(args))
    host = object()
    entry = object()
    hkx_editor_dialog.ArchiveHkxEditorDialogMixin._open_archive_hkx_editor_dialog(host, entry, "xml", initial_section="Collision")
    assert calls == [(host, entry, "xml", "Collision", hkx_editor_dialog.__dict__, DIALOG_STEPS)]


def test_hkx_editor_owners_obey_phase6_caps() -> None:
    paths = [
        OWNER_ROOT / "hkx_editor_dialog.py",
        OWNER_ROOT / "hkx_editor_dialog_runtime.py",
        OWNER_ROOT / "hkx_editor_dialog_owners.py",
        *OWNER_ROOT.glob("hkx_editor_dialog_*_part_*.py"),
    ]
    assert len(tuple(DIALOG_STEPS)) == 159
    assert len({id(step) for step in DIALOG_STEPS}) == len(DIALOG_STEPS)
    for path in paths:
        source = path.read_text(encoding="utf-8")
        assert len(source.splitlines()) <= DEFAULT_OWNER_FILE_LINE_LIMIT, path
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.end_lineno - node.lineno + 1 <= 150, (path, node.name)


def test_hkx_editor_box_document_build_matches_presplit_golden(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    fingerprints: list[str] = []
    visible_states: list[bool] = []

    def capture(dialog: QDialog) -> int:
        fingerprints.append(_dialog_fingerprint(dialog))
        visible_states.append(dialog.isVisible())
        return 0

    monkeypatch.setattr(QDialog, "exec", capture)

    class Host(QWidget, hkx_editor_dialog.ArchiveHkxEditorDialogMixin):
        def __init__(self) -> None:
            super().__init__()
            self.settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
            self.current_theme_key = "dark"
            self.texconv_path_edit = QLineEdit()
            self.archive_entries_by_basename = {}
            self.archive_entries_by_normalized_path = {}
            self.archive_sidecar_entries_by_texture_basename = {}
            self.archive_sidecar_entries_by_texture_path = {}
            self.archive_model_preview = None

        def __getattr__(self, _name: str):
            return lambda *_args, **_kwargs: None

        def _current_model_preview_render_settings(self) -> dict[str, object]:
            return {}

        def _background_task_active(self) -> bool:
            return False

        def _ui_evidence_label(self, *_args, **_kwargs) -> str:
            return ""

    entry = ArchiveEntry("object/box.hkx", Path("0.pamt"), Path("0.paz"), 0, 0, 0, 0, 0)
    Host()._open_archive_hkx_editor_dialog(entry, _box_hkx_document())
    assert app is QApplication.instance()
    assert visible_states == [False]
    assert fingerprints == ["bb1fc70d274e24b9719308b6c830b1a05d82827490105b68638fbdb57dc3d163"]
