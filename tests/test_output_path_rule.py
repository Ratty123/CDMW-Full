"""P13 stage C, item 2: the one rule for output paths refuses the game, always."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from cdmw.domain.output_paths import OutputPathRefused, check_output_path, game_folder_holding, is_dlc_folder


@pytest.fixture
def game(tmp_path) -> Path:
    """A folder laid out like the game: meta/0.papgt, an archive group and a DLC."""

    root = tmp_path / "Crimson Desert"
    (root / "meta").mkdir(parents=True)
    (root / "meta" / "0.papgt").write_bytes(b"\0" * 16)
    (root / "0009").mkdir()
    (root / "dlc" / "dlc_01" / "0036").mkdir(parents=True)
    return root


def test_an_absolute_path_in_an_existing_folder_outside_the_game_is_accepted(tmp_path, game) -> None:
    mods = tmp_path / "mods"
    mods.mkdir()
    assert check_output_path(mods / "My Mod", game_folder=game) == Path(os.path.realpath(mods / "My Mod"))
    assert check_output_path(str(mods / "texture.dds")).name == "texture.dds"


@pytest.mark.parametrize("bad", ["", "   ", "relative\\mod", "mods/x.dds", "\\no-drive\\x"])
def test_a_relative_or_empty_path_is_refused(bad) -> None:
    with pytest.raises(OutputPathRefused):
        check_output_path(bad)


def test_the_folder_must_exist(tmp_path) -> None:
    with pytest.raises(OutputPathRefused, match="does not exist"):
        check_output_path(tmp_path / "missing" / "mod")


def test_nothing_inside_the_configured_game_folder(game) -> None:
    for target in (game / "new.dds", game / "0009" / "0.paz", game / "meta" / "1.papgt", game / "new-mod"):
        with pytest.raises(OutputPathRefused, match="game"):
            check_output_path(target, game_folder=game)


def test_nothing_inside_any_installation_even_when_none_is_configured(game, tmp_path) -> None:
    # A second copy of the game somewhere else, never configured.
    copy = tmp_path / "Copy"
    (copy / "meta").mkdir(parents=True)
    (copy / "meta" / "0.papgt").write_bytes(b"\0")
    (copy / "0012").mkdir()
    for target in (copy / "0012" / "x.pamt", copy / "x.txt", game / "0009" / "x"):
        with pytest.raises(OutputPathRefused, match="game installation"):
            check_output_path(target)
    assert game_folder_holding(copy / "0012") == copy


def test_nothing_inside_a_dlc_folder_of_the_game(game, tmp_path) -> None:
    dlc = game / "dlc" / "dlc_01"
    assert is_dlc_folder(dlc) and not is_dlc_folder(game / "dlc") and not is_dlc_folder(tmp_path / "dlc_01")
    # A DLC folder moved out of its game is still refused by its name and place.
    loose = tmp_path / "elsewhere" / "dlc" / "dlc_02"
    loose.mkdir(parents=True)
    for target in (dlc / "0036" / "x.paz", loose / "x.paz", game / "dlc" / "dlc_03"):
        with pytest.raises(OutputPathRefused, match="game"):
            check_output_path(target)


def test_upper_case_and_dot_segments_do_not_get_round_it(game) -> None:
    sneaky = Path(str(game).upper()) / "0009" / ".." / "0009" / "x.paz"
    with pytest.raises(OutputPathRefused):
        check_output_path(sneaky, game_folder=game)
    beside = game.parent / "mods"
    beside.mkdir()
    with pytest.raises(OutputPathRefused):
        check_output_path(beside / ".." / game.name / "x", game_folder=game)
    # A sibling whose name starts with the game's name is not inside it.
    sibling = game.parent / (game.name + " Mods")
    sibling.mkdir()
    assert check_output_path(sibling / "x.dds", game_folder=game)


@pytest.mark.skipif(os.name != "nt", reason="junctions are Windows folders")
def test_a_junction_into_the_game_is_followed_and_refused(game, tmp_path) -> None:
    link = tmp_path / "looks-harmless"
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(game / "0009")],
                            capture_output=True, text=True)
    if result.returncode != 0:
        pytest.skip(f"could not make a junction: {result.stderr.strip()}")
    with pytest.raises(OutputPathRefused, match="game"):
        check_output_path(link / "x.paz", game_folder=game)
    with pytest.raises(OutputPathRefused, match="game installation"):
        check_output_path(link / "x.paz")


def test_an_output_never_replaces_a_file_or_folder(tmp_path) -> None:
    existing = tmp_path / "existing.dds"
    existing.write_bytes(b"x")
    folder = tmp_path / "Existing Mod"
    folder.mkdir()
    for target in (existing, folder):
        with pytest.raises(OutputPathRefused, match="never replace"):
            check_output_path(target)
    assert check_output_path(existing, allow_existing=True) == Path(os.path.realpath(existing))
