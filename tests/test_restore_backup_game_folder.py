"""Restore Backup writes back only inside the configured game folder (decision 41).

Every backup here is made in an owned folder under ``tmp_path``; nothing reads or
writes a real game installation.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from cdmw.services.archive_mutation_service import ArchiveMutationService, RestoreOutsideGameFolder


def _game(root: Path) -> Path:
    (root / "meta").mkdir(parents=True)
    (root / "0009").mkdir()
    (root / "meta" / "0.papgt").write_bytes(b"current mount list")
    (root / "0009" / "0.pamt").write_bytes(b"current index")
    return root


def _backup(folder: Path, files: dict[str, bytes], *, originals: dict[str, str] | None = None) -> Path:
    """A Restore-style backup: one copy per file and a manifest naming where it goes back."""
    folder.mkdir(parents=True)
    rows = []
    for index, (original, payload) in enumerate(files.items()):
        copy = folder / f"file{index}"
        copy.write_bytes(payload)
        rows.append({"original_path": (originals or {}).get(original, original), "backup_path": str(copy)})
    (folder / "backup_manifest.json").write_text(json.dumps({"description": "test", "files": rows}), encoding="utf-8")
    return folder


def _bytes(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_a_backup_made_for_this_game_folder_is_restored(tmp_path):
    game = _game(tmp_path / "game")
    backup = _backup(tmp_path / "backups" / "one", {
        str(game / "meta" / "0.papgt"): b"old mount list",
        str(game / "0009" / "0.pamt"): b"old index",
    })
    assert ArchiveMutationService().restore_backup(backup, confirmed=True, game_root=game) == backup.resolve()
    assert (game / "meta" / "0.papgt").read_bytes() == b"old mount list"
    assert (game / "0009" / "0.pamt").read_bytes() == b"old index"


def test_a_manifest_path_outside_the_game_is_refused_before_anything_is_written(tmp_path):
    game = _game(tmp_path / "game")
    outside = tmp_path / "elsewhere" / "notes.txt"
    backup = _backup(tmp_path / "backups" / "two", {
        str(game / "meta" / "0.papgt"): b"old mount list",
        str(outside): b"planted",
    })
    before = _bytes(game)
    with pytest.raises(RestoreOutsideGameFolder) as refused:
        ArchiveMutationService().restore_backup(backup, confirmed=True, game_root=game)
    message = str(refused.value)
    assert str(outside) in message and "game folder the backup was made for" in message
    assert _bytes(game) == before and not outside.exists()


def test_a_dot_dot_escape_is_refused(tmp_path):
    game = _game(tmp_path / "game")
    escape = str(game / "meta" / ".." / ".." / "escaped.bin")
    backup = _backup(tmp_path / "backups" / "three", {escape: b"planted"})
    before = _bytes(game)
    with pytest.raises(RestoreOutsideGameFolder, match="escaped.bin"):
        ArchiveMutationService().restore_backup(backup, confirmed=True, game_root=game)
    assert _bytes(game) == before and not (tmp_path / "escaped.bin").exists()


def test_a_path_through_a_link_out_of_the_game_is_refused(tmp_path):
    game = _game(tmp_path / "game")
    target = tmp_path / "linked-target"
    target.mkdir()
    link = game / "linked"
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError:
        # Without the symlink privilege, a junction is the link Windows users meet.
        import subprocess
        if os.name != "nt" or subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                                             capture_output=True).returncode != 0:
            pytest.skip("cannot create a link here")
    backup = _backup(tmp_path / "backups" / "four", {str(link / "0.pamt"): b"planted"})
    with pytest.raises(RestoreOutsideGameFolder, match="linked"):
        ArchiveMutationService().restore_backup(backup, confirmed=True, game_root=game)
    assert not (target / "0.pamt").exists()


def test_a_backup_made_for_another_game_folder_is_refused(tmp_path):
    game = _game(tmp_path / "game")
    other = _game(tmp_path / "other-game")
    backup = _backup(tmp_path / "backups" / "five", {str(other / "meta" / "0.papgt"): b"old mount list"})
    with pytest.raises(RestoreOutsideGameFolder) as refused:
        ArchiveMutationService().restore_backup(backup, confirmed=True, game_root=game)
    assert str(other / "meta" / "0.papgt") in str(refused.value)
    assert str(game) in str(refused.value)
    assert (other / "meta" / "0.papgt").read_bytes() == b"current mount list"
    assert (game / "meta" / "0.papgt").read_bytes() == b"current mount list"


def test_a_backup_copy_from_outside_its_backup_folder_is_refused(tmp_path):
    game = _game(tmp_path / "game")
    stray = tmp_path / "stray.bin"
    stray.write_bytes(b"not part of the backup")
    backup = _backup(tmp_path / "backups" / "six", {str(game / "meta" / "0.papgt"): b"old"})
    manifest = json.loads((backup / "backup_manifest.json").read_text(encoding="utf-8"))
    manifest["files"][0]["backup_path"] = str(stray)
    (backup / "backup_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(RestoreOutsideGameFolder, match="stray.bin"):
        ArchiveMutationService().restore_backup(backup, confirmed=True, game_root=game)
    assert (game / "meta" / "0.papgt").read_bytes() == b"current mount list"


def test_restore_needs_the_game_folder(tmp_path):
    backup = _backup(tmp_path / "backups" / "seven", {str(tmp_path / "x"): b"x"})
    with pytest.raises(RestoreOutsideGameFolder, match="Choose the game folder"):
        ArchiveMutationService().restore_backup(backup, confirmed=True, game_root=None)
    with pytest.raises(RestoreOutsideGameFolder, match="Choose the game folder"):
        ArchiveMutationService().restore_backup(backup, confirmed=True, game_root=tmp_path / "missing")
