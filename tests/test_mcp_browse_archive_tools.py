from pathlib import Path

from PySide6.QtWidgets import QApplication, QDialog

from cdmw.models import ArchiveEntry
from tests.test_mcp_real_window import app, profile, real


def test_browse_archive_controls_export_and_keep_the_game_unchanged(real, tmp_path, monkeypatch):
    from cdmw.services.archive_preview_service import build_archive_preview_result

    root = tmp_path / "owned-game"
    archive = real.window.archive
    package = root / "0012"
    package.mkdir(parents=True)
    index = root / "meta" / "0.papgt"
    index.parent.mkdir()
    index.write_bytes(b"owned index marker")
    payload = b"This is the text-search fixture.\n"
    (package / "0.paz").write_bytes(payload)
    path = "owned/sample.txt"
    entry = ArchiveEntry(path, package / "0.pamt", package / "0.paz", 0, len(payload), len(payload), 0, 0)
    monkeypatch.setattr(archive, "archive_remote_bridge", None)
    archive.archive_entries = archive.archive_filtered_entries = [entry]
    archive.archive_tree.use_legacy_model()
    archive.archive_tree.set_archive_state([entry], mode="flat")
    selected = archive._select_archive_tree_entry(0)
    archive.archive_tree.setCurrentItem(selected)
    selected.setSelected(True)
    archive.archive_preview_request_entry = entry
    archive.current_archive_preview_result = build_archive_preview_result(entry)
    archive._update_archive_model_action_controls(None)
    before = {item: item.read_bytes() for item in root.rglob("*") if item.is_file()}
    assert real.ok("files_browser_state")["path"] == path

    real.ok("files_browser_export", {"action": "copy_filename"})
    assert QApplication.clipboard().text() == Path(path).name
    target = tmp_path / "one.txt"
    real.ok("files_browser_export", {"action": "file", "path": str(target)})
    real.wait_until(lambda: target.is_file() and not real.ok("files_browser_state")["busy"])
    assert target.read_bytes() == payload
    extraction = tmp_path / "extracted"
    real.ok("files_browser_export", {"action": "extract", "path": str(extraction)})
    real.wait_until(lambda: any(extraction.rglob(Path(path).name)), timeout=30)
    assert next(extraction.rglob(Path(path).name)).read_bytes() == target.read_bytes()

    real.wait_until(archive.archive_action_open_preview_window_button.isEnabled)
    real.ok("files_browser_view", {"action": "open_preview"})
    selector = "layout_cdmw_ui_archive_browser_reference_preview__show_archive_reference_preview_dialog_dialog"
    real.wait_until(lambda: any(dialog.isVisible() for dialog in archive.findChildren(QDialog, selector)))
    preview = next(dialog for dialog in archive.findChildren(QDialog, selector) if dialog.isVisible())
    assert not preview.isModal()
    preview.close()
    real.ok("search_text_action", {"action": "start", "source": "archive", "query": "fixture", "extensions": ".txt"})
    real.wait_until(lambda: real.ok("search_text_state")["total"] == 1)
    real.ok("search_text_action", {"action": "open_hit", "row": 0})
    assert real.ok("files_browser_state")["path"] == path
    assert real.error("files_browser_edit", {"action": "open_mesh"})["code"] == "unavailable"
    blocked = real.error("files_browser_export", {"action": "file", "path": str(root / "refused.txt")})
    assert blocked["code"] == "refused"
    real.wait_until(lambda: not real.ok("files_browser_state")["busy"])
    assert {item: item.read_bytes() for item in root.rglob("*") if item.is_file()} == before
