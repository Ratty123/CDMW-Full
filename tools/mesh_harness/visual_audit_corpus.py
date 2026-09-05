from __future__ import annotations

import hashlib
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Sequence

from tools.mesh_harness.material_profile_corpus import _dds_header_row
from tools.mesh_harness.visual_audit_manifest_v2 import (
    VISUAL_AUDIT_V2_CATEGORY_COUNTS,
    VisualAuditV2Candidate,
    build_visual_audit_v2_candidates,
    select_visual_audit_v2_candidates,
    validate_visual_audit_v2_selection,
    visual_audit_v2_contract_for_asset_count,
)


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


def validate_visual_audit_specs(
    specs: Sequence[VisualAuditAssetSpec],
    *,
    expected_asset_count: int | None = None,
) -> dict[str, int]:
    _validate_visual_audit_identities(specs)
    v2_categories = set(VISUAL_AUDIT_V2_CATEGORY_COUNTS)
    selected_categories = {spec.model_category for spec in specs}
    if selected_categories and selected_categories <= v2_categories:
        # Without a pinned count this infers the milestone from the specs it was
        # handed, so a 120-PAC corpus validates cleanly where 500 was intended.
        # Callers that know which milestone they asked for should pass it.
        if expected_asset_count is not None and len(specs) != int(expected_asset_count):
            raise ValueError(
                f"Visual-audit corpus requires exactly {int(expected_asset_count)} "
                f"PACs; found {len(specs)}."
            )
        category_counts, graph_minimums = visual_audit_v2_contract_for_asset_count(
            len(specs)
        )
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
            ),
            category_counts=category_counts,
            graph_minimums=graph_minimums,
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


__all__ = ['VISUAL_AUDIT_VIEWS', 'VISUAL_AUDIT_REGION_ANGLES', 'VISUAL_AUDIT_REGION_DEBUG_MODES', 'VisualAuditAssetSpec', 'default_visual_audit_specs', 'default_visual_audit_v2_specs', 'validate_visual_audit_specs']
