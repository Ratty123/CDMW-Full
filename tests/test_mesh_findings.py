"""One findings model (P17 stage 2): the cloth guide check and builders agree, on owned fixtures."""

from __future__ import annotations

import struct
from dataclasses import asdict, replace

import pytest

from cdmw.domain.mesh.export_validation import MeshExportValidationIssue, describe_mesh_export_issue
from cdmw.domain.mesh.findings import (
    FIX_CLEAN_UP_MESH,
    FIX_CLOTH_PINS,
    FIX_CLOTH_REDUCE_SKINNING,
    FIX_CLOTH_SOURCE_LOD,
    MAX_FINDING_ELEMENTS,
    MeshFinding,
    MeshFindingError,
    fix_fallback_command,
    mesh_finding,
)
from cdmw.modding.pac_cloth import pac_cloth_lods
from cdmw.modding.pac_cloth_guide_builder import (
    CODE_COLLAPSED_TRIANGLES,
    CODE_FLAT_TRIANGLES,
    CODE_NEEDS_REDUCE_SKINNING,
    CODE_NON_MANIFOLD,
    CODE_NOTHING_LEFT,
    CODE_UNHELD_PIECE,
    check_pac_cloth_guides,
    cloth_guide_lod_statuses,
    create_pac_cloth_guides_with_report,
)
from cdmw.modding.pac_cloth_painted_guides import create_painted_cloth_guides
from tests.test_pac_cloth_guide_builder import FACES, POINTS, SEAM, STEP, guide_free_pac, rule
from tests.test_pac_cloth_painted_guides import TOLERANCE, grid_pac, paint_below


def test_export_validation_issue_is_the_shared_finding_and_old_callers_still_work():
    assert MeshExportValidationIssue is MeshFinding
    old = MeshExportValidationIssue("blocker", "hair_output", "Refused", "topology")
    assert (old.category, old.lod_index, old.part, old.elements, old.fix) == ("topology", -1, "", (), None)
    assert describe_mesh_export_issue(old) == "Refused"
    assert asdict(old)["element_count"] == 0
    found = mesh_finding("warning", "cloth_guide.flat_triangles", "Skipped", part="Cloak", lod=1, submesh=2,
                         element_kind="face", elements=range(1000, 0, -1), fix_command=FIX_CLEAN_UP_MESH,
                         fix_arguments={"part": 2, "lod": 1})
    assert found.kind == "cloth_guide.flat_triangles" and not found.is_blocker
    assert len(found.elements) == MAX_FINDING_ELEMENTS and found.elements[0] == 1 and found.count == 1000
    assert found.fix == (FIX_CLEAN_UP_MESH, {"lod": 1, "part": 2})
    assert found.fix_arguments == (("lod", 1), ("part", 2))
    assert describe_mesh_export_issue(found) == "Skipped [lod_index=1; submesh_index=2; face_count=1000]"
    assert fix_fallback_command(FIX_CLOTH_REDUCE_SKINNING) == "mesh_editor.page.cloth"
    hash(found)  # frozen findings stay usable as keys and in sets


def _agree(source, rules):
    """The check and the builder give the same findings, and the builder refuses on the check's blockers."""
    check = check_pac_cloth_guides(source, rules)
    try:
        _result, report = create_pac_cloth_guides_with_report(source, rules)
    except MeshFindingError as error:
        assert not check.builds
        assert error.findings == check.findings and str(error) == check.blockers[0].message
        return check, None
    assert check.builds
    assert report.findings == check.findings and report.guide_count == check.guide_count
    return check, report


def test_a_seam_weld_collapse_is_a_warning_with_its_face_and_a_clean_up_fix():
    check, report = _agree(guide_free_pac(lods=3, shapes={0: SEAM}), {0: rule()})
    (finding,) = check.findings
    assert (finding.code, finding.severity, finding.part, finding.lod_index) == (
        CODE_COLLAPSED_TRIANGLES, "warning", "guide0", 0)
    assert finding.element_kind == "face" and finding.elements == (2,) and finding.count == 1
    assert finding.fix == (FIX_CLEAN_UP_MESH, {"lod": 0, "part": 0})
    assert finding.message == "Skipped 1 collapsed triangles on guide0, LOD 0."
    assert report.skipped[0].collapsed == 1 and check.part_guides == ((0, 4),)


def test_a_triangle_flat_once_stored_is_a_warning_naming_its_source_face():
    thin = ((16000 * STEP, .2, 0.), (16001 * STEP, .5, 0.), (16000 * STEP, .8, 0.))
    source = guide_free_pac(lods=2, parts=2, shapes={0: (POINTS + thin, FACES + ((4, 5, 6),))})
    check, _report = _agree(source, {0: rule(), 1: rule()})
    (finding,) = check.findings
    assert (finding.code, finding.part, finding.elements) == (CODE_FLAT_TRIANGLES, "guide0", (2,))


def test_a_part_left_with_nothing_refuses_with_the_checks_own_finding():
    points = ((0., 0., 0.), (1., 0., 0.), (1., 0., 0.), (0., 1., 0.))
    source = guide_free_pac(lods=2, parts=2, shapes={1: (points, ((0, 1, 2),))})
    check, _ = _agree(source, {0: rule(), 1: rule()})
    (blocker,) = check.blockers
    assert (blocker.code, blocker.part, blocker.lod_index, blocker.elements) == (CODE_NOTHING_LEFT, "guide1", 0, (0,))
    assert blocker.message.startswith("guide1, LOD 0: all 1 triangles collapse")
    assert blocker.fix == (FIX_CLOTH_SOURCE_LOD, {"part": 1})


def test_a_piece_nothing_holds_names_its_part_and_guides():
    points = ((0., .6, 0.), (1., .6, 0.), (0., 1., 0.), (0., 0., 0.), (1., 0., 0.), (0., .3, 0.), (0., 1., 0.))
    source = guide_free_pac(lods=2, shapes={0: (points, ((0, 1, 2), (3, 4, 5), (2, 6, 3)))})
    check, _ = _agree(source, {0: rule()})
    blocker = next(finding for finding in check.blockers if finding.code == CODE_UNHELD_PIECE)
    assert "(1 on guide0, LOD 0 without one)" in blocker.message
    assert blocker.element_kind == "guide" and blocker.count == 3 and blocker.fix[0] == FIX_CLOTH_PINS


def test_an_edge_shared_by_three_triangles_is_named_before_the_build():
    points = ((0., 0., 0.), (1., 0., 0.), (0., 1., 0.), (1., 1., 0.), (.5, .5, 1.))
    source = guide_free_pac(lods=2, shapes={0: (points, ((0, 1, 2), (1, 0, 3), (0, 1, 4)))})
    check, _ = _agree(source, {0: rule()})
    (blocker,) = check.blockers
    assert blocker.code == CODE_NON_MANIFOLD and blocker.part == "guide0" and blocker.elements == (0, 1, 2)
    assert blocker.message.startswith("guide0, LOD 0: 1 edges are shared by more than two triangles")


def _heavy_skin(source):
    """Give every vertex of part 0, at every LOD, six influences, so it needs Reduce skinning."""
    data = bytearray(source)
    for level in pac_cloth_lods(source):
        for offset in level.submeshes[0].source_vertex_offsets:
            struct.pack_into("<2I", data, offset + 20, 0 | 1 << 10 | 2 << 20 | 0xc0000000, 3 | 4 << 10 | 5 << 20 | 0x80000000)
            data[offset + 28:offset + 34] = bytes((50, 50, 50, 50, 50, 5))
    return bytes(data)


def test_vertices_that_need_reduce_skinning_are_counted_per_lod_and_offer_the_setting():
    source = _heavy_skin(guide_free_pac(lods=2))
    check, _ = _agree(source, {0: rule()})
    assert [(f.code, f.lod_index, f.count) for f in check.blockers] == [
        (CODE_NEEDS_REDUCE_SKINNING, 0, 4), (CODE_NEEDS_REDUCE_SKINNING, 1, 4)]
    assert check.blockers[0].fix == (FIX_CLOTH_REDUCE_SKINNING, {"part": 0})
    assert check.blockers[0].message.startswith("guide0, LOD 0: 4 vertices need skeletal weight conversion.")
    # With the setting on, the same source builds.
    reduced = replace(rule(), reduce_skinning=True)
    assert _agree(source, {0: reduced})[0].builds


def test_each_source_lod_says_whether_it_builds():
    source = guide_free_pac(lods=3, shapes={0: SEAM})
    statuses = cloth_guide_lod_statuses(source, {0: rule()})
    assert [(s.part, s.lod, s.guide_count, s.collapsed, s.builds) for s in statuses] == [
        ("guide0", 0, 4, 1, True), ("guide0", 1, 4, 1, True), ("guide0", 2, 4, 1, True)]
    points = ((0., 0., 0.), (1., 0., 0.), (1., 0., 0.), (0., 1., 0.))
    bad = guide_free_pac(lods=2, parts=2, shapes={1: (points, ((0, 1, 2),))})
    rows = cloth_guide_lod_statuses(bad, {0: rule(), 1: rule()})
    assert [(s.part, s.lod, s.builds) for s in rows] == [
        ("guide0", 0, True), ("guide0", 1, True), ("guide1", 0, False), ("guide1", 1, False)]
    assert rows[2].blockers[0].code == CODE_NOTHING_LEFT


def test_painted_cloth_refusals_and_notes_are_findings_too():
    data = grid_pac()
    with pytest.raises(MeshFindingError, match="Nothing holds the painted cloth") as raised:
        create_painted_cloth_guides(data, paint_below(data, 2.0), max_sample_distance=TOLERANCE)
    assert raised.value.blockers[0].code == "cloth_guide.pins" and raised.value.blockers[0].fix[0] == FIX_CLOTH_PINS
    _result, report = create_painted_cloth_guides(data, paint_below(data, .55), max_sample_distance=TOLERANCE)
    assert all(not finding.is_blocker for finding in report.findings)
