from __future__ import annotations

import gc
import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.archive_preview_result_builder import build_archive_preview_result
from cdmw.rendering.model_preview_prepare import prepare_model_preview
from cdmw.services.mesh_dotnet_experiment import build_mesh_dotnet_experiment_package
from cdmw.services.mesh_dotnet_material_compiler import (
    MeshDotNetMaterialCompileRequest,
    compile_mesh_dotnet_material_update,
    snapshot_mesh_dotnet_material_inputs,
)
from cdmw.services.mesh_dotnet_material_state import copy_dotnet_preview_material_bindings
from cdmw.services.mesh_dotnet_material_state import mesh_dotnet_material_state_payload
from cdmw.services.mesh_service import MeshService
from cdmw.services.atomic_file_service import atomic_write_text
from tools.mesh_harness.archive_provenance import (
    _archive_content_fingerprints,
    _archive_entry_provenance,
    _hydrate_real_archive_mesh_materials,
)
from tools.mesh_harness.material_profile_corpus import _dds_header_row
from tools.mesh_harness.real_common import (
    _archive_entry_indexes,
    _archive_key,
    _read_archive_payload,
)
from tools.mesh_harness.visual_audit_manifest_v2 import (
    VISUAL_AUDIT_V2_CATEGORY_COUNTS,
    VisualAuditV2Candidate,
    build_visual_audit_v2_candidates,
    select_visual_audit_v2_candidates,
    validate_visual_audit_v2_selection,
)
from tools.mesh_harness.visual_audit_source_boards import build_source_material_boards


@dataclass(frozen=True, slots=True)
class VisualAuditAssetSpec:
    index: int
    asset_id: str
    virtual_path: str
    model_category: str
    coverage_tags: tuple[str, ...]
    selection_reason: str
    graph_complexity: int = 0
    graph_tags: tuple[str, ...] = ()
    pac_xml_virtual_path: str = ""
    pac_xml_sha256: str = ""


VISUAL_AUDIT_VIEWS: tuple[dict[str, object], ...] = (
    {"name": "front", "yaw": 0.0, "pitch": 0.0},
    {"name": "three-quarter-front", "yaw": -35.0, "pitch": 20.0},
    {"name": "side", "yaw": 90.0, "pitch": 0.0},
    {"name": "back", "yaw": 180.0, "pitch": 0.0},
    {"name": "slightly-above", "yaw": -35.0, "pitch": -28.0},
    {"name": "slightly-below", "yaw": -35.0, "pitch": 28.0},
)

VISUAL_AUDIT_REGION_ANGLES: tuple[dict[str, object], ...] = (
    {"name": "front", "yaw": 0.0, "pitch": 0.0},
    {"name": "oblique", "yaw": -35.0, "pitch": 20.0},
)

VISUAL_AUDIT_REGION_DEBUG_MODES: tuple[str, ...] = (
    "base",
    "normal",
    "roughness",
    "metallic",
    "specular",
    "layer_mask",
)


_DEFAULT_ASSETS: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("character/model/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_sword_0001.pac", "weapon_sword", ("weapon", "sword", "metal", "painted"), "Standard-v2 sword with four material regions and packed metal/roughness channels."),
    ("character/model/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_sword_0005.pac", "weapon_sword", ("weapon", "sword", "metal", "dark_material"), "Compact dark sword with four material regions and full packed-channel inputs."),
    ("character/model/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_sword_0016.pac", "weapon_sword", ("weapon", "sword", "metal", "ornament"), "Known import-reference sword with two high-signal material regions."),
    ("character/model/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_sword_0036.pac", "weapon_sword", ("weapon", "sword", "metal", "wood"), "Legacy-standard sword selected to contrast standard and standard-v2 interpretation."),
    ("character/model/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0014.pac", "weapon_sword", ("weapon", "sword", "emissive", "multi_material"), "Six-region two-handed sword with standard-v2 and emissive-v2 material families."),
    ("character/model/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0039.pac", "weapon_sword", ("weapon", "sword", "metal", "reflective"), "Two-region reflective two-handed sword with packed PBR channels."),
    ("character/model/1_pc/1_phm/weapon/4_bow/cd_phm_04_bow_0012.pac", "weapon_bow", ("weapon", "wood", "leather", "painted"), "High-face-count bow exercising nonmetal wood/leather response and material separation."),
    ("character/model/1_pc/1_phm/weapon/3_shield/cd_phm_03_shield_0100.pac", "weapon_shield", ("weapon", "metal", "wood", "reflective"), "Shield exercising broad planar highlights and front/back material behavior."),
    ("character/model/1_pc/14_ptm/armor/9_upperbody/cd_ptm_01_ub_0001.pac", "armor_upperbody", ("armor", "cloth", "layered"), "PTM upper-body standard material with broad cloth-like surfaces."),
    ("character/model/1_pc/14_ptm/armor/9_upperbody/cd_ptm_01_ub_0048.pac", "armor_upperbody", ("armor", "cloth", "leather"), "Higher-detail PTM outfit selected for soft-surface and seam inspection."),
    ("character/model/1_pc/14_ptm/armor/9_upperbody/cd_ptm_01_ub_0083.pac", "armor_upperbody", ("armor", "cloth", "dark_material"), "Compact dark PTM outfit contrasting with the PHM cloth-v2 variant."),
    ("character/model/1_pc/1_phm/armor/9_upperbody/cd_phm_00_ub_0001.pac", "armor_upperbody", ("armor", "leather", "specular"), "Generic/specular PHM outfit selected to exercise the non-PBR compatibility profile."),
    ("character/model/1_pc/1_phm/armor/9_upperbody/cd_phm_00_ub_0054.pac", "armor_upperbody", ("armor", "metal", "layered"), "High-detail PHM upper-body model with standard hard-surface response."),
    ("character/model/1_pc/1_phm/armor/9_upperbody/cd_phm_00_ub_0083.pac", "armor_upperbody", ("armor", "cloth", "layered"), "Explicit cloth-v2 PHM material-family sample."),
    ("character/model/1_pc/14_ptm/armor/10_lowerbody/cd_ptm_01_lb_0011.pac", "armor_lowerbody", ("armor", "cloth", "emissive"), "Cloth lower-body sample whose sidecar exposes an emissive input."),
    ("character/model/1_pc/14_ptm/armor/9_upperbody/cd_ptm_00_m0001_00_ub_belt_0001.pac", "armor_accessory", ("armor", "leather", "layered"), "Layered belt/accessory selected for material-boundary and leather response."),
    ("character/model/1_pc/14_ptm/nude/cd_ptm_00_nude_00_0001.pac", "body_skin", ("body", "skin", "character_variant"), "Canonical PTM skin model with three source material regions."),
    ("character/model/1_pc/1_phm/nude/cd_phm_00_nude_00_0001.pac", "body_skin", ("body", "skin", "character_variant"), "Canonical PHM skin variant for cross-character hue and response stability."),
    ("character/model/1_pc/2_phw/nude/cd_phw_00_nude_00_0001.pac", "body_skin", ("body", "skin", "character_variant"), "PHW skin variant with a different topology and texture set."),
    ("character/model/1_pc/10_pgw/nude/cd_pgw_00_nude_00_0001.pac", "body_skin", ("body", "skin", "character_variant"), "PGW skin variant selected for consistent skin-family classification."),
    ("character/model/1_pc/7_pdm/nude/cd_pdm_00_nude_00_0001.pac", "body_skin", ("body", "skin", "character_variant"), "PDM skin variant completing broad character/body coverage."),
    ("character/model/1_pc/14_ptm/head/hair/cd_ptm_00_hair_00_0003.pac", "hair_alpha", ("hair", "alpha_cutout", "two_region"), "Two-region hair model with explicit hair-family cutout classification."),
    ("character/model/1_pc/1_phm/head/hair/cd_phm_00_hair_00_0001.pac", "hair_alpha", ("hair", "alpha_cutout", "dense_geometry"), "Dense single-region hair model for cutout, culling, and tangent detail."),
    ("character/model/2_mon/cd_m0001_00_twofeet/cd_m0001_00_beastman/cd_m0001_00_beastman_fur_0001.pac", "fur_alpha", ("hair", "fur", "alpha_cutout"), "Real fur material classified through the hair fallback family."),
    ("character/model/6_object/object/t0263_harpyfeather/cd_t0263_harpyfeather_0001.pac", "feather_alpha", ("hair", "feather", "alpha_cutout", "two_sided_probe"), "Small feather plane selected for front/back cutout and culling inspection."),
    ("character/model/1_pc/1_phm/nude/cd_phm_00_nude_00_4001_hand_hair.pac", "body_hair_alpha", ("hair", "body_hair", "alpha_cutout"), "Body-hair card model exercising fine cutout coverage at close range."),
    ("character/model/6_object/tools/cd_t0000_lantern_0001.pac", "unusual_lantern", ("unusual", "reflective", "light_fixture"), "Lantern selected to expose emissive or glass classification omissions and hard-surface reflections."),
    ("character/model/1_pc/1_phm/armor/40_glasses/cd_phm_00_glasses_00_0001.pac", "unusual_glasses", ("unusual", "glass_like", "translucency_probe"), "Glasses selected specifically to test the current opaque standard-v2 classification against appearance."),
    ("character/model/2_mon/cd_m0006_00_insect/cd_m0006_00_glassmarblespider/cd_m0006_00_glass_marblespider/cd_m0006_00_glassmarblespider_00_0001.pac", "unusual_multimaterial", ("unusual", "multi_material", "alpha_cutout", "reflective"), "Four-region spider mixing cloth-v2, standard-v2, and hair/cutout families."),
    ("character/model/6_object/object/t0150_sandglass/cd_t0150_sandglass_0001.pac", "unusual_sandglass", ("unusual", "glass_like", "translucency_probe", "wood"), "Sandglass selected to test whether an apparently glass-like region is missing from recovered material authority."),
)


def default_visual_audit_specs() -> tuple[VisualAuditAssetSpec, ...]:
    return tuple(
        VisualAuditAssetSpec(
            index=index,
            asset_id=f"{index:03d}-{category}-{Path(path).stem.lower().replace('_', '-')}",
            virtual_path=path,
            model_category=category,
            coverage_tags=tags,
            selection_reason=reason,
        )
        for index, (path, category, tags, reason) in enumerate(_DEFAULT_ASSETS, 1)
    )


def default_visual_audit_v2_specs(game_root: Path) -> tuple[VisualAuditAssetSpec, ...]:
    selected = select_visual_audit_v2_candidates(
        build_visual_audit_v2_candidates(game_root)
    )
    validate_visual_audit_v2_selection(selected)
    return tuple(
        VisualAuditAssetSpec(
            index=index,
            asset_id=(
                f"{index:03d}-{candidate.category}-"
                f"{Path(candidate.virtual_path).stem.lower().replace('_', '-')}"
            ),
            virtual_path=candidate.virtual_path,
            model_category=candidate.category,
            coverage_tags=tuple(sorted({candidate.category, *candidate.graph_tags})),
            selection_reason=(
                "PAC-aware v2 deterministic selection by descending PAC XML graph "
                "complexity, with virtual path as the tie-breaker."
            ),
            graph_complexity=candidate.graph_complexity,
            graph_tags=candidate.graph_tags,
            pac_xml_virtual_path=candidate.pac_xml_virtual_path,
            pac_xml_sha256=candidate.pac_xml_sha256,
        )
        for index, candidate in enumerate(selected, 1)
    )


def validate_visual_audit_specs(specs: Sequence[VisualAuditAssetSpec]) -> dict[str, int]:
    _validate_visual_audit_identities(specs)
    v2_categories = set(VISUAL_AUDIT_V2_CATEGORY_COUNTS)
    selected_categories = {spec.model_category for spec in specs}
    if selected_categories and selected_categories <= v2_categories:
        validation = validate_visual_audit_v2_selection(
            tuple(
                VisualAuditV2Candidate(
                    virtual_path=spec.virtual_path,
                    category=spec.model_category,
                    graph_complexity=spec.graph_complexity,
                    graph_tags=spec.graph_tags,
                    pac_xml_virtual_path=spec.pac_xml_virtual_path,
                    pac_xml_sha256=spec.pac_xml_sha256,
                )
                for spec in specs
            )
        )
        return {
            **dict(validation["category_counts"]),
            **dict(validation["graph_coverage"]),
        }
    if len(specs) < 30:
        raise ValueError("Visual-audit corpus requires at least 30 unique PAC paths.")
    counts = {
        "weapon": sum("weapon" in spec.coverage_tags for spec in specs),
        "sword": sum("sword" in spec.coverage_tags for spec in specs),
        "armor": sum("armor" in spec.coverage_tags for spec in specs),
        "body": sum("body" in spec.coverage_tags for spec in specs),
        "hair_fur_feather": sum(
            bool({"hair", "fur", "feather"} & set(spec.coverage_tags)) for spec in specs
        ),
        "unusual": sum("unusual" in spec.coverage_tags for spec in specs),
    }
    required = {
        "weapon": 8,
        "sword": 5,
        "armor": 8,
        "body": 5,
        "hair_fur_feather": 5,
        "unusual": 4,
    }
    short = {name: (counts[name], minimum) for name, minimum in required.items() if counts[name] < minimum}
    if short:
        raise ValueError(f"Visual-audit corpus coverage is incomplete: {short}")
    return counts


def prepare_visual_audit_corpus(
    game_root: Path,
    temporary_root: Path,
    specs: Sequence[VisualAuditAssetSpec],
    *,
    progress: Callable[[int, int, str], None] | None = None,
    checkpoint: Callable[[Mapping[str, object]], None] | None = None,
    allow_partial: bool = False,
    resume_checkpoint: Mapping[str, object] | None = None,
    source_board_root: Path | None = None,
) -> dict[str, object]:
    game_root = Path(game_root).resolve()
    temporary_root = Path(temporary_root).resolve()
    if temporary_root.is_relative_to(game_root):
        raise ValueError("Visual-audit temporary output must be outside the game root.")
    if allow_partial:
        _validate_visual_audit_identities(specs)
        coverage = _coverage_counts(specs)
    else:
        coverage = validate_visual_audit_specs(specs)
    pamt_path = game_root / "0009" / "0.pamt"
    entries = parse_archive_pamt(pamt_path)
    entries_by_path, entries_by_basename = _archive_entry_indexes(entries)
    rows, runtime_assets, fingerprint_paths = _resume_visual_audit_state(
        resume_checkpoint,
        specs=specs,
        game_root=game_root,
        pamt_path=pamt_path,
        coverage=coverage,
    )
    package_root = temporary_root / "packages"
    package_root.mkdir(parents=True, exist_ok=True)
    for offset, spec in enumerate(specs[len(rows) :], len(rows) + 1):
        if progress is not None:
            progress(offset, len(specs), spec.virtual_path)
        (
            entry,
            payload,
            mesh,
            preview_result,
            resolved_textures,
            material_diagnostics,
            started,
            archive_started,
        ) = _load_visual_audit_asset(
            spec,
            entries_by_path=entries_by_path,
            entries_by_basename=entries_by_basename,
        )
        # Package writing is the single material-combiner authority for this
        # harness. Running it here as well repeats the same expensive graph
        # synthesis without changing the captured package contract.
        prepared_model, _prepared_preview = prepare_model_preview(
            preview_result.preview_model,
            enable_material_combiner=False,
        )
        comparison_overlays = _remove_visual_audit_overlays(prepared_model)
        copy_dotnet_preview_material_bindings(mesh, prepared_model)
        archive_prepare_ms = (time.perf_counter() - archive_started) * 1000.0
        material_state = mesh_dotnet_material_state_payload(
            mesh,
            session_id=spec.asset_id,
            edit_revision=0,
            generation=1,
        )
        source_boards = (
            build_source_material_boards(
                spec.asset_id,
                resolved_textures,
                material_state,
                source_board_root,
            )
            if source_board_root is not None
            else {"schema": "cdmw_mesh_visual_audit_source_board_v2", "boards": [], "textures": []}
        )
        metadata_elapsed_ms = (time.perf_counter() - started) * 1000.0
        dotnet_started = time.perf_counter()
        dotnet_package = build_mesh_dotnet_experiment_package(
            mesh,
            output_root=package_root / "mesh-editor",
            comparison_mode="replacement_only",
            interaction_mode="placement",
            scene_session_id=spec.asset_id,
        )
        resident_material_state = compile_mesh_dotnet_material_update(
            MeshDotNetMaterialCompileRequest(
                session_id=spec.asset_id,
                edit_revision=0,
                generation=1,
                role="replacement",
                mesh_snapshot=snapshot_mesh_dotnet_material_inputs(
                    mesh,
                    scene_material_slot_indices=dotnet_package.scene_material_slot_indices,
                ),
                output_root=temporary_root / "resident-material-cache",
                reason="visual_audit_initial_resident_equivalence",
            )
        )
        resident_material_state_path = dotnet_package.package_dir / "resident_material_state_v3.json"
        initial_material_state_path = dotnet_package.package_dir / "net_materials.json"
        atomic_write_text(
            resident_material_state_path,
            json.dumps(resident_material_state, indent=2, sort_keys=True),
        )
        initial_resident_equivalence = _initial_resident_material_equivalence(
            initial_material_state_path,
            resident_material_state,
        )
        if not initial_resident_equivalence["equivalent"]:
            raise RuntimeError(
                f"Initial/resident material compiler mismatch for {spec.virtual_path}: "
                f"{initial_resident_equivalence['mismatches']}"
            )
        dotnet_package_ms = (time.perf_counter() - dotnet_started) * 1000.0
        archive_package_ms = dotnet_package_ms
        archive_package_stability = {
            "schema": "cdmw_visual_audit_shared_dotnet_package_v1",
            "renderer_id": "d3d11_vortice_shader",
            "same_package_for_archive_and_mesh_editor": True,
            "package_dir": str(dotnet_package.package_dir),
        }
        provenance = _archive_entry_provenance(entry)
        fingerprint_paths.update((Path(entry.pamt_path), Path(entry.paz_file)))
        for texture in resolved_textures:
            texture_provenance = texture.get("archive_provenance")
            if isinstance(texture_provenance, Mapping):
                for key in ("pamt_path", "paz_path"):
                    if str(texture_provenance.get(key, "")).strip():
                        fingerprint_paths.add(Path(str(texture_provenance[key])))
        row = _visual_audit_corpus_row(
            spec=spec,
            entry_provenance=provenance,
            payload=payload,
            mesh=mesh,
            material_state=material_state,
            resolved_textures=resolved_textures,
            material_diagnostics=material_diagnostics,
            source_boards=source_boards,
            comparison_overlays=comparison_overlays,
            preview_timings=preview_result.timings,
            archive_prepare_ms=archive_prepare_ms,
            archive_package_ms=archive_package_ms,
            archive_package_stability=archive_package_stability,
            dotnet_package_ms=dotnet_package_ms,
            metadata_elapsed_ms=metadata_elapsed_ms,
            started=started,
            initial_resident_equivalence=initial_resident_equivalence,
            material_graph_evidence={
                "initial": _file_evidence(initial_material_state_path),
                "resident": _file_evidence(resident_material_state_path),
            },
        )
        rows.append(row)
        runtime_assets.append(
            {
                "id": spec.asset_id,
                "virtual_path": spec.virtual_path,
                "archive_package_dir": str(dotnet_package.package_dir),
                "dotnet_package_dir": str(dotnet_package.package_dir),
                "resident_material_state_path": str(resident_material_state_path),
                "views": [dict(view) for view in VISUAL_AUDIT_VIEWS],
                "material_regions": _visual_audit_material_regions(mesh, material_state),
            }
        )
        if checkpoint is not None:
            checkpoint(
                _visual_audit_checkpoint(
                    game_root=game_root,
                    pamt_path=pamt_path,
                    requested_asset_count=len(specs),
                    coverage=coverage,
                    rows=rows,
                    runtime_assets=runtime_assets,
                    fingerprint_paths=fingerprint_paths,
                )
            )
        del (
            dotnet_package,
            entry,
            material_state,
            mesh,
            payload,
            prepared_model,
            preview_result,
            resident_material_state,
            resolved_textures,
            source_boards,
        )
        gc.collect()
    return {
        "schema": "cdmw_mesh_visual_audit_corpus_v2",
        "compatible_reader_schemas": ["cdmw_mesh_visual_audit_corpus_v1"],
        "game_root": str(game_root),
        "pamt_path": str(pamt_path),
        "coverage": coverage,
        "asset_count": len(rows),
        "assets": rows,
        "runtime_assets": runtime_assets,
        "archive_fingerprint_paths": [str(path) for path in sorted(fingerprint_paths, key=lambda value: str(value).casefold())],
        "archive_fingerprints": _archive_content_fingerprints(tuple(fingerprint_paths)),
    }


def _resume_visual_audit_state(
    checkpoint: Mapping[str, object] | None,
    *,
    specs: Sequence[VisualAuditAssetSpec],
    game_root: Path,
    pamt_path: Path,
    coverage: Mapping[str, int],
) -> tuple[list[dict[str, object]], list[dict[str, object]], set[Path]]:
    if checkpoint is None:
        return [], [], set()
    if str(checkpoint.get("schema", "")) != "cdmw_mesh_visual_audit_preparation_checkpoint_v1":
        raise ValueError("Visual-audit resume checkpoint has an unsupported schema.")
    if Path(str(checkpoint.get("game_root", "") or "")).resolve() != game_root:
        raise ValueError("Visual-audit resume checkpoint belongs to a different game root.")
    if Path(str(checkpoint.get("pamt_path", "") or "")).resolve() != pamt_path:
        raise ValueError("Visual-audit resume checkpoint belongs to a different archive index.")
    if int(checkpoint.get("requested_asset_count", 0) or 0) != len(specs):
        raise ValueError("Visual-audit resume checkpoint has a different requested asset count.")
    checkpoint_coverage = checkpoint.get("coverage")
    if not isinstance(checkpoint_coverage, Mapping) or dict(checkpoint_coverage) != dict(coverage):
        raise ValueError("Visual-audit resume checkpoint has different coverage requirements.")

    asset_values = tuple(checkpoint.get("assets", ()) or ())
    runtime_values = tuple(checkpoint.get("runtime_assets", ()) or ())
    if len(asset_values) != len(runtime_values) or len(asset_values) > len(specs):
        raise ValueError("Visual-audit resume checkpoint has inconsistent prepared assets.")
    rows: list[dict[str, object]] = []
    runtime_assets: list[dict[str, object]] = []
    for index, (asset_value, runtime_value) in enumerate(zip(asset_values, runtime_values)):
        if not isinstance(asset_value, Mapping) or not isinstance(runtime_value, Mapping):
            raise ValueError("Visual-audit resume checkpoint contains an invalid prepared asset.")
        spec = specs[index]
        expected_path = spec.virtual_path.replace("\\", "/").casefold()
        asset_path = str(asset_value.get("virtual_path", "")).replace("\\", "/").casefold()
        runtime_path = str(runtime_value.get("virtual_path", "")).replace("\\", "/").casefold()
        if (
            str(asset_value.get("asset_id", "")).casefold() != spec.asset_id.casefold()
            or str(runtime_value.get("id", "")).casefold() != spec.asset_id.casefold()
            or asset_path != expected_path
            or runtime_path != expected_path
        ):
            raise ValueError("Visual-audit resume checkpoint does not match the manifest prefix.")
        rows.append(dict(asset_value))
        runtime_assets.append(dict(runtime_value))

    prepared_count = int(checkpoint.get("prepared_asset_count", -1) or 0)
    if prepared_count != len(rows):
        raise ValueError("Visual-audit resume checkpoint has an invalid prepared asset count.")
    fingerprint_values = tuple(checkpoint.get("archive_fingerprint_paths", ()) or ())
    return rows, runtime_assets, {Path(str(value)).resolve() for value in fingerprint_values}


def _load_visual_audit_asset(
    spec: VisualAuditAssetSpec,
    *,
    entries_by_path: Mapping[str, Sequence[object]],
    entries_by_basename: Mapping[str, Sequence[object]],
) -> tuple[object, bytes, object, object, Sequence[Mapping[str, object]], Sequence[object], float, float]:
    entry = next(iter(entries_by_path.get(_archive_key(spec.virtual_path), ())), None)
    if entry is None:
        raise FileNotFoundError(f"Visual-audit PAC is missing: {spec.virtual_path}")
    started = time.perf_counter()
    payload = _read_archive_payload(entry)
    mesh = MeshService().load_mesh_bytes(payload, entry.path)
    archive_started = time.perf_counter()
    preview_result = build_archive_preview_result(
        entry,
        (),
        texture_entries_by_normalized_path=dict(entries_by_path),
        texture_entries_by_basename=dict(entries_by_basename),
        include_loose_preview_assets=False,
        visible_texture_mode="mesh_base_first",
        support_texture_slots=("normal", "material", "height", "emissive"),
        quality_tier="full",
    )
    if preview_result.status != "ok" or preview_result.preview_model is None:
        raise RuntimeError(
            f"Archive Browser preview failed for {entry.path}: "
            f"{preview_result.warning_text or preview_result.detail_text}"
        )
    resolved_textures, material_diagnostics = _hydrate_real_archive_mesh_materials(
        mesh,
        entry,
        entries_by_path,
        entries_by_basename,
        preview_model=preview_result.preview_model,
    )
    return (
        entry,
        payload,
        mesh,
        preview_result,
        resolved_textures,
        material_diagnostics,
        started,
        archive_started,
    )


def _visual_audit_corpus_row(
    *,
    spec: VisualAuditAssetSpec,
    entry_provenance: Mapping[str, object],
    payload: bytes,
    mesh: object,
    material_state: Mapping[str, object],
    resolved_textures: Sequence[Mapping[str, object]],
    material_diagnostics: Sequence[object],
    source_boards: Mapping[str, object],
    comparison_overlays: Mapping[str, bool],
    preview_timings: Mapping[str, object] | None,
    archive_prepare_ms: float,
    archive_package_ms: float,
    archive_package_stability: Mapping[str, object],
    dotnet_package_ms: float,
    metadata_elapsed_ms: float,
    started: float,
    initial_resident_equivalence: Mapping[str, object],
    material_graph_evidence: Mapping[str, object],
) -> dict[str, object]:
    submeshes = [
        dict(value)
        for value in tuple(material_state.get("submeshes", ()) or ())
        if isinstance(value, Mapping)
    ]
    texture_rows = _texture_rows(resolved_textures)
    material_families = sorted({str(row.get("shader_family", "") or "unknown") for row in submeshes})
    expected_channels = sorted(
        {
            str(channel)
            for row in submeshes
            for channel in (row.get("channels", {}) if isinstance(row.get("channels"), Mapping) else {})
        }
    )
    alpha_modes = sorted({str(row.get("alpha_mode", "opaque") or "opaque") for row in submeshes})
    return {
        **asdict(spec),
        "archive_provenance": dict(entry_provenance),
        "payload_bytes": len(payload),
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "submesh_count": len(mesh.submeshes),
        "vertex_count": sum(len(submesh.vertices) for submesh in mesh.submeshes),
        "face_count": sum(len(submesh.faces) for submesh in mesh.submeshes),
        "expected_material_families": material_families,
        "shader_profile_classification": material_families,
        "expected_texture_channels": expected_channels,
        "alpha_modes": alpha_modes,
        "double_sided_submesh_count": sum(bool(row.get("double_sided")) for row in submeshes),
        "resolved_texture_count": len(texture_rows),
        "resolved_textures": texture_rows,
        "material_resolution_diagnostics": list(material_diagnostics),
        "pac_material_graphs": [
            _pac_material_graph_summary(row.get("source_contract", {}) or {})
            for row in submeshes
            if isinstance(row.get("source_contract"), Mapping)
        ],
        "binding_conservation": [
            dict(row.get("binding_conservation", {}) or {})
            for row in submeshes
            if isinstance(row.get("binding_conservation"), Mapping)
        ],
        "source_boards": _source_board_corpus_summary(source_boards),
        "material_graph_evidence": dict(material_graph_evidence),
        "comparison_presentation": {
            "skeleton_overlay_disabled": comparison_overlays["skeleton_overlay_disabled"],
            "cloth_overlay_disabled": comparison_overlays["cloth_overlay_disabled"],
            "reason": "Material-parity captures exclude non-material editor overlays.",
        },
        "archive_browser_timings": {
            **dict(preview_timings or {}),
            "prepare_ms": archive_prepare_ms,
            "package_ms": archive_package_ms,
        },
        "archive_package_stability": dict(archive_package_stability),
        "mesh_editor_package_ms": dotnet_package_ms,
        "initial_resident_material_equivalence": dict(initial_resident_equivalence),
        "metadata_ms": metadata_elapsed_ms,
        "preparation_total_ms": (time.perf_counter() - started) * 1000.0,
    }


def _file_evidence(path: Path) -> dict[str, object]:
    resolved = Path(path).resolve()
    digest = hashlib.sha256()
    size = 0
    with resolved.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return {"path": str(resolved), "bytes": size, "sha256": digest.hexdigest()}


def _pac_material_graph_summary(value: object) -> dict[str, object]:
    graph = value if isinstance(value, Mapping) else {}
    bindings = tuple(row for row in tuple(graph.get("bindings", ()) or ()) if isinstance(row, Mapping))
    parameters = tuple(row for row in tuple(graph.get("parameters", ()) or ()) if isinstance(row, Mapping))
    wrappers = tuple(row for row in tuple(graph.get("wrappers", ()) or ()) if isinstance(row, Mapping))
    dispositions: dict[str, int] = {}
    for binding in bindings:
        disposition = str(binding.get("binding_disposition", "") or "unknown")
        dispositions[disposition] = dispositions.get(disposition, 0) + 1
    return {
        "version": graph.get("version"),
        "schema": str(graph.get("schema", "") or ""),
        "source_kind": str(graph.get("source_kind", "") or ""),
        "source_asset_path": str(graph.get("source_asset_path", "") or ""),
        "source_submesh_index": graph.get("source_submesh_index"),
        "graph_hash": str(graph.get("graph_hash", "") or ""),
        "binding_count": len(bindings),
        "binding_dispositions": dispositions,
        "parameter_count": len(parameters),
        "wrapper_count": len(wrappers),
        "binding_conservation": dict(
            graph.get("binding_conservation", {})
            if isinstance(graph.get("binding_conservation"), Mapping)
            else {}
        ),
        "unsupported_features": list(graph.get("unsupported_features", ()) or ()),
    }


def _source_board_corpus_summary(value: Mapping[str, object]) -> dict[str, object]:
    manifest_path_text = str(value.get("manifest_path", "") or "")
    manifest_evidence = _file_evidence(Path(manifest_path_text)) if manifest_path_text else {}
    return {
        "schema": str(value.get("schema", "") or ""),
        "asset_id": str(value.get("asset_id", "") or ""),
        "manifest_path": manifest_path_text,
        "manifest_evidence": manifest_evidence,
        "boards": [
            dict(row)
            for row in tuple(value.get("boards", ()) or ())
            if isinstance(row, Mapping)
        ],
        "texture_count": len(tuple(value.get("textures", ()) or ())),
    }


def _initial_resident_material_equivalence(
    initial_manifest_path: Path,
    resident_payload: Mapping[str, object],
) -> dict[str, object]:
    """Compare canonical semantics while ignoring content-addressed output roots."""

    try:
        initial = json.loads(Path(initial_manifest_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {"equivalent": False, "mismatches": [f"initial_manifest:{type(exc).__name__}"]}
    if not isinstance(initial, Mapping):
        return {"equivalent": False, "mismatches": ["initial_manifest:not_object"]}
    initial_rows = {
        int(row.get("submesh_index", -1)): row
        for row in tuple(initial.get("submeshes", ()) or ())
        if isinstance(row, Mapping)
    }
    resident_rows = {
        int(row.get("submesh_index", -1)): row
        for row in tuple(resident_payload.get("submeshes", ()) or ())
        if isinstance(row, Mapping)
    }
    mismatches: list[str] = []
    if set(initial_rows) != set(resident_rows):
        mismatches.append("submesh_indices")
    compared_fields = (
        "material_slot_index",
        "material",
        "texture",
        "resource_channels",
        "channel_components",
        "shader_family",
        "shader_technique",
        "shader_authority",
        "material_category",
        "material_category_reason",
        "material_response_promoted",
        "channel_color_spaces",
        "channel_authorities",
        "alpha_mode",
        "alpha_cutoff",
        "opacity_factor",
        "double_sided",
        "source_contract",
        "binding_conservation",
        "unsupported_features",
        "material_synthesis",
        "parameters",
    )
    for index in sorted(set(initial_rows) | set(resident_rows)):
        left = initial_rows.get(index, {})
        right = resident_rows.get(index, {})
        for field in compared_fields:
            if left.get(field) != right.get(field):
                mismatches.append(f"submesh_{index}:{field}")
    initial_resources = {
        str(row.get("resource_id", "")): (
            str(row.get("fingerprint", "")),
            str(row.get("material_channel", "")),
            str(row.get("semantic", "")),
            str(row.get("color_space", "")),
            bool(row.get("required", False)),
        )
        for row in tuple(initial.get("resources", ()) or ())
        if isinstance(row, Mapping)
    }
    resident_resources = {
        str(row.get("resource_id", "")): (
            str(row.get("fingerprint", "")),
            str(row.get("material_channel", "")),
            str(row.get("semantic", "")),
            str(row.get("color_space", "")),
            bool(row.get("required", False)),
        )
        for row in tuple(resident_payload.get("resources", ()) or ())
        if isinstance(row, Mapping)
    }
    if initial_resources != resident_resources:
        mismatches.append("resource_fingerprints")
    if str(initial.get("material_signature", "")) != str(
        resident_payload.get("material_signature", "")
    ):
        mismatches.append("material_signature")
    return {
        "schema": "cdmw_mesh_initial_resident_material_equivalence_v1",
        "equivalent": not mismatches,
        "mismatches": mismatches,
        "submesh_count": len(initial_rows),
        "resource_count": len(initial_resources),
        "initial_material_signature": str(initial.get("material_signature", "")),
        "resident_material_signature": str(resident_payload.get("material_signature", "")),
    }


def _visual_audit_checkpoint(
    *,
    game_root: Path,
    pamt_path: Path,
    requested_asset_count: int,
    coverage: Mapping[str, int],
    rows: Sequence[Mapping[str, object]],
    runtime_assets: Sequence[Mapping[str, object]],
    fingerprint_paths: set[Path],
) -> dict[str, object]:
    return {
        "schema": "cdmw_mesh_visual_audit_preparation_checkpoint_v1",
        "game_root": str(game_root),
        "pamt_path": str(pamt_path),
        "requested_asset_count": requested_asset_count,
        "prepared_asset_count": len(rows),
        "coverage": dict(coverage),
        "assets": list(rows),
        "runtime_assets": list(runtime_assets),
        "archive_fingerprint_paths": [
            str(path) for path in sorted(fingerprint_paths, key=lambda value: str(value).casefold())
        ],
        "complete": len(rows) == requested_asset_count,
    }


def _coverage_counts(specs: Sequence[VisualAuditAssetSpec]) -> dict[str, int]:
    return {
        "weapon": sum("weapon" in spec.coverage_tags for spec in specs),
        "sword": sum("sword" in spec.coverage_tags for spec in specs),
        "armor": sum("armor" in spec.coverage_tags for spec in specs),
        "body": sum("body" in spec.coverage_tags for spec in specs),
        "hair_fur_feather": sum(
            bool({"hair", "fur", "feather"} & set(spec.coverage_tags)) for spec in specs
        ),
        "unusual": sum("unusual" in spec.coverage_tags for spec in specs),
    }


def _validate_visual_audit_identities(specs: Sequence[VisualAuditAssetSpec]) -> None:
    paths = [spec.virtual_path.replace("\\", "/").casefold() for spec in specs]
    ids = [spec.asset_id.casefold() for spec in specs]
    if len(set(paths)) != len(paths):
        raise ValueError("Visual-audit corpus requires unique PAC paths.")
    if len(set(ids)) != len(ids):
        raise ValueError("Visual-audit corpus requires unique asset IDs.")
    for spec in specs:
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,119}", spec.asset_id) is None:
            raise ValueError(f"Visual-audit asset ID is not a safe filename component: {spec.asset_id!r}")
        path = spec.virtual_path.replace("\\", "/")
        parts = tuple(part for part in path.split("/") if part)
        if not path.casefold().endswith(".pac") or path.startswith("/") or ".." in parts:
            raise ValueError(f"Visual-audit virtual path must be a relative PAC path: {spec.virtual_path!r}")


def _visual_audit_material_regions(
    mesh: object,
    material_state: Mapping[str, object],
) -> list[dict[str, object]]:
    material_rows = {
        int(row.get("submesh_index", index) if row.get("submesh_index") is not None else index): row
        for index, row in enumerate(tuple(material_state.get("submeshes", ()) or ()))
        if isinstance(row, Mapping)
    }
    regions: list[dict[str, object]] = []
    for index, submesh in enumerate(tuple(getattr(mesh, "submeshes", ()) or ())):
        if not tuple(getattr(submesh, "vertices", ()) or ()) or not tuple(getattr(submesh, "faces", ()) or ()):
            continue
        material = material_rows.get(index, {})
        regions.append(
            {
                "source_submesh_index": index,
                "submesh_name": str(getattr(submesh, "name", "") or f"submesh_{index}"),
                "material_name": str(material.get("material_name", "") or ""),
                "capture_angles": [dict(angle) for angle in VISUAL_AUDIT_REGION_ANGLES],
                "debug_modes": list(VISUAL_AUDIT_REGION_DEBUG_MODES),
            }
        )
    return regions


def _remove_visual_audit_overlays(model: object) -> dict[str, bool]:
    """Remove cloned, non-material overlays from comparison-only packages."""

    skeleton_overlay_disabled = getattr(model, "physics_overlay", None) is not None
    cloth_overlay_disabled = getattr(model, "cloth_preview", None) is not None
    if hasattr(model, "physics_overlay"):
        setattr(model, "physics_overlay", None)
    if hasattr(model, "cloth_preview"):
        setattr(model, "cloth_preview", None)
    return {
        "skeleton_overlay_disabled": skeleton_overlay_disabled,
        "cloth_overlay_disabled": cloth_overlay_disabled,
    }


def _texture_rows(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    unique: dict[tuple[str, str, str], dict[str, object]] = {}
    for row in rows:
        source_text = str(row.get("source_path", "") or "").strip()
        if not source_text:
            continue
        source = Path(source_text)
        semantic = str(row.get("semantic", "") or "material")
        key = (source_text.casefold(), semantic.casefold(), str(row.get("parameter_name", "")).casefold())
        if key in unique:
            continue
        dds = _dds_header_row(source) if source.is_file() else {"status": "missing"}
        unique[key] = {
            "archive_path": str(row.get("archive_path", "") or "").replace("\\", "/"),
            "semantic": semantic,
            "parameter_name": str(row.get("parameter_name", "") or ""),
            "material_authority": str(row.get("material_authority", "") or ""),
            "source_bytes": int(row.get("source_bytes", 0) or 0),
            "source_sha256": str(row.get("source_sha256", "") or ""),
            "dds": dds,
        }
    return sorted(
        unique.values(),
        key=lambda row: (str(row["semantic"]).casefold(), str(row["archive_path"]).casefold()),
    )


__all__ = [
    "VISUAL_AUDIT_VIEWS",
    "VISUAL_AUDIT_REGION_ANGLES",
    "VISUAL_AUDIT_REGION_DEBUG_MODES",
    "VisualAuditAssetSpec",
    "default_visual_audit_specs",
    "default_visual_audit_v2_specs",
    "prepare_visual_audit_corpus",
    "validate_visual_audit_specs",
]
