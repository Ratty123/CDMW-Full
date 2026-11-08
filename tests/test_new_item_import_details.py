"""Import details are grouped per part, not one paragraph per part."""
from types import SimpleNamespace

from cdmw.domain.mesh.skin_policy import SkinningPartReport
from cdmw.ui.new_item.import_details import build_note_lines, import_detail_lines
from cdmw.ui.new_item.ui_kit import WARN

DONOR = "character/model/1_pc/2_phw/armor/9_upperbody/cd_phw_00_ub_00_0151.pac"


def _report(index, details):
    return SkinningPartReport(index, f"Main_submesh{index}", "transfer", DONOR, transfer_details=tuple(details))


def test_transfer_reports_become_a_heading_and_one_bullet_per_part():
    far = _report(0, (
        "Skin weights target 0 (Belt): transferred 1,366 vertices; surface-distance p95 0.143237 (limit 0.059502).",
        "Warning: skin weights for target 0 (Belt) were matched from far off the source surface (p95 0.143237, "
        "more than 5% of the source bounds, limit 0.059502); check the rig deforms as intended.",
        "Skin weights target 4 (Vest): transferred 100 vertices; surface-distance p95 0.01 (limit 0.059502).",
    ))
    near = _report(1, ("Skin weights target 1 (Bag): transferred 3,655 vertices; surface-distance p95 0.0578 (limit 0.0595).",))
    source = SimpleNamespace(skinning_reports=(far, near), notes=(
        far.summary(), near.summary(), "Extracted 22 embedded glTF texture file(s) for supplemental import."))
    lines = import_detail_lines(source)
    texts = [text for text, _tone in lines]
    assert texts[0].startswith("Weights: taken from cd_phw_00_ub_00_0151.pac.")
    assert "• Main_submesh0: 1,466 vertices weighted from the template" in texts
    assert "• Main_submesh1: 3,655 vertices weighted from the template" in texts
    warnings = [text for text, tone in lines if tone == WARN]
    assert warnings == ["    Matched far from the template's surface (1 target(s)); check how it bends."]
    assert texts[-2:] == ["File: what the reader found",
                          "• Extracted 22 embedded glTF texture file(s) for supplemental import."]
    assert not any("surface-distance" in text for text in texts)


def test_apply_notes_drop_repeated_weight_lines_and_count_far_matches():
    lines = build_note_lines((
        "Replacement source: model.glb",
        "Skin weights target 0 (Belt): transferred 10 vertices; surface-distance p95 0.1 (limit 0.05).",
        "Warning: skin weights for target 0 (Belt) were matched from far off the source surface (p95 0.1, limit 0.05).",
    ))
    assert lines == [("• Replacement source: model.glb", None),
                     ("• 1 weight target(s) matched far from the template's surface; check how they bend.", WARN)]
