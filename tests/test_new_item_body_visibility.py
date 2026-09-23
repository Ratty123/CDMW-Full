"""Experimental visibility: exact component edits, isolated rules, export and UI."""
from dataclasses import replace
import json
import os
import struct
import xml.etree.ElementTree as ET

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtWidgets import QApplication

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.equipment_visibility import (
    POSTFIX_PATH, SHRINK_PATH, VisibilityProfile, clone_postfix_rules,
    clone_shrink_rules, matching_postfixes,
)
from cdmw.core.prefab_binary import KIND_COLLECTION, KIND_POINTER, KIND_STRING, decode_prefab_binary
from cdmw.domain.new_item.body_visibility import BodyVisibilityChoice
from cdmw.domain.new_item.rules import validate_spec
from cdmw.services.new_item_mod_base import build_mod_base_snapshot
from cdmw.services.new_item_service import NewItemService
from tests.test_new_item_provenance import current_files, spec
from tests.test_new_item_service import PAC, TEMPLATE, _read, build_package
from tests.test_new_item_variant_authoring import selections
from tests.test_prefab_component_graft import _Blob, _member, _pointer_header, _text, _type

SKIN = BodyVisibilityChoice(keep_skin=True)
HAIR = BodyVisibilityChoice(keep_hair=True)
BOTH = BodyVisibilityChoice(True, True)
SHRINK = b'''\xef\xbb\xbf<?xml version="1.0" encoding="utf-8"?>
<!-- preserved unknown comment -->
<GlobalSetting><ShrinkDepthBias><Helm Value="0.01" UseCustomVolume="True"/></ShrinkDepthBias>
<ConditionalShrinkDepthBias><Caster ShrinkTag="Helm"><Bone Name="neck" Scale="0.5"/></Caster></ConditionalShrinkDepthBias>
<SocketToShrinkTag><Head toTag="Zero"/></SocketToShrinkTag></GlobalSetting>
<Shrink>
<ShrinkTag Name="Helm"><Shrink>Nude</Shrink><Shrink>Hair</Shrink><Shrink>LongHair</Shrink><Shrink>Hair_Tail</Shrink><Shrink>Beard</Shrink><Shrink>Underwear</Shrink><Shrink>Mask</Shrink></ShrinkTag>
<ShrinkTag Name="Shoulder"><Shrink>Helm</Shrink><Shrink>Nude</Shrink></ShrinkTag>
<ShrinkTag Name="Hand"><Shrink>Nude</Shrink><Shrink>Underwear</Shrink></ShrinkTag>
</Shrink>'''
POSTFIX = b'''<!-- original conditions stay intact -->
<PostfixCondition Type="Hide" SourcePartPrefabPostfix="_R"><TargetPart PartName="CD_Head"/><TargetPart PartName="CD_Hair"/><TargetPart PartName="CD_Beard"/><TargetPart PartName="CD_Hand"/></PostfixCondition>
<PostfixCondition Type="Hide" SourcePartPrefabPostfix="_L"><TargetPart PartName="CD_Nude"/><TargetPart PartName="CD_Hair"/></PostfixCondition>
<PostfixCondition Type="Swap" SourcePartPrefabPostfix="_R" Extra="preserve"><TargetPart PartName="CD_Head"/></PostfixCondition>'''


def xml(data):
    text = data.decode("utf-8-sig")
    if text.startswith("<?xml"):
        text = text.split("?>", 1)[1]
    return ET.fromstring("<root>" + text + "</root>")


def prefab(components):
    """Pointer-backed mesh references, labels and transforms, as in real prefabs."""
    types = _type("SceneObject", _member("_components", "ReflectObjectPtr", KIND_COLLECTION, 0))
    types += _type("SkinnedMeshComponent", _member("_shrinkTag", "staticstringA", KIND_STRING, 1),
                   _member("_skinnedMeshFile", "ReflectObjectPtr", KIND_POINTER, 8),
                   _member("_label", "staticstringA", KIND_STRING, 1), _member("_offsetTransform", "Transform", 0, 40))
    types += _type("ResourceReferencePath_SkinnedMesh", _member("_path", "NormalizedPathA", KIND_STRING, 1))
    header = struct.pack("<HHH", 0xFFFF, 4, 0) + bytes(8) + struct.pack("<IH", 15, 3) + types
    pool = struct.pack("<I", 0)
    base = len(header) + len(pool) + 28
    blob = _Blob(base)
    blob.out += struct.pack("<H", 2) + (1).to_bytes(6, "little") + b"\0" + struct.pack("<I", len(components))
    for i, (path, tag) in enumerate(components):
        blob.out += _pointer_header(15, 1)
        name = blob.pointer(bytes(8))
        blob.out += struct.pack("<HHH", 0, 1, 0) + _text(f"CD_TestComponent_{i:02}") + _text(tag) + b"\1"
        blob.out += _pointer_header(1, 2)
        pointer = blob.pointer()
        blob.out += struct.pack("<I", 0) + _text(path)
        blob.length_field(pointer)
        blob.out += _text(tag) + struct.pack("<10f", 1, 1, 1, 0, 0, 0, 1, 0.1, 0.2, 0.3)
        blob.length_field(name)
    blob.out += b"\1"
    data_header = struct.pack("<IIIQII", 1, base + len(blob.out), 0, 0xFFFFFFFFFFFFFFFF, base, len(blob.out))
    return header + pool + data_header + blob.out


def game(tmp_path, *, components=None, shrink=SHRINK, postfix=POSTFIX):
    files = current_files()
    for path in tuple(files):
        if path.endswith(".prefab") and "sword_0109" in path:
            files[path] = prefab(components or ((PAC, "Helm"),))
    files[SHRINK_PATH], files[POSTFIX_PATH] = shrink, postfix
    for path, _tag in components or ():
        files.setdefault(path, files[PAC])
        side = path.replace("character/model/", "character/modelproperty/").removesuffix(".pac") + ".pac_xml"
        files.setdefault(side, b"<Materials/>")
    entries = parse_archive_pamt(build_package(tmp_path / "fixture", files))
    service = NewItemService()
    return service, service.build_snapshot(entries, read_entry=_read), files


def receivers(data, tag):
    return {node.text for node in xml(data).find(f"./Shrink/ShrinkTag[@Name='{tag}']").iter("Shrink")}


@pytest.mark.parametrize("choice,remaining", [(SKIN, {"Hair", "LongHair", "Hair_Tail", "Beard", "Underwear", "Mask"}),
                                              (HAIR, {"Nude", "Underwear", "Mask"}), (BOTH, {"Underwear", "Mask"})])
def test_rule_profiles_filter_only_requested_receivers_and_keep_incoming_rules(choice, remaining):
    result = clone_shrink_rules(SHRINK, (VisibilityProfile("Helm", "CDMW_Test", choice),))
    root = xml(result)
    assert receivers(result, "CDMW_Test") == remaining
    assert receivers(result, "Helm") == receivers(SHRINK, "Helm")
    assert receivers(result, "Shoulder") == {"Helm", "Nude", "CDMW_Test"}
    assert root.find("./GlobalSetting/ShrinkDepthBias/CDMW_Test").attrib == {"Value": "0.01", "UseCustomVolume": "True"}
    assert root.find("./GlobalSetting/ConditionalShrinkDepthBias/Caster[@ShrinkTag='CDMW_Test']/Bone").attrib == {"Name": "neck", "Scale": "0.5"}
    assert b"<!-- preserved unknown comment -->" in result
    assert b'<SocketToShrinkTag><Head toTag="Zero"/></SocketToShrinkTag>' in result
    assert result.startswith(SHRINK[:SHRINK.index(b"\n")])


def test_multiple_profiles_and_later_items_preserve_incoming_relationships():
    first = clone_shrink_rules(SHRINK, (VisibilityProfile("Helm", "HelmetA", SKIN), VisibilityProfile("Shoulder", "ShoulderA", SKIN)))
    second = clone_shrink_rules(first, (VisibilityProfile("Helm", "HelmetB", HAIR),))
    assert receivers(second, "ShoulderA") == {"Helm", "HelmetA", "HelmetB"}
    assert receivers(second, "Shoulder") == {"Helm", "HelmetA", "HelmetB", "Nude"}


def test_postfix_copies_are_isolated_and_keep_other_hiding_and_non_hide_rules():
    result = clone_postfix_rules(POSTFIX, (("helmet_r", "new_item", SKIN),))
    assert result.startswith(POSTFIX)
    nodes = xml(result).findall("./PostfixCondition[@SourcePartPrefabPostfix='new_item']")
    assert [{n.get("PartName") for n in node} for node in nodes] == [{"CD_Hair", "CD_Beard", "CD_Hand"}, {"CD_Head"}]
    assert nodes[1].attrib["Extra"] == "preserve"
    hair = clone_postfix_rules(POSTFIX, (("helmet_r", "new_item", HAIR),))
    assert {n.get("PartName") for n in xml(hair).find("./PostfixCondition[@SourcePartPrefabPostfix='new_item']")} == {"CD_Head", "CD_Hand"}


@pytest.mark.parametrize("data,match", [(b"<Shrink>", "Malformed"), (b'<!DOCTYPE Shrink []><Shrink/>', "Unsupported"),
                                       (SHRINK + b"<UsePostCutbox><Helm/></UsePostCutbox>", "not supported")])
def test_unsupported_descriptor_cannot_silently_produce_rules(data, match):
    with pytest.raises(ValueError, match=match):
        clone_shrink_rules(data, (VisibilityProfile("Helm", "New", SKIN),))


def test_occupied_profile_and_matching_output_suffix_are_rejected():
    with pytest.raises(ValueError, match="occupied"):
        clone_shrink_rules(SHRINK, (VisibilityProfile("Helm", "Hand", SKIN),))
    with pytest.raises(ValueError, match="still matches"):
        clone_postfix_rules(POSTFIX, (("helmet_r", "custom_r", SKIN),))


def test_disabled_defaults_do_not_read_or_export_descriptors(tmp_path):
    service, snapshot, _ = game(tmp_path, shrink=b"malformed", postfix=b"malformed")
    plan = service.plan(spec(), snapshot)
    assert not plan.spec.needs_own_family
    assert "body_visibility" not in plan.manifest
    assert SHRINK_PATH not in plan.loose_files and POSTFIX_PATH not in plan.loose_files


def test_visibility_only_plan_clones_component_tags_and_isolates_legacy_suffixes(tmp_path):
    service, snapshot, files = game(tmp_path)
    plan = service.plan(replace(spec(), body_visibility=SKIN), snapshot)
    assert plan.spec.needs_own_family
    assert {SHRINK_PATH, POSTFIX_PATH} <= {p.entry.path for p in plan.patches}
    for record in plan.manifest["body_visibility"]["prefabs"]:
        before = decode_prefab_binary(files[record["source_prefab"]])
        after = decode_prefab_binary(plan.loose_files[record["output_prefab"]])
        assert before.walk_complete and after.walk_complete and not after.inferred_objects
        old, new = before.objects[0], after.objects[0]
        values = dict(new.values)
        assert values["_shrinkTag"].text == record["components"][0]["profile"]
        assert len(values["_shrinkTag"].text) == len(dict(old.values)["_shrinkTag"].text)
        assert values["_label"].text == "Helm"
        assert [n.raw for n in new.numbers] == [n.raw for n in old.numbers]
        assert values["_skinnedMeshFile"].text in plan.loose_files
        assert not matching_postfixes(POSTFIX, record["output_prefab"].split("/")[-1].removesuffix(".prefab"))
        assert "Nude" not in receivers(plan.loose_files[SHRINK_PATH], values["_shrinkTag"].text)
        assert record["source_prefab"] not in plan.loose_files
    assert snapshot.payload(SHRINK_PATH) == SHRINK
    assert snapshot.payload(POSTFIX_PATH) == POSTFIX
    assert any("in-game A/B" in w for w in plan.warnings)


def test_off_baseline_keeps_original_postfix_hiding_when_variant_name_changes(tmp_path):
    service, snapshot, _ = game(tmp_path, shrink=b"unused malformed shrink descriptor")
    choice = selections(snapshot)[0]
    plan = service.plan(replace(spec(), variants=(choice,)), snapshot)
    record, = plan.manifest["body_visibility"]["prefabs"]
    assert not plan.manifest["body_visibility"]["experimental"]
    assert SHRINK_PATH not in plan.loose_files
    output = record["output_prefab"].split("/")[-1].removesuffix(".prefab")
    nodes = xml(plan.loose_files[POSTFIX_PATH]).findall(f"./PostfixCondition[@SourcePartPrefabPostfix='{output}']")
    assert [{n.get("PartName") for n in node} for node in nodes] == [{"CD_Head", "CD_Hair", "CD_Beard", "CD_Hand"}, {"CD_Head"}]
    assert dict(decode_prefab_binary(plan.loose_files[record["output_prefab"]]).objects[0].values)["_shrinkTag"].text == "Helm"


def test_exact_binding_changes_all_its_components_but_not_other_meshes(tmp_path):
    other = PAC.removesuffix(".pac") + "_trim.pac"
    service, snapshot, _ = game(tmp_path, components=((PAC, "Helm"), (PAC, "Hand"), (other, "Helm")))
    choice = replace(next(v for v in selections(snapshot) if v.model_path == PAC), body_visibility=SKIN)
    plan = service.plan(replace(spec(), variants=(choice,)), snapshot)
    record, = plan.manifest["body_visibility"]["prefabs"]
    doc = decode_prefab_binary(plan.loose_files[record["output_prefab"]])
    assert doc.walk_complete
    assert [dict(o.values)["_shrinkTag"].text != tag for o, tag in zip(doc.objects, ("Helm", "Hand", "Helm"))] == [True, True, False]
    assert dict(doc.objects[2].values)["_shrinkTag"].text == "Helm"
    assert len(plan.manifest["pappt_records"]) == 1
    assert any(v["appearance"] == "template" for v in plan.manifest["variants"])


def test_two_bindings_combine_whole_part_choices_without_combining_shrink_profiles(tmp_path):
    other = PAC.removesuffix(".pac") + "_trim.pac"
    service, snapshot, _ = game(tmp_path, components=((PAC, "Helm"), (other, "Helm")))
    first = selections(snapshot)[0]
    choices = (replace(first, body_visibility=SKIN), replace(first, model_path=other, body_visibility=HAIR))
    plan = service.plan(replace(spec(), variants=choices), snapshot)
    record, = plan.manifest["body_visibility"]["prefabs"]
    assert record["whole_part_keep_skin"] and record["whole_part_keep_hair"]
    one, two = record["components"]
    assert "Nude" not in receivers(plan.loose_files[SHRINK_PATH], one["profile"])
    assert "Nude" in receivers(plan.loose_files[SHRINK_PATH], two["profile"])


def test_short_profile_collision_uses_another_name_and_reuses_it_for_shared_choice(tmp_path):
    service, snapshot, _ = game(tmp_path / "first", components=((PAC, "Helm"), (PAC, "Helm")))
    choice = replace(selections(snapshot)[0], body_visibility=SKIN)
    first = service.plan(replace(spec(), variants=(choice,)), snapshot)
    tag = first.manifest["body_visibility"]["profiles"][0]["tag"]
    occupied = SHRINK
    end = occupied.rfind(b"</Shrink>")
    occupied = occupied[:end] + f'<ShrinkTag Name="{tag}"><Shrink>Mask</Shrink></ShrinkTag>'.encode() + occupied[end:]
    service, snapshot, _ = game(tmp_path / "occupied", components=((PAC, "Helm"), (PAC, "Helm")), shrink=occupied)
    second = service.plan(replace(spec(), variants=(choice,)), snapshot)
    profile, = second.manifest["body_visibility"]["profiles"]
    assert profile["tag"] != tag and len(profile["tag"]) == len("Helm")
    assert receivers(second.loose_files[SHRINK_PATH], tag) == {"Mask"}
    assert {c["profile"] for c in second.manifest["body_visibility"]["prefabs"][0]["components"]} == {profile["tag"]}


def test_unknown_shrink_tag_reports_partial_support_and_no_rules_fails(tmp_path):
    service, snapshot, _ = game(tmp_path, components=((PAC, "UnknownTag"),))
    plan = service.plan(replace(spec(), body_visibility=SKIN), snapshot)
    assert any("unknown shrink tag 'UnknownTag'" in w for w in plan.warnings)
    assert SHRINK_PATH not in plan.loose_files
    service, snapshot, _ = game(tmp_path / "no-rules", components=((PAC, ""),), postfix=b"<!-- none -->")
    with pytest.raises(ValueError, match="no supported shrink or postfix"):
        service.plan(replace(spec(), body_visibility=SKIN), snapshot)


@pytest.mark.parametrize("variant", [False, True])
def test_unsafe_mesh_path_copy_names_the_prefab_and_keeps_the_real_cause(tmp_path, monkeypatch, variant):
    service, snapshot, _ = game(tmp_path)
    choice = replace(selections(snapshot)[0], body_visibility=SKIN)
    def refuse(*_args):
        raise ValueError("The pointee has two possible length fields; refusing to guess.")
    module = "cdmw.services.new_item_variants" if variant else "cdmw.services.new_item_planning"
    monkeypatch.setattr(module + ".rewrite_prefab_paths_any_length", refuse)
    request = replace(spec(), variants=(choice,)) if variant else replace(spec(), body_visibility=SKIN)
    with pytest.raises(ValueError, match="Cannot copy prefab .*prefab: The pointee has two possible length fields"):
        service.plan(request, snapshot)


def test_loose_export_and_mod_base_preserve_each_items_rules_and_provenance(tmp_path):
    service, snapshot, _ = game(tmp_path)
    first = service.plan(replace(spec("Visibility_A"), body_visibility=SKIN), snapshot)
    folder = tmp_path / "A"
    service.export_loose(first, folder, manager="JMM")
    assert (folder / SHRINK_PATH).read_bytes() == first.loose_files[SHRINK_PATH]
    manifest = json.loads((folder / "new-item.json").read_text(encoding="utf-8"))
    assert manifest["body_visibility"]["experimental"]
    assert SHRINK_PATH in json.dumps(manifest["sources"])
    base = build_mod_base_snapshot(service, snapshot, folder, read_entry=_read)
    second = service.plan(replace(spec("Visibility_B"), body_visibility=HAIR), base)
    for p in first.manifest["body_visibility"]["profiles"]:
        assert receivers(second.loose_files[SHRINK_PATH], p["tag"]) == receivers(first.loose_files[SHRINK_PATH], p["tag"])
    assert second.loose_files[POSTFIX_PATH].startswith(first.loose_files[POSTFIX_PATH])
    assert second.manifest["previous_items"][0]["body_visibility"] == first.manifest["body_visibility"]


@pytest.mark.parametrize("choice", [None, BodyVisibilityChoice(keep_skin="yes")])
def test_invalid_choices_are_validation_errors(choice):
    assert any(i.code == "body_visibility.invalid" for i in validate_spec(replace(spec(), body_visibility=choice)))


def test_invalid_variant_choice_and_workflow_error_location():
    from cdmw.domain.new_item.authoring import VariantAppearance
    from cdmw.ui.new_item.tab import _workflow_step_for_issue
    variant = VariantAppearance("test.prefab", "test.pac", body_visibility=BodyVisibilityChoice(keep_hair=1))
    issue = next(i for i in validate_spec(replace(spec(), variants=(variant,))) if i.code == "body_visibility.invalid")
    assert issue.field == "variants[0].body_visibility"
    assert _workflow_step_for_issue(issue) == 2


def test_fixture_overlay_contains_rules_and_restore_preserves_shipped_archives(tmp_path):
    from cdmw.services.archive_mutation_service import ArchiveMutationService
    service, snapshot, _ = game(tmp_path)
    root = tmp_path / "fixture"
    original = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    plan = service.plan(replace(spec(), body_visibility=BOTH), snapshot)
    mutations = ArchiveMutationService()
    result = service.install_overlay(plan, mutation_service=mutations, confirmed=True, game_running=lambda: False)
    entries = {entry.path: entry for entry in parse_archive_pamt(result.directory / "0.pamt")}
    for path in (SHRINK_PATH, POSTFIX_PATH):
        assert _read(entries[path]) == plan.loose_files[path]
    for path, payload in original.items():
        if path.suffix in {".pamt", ".paz"}:
            assert path.read_bytes() == payload
    assert result.backup_dir is not None
    mutations.restore_backup(result.backup_dir, confirmed=True)
    for path, payload in original.items():
        assert path.read_bytes() == payload


def test_panel_controls_invalidate_plan_and_survive_variant_switch_and_reset(tmp_path):
    from cdmw.ui.new_item.controller import NewItemStudioController
    from cdmw.ui.new_item.panels_model import ModelPanel
    app = QApplication.instance() or QApplication([])
    service, snapshot, _ = game(tmp_path)
    controller = NewItemStudioController(synchronous=True)
    controller.snapshot = snapshot
    controller.set_template(TEMPLATE)
    panel = ModelPanel(controller)
    try:
        editor = panel.body_visibility_editor
        assert editor.isEnabled() and not editor.keep_skin.isChecked() and not editor.keep_hair.isChecked()
        first, second = [v.identity for v in selections(snapshot)[:2]]
        revision = controller._draft_revision
        editor.keep_skin.click()
        assert controller._draft_revision > revision
        assert controller.current_spec().variants[0].body_visibility == SKIN
        assert controller.draft.body_visibility == SKIN
        controller.select_variant(second)
        assert not editor.keep_skin.isChecked()
        editor.keep_hair.click()
        assert controller.draft.body_visibility == HAIR
        controller.select_variant(first)
        assert editor.keep_skin.isChecked() and not editor.keep_hair.isChecked()
        controller.draft.reset_for_template(TEMPLATE)
        assert controller.draft.body_visibility == BodyVisibilityChoice()
    finally:
        panel.close()
        controller.shutdown()
