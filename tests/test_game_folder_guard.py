"""Decision 46, review round 2: game folders are refused in every process, and never cleared.

Owned folders under tmp_path only. A "game" here holds meta/0.papgt and
bin64/CrimsonDesert.exe, as an installation does.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from cdmw.core import protected_roots
from cdmw.core.atomic_file import (
    atomic_publish_directory,
    atomic_publish_files,
    atomic_publish_paths,
    atomic_write_bytes,
)
from cdmw.core.protected_roots import ProtectedGameFolderWrite


def _game(folder: Path) -> Path:
    (folder / "meta").mkdir(parents=True)
    (folder / "meta" / "0.papgt").write_bytes(b"papgt")
    (folder / "bin64").mkdir()
    (folder / "bin64" / "CrimsonDesert.exe").write_bytes(b"MZ")
    return folder


def _files(root: Path) -> set[str]:
    return {path.relative_to(root).as_posix() for path in root.rglob("*")}


# --- G: a rule that needs no process state.

def test_a_folder_holding_the_games_index_is_refused_though_nothing_was_configured(tmp_path):
    game = _game(tmp_path / "Crimson Desert")
    assert protected_roots.protected_roots() == ()
    with pytest.raises(ProtectedGameFolderWrite, match="does not write into the game folder"):
        atomic_write_bytes(game / "mods" / "x.bin", b"x")
    with pytest.raises(ProtectedGameFolderWrite):
        atomic_write_bytes(game / "x.bin", b"x")
    assert _files(game) == {"meta", "meta/0.papgt", "bin64", "bin64/CrimsonDesert.exe"}


def test_an_archive_mod_with_its_own_index_is_not_a_game(tmp_path):
    """DMM's archive-style mods, which CDMW writes, hold their own meta/0.papgt."""
    mod = tmp_path / "dmm-mods" / "Frost blade"
    (mod / "meta").mkdir(parents=True)
    (mod / "meta" / "0.papgt").write_bytes(b"the mod's own index")
    atomic_write_bytes(mod / "0036" / "0.paz", b"x")
    staged = tmp_path / "staged"
    staged.mkdir()
    atomic_publish_directory(staged, mod)  # replacing an earlier build of the mod


def test_the_send_worker_refuses_a_mods_folder_in_the_game_by_itself(tmp_path, capsys):
    """The --dmm-send-worker child's own code path, without the parent's check."""

    from cdmw.services.dmm_send_process import run_dmm_send_worker

    game = _game(tmp_path / "game")
    (game / "mods").mkdir()
    package = tmp_path / "item.cdmw"
    package.write_bytes(b"not read: the destination is refused first")
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"schema": 1, "nonce": "n", "root": str(game), "mods": str(game / "mods"),
                                   "title": "Two items", "packages": [str(package)]}), encoding="utf-8")
    before = _files(game)
    assert run_dmm_send_worker(request, tmp_path / "result.json") == 1
    assert "does not write into the game folder" in capsys.readouterr().err
    assert _files(game) == before and not (tmp_path / "result.json").exists()
    assert game.resolve() in protected_roots.protected_roots()


def test_the_parent_refuses_before_it_starts_a_child(tmp_path, monkeypatch):
    from cdmw.services import dmm_send_process

    game = _game(tmp_path / "game")
    (game / "mods").mkdir()
    monkeypatch.setattr(dmm_send_process, "run_process_with_cancellation",
                        lambda *a, **k: pytest.fail("a child was started"))
    with pytest.raises(ProtectedGameFolderWrite):
        dmm_send_process.send_item_packages_in_subprocess([tmp_path / "item.cdmw"], game, game / "mods", "Two")


def test_child_processes_inherit_the_sessions_roots(tmp_path):
    first, second = _game(tmp_path / "one"), _game(tmp_path / "two")
    protected_roots.add_game_root(first)
    protected_roots.add_game_root(second)
    passed = json.loads(os.environ[protected_roots.ROOTS_ENVIRONMENT])
    assert sorted(passed) == sorted(str(path.resolve()) for path in (first, second))
    # A child starts with no roots and adopts what its parent passed down.
    with protected_roots._lock:
        protected_roots._roots.clear()
    assert set(protected_roots.adopt_environment()) == {first.resolve(), second.resolve()}


def test_bootstrap_adopts_the_roots_before_any_helper_mode():
    source = (Path(__file__).resolve().parents[1] / "cdmw" / "app" / "bootstrap.py").read_text(encoding="utf-8")
    adopt = source.index("adopt_environment()")
    assert adopt < source.index("if args.mcp_bridge:") < source.index("if args.dmm_send_worker:")


# --- I: a session set of roots.

def test_roots_are_a_session_set_that_only_grows(tmp_path):
    first, second = _game(tmp_path / "first"), _game(tmp_path / "second")
    assert protected_roots.set_configured_game_root(first) == first.resolve()
    protected_roots.set_configured_game_root(second)
    protected_roots.set_configured_game_root("")
    protected_roots.set_configured_game_root(None)
    assert set(protected_roots.protected_roots()) == {first.resolve(), second.resolve()}
    with pytest.raises(ProtectedGameFolderWrite):
        protected_roots.check_writable(first / "x")  # the previous game folder is still protected


def test_a_drive_root_or_a_folder_that_is_not_a_game_is_never_added(tmp_path):
    plain = tmp_path / "half-typed"
    plain.mkdir()
    assert protected_roots.add_game_root(Path(tmp_path.anchor)) is None
    assert protected_roots.add_game_root(plain) is None
    assert protected_roots.add_game_root(tmp_path / "missing") is None
    assert protected_roots.protected_roots() == ()
    atomic_write_bytes(plain / "x.bin", b"x")  # CDMW's own writes there go on


def test_a_package_root_with_a_game_files_folder_is_added(tmp_path):
    root = tmp_path / "package-root"
    _game(root / "game_files")
    assert protected_roots.add_game_root(root) == root.resolve()


def test_a_detected_install_is_protected(tmp_path, monkeypatch):
    from cdmw.core import archive_format

    game = _game(tmp_path / "detected")
    monkeypatch.setattr(archive_format, "discover_steam_roots", lambda: [])
    monkeypatch.setattr(archive_format, "discover_non_steam_archive_package_roots", lambda **_: [game])
    archive_format.autodetect_archive_package_roots()
    assert game.resolve() in protected_roots.protected_roots()


# --- H: never clear or replace a game folder or a folder that holds one.

@pytest.mark.parametrize("pick", ["game", "library"])
def test_publishing_over_the_game_or_its_library_is_refused(tmp_path, pick):
    game = _game(tmp_path / "library" / "Crimson Desert")
    protected_roots.add_game_root(game)
    target = game if pick == "game" else game.parent
    staged = tmp_path / "staged"
    staged.mkdir()
    for attempt in (lambda: atomic_publish_directory(staged, target),
                    lambda: atomic_publish_paths(((staged, target),))):
        with pytest.raises(ProtectedGameFolderWrite):
            attempt()
    assert (game / "meta" / "0.papgt").is_file() and staged.is_dir()


def test_the_permit_never_allows_removing_the_game_folder_itself(tmp_path):
    game = _game(tmp_path / "game")
    with protected_roots.game_folder_write_permit("Restore Backup"):
        protected_roots.check_removable(game / "meta" / "0.papgt")  # inside, with the permit: allowed
        with pytest.raises(ProtectedGameFolderWrite):
            protected_roots.check_removable(game)
    with pytest.raises(ProtectedGameFolderWrite, match="whole drive"):
        protected_roots.check_removable(Path(tmp_path.anchor))


def test_the_mesh_loose_export_never_clears_a_game_folder(tmp_path):
    from cdmw.core.archive_loose_export import _clear_existing_mesh_loose_package_root

    game = _game(tmp_path / "exports" / "Crimson Desert")
    with pytest.raises(ProtectedGameFolderWrite):
        _clear_existing_mesh_loose_package_root(game, (tmp_path / "exports").resolve())
    assert (game / "meta" / "0.papgt").is_file()


def test_extraction_refuses_a_game_folder(tmp_path):
    from cdmw.core.archive_extraction import extract_archive_entries

    game = _game(tmp_path / "game")
    with pytest.raises(ProtectedGameFolderWrite):
        extract_archive_entries([], game / "extracted")
    assert not (game / "extracted").exists()


# --- The writers' smaller points.

def test_an_extended_length_path_into_the_game_is_refused(tmp_path):
    game = _game(tmp_path / "game")
    with pytest.raises(ProtectedGameFolderWrite):
        atomic_write_bytes("\\\\?\\" + str(game / "x.bin"), b"x")
    assert not (game / "x.bin").exists()


def test_the_check_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(protected_roots, "_resolved", lambda _path: None)
    with pytest.raises(ProtectedGameFolderWrite, match="could not tell"):
        atomic_write_bytes(tmp_path / "x.bin", b"x")
    with pytest.raises(ProtectedGameFolderWrite, match="could not tell"):
        protected_roots.check_removable(tmp_path)


def test_a_staged_source_in_the_game_is_not_moved_out(tmp_path):
    game = _game(tmp_path / "game")
    target = tmp_path / "out" / "0.papgt"
    with pytest.raises(ProtectedGameFolderWrite):
        atomic_publish_files({game / "meta" / "0.papgt": target})
    with pytest.raises(ProtectedGameFolderWrite):
        atomic_publish_directory(game / "meta", tmp_path / "out-folder")
    assert (game / "meta" / "0.papgt").is_file() and not target.exists()


def test_a_junction_made_while_the_folder_is_made_is_caught(tmp_path, monkeypatch):
    """The target's folder turns into a junction into the game between the first check
    and the write; the check after mkdir refuses it."""

    import _winapi

    game = _game(tmp_path / "game")
    (tmp_path / "out").mkdir()
    sneaky = tmp_path / "out" / "sub"
    real_mkdir = Path.mkdir

    def mkdir(self, *args, **kwargs):
        if self == sneaky and not os.path.lexists(sneaky):
            _winapi.CreateJunction(str(game), str(sneaky))
            return None
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", mkdir)
    with pytest.raises(ProtectedGameFolderWrite):
        atomic_write_bytes(sneaky / "x.bin", b"x")
    monkeypatch.setattr(Path, "mkdir", real_mkdir)
    assert _files(game) == {"meta", "meta/0.papgt", "bin64", "bin64/CrimsonDesert.exe"}
