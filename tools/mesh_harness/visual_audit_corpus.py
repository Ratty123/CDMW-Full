from __future__ import annotations

import hashlib
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.archive_preview_result_builder import build_archive_preview_result
from cdmw.rendering.model_preview_prepare import prepare_model_preview
from cdmw.rendering.native_preview_package import write_isolated_d3d11_preview_package
from cdmw.services.mesh_dotnet_experiment import build_mesh_dotnet_experiment_package
from cdmw.services.mesh_dotnet_material_state import mesh_dotnet_material_state_payload
from cdmw.services.mesh_service import MeshService
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


@dataclass(frozen=True, slots=True)
class VisualAuditAssetSpec:
    index: int
    asset_id: str
    virtual_path: str
    model_category: str
    coverage_tags: tuple[str, ...]
    selection_reason: str


VISUAL_AUDIT_VIEWS: tuple[dict[str, object], ...] = (
    {"name": "front", "yaw": 0.0, "pitch": 0.0},
    {"name": "three-quarter-front", "yaw": -35.0, "pitch": 20.0},
    {"name": "side", "yaw": 90.0, "pitch": 0.0},
    {"name": "back", "yaw": 180.0, "pitch": 0.0},
    {"name": "slightly-above", "yaw": -35.0, "pitch": -28.0},
    {"name": "slightly-below", "yaw": -35.0, "pitch": 28.0},
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


def validate_visual_audit_specs(specs: Sequence[VisualAuditAssetSpec]) -> dict[str, int]:
    _validate_visual_audit_identities(specs)
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
    allow_partial: bool = False,
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
    rows: list[dict[str, object]] = []
    runtime_assets: list[dict[str, object]] = []
    fingerprint_paths: set[Path] = set()
    package_root = temporary_root / "packages"
    texture_cache = temporary_root / "archive-texture-cache"
    package_root.mkdir(parents=True, exist_ok=True)
    for offset, spec in enumerate(specs, 1):
        if progress is not None:
            progress(offset, len(specs), spec.virtual_path)
        entry = next(iter(entries_by_path.get(_archive_key(spec.virtual_path), ())), None)
        if entry is None:
            raise FileNotFoundError(f"Visual-audit PAC is missing: {spec.virtual_path}")
        started = time.perf_counter()
        payload = _read_archive_payload(entry)
        mesh = MeshService().load_mesh_bytes(payload, entry.path)
        resolved_textures, material_diagnostics = _hydrate_real_archive_mesh_materials(
            mesh,
            entry,
            entries_by_path,
            entries_by_basename,
        )
        material_state = mesh_dotnet_material_state_payload(
            mesh,
            session_id=spec.asset_id,
            edit_revision=0,
            generation=1,
        )
        metadata_elapsed_ms = (time.perf_counter() - started) * 1000.0
        archive_started = time.perf_counter()
        preview_result = build_archive_preview_result(
            None,
            entry,
            (),
            texture_entries_by_normalized_path=dict(entries_by_path),
            texture_entries_by_basename=dict(entries_by_basename),
            include_loose_preview_assets=False,
            visible_texture_mode="mesh_base_first",
            support_texture_slots=("normal", "material", "height"),
            quality_tier="full",
        )
        if preview_result.status != "ok" or preview_result.preview_model is None:
            raise RuntimeError(
                f"Archive Browser preview failed for {entry.path}: "
                f"{preview_result.warning_text or preview_result.detail_text}"
            )
        prepared_model, prepared_preview = prepare_model_preview(preview_result.preview_model)
        comparison_overlays = _remove_visual_audit_overlays(prepared_model)
        archive_prepare_ms = (time.perf_counter() - archive_started) * 1000.0
        archive_package_dir = package_root / "archive-browser" / spec.asset_id
        archive_package_started = time.perf_counter()
        write_isolated_d3d11_preview_package(
            prepared_model,
            prepared_preview,
            output_root=archive_package_dir,
            use_textures=True,
            high_quality_textures=True,
            backend="d3d11",
            enable_material_combiner=True,
            display_mode="replacement_only",
            texture_cache_dir=texture_cache,
        )
        archive_package_ms = (time.perf_counter() - archive_package_started) * 1000.0
        dotnet_started = time.perf_counter()
        dotnet_package = build_mesh_dotnet_experiment_package(
            mesh,
            output_root=package_root / "mesh-editor",
            comparison_mode="replacement_only",
            interaction_mode="placement",
            scene_session_id=spec.asset_id,
        )
        dotnet_package_ms = (time.perf_counter() - dotnet_started) * 1000.0
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
        provenance = _archive_entry_provenance(entry)
        fingerprint_paths.update((Path(entry.pamt_path), Path(entry.paz_file)))
        for texture in resolved_textures:
            texture_provenance = texture.get("archive_provenance")
            if isinstance(texture_provenance, Mapping):
                for key in ("pamt_path", "paz_path"):
                    if str(texture_provenance.get(key, "")).strip():
                        fingerprint_paths.add(Path(str(texture_provenance[key])))
        row = {
            **asdict(spec),
            "archive_provenance": provenance,
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
            "comparison_presentation": {
                "skeleton_overlay_disabled": comparison_overlays["skeleton_overlay_disabled"],
                "cloth_overlay_disabled": comparison_overlays["cloth_overlay_disabled"],
                "reason": "Material-parity captures exclude non-material editor overlays.",
            },
            "archive_browser_timings": {
                **dict(preview_result.timings or {}),
                "prepare_ms": archive_prepare_ms,
                "package_ms": archive_package_ms,
            },
            "mesh_editor_package_ms": dotnet_package_ms,
            "metadata_ms": metadata_elapsed_ms,
        }
        rows.append(row)
        runtime_assets.append(
            {
                "id": spec.asset_id,
                "virtual_path": spec.virtual_path,
                "archive_package_dir": str(archive_package_dir),
                "dotnet_package_dir": str(dotnet_package.package_dir),
                "views": [dict(view) for view in VISUAL_AUDIT_VIEWS],
            }
        )
    return {
        "schema": "cdmw_mesh_visual_audit_corpus_v1",
        "game_root": str(game_root),
        "pamt_path": str(pamt_path),
        "coverage": coverage,
        "asset_count": len(rows),
        "assets": rows,
        "runtime_assets": runtime_assets,
        "archive_fingerprint_paths": [str(path) for path in sorted(fingerprint_paths, key=lambda value: str(value).casefold())],
        "archive_fingerprints": _archive_content_fingerprints(tuple(fingerprint_paths)),
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
    "VisualAuditAssetSpec",
    "default_visual_audit_specs",
    "prepare_visual_audit_corpus",
    "validate_visual_audit_specs",
]
