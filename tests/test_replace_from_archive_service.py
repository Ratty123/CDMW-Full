from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cdmw.domain.archives.replace_from_archive import (
    ReplaceFromArchiveActionKind,
    ReplaceFromArchiveCharacterMode,
    ReplaceFromArchiveFileAction,
    ReplaceFromArchivePlan,
    ReplaceFromArchiveRequest,
)
from cdmw.domain.packages.export_policy import ModPackageExportOptions
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.models import ArchiveEntry, ModPackageInfo
from cdmw.services.replace_from_archive_service import (
    build_replace_from_archive_plan,
    export_replace_from_archive_plan,
)


def _entry(path: str, offset: int) -> ArchiveEntry:
    return ArchiveEntry(
        path=path,
        pamt_path=Path("0.pamt"),
        paz_file=Path("0.paz"),
        offset=offset,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )


def _parsed() -> ParsedMesh:
    return ParsedMesh(
        path="source.pac",
        format="pac",
        submeshes=[SubMesh(name="mesh", vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)])],
        total_vertices=1,
        total_faces=1,
    )


def test_plan_maps_visual_family_and_reuses_source_dds() -> None:
    target = _entry("character/model/weapon/target.pac", 1)
    source = _entry("character/model/weapon/source.pac", 2)
    target_sidecar = _entry("character/modelproperty/weapon/target.pac_xml", 3)
    source_sidecar = _entry("character/modelproperty/weapon/source.pac_xml", 4)
    target_hkx = _entry("character/bin__/meshphysics/weapon/target.hkx", 5)
    source_hkx = _entry("character/bin__/meshphysics/weapon/source.hkx", 6)
    source_dds = _entry("character/texture/source_base.dds", 7)

    related = {
        source.identity: (source_sidecar, source_hkx, source_dds),
        target.identity: (target_sidecar, target_hkx),
    }
    sidecars = {
        source.identity: (source_sidecar,),
        target.identity: (target_sidecar,),
    }
    with (
        patch(
            "cdmw.services.replace_from_archive_service._read", return_value=b"payload"
        ),
        patch(
            "cdmw.services.replace_from_archive_service.parse_mesh",
            return_value=_parsed(),
        ),
        patch(
            "cdmw.services.replace_from_archive_service._related",
            side_effect=lambda entry, _index: related.get(entry.identity, ()),
        ),
        patch(
            "cdmw.services.replace_from_archive_service._sidecars",
            side_effect=lambda entry, _index: sidecars.get(entry.identity, ()),
        ),
    ):
        plan = build_replace_from_archive_plan(
            ReplaceFromArchiveRequest(target, source),
            entries=(
                target,
                source,
                target_sidecar,
                source_sidecar,
                target_hkx,
                source_hkx,
                source_dds,
            ),
            entries_by_normalized_path={},
            entries_by_basename={},
        )

    assert plan.can_build
    by_role = {action.role: action for action in plan.actions}
    assert by_role["Model"].target_entry is target
    assert by_role["Model"].payload_data == b"payload"
    assert by_role["Material sidecar"].target_entry is target_sidecar
    assert by_role["Physics"].target_entry is target_hkx
    assert by_role["Texture reference"].kind is ReplaceFromArchiveActionKind.REUSE
    assert by_role["Texture reference"].target_entry is None


def test_plan_blocks_cross_container_replacement() -> None:
    target = _entry("character/model/target.pac", 1)
    source = _entry("character/model/source.pam", 2)

    plan = build_replace_from_archive_plan(
        ReplaceFromArchiveRequest(target, source),
        entries=(target, source),
        entries_by_normalized_path={},
        entries_by_basename={},
    )

    assert not plan.can_build
    assert any("containers differ" in blocker for blocker in plan.blockers)


def test_plan_blocks_invalid_target_output_path() -> None:
    target = _entry("../escape/target.pac", 1)
    source = _entry("character/model/source.pac", 2)
    with (
        patch(
            "cdmw.services.replace_from_archive_service._read", return_value=b"payload"
        ),
        patch(
            "cdmw.services.replace_from_archive_service.parse_mesh",
            return_value=_parsed(),
        ),
        patch("cdmw.services.replace_from_archive_service._related", return_value=()),
        patch("cdmw.services.replace_from_archive_service._sidecars", return_value=()),
    ):
        plan = build_replace_from_archive_plan(
            ReplaceFromArchiveRequest(target, source),
            entries=(target, source),
            entries_by_normalized_path={},
            entries_by_basename={},
        )

    assert not plan.can_build
    assert any("invalid target path" in blocker.casefold() for blocker in plan.blockers)


def test_character_identity_is_explicit() -> None:
    target = _entry("character/model/1_pc/1_phm/body/target.pac", 1)
    source = _entry("character/model/1_pc/2_phw/body/source.pac", 2)
    target_app = _entry("character/appearance/1_pc/1_phm/target.app_xml", 3)
    source_app = _entry("character/appearance/1_pc/2_phw/source.app_xml", 4)

    with (
        patch(
            "cdmw.services.replace_from_archive_service._read", return_value=b"payload"
        ),
        patch(
            "cdmw.services.replace_from_archive_service.parse_mesh",
            return_value=_parsed(),
        ),
        patch("cdmw.services.replace_from_archive_service._related", return_value=()),
        patch("cdmw.services.replace_from_archive_service._sidecars", return_value=()),
        patch(
            "cdmw.services.replace_from_archive_service._best_appearance",
            side_effect=(source_app, target_app),
        ),
    ):
        plan = build_replace_from_archive_plan(
            ReplaceFromArchiveRequest(
                target,
                source,
                ReplaceFromArchiveCharacterMode.FULL_SOURCE_IDENTITY,
            ),
            entries=(target, source, target_app, source_app),
            entries_by_normalized_path={},
            entries_by_basename={},
        )

    identity = next(
        action for action in plan.actions if action.role == "Full character identity"
    )
    assert identity.source_entry is source_app
    assert identity.target_entry is target_app


def test_character_preserve_target_does_not_include_app_xml() -> None:
    target = _entry("character/model/1_pc/1_phm/body/target.pac", 1)
    source = _entry("character/model/1_pc/2_phw/body/source.pac", 2)
    target_app = _entry("character/appearance/1_pc/1_phm/target.app_xml", 3)
    source_app = _entry("character/appearance/1_pc/2_phw/source.app_xml", 4)
    with (
        patch(
            "cdmw.services.replace_from_archive_service._read", return_value=b"payload"
        ),
        patch(
            "cdmw.services.replace_from_archive_service.parse_mesh",
            return_value=_parsed(),
        ),
        patch("cdmw.services.replace_from_archive_service._related", return_value=()),
        patch("cdmw.services.replace_from_archive_service._sidecars", return_value=()),
    ):
        plan = build_replace_from_archive_plan(
            ReplaceFromArchiveRequest(
                target,
                source,
                ReplaceFromArchiveCharacterMode.PRESERVE_TARGET,
            ),
            entries=(target, source, target_app, source_app),
            entries_by_normalized_path={},
            entries_by_basename={},
        )

    assert plan.can_build
    assert not any(action.target_path.endswith(".app_xml") for action in plan.actions)


def test_character_body_head_mode_uses_surgical_target_app_patch() -> None:
    target = _entry("character/model/1_pc/1_phm/body/target.pac", 1)
    source = _entry("character/model/1_pc/2_phw/body/source.pac", 2)
    target_app = _entry("character/appearance/1_pc/1_phm/target.app_xml", 3)
    with (
        patch(
            "cdmw.services.replace_from_archive_service._read", return_value=b"payload"
        ),
        patch(
            "cdmw.services.replace_from_archive_service.parse_mesh",
            return_value=_parsed(),
        ),
        patch("cdmw.services.replace_from_archive_service._related", return_value=()),
        patch("cdmw.services.replace_from_archive_service._sidecars", return_value=()),
        patch(
            "cdmw.services.replace_from_archive_service.build_character_swap_plan",
            return_value=SimpleNamespace(
                patched_target_app_xml=b"<Appearance surgical='true' />",
                patched_target_app_path=target_app.path,
            ),
        ),
    ):
        plan = build_replace_from_archive_plan(
            ReplaceFromArchiveRequest(
                target,
                source,
                ReplaceFromArchiveCharacterMode.BODY_HEAD_PATCH,
            ),
            entries=(target, source, target_app),
            entries_by_normalized_path={},
            entries_by_basename={},
        )

    patch_action = next(
        action
        for action in plan.actions
        if action.role == "Character body/head identity"
    )
    assert patch_action.target_entry is target_app
    assert patch_action.payload_data == b"<Appearance surgical='true' />"


def test_weapon_placement_failure_is_warning_not_blocker() -> None:
    target = _entry("character/model/weapon/1_onehandweapon/target.pac", 1)
    source = _entry("character/model/weapon/2_twohandweapon/source.pac", 2)
    with (
        patch(
            "cdmw.services.replace_from_archive_service._read", return_value=b"payload"
        ),
        patch(
            "cdmw.services.replace_from_archive_service.parse_mesh",
            return_value=_parsed(),
        ),
        patch("cdmw.services.replace_from_archive_service._related", return_value=()),
        patch("cdmw.services.replace_from_archive_service._sidecars", return_value=()),
    ):
        plan = build_replace_from_archive_plan(
            ReplaceFromArchiveRequest(target, source),
            entries=(target, source),
            entries_by_normalized_path={},
            entries_by_basename={},
        )

    assert plan.can_build
    assert any("placement" in warning.casefold() for warning in plan.warnings)


def test_weapon_plan_uses_target_owned_prefab_iteminfo_and_held_stowed_patchers() -> (
    None
):
    target = _entry("character/model/weapon/1_onehandweapon/target.pac", 1)
    source = _entry("character/model/weapon/2_twohandweapon/source.pac", 2)
    target_prefab = _entry("character/prefab/target.prefab", 3)
    source_prefab = _entry("character/prefab/source.prefab", 4)
    iteminfo = _entry("gamecommondata/iteminfo.pabgb", 5)
    iteminfo_header = _entry("gamecommondata/iteminfo.pabgh", 6)
    equip = _entry("gamecommondata/equiptypeinfo.pabgb", 7)
    equip_header = _entry("gamecommondata/equiptypeinfo.pabgh", 8)
    part_in_out = _entry("character/partinoutsocketinfo.xml", 9)
    entries = (
        target,
        source,
        target_prefab,
        source_prefab,
        iteminfo,
        iteminfo_header,
        equip,
        equip_header,
        part_in_out,
    )
    related = {
        target.identity: (target_prefab,),
        source.identity: (source_prefab,),
    }
    source_fields = (
        SimpleNamespace(field_name="_attachedSocketName", value="RHand_Socket"),
        SimpleNamespace(field_name="_pivotSocketName", value="Basic_Pivot"),
        SimpleNamespace(field_name="_partName", value="CD_TwoHandWeapon_Sword"),
        SimpleNamespace(
            field_name="_socketFileName", value="character/source.sockets.xml"
        ),
    )

    def _payload(entry: ArchiveEntry, _stop_event) -> bytes:
        if entry is part_in_out:
            return b"<PartInOutSocket PartName='Target' />"
        return b"payload"

    with (
        patch("cdmw.services.replace_from_archive_service._read", side_effect=_payload),
        patch(
            "cdmw.services.replace_from_archive_service.parse_mesh",
            return_value=_parsed(),
        ),
        patch(
            "cdmw.services.replace_from_archive_service._related",
            side_effect=lambda entry, _index: related.get(entry.identity, ()),
        ),
        patch("cdmw.services.replace_from_archive_service._sidecars", return_value=()),
        patch(
            "cdmw.services.replace_from_archive_service.inspect_prefab_attachment_profile_fields",
            return_value=source_fields,
        ),
        patch(
            "cdmw.services.replace_from_archive_service.build_prefab_attachment_profile_patch",
            return_value=SimpleNamespace(data=b"prefab-patched"),
        ),
        patch(
            "cdmw.services.replace_from_archive_service.build_iteminfo_behavior_equip_type_patch",
            return_value=SimpleNamespace(
                blocking_reason="",
                changed=True,
                data=b"iteminfo-patched",
                new_equip_type_name="TwoHandSword",
            ),
        ),
        patch(
            "cdmw.services.replace_from_archive_service.infer_part_in_out_weapon_class",
            side_effect=lambda path: (
                "TargetClass" if "target" in path else "SourceClass"
            ),
        ),
        patch(
            "cdmw.services.replace_from_archive_service.build_part_in_out_socket_class_copy_patch",
            side_effect=(
                SimpleNamespace(
                    text="<PartInOutSocket stowed='source' />", diffs=(object(),)
                ),
                SimpleNamespace(
                    text="<PartInOutSocket held='source' />", diffs=(object(),)
                ),
            ),
        ),
    ):
        plan = build_replace_from_archive_plan(
            ReplaceFromArchiveRequest(target, source),
            entries=entries,
            entries_by_normalized_path={},
            entries_by_basename={},
        )

    roles = {action.role: action for action in plan.actions}
    assert roles["Weapon placement"].target_entry is target_prefab
    assert roles["Weapon equip behavior"].target_entry is iteminfo
    assert roles["Weapon held/stowed sockets"].target_entry is part_in_out
    assert plan.can_build


def test_paired_lod_and_motion_mapping_require_proven_target_roles() -> None:
    target = _entry("character/model/target.pam", 1)
    source = _entry("character/model/source.pam", 2)
    target_lod = _entry("character/model/target.pamlod", 3)
    source_lod = _entry("character/model/source.pamlod", 4)
    target_motion = _entry("character/motion/target.paa", 5)
    source_motion = _entry("character/motion/source.paa", 6)
    unmatched_motion = _entry("character/motion/other.paa_metabin", 7)
    related = {
        source.identity: (source_lod, source_motion, unmatched_motion),
        target.identity: (target_lod, target_motion),
    }
    with (
        patch(
            "cdmw.services.replace_from_archive_service._read", return_value=b"payload"
        ),
        patch(
            "cdmw.services.replace_from_archive_service.parse_mesh",
            return_value=_parsed(),
        ),
        patch(
            "cdmw.services.replace_from_archive_service._related",
            side_effect=lambda entry, _index: related.get(entry.identity, ()),
        ),
        patch("cdmw.services.replace_from_archive_service._sidecars", return_value=()),
    ):
        plan = build_replace_from_archive_plan(
            ReplaceFromArchiveRequest(target, source),
            entries=(
                target,
                source,
                target_lod,
                source_lod,
                target_motion,
                source_motion,
                unmatched_motion,
            ),
            entries_by_normalized_path={},
            entries_by_basename={},
        )

    assert any(
        action.role == "Paired LOD" and action.target_entry is target_lod
        for action in plan.actions
    )
    assert any(
        action.role == "Motion" and action.target_entry is target_motion
        for action in plan.actions
    )
    assert not any(
        action.source_entry is unmatched_motion for action in plan.copied_actions
    )
    assert any("other.paa_metabin" in warning for warning in plan.warnings)


def test_duplicate_target_mapping_is_a_fatal_blocker() -> None:
    target = _entry("character/model/target.pac", 1)
    source = _entry("character/model/source.pac", 2)
    target_hkx = _entry("character/physics/target.hkx", 3)
    source_hkx_a = _entry("character/physics/source.hkx", 4)
    source_hkx_b = _entry("character/alternate/source.hkx", 5)
    related = {
        source.identity: (source_hkx_a, source_hkx_b),
        target.identity: (target_hkx,),
    }
    with (
        patch(
            "cdmw.services.replace_from_archive_service._read", return_value=b"payload"
        ),
        patch(
            "cdmw.services.replace_from_archive_service.parse_mesh",
            return_value=_parsed(),
        ),
        patch(
            "cdmw.services.replace_from_archive_service._related",
            side_effect=lambda entry, _index: related.get(entry.identity, ()),
        ),
        patch("cdmw.services.replace_from_archive_service._sidecars", return_value=()),
    ):
        plan = build_replace_from_archive_plan(
            ReplaceFromArchiveRequest(target, source),
            entries=(target, source, target_hkx, source_hkx_a, source_hkx_b),
            entries_by_normalized_path={},
            entries_by_basename={},
        )

    assert not plan.can_build
    assert any(
        "more than one replacement action" in blocker.casefold()
        for blocker in plan.blockers
    )


def test_world_and_unknown_families_warn_without_copying_unmatched_companions() -> None:
    target = _entry("object/world/target.pac", 1)
    source = _entry("mystery/source.pac", 2)
    source_hkx = _entry("mystery/unmatched.hkx", 3)
    with (
        patch(
            "cdmw.services.replace_from_archive_service._read", return_value=b"payload"
        ),
        patch(
            "cdmw.services.replace_from_archive_service.parse_mesh",
            return_value=_parsed(),
        ),
        patch(
            "cdmw.services.replace_from_archive_service._related",
            side_effect=lambda entry, _index: (source_hkx,) if entry is source else (),
        ),
        patch("cdmw.services.replace_from_archive_service._sidecars", return_value=()),
    ):
        plan = build_replace_from_archive_plan(
            ReplaceFromArchiveRequest(target, source),
            entries=(target, source, source_hkx),
            entries_by_normalized_path={},
            entries_by_basename={},
        )

    assert plan.can_build
    assert not any(action.source_entry is source_hkx for action in plan.copied_actions)
    assert any("cross-family" in warning.casefold() for warning in plan.warnings)


def test_export_is_cancellable_atomic_and_does_not_mutate_source_or_archives(
    tmp_path: Path,
) -> None:
    source_payload = b"exact-source-model"
    source_file = tmp_path / "prepared-source.pac"
    source_file.write_bytes(source_payload)
    source = _entry("character/model/source.pac", 2)
    source.prepared_path = source_file
    source.comp_size = len(source_payload)
    source.orig_size = len(source_payload)
    target_archive = tmp_path / "game" / "0.pamt"
    target = ArchiveEntry(
        path="character/model/target.pac",
        pamt_path=target_archive,
        paz_file=tmp_path / "game" / "0.paz",
        offset=1,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )
    action = ReplaceFromArchiveFileAction(
        role="Model",
        kind=ReplaceFromArchiveActionKind.COPY,
        source_entry=source,
        target_entry=target,
    )
    plan = ReplaceFromArchivePlan(
        ReplaceFromArchiveRequest(target, source),
        actions=(action,),
        warnings=("Missing optional physics.",),
    )
    before_hash = hashlib.sha256(source_file.read_bytes()).hexdigest()
    output_root = tmp_path / "mods"
    result = export_replace_from_archive_plan(
        plan,
        parent_root=output_root,
        package_info=ModPackageInfo(
            title="Replacement Test", description="User description"
        ),
        export_options=ModPackageExportOptions(
            manager_targets=(), create_no_encrypt_file=False
        ),
        create_no_encrypt_file=False,
    )

    payload = result.package_root / "character" / "model" / "target.pac"
    assert payload.read_bytes() == source_payload
    assert hashlib.sha256(source_file.read_bytes()).hexdigest() == before_hash
    assert not target_archive.exists()
    manifest = json.loads(
        (result.package_root / "manifest.json").read_text(encoding="utf-8")
    )
    assert "Replace from Archive" in manifest["description"]
    assert "Missing optional physics" in manifest["description"]
    assert not any(
        path.name.startswith(".cdmw-replace-from-archive-")
        for path in output_root.iterdir()
    )

    sentinel = result.package_root / "obsolete.txt"
    sentinel.write_text("old", encoding="utf-8")
    export_replace_from_archive_plan(
        plan,
        parent_root=output_root,
        package_info=ModPackageInfo(title="Replacement Test"),
        export_options=ModPackageExportOptions(
            manager_targets=(), create_no_encrypt_file=False
        ),
        create_no_encrypt_file=False,
    )
    assert not sentinel.exists()

    multi = export_replace_from_archive_plan(
        plan,
        parent_root=output_root,
        package_info=ModPackageInfo(title="Multi Replacement"),
        export_options=ModPackageExportOptions(
            export_profiles=("jmm", "cdumm"),
            create_zip=True,
        ),
        create_no_encrypt_file=False,
    )
    assert len(multi.package_roots) == 2
    assert (multi.package_roots[0] / "mod.json").is_file()
    assert (multi.package_roots[0] / "character" / "model" / "target.pac").is_file()
    assert (multi.package_roots[1] / "manifest.json").is_file()
    assert (
        multi.package_roots[1] / "files" / "character" / "model" / "target.pac"
    ).is_file()
    assert not (multi.package_roots[0].with_suffix(".zip")).exists()
    assert not (multi.package_roots[1].with_suffix(".zip")).exists()

    mid_export_cancel = threading.Event()

    def _cancel_on_first_write(message: str) -> None:
        if "Writing loose mod payload" in message:
            mid_export_cancel.set()

    with pytest.raises(Exception, match="cancel"):
        export_replace_from_archive_plan(
            plan,
            parent_root=output_root,
            package_info=ModPackageInfo(title="Mid Export Cancel"),
            export_options=ModPackageExportOptions(manager_targets=()),
            create_no_encrypt_file=False,
            on_log=_cancel_on_first_write,
            stop_event=mid_export_cancel,
        )
    assert not (output_root / "Mid Export Cancel").exists()

    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(Exception, match="cancel"):
        export_replace_from_archive_plan(
            plan,
            parent_root=output_root,
            package_info=ModPackageInfo(title="Cancelled Replacement"),
            export_options=ModPackageExportOptions(manager_targets=()),
            create_no_encrypt_file=False,
            stop_event=cancelled,
        )
