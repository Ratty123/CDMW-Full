from __future__ import annotations

from pathlib import Path

from cdmw.core.archive_tree_preflight import find_suspicious_archive_tree_roots


def _write_pamt(root: Path, group: str) -> None:
    path = root / group / "0.pamt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")


def test_archive_root_preflight_flags_copied_archive_tree(tmp_path: Path) -> None:
    _write_pamt(tmp_path, "0000")
    copied_root = tmp_path / "backup"
    _write_pamt(copied_root, "0000")

    assert find_suspicious_archive_tree_roots(tmp_path) == (copied_root,)


def test_archive_root_preflight_accepts_game_files_layout(tmp_path: Path) -> None:
    _write_pamt(tmp_path / "game_files", "0000")

    assert find_suspicious_archive_tree_roots(tmp_path) == ()
