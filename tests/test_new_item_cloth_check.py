"""Create New Item: a cloth-painted model is checked for guides, bindings and a profile.

These run the cloth services on the real import result class. A stand-in object
takes any attribute, which hid a field the real class did not have.
"""

import struct
from types import SimpleNamespace

import pytest

from cdmw.domain.archives.mesh_contracts import MeshImportPreviewResult
from cdmw.modding.pac_cloth import decode_pac_cloth_binding, pac_cloth_lods
from cdmw.services.new_item_cloth_check import (
    CATALOGUE_PATH, cloth_part_profiles, painted_cloth_parts, profile_document_paths, verify_painted_cloth,
)
from cdmw.services.new_item_cloth_guides import apply_import_cloth_guides
from tests.test_new_item_cloth_guides import CATALOGUE, IDENTITY, SIDECAR, imported_from
from tests.test_pac_cloth_painted_guides import grid_pac

SIDECAR_PATH = "character/modelproperty/1_pc/1_phm/armor/skirt.pac_xml"
PROFILE_DOCUMENT = "character/descriptors/pbd/material/cloth_skirt.xml"


def built(data, *, sidecar=None):
    """The result Apply placement really hands on, with only its required fields set."""
    specs = () if sidecar is None else (SimpleNamespace(target_path=SIDECAR_PATH, payload_data=sidecar, source_path=None),)
    return MeshImportPreviewResult(rebuilt_data=data, parsed_mesh=None, preview_model=None, summary_lines=[],
                                   supplemental_file_specs=specs)


def painted(profile="Cloth_Skirt", *, sidecar=SIDECAR % b""):
    data = grid_pac()
    result = built(data, sidecar=sidecar)
    assert apply_import_cloth_guides(result, imported_from(data), IDENTITY, profile=profile)
    return result


def first_cloth_vertex(pac):
    for level in pac_cloth_lods(pac):
        for part in level.submeshes:
            for offset in part.source_vertex_offsets:
                if decode_pac_cloth_binding(pac, offset) is not None:
                    return offset
    raise AssertionError("no cloth vertex")


def test_the_real_import_result_carries_own_guides_through_to_the_plan_files():
    from cdmw.services.new_item_planning import model_files_from_import

    result = painted()
    assert result.cloth_profile_edit == ("Cloth_Skirt", ("skirt",))
    assert result.cloth_paint_report.guide_count and "new cloth guides" in result.summary_lines[-1]
    family = SimpleNamespace(files_for=lambda role: (SimpleNamespace(path=SIDECAR_PATH),) if role == "pac_xml" else ())
    files = model_files_from_import(result, family=family)
    assert files.cloth_painted and files.cloth_profile == ("Cloth_Skirt", ("skirt",))
    check = verify_painted_cloth(files.pac_data, files.side_files[SIDECAR_PATH], catalogue=CATALOGUE)
    assert check.cloth_parts == ("skirt",) and check.guide_count == result.cloth_paint_report.guide_count
    assert check.cloth_vertices == result.cloth_paint_report.cloth_vertices
    assert check.profiles == (("skirt", "Cloth_Skirt"),) and check.profile_paths == (PROFILE_DOCUMENT,)


def test_the_real_import_result_also_takes_paint_bound_to_the_template_guides():
    from cdmw.services.new_item_cloth_paint import apply_import_cloth_paint
    from tests.test_new_item_cloth_paint import cloth_template, imported

    data = cloth_template()
    dress = pac_cloth_lods(data)[0].submeshes[1]
    result = built(data)
    assert apply_import_cloth_paint(result, imported(dress.vertices, [1.] * len(dress.vertices)), IDENTITY)
    assert result.cloth_paint_report is not None and result.cloth_profile_edit is None


def test_a_model_without_cloth_has_nothing_to_check():
    check = verify_painted_cloth(grid_pac(), None, catalogue=CATALOGUE)
    assert check.cloth_parts == () and check.guide_count == 0 and check.cloth_vertices == 0


@pytest.mark.parametrize("material, catalogue, message", [
    (None, CATALOGUE, "no material file"),
    (SIDECAR % b"", CATALOGUE, "no cloth profile"),
    (SIDECAR % b' _pbdSimulationMaterialName="Made_Up"', CATALOGUE, "not in the game's profile catalogue"),
    ((SIDECAR % b' _pbdSimulationMaterialName="wing"').replace(b'"skirt"', b'"cape"'), CATALOGUE,
     r"no entry for cloth part\(s\): skirt"),
    (SIDECAR % b' _pbdSimulationMaterialName="wing"', b"<PbdConfig/>", "not in the game's profile catalogue"),
])
def test_cloth_without_a_resolving_profile_is_refused(material, catalogue, message):
    pac = painted().rebuilt_data
    with pytest.raises(ValueError, match=message):
        verify_painted_cloth(pac, material, catalogue=catalogue)


def test_profile_names_are_required_but_not_resolved_without_a_catalogue():
    pac = painted().rebuilt_data
    check = verify_painted_cloth(pac, SIDECAR % b' _pbdSimulationMaterialName="Anything"')
    assert check.profiles == (("skirt", "Anything"),) and check.profile_paths == ()
    assert cloth_part_profiles(SIDECAR % b' _pbdSimulationMaterialName="wing"', ("skirt", "belt")) == (
        ("skirt", "wing"), ("belt", "wing"))
    assert profile_document_paths(CATALOGUE, ("wing", "Cloth_Skirt", "wing")) == (
        "character/descriptors/pbd/material/wing.xml", PROFILE_DOCUMENT)
    # A name the catalogue declares twice resolves to both documents, and both are pinned.
    twice = CATALOGUE.replace(b"</PbdConfig>", b'\t<Material Name="wing" Filename="material/other.xml"/>\n</PbdConfig>')
    assert profile_document_paths(twice, ("wing",)) == (
        "character/descriptors/pbd/material/wing.xml", "character/descriptors/pbd/material/other.xml")
    # A part under two owners may be given a profile by each, as shipped material files do.
    variants = (SIDECAR % b' _pbdSimulationMaterialName="wing"').replace(
        b"</ModelPropertyList>",
        b'\t<ModelProperty Index="1" Version="Reflection">\n'
        b'\t\t<SkinnedMeshProperty ReflectObjectXMLDataVersion="9" _pbdSimulationMaterialName="Cloth_Skirt">\n'
        b'\t\t\t<Vector Name="_subMeshResources">\n'
        b'\t\t\t\t<SkinnedMeshMaterialWrapper ItemID="1" _subMeshName="skirt" _jiggleWindWeight="0"/>\n'
        b'\t\t\t</Vector>\n\t\t</SkinnedMeshProperty>\n\t</ModelProperty>\n</ModelPropertyList>')
    assert cloth_part_profiles(variants, ("skirt",)) == (("skirt", "wing"), ("skirt", "Cloth_Skirt"))


def test_a_cloth_vertex_naming_a_guide_that_does_not_exist_is_refused():
    pac = bytearray(painted().rebuilt_data)
    offset = first_cloth_vertex(bytes(pac))
    group, = struct.unpack_from("<I", pac, offset + 24)
    struct.pack_into("<I", pac, offset + 24, (group & ~(1023 << 10)) | (1023 << 10))
    with pytest.raises(ValueError, match=r"follow cloth guides the model does not have \(it has \d+\)"):
        painted_cloth_parts(bytes(pac))


def test_cloth_vertices_without_a_guide_mesh_are_refused():
    from cdmw.modding.pac_cloth_painted_guides import remove_pac_cloth_guides

    pac = painted().rebuilt_data
    offset = first_cloth_vertex(pac)
    stripped, removed = remove_pac_cloth_guides(pac)
    assert removed and painted_cloth_parts(stripped).cloth_parts == ()
    # the same PAC with one binding left behind, as a partial strip would leave it;
    # removing the guide block moved the vertex records, so find the record again
    records = [o for level in pac_cloth_lods(pac) for part in level.submeshes for o in part.source_vertex_offsets]
    moved = [o for level in pac_cloth_lods(stripped) for part in level.submeshes for o in part.source_vertex_offsets]
    target = moved[records.index(offset)]
    broken = bytearray(stripped)
    broken[target:target + 40] = pac[offset:offset + 40]
    with pytest.raises(ValueError, match=r"does not have \(it has 0\)"):
        painted_cloth_parts(bytes(broken))


def test_the_package_audit_verifies_painted_cloth_and_pins_its_profile():
    from cdmw.domain.new_item.independent import IndependentItemError
    from cdmw.services.independent_item_physics import audit_painted_cloth

    result = painted()
    sidecar = SIDECAR % b' _pbdSimulationMaterialName="Cloth_Skirt"'
    files = {CATALOGUE_PATH: CATALOGUE, PROFILE_DOCUMENT: b"<Profile/>"}
    snapshot = SimpleNamespace(has_entry=files.__contains__, payload=files.__getitem__)
    required = []
    audit_painted_cloth("model.pac", result.rebuilt_data, sidecar, snapshot, required.append)
    assert required == [CATALOGUE_PATH, PROFILE_DOCUMENT]

    for material, present, message in (
            (SIDECAR % b"", files, "no cloth profile"),
            (None, files, "no material file"),
            (sidecar, {}, "not in the game's profile catalogue")):
        partial = SimpleNamespace(has_entry=present.__contains__, payload=present.__getitem__)
        with pytest.raises(IndependentItemError, match=message):
            audit_painted_cloth("model.pac", result.rebuilt_data, material, partial, lambda path: None)

    # A profile document the game does not ship is refused by the pin itself, as the
    # audit's own `require` refuses any dependency it cannot resolve.
    def pin(path):
        if path not in {CATALOGUE_PATH}:
            raise IndependentItemError(f"Unresolved item dependency: {path}")

    only_catalogue = SimpleNamespace(has_entry={CATALOGUE_PATH}.__contains__, payload=files.__getitem__)
    with pytest.raises(IndependentItemError, match="Unresolved item dependency: " + PROFILE_DOCUMENT):
        audit_painted_cloth("model.pac", result.rebuilt_data, sidecar, only_catalogue, pin)

    # Painted in the editor, but none of the paint reached this model: nothing to pin.
    untouched = []
    audit_painted_cloth("model.pac", grid_pac(), None, SimpleNamespace(has_entry=lambda path: False), untouched.append)
    assert untouched == []
