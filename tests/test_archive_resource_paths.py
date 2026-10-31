"""Engine resource roots and installed-layout companions for animation and voice files.

Owned synthetic fixtures only; the conventions themselves were measured on the
installed build (docs/crimson-desert-research.md §7.3 and §11.3).
"""
from __future__ import annotations

import pytest

from cdmw.core.archive_action_chart import action_chart_resource_names
from cdmw.core.archive_asset_family import build_archive_asset_family_graph
from cdmw.core.archive_preview_result_builder import build_archive_preview_result
from cdmw.core.archive_references import (
    build_archive_related_file_references,
    build_archive_relationship_references,
)
from cdmw.core.archive_reverse_references import reference_evidence_group
from cdmw.domain.archives import resource_paths as rp
from cdmw.models import ArchiveEntry

CLIP_KO = "character/motion/1_pc/1_phm/99_autofacial/korean/line_0001.paa"
CLIP_EN = "character/motion/1_pc/1_phm/99_autofacial/english(us)/line_0001.paa"
META_KO = "actionchart/bin__/animmeta/1_pc/1_phm/99_autofacial/korean/line_0001.paa_metabin"
META_EN = "actionchart/bin__/animmeta/1_pc/1_phm/99_autofacial/english(us)/line_0001.paa_metabin"
LOD_KO = "character/motion/motion_lod__/1_pc/1_phm/99_autofacial/korean/line_0001_lod.paa"
VOICE_KO = "sound/windows/korean/line_0001.wem"
VOICE_EN = "sound/windows/english(us)/line_0001.wem"


def entries_at(tmp_path, payloads):
    entries = []
    paz = tmp_path / "fixture.paz"
    with paz.open("wb") as stream:
        for path, payload in payloads:
            entries.append(ArchiveEntry(path, tmp_path / "0.pamt", paz, stream.tell(), len(payload), len(payload), 0, 0))
            stream.write(payload)
    return entries


def indexes(entries):
    by_path, by_name = {}, {}
    for entry in entries:
        by_path.setdefault(entry.path.lower(), []).append(entry)
        by_name.setdefault(entry.basename.lower(), []).append(entry)
    return by_path, by_name


def framed(text: str) -> bytes:
    """The `.paac` string frame: `<strlen + 1><ASCII><NUL>`."""
    return bytes([len(text) + 1]) + text.encode("ascii") + b"\x00"


def padded_path(prefix: str, suffix: str, length: int) -> str:
    return prefix + "x" * (length - len(prefix) - len(suffix)) + suffix


@pytest.mark.parametrize("installed, stored", [
    ("character/motion/1_pc/1_phm/clip.paa", "1_pc/1_phm/clip.paa"),
    ("character/binary/motionblending/phm/walk.motionblending", "phm/walk.motionblending"),
    ("character/bin__/prefab/6_object/tools/torch.prefab", "character/prefab/6_object/tools/torch.prefab"),
    ("object/bin__/prefab/preset/camera.prefab", "object/prefab/preset/camera.prefab"),
    ("actionchart/bin__/loweraction/2_mon/default_fist_lower.paac", "loweraction/2_mon/default_fist_lower"),
    ("sequencer/baseseq/gamesystemfx/effect/dark.paseq", "baseseq/gamesystemfx/effect/dark"),
])
def test_stored_forms_and_installed_candidates_are_inverse(installed, stored):
    assert rp.stored_reference_forms(installed) == (installed, stored)
    assert installed in rp.installed_path_candidates(stored)
    assert installed in rp.installed_path_candidates("/" + stored.upper())


def test_bare_names_and_unrelated_paths_get_no_engine_root():
    assert rp.installed_path_candidates("clip.paa") == ("clip.paa",)
    assert rp.stored_reference_forms("textures/rock.dds") == ("textures/rock.dds",)
    assert rp.stored_reference_forms("actionchart/bin__/animmeta/a.paa_metabin") == ("actionchart/bin__/animmeta/a.paa_metabin",)


def test_length_prefix_variants_strip_only_the_implied_length():
    chart_string = padded_path("1_pc/", ".paa", 98)  # framed as chr(99) == "c"
    clip_string = padded_path("character/model/", ".pab", 100)  # framed as chr(100) == "d"
    assert rp.length_prefix_variants("c" + chart_string) == ("c" + chart_string, chart_string)
    assert rp.length_prefix_variants("d" + clip_string) == ("d" + clip_string, clip_string)
    assert rp.length_prefix_variants("1_pc/clip.paa") == ("1_pc/clip.paa",)


def test_lip_sync_clip_layout_names_metadata_lod_voice_and_languages():
    companions = {(item.kind, item.path) for item in rp.layout_companions(CLIP_KO)}
    assert (rp.ANIMATION_METADATA, META_KO) in companions
    assert (rp.LOD_CLIP, LOD_KO) in companions
    assert (rp.VOICE_LINE, VOICE_KO) in companions
    assert (rp.LANGUAGE_VARIANT, CLIP_EN) in companions
    assert sum(kind == rp.LANGUAGE_VARIANT for kind, _ in companions) == len(rp.VOICE_LANGUAGE_FOLDERS) - 1
    assert rp.layout_relation(META_KO, CLIP_KO).kind == rp.ANIMATION_CLIP
    assert rp.layout_relation(LOD_KO, CLIP_KO).kind == rp.BASE_CLIP
    assert rp.layout_relation(VOICE_KO, CLIP_KO).kind == rp.LIP_SYNC_CLIP
    assert rp.layout_relation(VOICE_KO, CLIP_KO).confidence == rp.LINE_NAME_CONFIDENCE
    assert rp.layout_relation(CLIP_KO, LOD_KO).confidence == rp.PATH_LAYOUT_CONFIDENCE


@pytest.mark.parametrize("candidate", [
    CLIP_EN,  # another language
    "character/motion/1_pc/1_phm/02_mission/korean/line_0001.paa",  # not a lip-sync folder
    "character/motion/motion_lod__/1_pc/1_phm/99_autofacial/korean/line_0001.paa",  # LOD tree
    "character/motion/1_pc/1_phm/99_autofacial/korean/extra/line_0001.paa",  # nested deeper
])
def test_voice_line_pairs_only_with_its_own_language_lip_sync_folder(candidate):
    relation = rp.layout_relation(VOICE_KO, candidate)
    assert relation is None or relation.kind != rp.LIP_SYNC_CLIP


def test_action_chart_reader_keeps_framed_paths_without_their_length_byte():
    clip = padded_path("1_pc/1_phm/", "_idle.paa", 98)
    data = (
        b"\x07\x00\x00\x00" + framed(clip) + framed("loweraction/2_mon/default_fist_lower")
        + framed("RHand_Socket") + b"\x10unframed/clip_00.paa" + b"\x01\x02"
        + framed("character/binary/motionblending/phm/walk.motionblending")
    )
    assert action_chart_resource_names(data) == (
        clip, "loweraction/2_mon/default_fist_lower", "character/binary/motionblending/phm/walk.motionblending",
    )


def chart_fixture(tmp_path):
    clip = padded_path("1_pc/1_phm/", "_idle.paa", 98)
    chart_data = b"".join(framed(name) for name in (
        clip,
        "loweraction/2_mon/default_fist_lower",
        "/character/prefab/6_object/tools/torch.prefab",
        "character/binary/motionblending/phm/walk.motionblending",
        "1_pc/2_phw/moved_clip.paa",
        "baseseq/never/installed",
    ))
    entries = entries_at(tmp_path, [
        ("actionchart/bin__/upperaction/1_pc/1_phm/basic_upper.paac", chart_data),
        ("character/motion/" + clip, b"PAR "),
        ("actionchart/bin__/loweraction/2_mon/default_fist_lower.paac", b"\x00"),
        ("character/bin__/prefab/6_object/tools/torch.prefab", b"\x00"),
        ("character/binary/motionblending/phm/walk.motionblending", b"\x00"),
        ("character/motion/1_pc/1_phm/moved_clip.paa", b"PAR "),
    ])
    return entries, chart_data


def test_chart_references_resolve_exactly_under_engine_roots(tmp_path):
    entries, chart_data = chart_fixture(tmp_path)
    chart, clip, sub_chart, prefab, blend, moved = entries
    by_path, by_name = indexes(entries)
    refs = build_archive_related_file_references(
        chart, explicit_reference_names=action_chart_resource_names(chart_data),
        archive_entries_by_normalized_path=by_path, archive_entries_by_basename=by_name,
    )
    groups = {ref.resolved_entry.path: reference_evidence_group(ref.relation_confidence) for ref in refs}
    assert groups == {
        clip.path: "Confirmed references",
        sub_chart.path: "Confirmed references",
        prefab.path: "Confirmed references",
        blend.path: "Confirmed references",
        # A stale folder is still only a basename guess.
        moved.path: "Name-based guesses",
    }
    # An extensionless string that resolves to nothing is not reported as a missing file.
    assert all(ref.resolution_status == "resolved" for ref in refs)


def test_chart_preview_lists_its_resources_in_asset_family(tmp_path):
    entries, _chart_data = chart_fixture(tmp_path)
    by_path, by_name = indexes(entries)
    result = build_archive_preview_result(
        entries[0], texture_entries_by_normalized_path=by_path, texture_entries_by_basename=by_name,
        enable_hkx_visual_preview=False,
    )
    rows = {row.path: row for row in result.asset_family_graph.member_rows}
    for entry in entries[1:5]:
        assert rows[entry.path].confidence == "Exact"
        assert rows[entry.path].include_policy == "required"


def test_leaked_length_byte_still_resolves_the_exact_clip(tmp_path):
    clip = padded_path("1_pc/1_phm/", "_idle.paa", 98)
    source, target = entries_at(tmp_path, [("character/binary/motionblending/a.motionblending", b""),
                                           ("character/motion/" + clip, b"PAR ")])
    by_path, by_name = indexes([source, target])
    (ref,) = build_archive_related_file_references(
        source, explicit_reference_names=["c" + clip],
        archive_entries_by_normalized_path=by_path, archive_entries_by_basename=by_name,
    )
    assert ref.resolved_entry == target and ref.reference_name == clip
    assert reference_evidence_group(ref.relation_confidence) == "Confirmed references"


def lip_sync_fixture(tmp_path):
    return entries_at(tmp_path, [(path, b"\x00") for path in (
        CLIP_KO, CLIP_EN, META_KO, META_EN, LOD_KO, VOICE_KO, VOICE_EN,
        # Same names in unrelated folders must not join as layout companions.
        "character/motion/1_pc/1_phm/other/line_0001_lod.paa",
        "sound/windows/media/line_0001.wem",
    )])


def family_rows(source, entries):
    by_path, by_name = indexes(entries)
    refs = build_archive_relationship_references(
        source, archive_entries_by_normalized_path=by_path, archive_entries_by_basename=by_name,
    )
    graph = build_archive_asset_family_graph(source, refs)
    return {row.path: row for row in graph.member_rows if row.path != source.path}


def test_clip_family_lists_layout_companions_with_roles(tmp_path):
    entries = lip_sync_fixture(tmp_path)
    rows = family_rows(entries[0], entries)
    expected = {
        CLIP_EN: ("Language Variant", "Path layout", "manual"),
        META_KO: ("Animation Metadata", "Path layout", "recommended"),
        LOD_KO: ("LOD Clip", "Path layout", "recommended"),
        VOICE_KO: ("Voice Line", "Line name", "manual"),
    }
    assert {path: (row.role, row.confidence, row.include_policy) for path, row in rows.items() if path in expected} == expected
    # Another language's metadata belongs to that language's clip, not to this one.
    assert META_EN not in rows
    assert "character/motion/1_pc/1_phm/other/line_0001_lod.paa" not in rows
    assert not rows[VOICE_KO].warning


def test_voice_line_family_lists_its_lip_sync_clip_and_language_copies(tmp_path):
    entries = lip_sync_fixture(tmp_path)
    voice = next(entry for entry in entries if entry.path == VOICE_KO)
    rows = family_rows(voice, entries)
    assert rows[CLIP_KO].role == "Lip-sync Clip" and rows[CLIP_KO].confidence == "Line name"
    assert rows[VOICE_EN].role == "Language Variant"
    assert (rows[CLIP_KO].group, rows[VOICE_EN].group) == ("Animation / Motion", "Audio / Video")
    # The other language's clip pairs with the other language's line, not this one.
    assert set(rows) == {CLIP_KO, VOICE_EN}


def test_lod_clip_family_names_its_base_clip(tmp_path):
    entries = lip_sync_fixture(tmp_path)
    lod = next(entry for entry in entries if entry.path == LOD_KO)
    rows = family_rows(lod, entries)
    assert rows[CLIP_KO].role == "Base Clip" and rows[CLIP_KO].include_policy == "recommended"
