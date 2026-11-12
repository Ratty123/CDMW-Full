"""Combine built Mesh Editor mods into one mod (GitHub issue 31), on owned fixtures only."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

import pytest

from cdmw.core.mod_package import MeshLooseModAsset, MeshLooseModFile, write_mesh_loose_mod_package_metadata
from cdmw.domain.packages.export_policy import mod_package_export_options_for_manager
from cdmw.domain.packages.game_file_label import ELLIPSIS, game_file_label, shorten_game_path
from cdmw.domain.packages.mesh_build_combine import (
    CONFLICT_DIFFERENT_COMPANION,
    CONFLICT_SHARED_TARGET,
    LAYOUT_ARCHIVE_GROUP,
    LAYOUT_LOOSE,
    MeshBuildFile,
    MeshBuildSource,
    plan_mesh_build_combine,
)
from cdmw.models import ArchiveEntry, ModPackageInfo
from cdmw.services.mesh_build_combine_service import (
    COMBINED_METADATA_FORMAT,
    export_combined_mesh_builds,
    prepare_mesh_build_combine,
)
from cdmw.services.mesh_mod_publish import publish_mesh_mod_output
from cdmw.services.mesh_saved_work_service import (
    KIND_BUILT_MOD,
    MeshDraftRequest,
    add_built_mod_folder,
    list_saved_work,
    plan_session_draft,
    register_built_mod,
    register_combined_mod,
)

# The reporter's pair from issue 31: two files of one armour in different folders.
UPPER = "character/model/1_pc/1_phw/armor/9_upperbody/cd_phw_00_ub_00_0151.pac"
SHOULDER = "character/model/1_pc/1_phw/armor/14_sho/cd_phw_00_sho_under_00_0151.pac"
WING_TEXTURE = "character/texture/cd_phw_00_wing_0151_d.dds"


def _build(root: Path, name: str, files: dict[str, tuple[bytes, str]], *, profile: str = "dmm",
           companions: dict[str, bytes] | None = None) -> Path:
    """A built mod made the way Build Mod makes one: staged, written by the loose writer, published."""

    target = root / name
    staging = Path(tempfile.mkdtemp(prefix=f".{name}.staging-", dir=root))
    assets, rows = [], []
    for path, (data, group) in files.items():
        (staging / path).parent.mkdir(parents=True, exist_ok=True)
        (staging / path).write_bytes(data)
        assets.append(MeshLooseModAsset(entry_path=path, package_group=group, format="pac",
                                        note="Validated Mesh Editor replacement"))
        rows.append(MeshLooseModFile(path=path, package_group=group, format="pac",
                                     note="Validated Mesh Editor replacement"))
    for path, data in (companions or {}).items():
        (staging / path).parent.mkdir(parents=True, exist_ok=True)
        (staging / path).write_bytes(data)
        rows.append(MeshLooseModFile(path=path, package_group="0012", format=Path(path).suffix[1:],
                                     note="Replacement companion"))
    metadata = {"format": "cdmw_mesh_editor_output_v1", "source_path": next(iter(files)),
                "manager_profile": profile, "assets": [{"path": path} for path in files]}
    (staging / "mesh-editor-session.json").write_text(json.dumps(metadata), encoding="utf-8")
    options = mod_package_export_options_for_manager(profile)
    write_mesh_loose_mod_package_metadata(staging, ModPackageInfo(title=name), assets=assets, files=rows,
                                          include_paired_lod=False, export_options=options,
                                          create_no_encrypt_file=bool(options.create_no_encrypt_file))
    publish_mesh_mod_output(staging, target, manager_profile=profile)
    return target


def _fingerprint(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()}


@pytest.fixture
def reporter_builds(tmp_path):
    builds = tmp_path / "mods"
    builds.mkdir()
    skirt = _build(builds, "Skirt edit", {UPPER: (b"edited upper body", "0009")})
    wing = _build(builds, "Wing piece", {SHOULDER: (b"replacement shoulder", "0014")},
                  companions={WING_TEXTURE: b"DDS wing texture"})
    return skirt, wing


def test_reporter_pair_combines_into_one_mod_with_both_files_and_counts(reporter_builds, tmp_path):
    skirt, wing = reporter_builds
    before = {folder: _fingerprint(folder) for folder in (skirt, wing)}
    prepared = prepare_mesh_build_combine((skirt, wing), labels=("Skirt", "Wing"))
    assert prepared.can_combine, prepared.refusal
    assert prepared.plan.layout == LAYOUT_LOOSE and prepared.plan.manager_profile == "dmm"
    assert prepared.plan.target_paths == (UPPER, SHOULDER)

    result = export_combined_mesh_builds(prepared, tmp_path / "out" / "Combined armour", title="Combined armour")

    root = result.output_path
    assert (root / UPPER).read_bytes() == b"edited upper body"
    assert (root / SHOULDER).read_bytes() == b"replacement shoulder"
    assert (root / WING_TEXTURE).read_bytes() == b"DDS wing texture"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["kind"] == "mesh_loose_mod"
    assert manifest["asset_count"] == 2 and manifest["file_count"] == 3
    groups = {row["path"]: row["package_group"] for row in manifest["files"]}
    # The two files live in different group folders; their groups survive the combination.
    assert groups == {UPPER: "0009", SHOULDER: "0014", WING_TEXTURE: "0012"}
    assert not (root / "mesh-editor-session.json").exists()  # kept in CDMW's history, not the package
    from cdmw.core.mod_export_history import mod_metadata_path

    record = json.loads(mod_metadata_path(root, "mesh-editor-session.json").read_text(encoding="utf-8"))
    assert record["format"] == COMBINED_METADATA_FORMAT
    assert [item["path"] for item in record["assets"]] == [UPPER, SHOULDER]
    assert [item["label"] for item in record["combined_from"]] == ["Skirt", "Wing"]
    # The originals are kept exactly as they were.
    assert {folder: _fingerprint(folder) for folder in (skirt, wing)} == before

    again = prepare_mesh_build_combine((root, _build(tmp_path / "mods", "Other", {"character/x.pac": (b"x", "0001")})))
    assert again.plan.layout == LAYOUT_LOOSE  # the combined mod reads back as a build like any other


def test_two_builds_of_the_same_game_file_are_refused_by_name(tmp_path):
    builds = tmp_path / "mods"
    builds.mkdir()
    first = _build(builds, "First", {UPPER: (b"one", "0009")})
    second = _build(builds, "Second", {UPPER: (b"two", "0009"), SHOULDER: (b"three", "0014")})
    prepared = prepare_mesh_build_combine((first, second))
    assert not prepared.can_combine
    assert [conflict.kind for conflict in prepared.plan.conflicts] == [CONFLICT_SHARED_TARGET]
    assert '"First" and "Second"' in prepared.refusal and UPPER in prepared.refusal
    destination = tmp_path / "out"
    with pytest.raises(ValueError, match="cannot be combined") as raised:
        export_combined_mesh_builds(prepared, destination)
    assert str(raised.value) == prepared.refusal
    assert not destination.exists()


def test_a_shared_companion_is_kept_once_and_a_different_one_conflicts():
    def source(label, texture):
        return MeshBuildSource(label, f"C:/mods/{label}", LAYOUT_LOOSE, "dmm", (
            MeshBuildFile(f"character/{label}.pac", hashlib.sha256(label.encode()).hexdigest(), format="pac"),
            MeshBuildFile(WING_TEXTURE, hashlib.sha256(texture).hexdigest(), format="dds"),
        ))

    same = plan_mesh_build_combine((source("a", b"t"), source("b", b"t")))
    assert same.can_combine and same.shared_companions == (WING_TEXTURE,)
    assert [item.path for item, _label in same.files].count(WING_TEXTURE) == 1
    different = plan_mesh_build_combine((source("a", b"t"), source("b", b"u")))
    assert [conflict.kind for conflict in different.conflicts] == [CONFLICT_DIFFERENT_COMPANION]
    assert "different versions" in different.refusal
    with pytest.raises(ValueError, match="at least two"):
        plan_mesh_build_combine((source("a", b"t"),))
    with pytest.raises(ValueError, match="more than once"):
        plan_mesh_build_combine((source("a", b"t"), source("a", b"t")))


def test_cdumm_builds_combine_into_a_cdumm_layout(tmp_path):
    builds = tmp_path / "mods"
    builds.mkdir()
    first = _build(builds, "First", {UPPER: (b"one", "0009")}, profile="cdumm")
    second = _build(builds, "Second", {SHOULDER: (b"two", "0014")}, profile="cdumm")
    assert (first / "files" / UPPER).is_file() and not (first / "manifest.json").exists()
    prepared = prepare_mesh_build_combine((first, second))
    assert prepared.plan.layout == LAYOUT_LOOSE and prepared.plan.manager_profile == "cdumm"
    result = export_combined_mesh_builds(prepared, tmp_path / "out", create_zip=True)
    assert (result.output_path / "files" / UPPER).read_bytes() == b"one"
    assert (result.output_path / "files" / SHOULDER).read_bytes() == b"two"
    assert (result.output_path / "modinfo.json").is_file()
    assert result.zip_path is not None and result.zip_path.is_file()


def test_builds_for_different_managers_need_the_archive_group_route(tmp_path):
    builds = tmp_path / "mods"
    builds.mkdir()
    first = _build(builds, "First", {UPPER: (b"one", "0009")}, profile="dmm")
    second = _build(builds, "Second", {SHOULDER: (b"two", "0014")}, profile="cdumm")
    prepared = prepare_mesh_build_combine((first, second))
    assert prepared.can_combine and prepared.plan.layout == LAYOUT_ARCHIVE_GROUP
    with pytest.raises(ValueError, match="needs the game folder"):
        export_combined_mesh_builds(prepared, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_mixed_builds_combine_through_the_merge_service_into_a_dmm_archive_group(tmp_path):
    from tests.test_new_item_provenance import setup_game
    from cdmw.services.new_item_mod_base import mod_folder_payloads
    from cdmw.core.archive_extraction import read_archive_entry_data

    _service, _snapshot, entries = setup_game(tmp_path)
    game_root = tmp_path / "game"
    game_before = _fingerprint(game_root)
    builds = tmp_path / "mods"
    builds.mkdir()
    first = _build(builds, "First", {UPPER: (b"one", "0009")}, profile="dmm")
    second = _build(builds, "Second", {SHOULDER: (b"two", "0014")}, profile="cdumm")
    prepared = prepare_mesh_build_combine((first, second))
    result = export_combined_mesh_builds(prepared, tmp_path / "out", title="Mixed", game_root=game_root,
                                         entries=entries)
    assert result.layout == LAYOUT_ARCHIVE_GROUP and result.manager_profile == "dmm"
    payloads = mod_folder_payloads(result.output_path)
    assert all(payloads[path].entry is not None for path in (UPPER, SHOULDER))
    assert read_archive_entry_data(payloads[UPPER].entry)[0] == b"one"
    assert read_archive_entry_data(payloads[SHOULDER].entry)[0] == b"two"
    assert _fingerprint(game_root) == game_before  # the game is only read


def test_a_build_changed_after_the_check_and_unsafe_outputs_are_refused(reporter_builds, tmp_path):
    skirt, wing = reporter_builds
    prepared = prepare_mesh_build_combine((skirt, wing))
    with pytest.raises(ValueError, match="separate from the game and every selected build"):
        export_combined_mesh_builds(prepared, skirt / "inside")
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "keep.txt").write_text("user file", encoding="utf-8")
    with pytest.raises(ValueError, match="new or empty output folder"):
        export_combined_mesh_builds(prepared, occupied)
    assert (occupied / "keep.txt").read_text(encoding="utf-8") == "user file"
    (skirt / UPPER).write_bytes(b"edited again")
    with pytest.raises(ValueError, match="changed since it was checked"):
        export_combined_mesh_builds(prepared, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_saved_work_records_every_target_file_and_reads_old_records(tmp_path):
    drafts = tmp_path / "drafts"
    game = tmp_path / "game" / "0009"
    entry = ArchiveEntry(UPPER, game / "0.pamt", game / "0.paz", 0, 1, 1, 0, 0)
    first_mod = tmp_path / "mods" / "Set build"
    first_mod.mkdir(parents=True)
    register_built_mod(drafts, mod_root=first_mod, entry=entry, source_sha256="a" * 64, draft_manifest_path=None,
                       target_paths=(UPPER, SHOULDER))
    # An index written before multi-file records: only the single path.
    index = drafts / "built_mods.json"
    payload = json.loads(index.read_text(encoding="utf-8"))
    old = dict(payload["mods"][0], id="old", mod_root=str(tmp_path / "mods" / "Old"), display_name="Old")
    old.pop("target_paths")
    payload["mods"].append(old)
    index.write_text(json.dumps(payload), encoding="utf-8")

    rows = {row.row_id: row for row in list_saved_work(drafts)}
    new_row = next(row for key, row in rows.items() if key != "old")
    assert new_row.kind == KIND_BUILT_MOD and new_row.game_files == (UPPER, SHOULDER)
    assert "target_paths" not in old and rows["old"].game_files == (UPPER,)
    # Filtering by any of a build's files finds it.
    assert [row.row_id for row in list_saved_work(drafts, path_filter=SHOULDER)] == [new_row.row_id]

    combined = tmp_path / "mods" / "Combined"
    combined.mkdir()
    record = register_combined_mod(drafts, mod_root=combined, target_paths=(UPPER, SHOULDER),
                                   combined_from=(new_row, rows["old"]), manager_profile="dmm")
    row = next(item for item in list_saved_work(drafts) if item.row_id == record["id"])
    assert row.game_files == (UPPER, SHOULDER) and record["combined_from"] == [new_row.row_id, "old"]
    assert record["output_kind"] == "combined"


def test_drafts_and_added_folders_record_their_files(reporter_builds, tmp_path):
    drafts = tmp_path / "drafts"
    game = tmp_path / "game" / "0009"
    entry = ArchiveEntry(UPPER, game / "0.pamt", game / "0.paz", 0, 1, 1, 0, 0)
    plan = plan_session_draft(drafts, entry, source_sha256="b" * 64,
                              request=MeshDraftRequest(target_paths=(UPPER, SHOULDER, UPPER)))
    assert plan.manifest["target_paths"] == [UPPER, SHOULDER]
    single = plan_session_draft(drafts, entry, source_sha256="b" * 64)
    assert single.manifest["target_paths"] == [UPPER]
    skirt, _wing = reporter_builds
    record = add_built_mod_folder(drafts, skirt)
    assert record["target_paths"] == [UPPER]


def test_game_file_column_keeps_file_names_whole_and_counts_the_rest():
    upper = shorten_game_path(UPPER, 40)
    shoulder = shorten_game_path(SHOULDER, 40)
    assert upper.endswith("cd_phw_00_ub_00_0151.pac") and shoulder.endswith("cd_phw_00_sho_under_00_0151.pac")
    assert upper != shoulder and upper.startswith(ELLIPSIS) and len(upper) <= 40
    assert shorten_game_path(UPPER, 400) == UPPER
    assert shorten_game_path("a/b/very_long_file_name.pac", 5) == "very_long_file_name.pac"
    label = game_file_label((UPPER, SHOULDER, UPPER.upper()), max_chars=48, package="0009")
    assert label.text.endswith(" + 1 more") and label.more_count == 1
    assert label.tooltip.splitlines() == [UPPER, SHOULDER, "0009"]
    assert game_file_label(()).text == ""
