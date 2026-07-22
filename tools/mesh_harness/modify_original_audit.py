from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.rendering.model_preview_prepare import prepare_model_preview
from cdmw.services.atomic_file_service import atomic_write_text
from cdmw.services.mesh_dotnet_experiment import build_mesh_dotnet_experiment_package
from cdmw.services.mesh_dotnet_material_compiler import (
    MeshDotNetMaterialCompileRequest,
    compile_mesh_dotnet_material_update,
    snapshot_mesh_dotnet_material_inputs,
)
from cdmw.services.mesh_dotnet_material_state import (
    copy_dotnet_preview_material_bindings,
    mesh_dotnet_material_state_payload,
)
from cdmw.services.modify_original_workspace_service import (
    ModifyOriginalWorkspacePreparationRequest,
    prepare_modify_original_workspace,
)
from cdmw.services.preview_workflow_service import parsed_mesh_to_preview_model
from cdmw.ui.archive_browser.static_replacement_preview_materials import (
    apply_resolved_original_materials_to_resident_editor,
)
from cdmw.ui.archive_browser.static_replacement_prompt_preflight import (
    StaticReplacementPromptPreflightRequest,
    prepare_static_replacement_prompt_preflight,
)
from tools.mesh_harness.archive_provenance import (
    _archive_content_fingerprints,
    _archive_entry_provenance,
)
from tools.mesh_harness.real_common import _archive_entry_indexes, _archive_key
from tools.mesh_harness.visual_audit_capture import run_dotnet_capture_batch
from tools.mesh_harness.visual_audit_corpus import (
    VISUAL_AUDIT_VIEWS,
    VisualAuditAssetSpec,
    _initial_resident_material_equivalence,
    _load_visual_audit_asset,
    _visual_audit_material_regions,
)
from tools.mesh_harness.visual_audit_manifest_v2 import (
    PRIOR_CONCERN_SWORD_PATH,
    REQUIRED_SWORD_PATH,
)
from tools.mesh_harness.visual_audit_source_boards import build_source_material_boards


MODIFY_ORIGINAL_SUBSET_SCHEMA = "cdmw_mesh_modify_original_material_subset_v1"
MODIFY_ORIGINAL_SUBSET_ROLES = (
    "reported_sword",
    "representative_guard",
    "mixed_armor",
    "true_metal_helmet",
    "soft_helmet",
    "boots",
    "shield",
    "belt_or_glove",
    "cloak_or_vest",
    "other_weapon",
    "hair_control",
    "glass_control",
)


@dataclass(frozen=True, slots=True)
class ModifyOriginalSubsetAsset:
    role: str
    spec: VisualAuditAssetSpec


def select_modify_original_subset(
    specs: Sequence[VisualAuditAssetSpec],
) -> tuple[ModifyOriginalSubsetAsset, ...]:
    """Select twelve unique deterministic roles from the canonical 120 corpus."""

    ordered = tuple(specs)
    used: set[str] = set()
    selected: list[ModifyOriginalSubsetAsset] = []

    def choose(
        role: str,
        predicate: Callable[[VisualAuditAssetSpec], bool],
        *,
        preferred_path: str = "",
    ) -> None:
        preferred = _archive_key(preferred_path) if preferred_path else ""
        candidates = [
            spec
            for spec in ordered
            if _archive_key(spec.virtual_path) not in used and predicate(spec)
        ]
        match = next(
            (spec for spec in candidates if preferred and _archive_key(spec.virtual_path) == preferred),
            candidates[0] if candidates else None,
        )
        if match is None:
            raise ValueError(f"Modify Original subset cannot satisfy role {role}.")
        used.add(_archive_key(match.virtual_path))
        selected.append(ModifyOriginalSubsetAsset(role, match))

    choose(
        "reported_sword",
        lambda spec: spec.model_category == "weapon_sword",
        preferred_path=REQUIRED_SWORD_PATH,
    )
    choose(
        "representative_guard",
        lambda spec: spec.model_category == "weapon_sword",
        preferred_path=PRIOR_CONCERN_SWORD_PATH,
    )
    choose(
        "mixed_armor",
        lambda spec: spec.model_category == "armor_body"
        and "mixed_hard_soft_candidate" in spec.graph_tags,
    )
    choose(
        "true_metal_helmet",
        lambda spec: spec.model_category == "helmet_mask"
        and "true_metal_control_candidate" in spec.graph_tags
        and "soft_control_candidate" not in spec.graph_tags,
    )
    choose(
        "soft_helmet",
        lambda spec: spec.model_category == "helmet_mask"
        and "soft_control_candidate" in spec.graph_tags,
    )
    choose(
        "boots",
        lambda spec: spec.model_category == "equipment_small"
        and any(token in _archive_key(spec.virtual_path) for token in ("foot", "boot")),
    )
    choose(
        "shield",
        lambda spec: spec.model_category == "weapon_shield",
    )
    choose(
        "belt_or_glove",
        lambda spec: spec.model_category == "equipment_small"
        and any(
            token in _archive_key(spec.virtual_path)
            for token in ("belt", "glove", "gauntlet", "/11_hand/")
        ),
    )
    choose(
        "cloak_or_vest",
        lambda spec: spec.model_category == "equipment_soft"
        and any(token in _archive_key(spec.virtual_path) for token in ("cloak", "cape", "vest")),
    )
    choose("other_weapon", lambda spec: spec.model_category == "weapon_other")
    choose(
        "hair_control",
        lambda spec: spec.model_category == "regression_control"
        and "hair" in _archive_key(spec.virtual_path),
    )
    choose(
        "glass_control",
        lambda spec: spec.model_category == "regression_control"
        and "glass" in _archive_key(spec.virtual_path),
    )
    if tuple(row.role for row in selected) != MODIFY_ORIGINAL_SUBSET_ROLES:
        raise AssertionError("Modify Original subset role order drifted.")
    if len(used) != len(MODIFY_ORIGINAL_SUBSET_ROLES):
        raise AssertionError("Modify Original subset assets must be unique.")
    return tuple(selected)


def run_modify_original_material_subset(
    *,
    game_root: Path,
    output_root: Path,
    temporary_root: Path,
    specs: Sequence[VisualAuditAssetSpec],
    assembly_path: Path,
    run_id: str,
    timeout_seconds: float = 900.0,
    progress: Callable[[int, int, str, str], None] | None = None,
) -> dict[str, object]:
    """Run production clone/preflight/late-material orchestration and hidden capture."""

    game_root = Path(game_root).resolve()
    output_root = Path(output_root).resolve()
    temporary_root = Path(temporary_root).resolve()
    if output_root.is_relative_to(game_root) or temporary_root.is_relative_to(game_root):
        raise ValueError("Modify Original audit output must remain outside the game root.")
    output_root.mkdir(parents=True, exist_ok=True)
    temporary_root.mkdir(parents=True, exist_ok=True)
    runtime_root = output_root / "runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    subset = select_modify_original_subset(specs)
    entries = parse_archive_pamt(game_root / "0009" / "0.pamt")
    entries_by_path, entries_by_basename = _archive_entry_indexes(entries)
    entries_by_extension: dict[str, list[object]] = {}
    for entry in entries:
        entries_by_extension.setdefault(str(entry.extension or "").casefold(), []).append(entry)

    fingerprint_paths: set[Path] = {game_root / "0009" / "0.pamt"}
    rows: list[dict[str, object]] = []
    runtime_assets: list[dict[str, object]] = []
    package_root = temporary_root / "packages"
    for index, subset_asset in enumerate(subset, 1):
        role = subset_asset.role
        spec = subset_asset.spec
        if progress is not None:
            progress(index, len(subset), role, spec.virtual_path)
        (
            entry,
            payload,
            original_mesh,
            preview_result,
            resolved_textures,
            material_diagnostics,
            _started,
            _archive_started,
        ) = _load_visual_audit_asset(
            spec,
            entries_by_path=entries_by_path,
            entries_by_basename=entries_by_basename,
        )
        prepared_model, _prepared_preview = prepare_model_preview(
            preview_result.preview_model,
            enable_material_combiner=False,
        )
        copy_dotnet_preview_material_bindings(original_mesh, prepared_model)
        resolved_original_preview = parsed_mesh_to_preview_model(original_mesh)

        workspace = temporary_root / "modify-original-sessions" / f"{index:02d}-{role}"
        prepared_workspace = prepare_modify_original_workspace(
            ModifyOriginalWorkspacePreparationRequest(
                entry=entry,
                workspace_dir=workspace,
                create_workspace=False,
                include_family_files=False,
                open_workspace_after_create=False,
                cleanup_stale_sessions=False,
                archive_entries_by_normalized_path=entries_by_path,
                archive_entries_by_basename=entries_by_basename,
                model_texture_references=tuple(
                    getattr(preview_result, "model_texture_references", ()) or ()
                ),
                asset_family_graph=getattr(preview_result, "asset_family_graph", None),
            ),
            stop_event=threading.Event(),
        )
        preflight = prepare_static_replacement_prompt_preflight(
            StaticReplacementPromptPreflightRequest(
                request_id=index,
                entry=entry,
                obj_path=Path(prepared_workspace["obj_path"]),
                supplemental_files=tuple(prepared_workspace.get("supplemental_files", ()) or ()),
                scene_import_result=prepared_workspace.get("scene_import_result"),
                original_mesh=prepared_workspace.get("original_mesh"),
                archive_entries_by_normalized_path=entries_by_path,
                archive_entries_by_basename=entries_by_basename,
                archive_entries_by_extension=entries_by_extension,
            ),
            stop_event=threading.Event(),
        )
        if preflight.modify_original_clone_mode is not True:
            raise RuntimeError(f"Production preflight did not recognize Modify Original clone: {entry.path}")
        resident_callbacks: list[str] = []
        dialog = SimpleNamespace(
            _mesh_editor_embedded_apply_clone_material_resources=(
                lambda _model: resident_callbacks.append("clone")
            ),
            _mesh_editor_embedded_apply_reference_material_resources=(
                lambda _model: resident_callbacks.append("reference")
            ),
        )
        apply_resolved_original_materials_to_resident_editor(
            dialog=dialog,
            replacement_mesh_base=preflight.replacement_mesh_base,
            replacement_mesh=preflight.replacement_mesh,
            preview_model=resolved_original_preview,
            modify_original_clone_mode=True,
            publish_resident_updates=True,
        )
        if resident_callbacks != ["clone", "reference"]:
            raise RuntimeError(f"Late Modify Original material delivery was incomplete: {resident_callbacks}")

        asset_id = f"{index:02d}-{role}-{Path(spec.virtual_path).stem.lower().replace('_', '-')}"
        material_state = mesh_dotnet_material_state_payload(
            preflight.replacement_mesh,
            session_id=asset_id,
            edit_revision=0,
            generation=1,
        )
        source_boards = build_source_material_boards(
            asset_id,
            resolved_textures,
            material_state,
            output_root / "source-boards",
        )
        package = build_mesh_dotnet_experiment_package(
            preflight.replacement_mesh,
            output_root=package_root / "mesh-editor",
            comparison_mode="replacement_only",
            interaction_mode="placement",
            scene_session_id=asset_id,
        )
        archive_package_stability = {
            "schema": "cdmw_visual_audit_shared_dotnet_package_v1",
            "renderer_id": "d3d11_vortice_shader",
            "same_package_for_archive_and_mesh_editor": True,
            "package_dir": str(package.package_dir),
        }
        resident_payload = compile_mesh_dotnet_material_update(
            MeshDotNetMaterialCompileRequest(
                session_id=asset_id,
                edit_revision=0,
                generation=1,
                role="replacement",
                mesh_snapshot=snapshot_mesh_dotnet_material_inputs(
                    preflight.replacement_mesh,
                    scene_material_slot_indices=package.scene_material_slot_indices,
                ),
                output_root=temporary_root / "resident-material-cache",
                reason="modify_original_late_material_delivery",
            )
        )
        resident_path = package.package_dir / "resident_material_state_v3.json"
        atomic_write_text(resident_path, json.dumps(resident_payload, indent=2, sort_keys=True))
        equivalence = _initial_resident_material_equivalence(
            package.package_dir / "net_materials.json",
            resident_payload,
        )
        if equivalence.get("equivalent") is not True:
            raise RuntimeError(f"Modify Original initial/resident mismatch for {entry.path}: {equivalence}")
        conservation_rows = [
            dict(row.get("binding_conservation", {}) or {})
            for row in tuple(material_state.get("submeshes", ()) or ())
            if isinstance(row, Mapping)
        ]
        conservation_ok = bool(conservation_rows) and all(
            row.get("conserved") is True
            and not tuple(row.get("dropped_parameters", ()) or ())
            and not tuple(row.get("cross_owner_bindings", ()) or ())
            and not tuple(row.get("layer_as_base_bindings", ()) or ())
            for row in conservation_rows
        )
        if not conservation_ok:
            raise RuntimeError(f"Modify Original binding conservation failed for {entry.path}")

        fingerprint_paths.update((Path(entry.pamt_path), Path(entry.paz_file)))
        for texture in resolved_textures:
            provenance = texture.get("archive_provenance")
            if not isinstance(provenance, Mapping):
                continue
            for key in ("pamt_path", "paz_path"):
                if str(provenance.get(key, "") or "").strip():
                    fingerprint_paths.add(Path(str(provenance[key])))
        rows.append(
            {
                "index": index,
                "id": asset_id,
                "role": role,
                "virtual_path": spec.virtual_path,
                "model_category": spec.model_category,
                "selection": asdict(spec),
                "archive_provenance": _archive_entry_provenance(entry),
                "payload_sha256": hashlib.sha256(payload).hexdigest(),
                "workspace_manifest": str(prepared_workspace["manifest_path"]),
                "workspace_manifest_sha256": _sha256_file(Path(prepared_workspace["manifest_path"])),
                "modify_original_clone_mode": preflight.modify_original_clone_mode,
                "suggested_mapping_count": len(preflight.suggested_mappings),
                "late_material_callbacks": resident_callbacks,
                "submesh_count": len(preflight.replacement_mesh.submeshes),
                "material_state_schema": str(material_state.get("schema", "")),
                "binding_conservation": conservation_rows,
                "binding_conservation_ok": conservation_ok,
                "initial_resident_material_equivalence": equivalence,
                "source_boards": source_boards,
                "material_resolution_diagnostics": list(material_diagnostics),
                "archive_package_stability": archive_package_stability,
            }
        )
        runtime_assets.append(
            {
                "id": asset_id,
                "virtual_path": spec.virtual_path,
                "dotnet_package_dir": str(package.package_dir),
                "resident_material_state_path": str(resident_path),
                "views": [dict(view) for view in VISUAL_AUDIT_VIEWS],
                "material_regions": _visual_audit_material_regions(
                    preflight.replacement_mesh,
                    material_state,
                ),
            }
        )

    before = _archive_content_fingerprints(tuple(fingerprint_paths))
    _write_json(runtime_root / "archive-fingerprints-before.json", before)
    capture = run_dotnet_capture_batch(
        runtime_assets,
        output_root / "captures",
        runtime_root,
        run_id=run_id,
        assembly_path=assembly_path,
        timeout_seconds=timeout_seconds,
    )
    after = _archive_content_fingerprints(tuple(fingerprint_paths))
    _write_json(runtime_root / "archive-fingerprints-after.json", after)
    archives_unchanged = bool(before) and before == after
    update_count = int(capture.get("resident_material_update_count", -1) or 0)
    update_failures = int(capture.get("resident_material_update_failure_count", -1) or 0)
    ok = (
        len(rows) == len(MODIFY_ORIGINAL_SUBSET_ROLES)
        and all(row["binding_conservation_ok"] is True for row in rows)
        and all(
            row["initial_resident_material_equivalence"].get("equivalent") is True
            for row in rows
        )
        and capture.get("ok") is True
        and update_count == len(rows)
        and update_failures == 0
        and archives_unchanged
    )
    report = {
        "schema": MODIFY_ORIGINAL_SUBSET_SCHEMA,
        "run_id": run_id,
        "ok": ok,
        "asset_count": len(rows),
        "roles": list(MODIFY_ORIGINAL_SUBSET_ROLES),
        "production_orchestration": [
            "prepare_modify_original_workspace",
            "prepare_static_replacement_prompt_preflight",
            "apply_resolved_original_materials_to_resident_editor",
            "canonical_mesh_dotnet_material_compiler",
            "hidden_d3d11_vortice_shader_resident_update",
        ],
        "archive_sources_unchanged": archives_unchanged,
        "temporary_root": str(temporary_root),
        "assets": rows,
        "dotnet_capture": capture,
    }
    _write_json(output_root / "modify-original-subset.json", report)
    return report


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: object) -> None:
    atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True))


__all__ = [
    "MODIFY_ORIGINAL_SUBSET_ROLES",
    "MODIFY_ORIGINAL_SUBSET_SCHEMA",
    "ModifyOriginalSubsetAsset",
    "run_modify_original_material_subset",
    "select_modify_original_subset",
]
