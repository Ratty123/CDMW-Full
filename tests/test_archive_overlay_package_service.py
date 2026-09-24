"""DMM package naming is independent of the installed game's archive slots."""
from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.papgt_format import PAPGT_DEFAULT_FLAGS, PapgtDirectory, serialize_papgt
from cdmw.domain.archives.mutation import ArchiveAddRequest
from cdmw.services.archive_overlay_package_service import export_archive_overlay_package


def test_package_uses_dmm_standalone_slot_when_game_slots_are_occupied(tmp_path):
    game = tmp_path / "game"
    (game / "meta").mkdir(parents=True)
    directories = [PapgtDirectory(f"{number:04d}", PAPGT_DEFAULT_FLAGS, 0)
                   for number in range(36, 42)]
    mount = serialize_papgt(directories)
    (game / "meta/0.papgt").write_bytes(mount)
    for directory in directories:
        (game / directory.name).mkdir()
        (game / directory.name / "0.pamt").write_bytes(b"occupied game slot")
    before = {path.relative_to(game): path.read_bytes() for path in game.rglob("*") if path.is_file()}
    addition = ArchiveAddRequest(game / "0000/0.pamt", "character/model/new.pac", b"new model")

    result = export_archive_overlay_package((), (addition,), package_root=tmp_path / "mod",
        game_root=game, metadata_files=(("meta/0.pathc", b"texture registrations"),))

    # DMM 3.2.1 treats 0042 as group-replace and drops paths absent from vanilla.
    assert result.group == "0036"
    assert {p.parent.name for p in result.package_root.glob("*/0.pamt")} == {"0036"}
    entries = parse_archive_pamt(result.package_root / "0036/0.pamt")
    assert len(entries) == 1 and entries[0].path == addition.path
    assert read_archive_entry_data(entries[0])[0] == addition.payload_data
    assert (result.package_root / "meta/0.pathc").read_bytes() == b"texture registrations"
    assert {path.relative_to(game): path.read_bytes() for path in game.rglob("*") if path.is_file()} == before
