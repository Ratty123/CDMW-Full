from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from tools.mesh_harness.archive_provenance import _archive_content_fingerprints
from tools.mesh_harness.visual_audit_manifest_v2 import (
    PRIOR_CONCERN_SWORD_PATH,
    REQUIRED_SWORD_PATH,
    VISUAL_AUDIT_V2_CATEGORY_COUNTS,
    VISUAL_AUDIT_V2_EXPANSION_RULES_VERSION,
    VISUAL_AUDIT_V2_GRAPH_MINIMUMS,
    VisualAuditV2Candidate,
    build_visual_audit_v2_candidates,
    normalize_visual_audit_virtual_path,
    select_visual_audit_v2_candidates,
    validate_visual_audit_v2_selection,
    visual_audit_v2_archive_paths,
)


DEFAULT_EXPANSION_SELECTION_SEED = "expanded-sixth-120-20260722"
EXPANSION_REPEAT_PATHS = (REQUIRED_SWORD_PATH, PRIOR_CONCERN_SWORD_PATH)


@dataclass(frozen=True, slots=True)
class VisualAuditExclusionRegistry:
    inputs: tuple[dict[str, object], ...]
    paths: frozenset[str]


def default_historical_manifest_paths() -> tuple[Path, ...]:
    owner = Path(__file__).resolve().parent
    return tuple(sorted(owner.glob("visual_audit_*.manifest.json"), key=_path_sort_key))


def load_visual_audit_exclusion_registry(
    paths: Iterable[Path],
) -> VisualAuditExclusionRegistry:
    unique_inputs: dict[str, Path] = {}
    for raw_path in paths:
        path = Path(raw_path).expanduser().resolve(strict=True)
        if not path.is_file():
            raise ValueError(f"Visual-audit exclusion input is not a file: {path}")
        unique_inputs[str(path).casefold()] = path

    input_rows: list[dict[str, object]] = []
    excluded_paths: set[str] = set()
    for path in sorted(unique_inputs.values(), key=_path_sort_key):
        raw = path.read_bytes()
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"Visual-audit exclusion input must be UTF-8 JSON: {path}"
            ) from exc
        if not isinstance(payload, Mapping):
            raise ValueError(f"Visual-audit exclusion input must be an object: {path}")

        asset_paths = _asset_virtual_paths(payload, path=path)
        declared_exclusions = _declared_excluded_paths(payload, path=path)
        input_paths = asset_paths | declared_exclusions
        if not input_paths:
            raise ValueError(f"Visual-audit exclusion input contains no PAC paths: {path}")
        excluded_paths.update(input_paths)
        input_rows.append(
            {
                "path": str(path),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "schema": str(payload.get("schema", "") or ""),
                "asset_path_count": len(asset_paths),
                "declared_excluded_path_count": len(declared_exclusions),
                "unique_path_count": len(input_paths),
            }
        )
    return VisualAuditExclusionRegistry(
        inputs=tuple(input_rows),
        paths=frozenset(excluded_paths),
    )


def build_visual_audit_expansion_manifest(
    candidates: Sequence[VisualAuditV2Candidate],
    exclusion_registry: VisualAuditExclusionRegistry,
    *,
    selection_seed: str = DEFAULT_EXPANSION_SELECTION_SEED,
    allowed_repeat_paths: Iterable[str] = EXPANSION_REPEAT_PATHS,
    archive_fingerprints_before: Mapping[str, Mapping[str, object]] | None = None,
    archive_fingerprints_after: Mapping[str, Mapping[str, object]] | None = None,
) -> dict[str, object]:
    normalized_repeats = {
        normalize_visual_audit_virtual_path(path)
        for path in allowed_repeat_paths
        if str(path or "").strip()
    }
    required_repeats = {
        normalize_visual_audit_virtual_path(path) for path in EXPANSION_REPEAT_PATHS
    }
    if normalized_repeats != required_repeats:
        raise ValueError(
            "The expanded 120-PAC milestone permits exactly the two required sword repeats."
        )
    missing_history = sorted(normalized_repeats - exclusion_registry.paths)
    if missing_history:
        raise ValueError(
            "Allowed repeat PACs are absent from the historical exclusion registry: "
            f"{missing_history}"
        )

    selected = select_visual_audit_v2_candidates(
        candidates,
        excluded_paths=exclusion_registry.paths,
        allowed_repeat_paths=normalized_repeats,
        selection_seed=selection_seed,
    )
    validation = validate_visual_audit_v2_selection(selected)
    selected_paths = {
        normalize_visual_audit_virtual_path(candidate.virtual_path)
        for candidate in selected
    }
    historical_overlap = selected_paths & exclusion_registry.paths
    if historical_overlap != normalized_repeats:
        unexpected = sorted(historical_overlap - normalized_repeats)
        missing = sorted(normalized_repeats - historical_overlap)
        raise ValueError(
            "Expanded visual-audit selection has an invalid historical overlap: "
            f"unexpected={unexpected}, missing_required={missing}"
        )
    new_path_count = len(selected_paths - exclusion_registry.paths)
    if new_path_count != 118:
        raise ValueError(
            f"Expanded visual-audit selection requires exactly 118 new PACs; found {new_path_count}."
        )
    if (archive_fingerprints_before is None) != (archive_fingerprints_after is None):
        raise ValueError("Source archive fingerprints require both before and after records.")
    if (
        archive_fingerprints_before is not None
        and archive_fingerprints_before != archive_fingerprints_after
    ):
        raise ValueError("Source PAMT/PAZ fingerprints changed during manifest selection.")

    effective_exclusions = sorted(exclusion_registry.paths - normalized_repeats)
    assets = [
        {
            "index": index,
            "asset_id": (
                f"{index:03d}-{candidate.category}-"
                f"{Path(candidate.virtual_path).stem.lower().replace('_', '-')}"
            ),
            "virtual_path": candidate.virtual_path,
            "model_category": candidate.category,
            "coverage_tags": sorted({candidate.category, *candidate.graph_tags}),
            "selection_reason": (
                "Coverage-aware deterministic expansion selection preferring new PAC XML "
                "fingerprints, rare shader/tag families, and graph complexity."
            ),
            "graph_complexity": candidate.graph_complexity,
            "graph_tags": list(candidate.graph_tags),
            "shader_families": list(candidate.shader_families),
            "pac_xml_virtual_path": candidate.pac_xml_virtual_path,
            "pac_xml_sha256": candidate.pac_xml_sha256,
            "wrapper_count": candidate.wrapper_count,
            "parameter_count": candidate.parameter_count,
            "texture_parameter_count": candidate.texture_parameter_count,
        }
        for index, candidate in enumerate(selected, 1)
    ]
    payload: dict[str, object] = {
        "schema": "cdmw_mesh_visual_audit_manifest_v2",
        "name": "expanded-sixth-120",
        "minimum_asset_count": 120,
        "required_coverage": {
            **dict(VISUAL_AUDIT_V2_CATEGORY_COUNTS),
            **dict(VISUAL_AUDIT_V2_GRAPH_MINIMUMS),
        },
        "excluded_virtual_paths": effective_exclusions,
        "selection_policy": (
            "historical exclusion, two explicit regression repeats, PAC XML fingerprint "
            "diversity, rare shader/tag families, graph complexity, seeded stable tie-breaker"
        ),
        "selection_provenance": {
            "schema": "cdmw_mesh_visual_audit_selection_provenance_v1",
            "selection_rules_version": VISUAL_AUDIT_V2_EXPANSION_RULES_VERSION,
            "selection_seed": selection_seed,
            "exclusion_inputs": [dict(row) for row in exclusion_registry.inputs],
            "excluded_path_count": len(exclusion_registry.paths),
            "effective_excluded_path_count": len(effective_exclusions),
            "allowed_repeat_paths": sorted(normalized_repeats),
            "historical_overlap_paths": sorted(historical_overlap),
            "new_path_count": new_path_count,
            "candidate_count": len(
                {
                    normalize_visual_audit_virtual_path(candidate.virtual_path)
                    for candidate in candidates
                }
            ),
            "category_counts": dict(validation["category_counts"]),
            "graph_tag_coverage": dict(validation["graph_coverage"]),
            "source_archive_fingerprints": {
                "recorded": archive_fingerprints_before is not None,
                "unchanged": (
                    archive_fingerprints_before == archive_fingerprints_after
                    if archive_fingerprints_before is not None
                    else None
                ),
                "path_count": len(archive_fingerprints_before or {}),
                "before": dict(archive_fingerprints_before or {}),
                "after": dict(archive_fingerprints_after or {}),
            },
        },
        "assets": assets,
    }
    provenance = payload["selection_provenance"]
    assert isinstance(provenance, dict)
    provenance["manifest_core_sha256"] = _canonical_payload_sha256(payload)
    return payload


def write_visual_audit_expansion_manifest(
    path: Path,
    payload: Mapping[str, object],
) -> dict[str, object]:
    output_path = Path(path).expanduser().resolve()
    encoded = (
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("utf-8")
    file_sha256 = hashlib.sha256(encoded).hexdigest()
    sha256_path = output_path.with_suffix(output_path.suffix + ".sha256")
    _atomic_write_bytes(output_path, encoded)
    _atomic_write_bytes(
        sha256_path,
        f"{file_sha256}  {output_path.name}\n".encode("ascii"),
    )
    return {
        "manifest_path": str(output_path),
        "manifest_sha256": file_sha256,
        "sha256_path": str(sha256_path),
    }


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate the deterministic expanded 120-PAC Mesh Editor visual-audit manifest."
        )
    )
    parser.add_argument("--game-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline-corpus", type=Path, required=True)
    parser.add_argument("--historical-manifest", type=Path, action="append", default=[])
    parser.add_argument("--historical-corpus", type=Path, action="append", default=[])
    parser.add_argument(
        "--selection-seed",
        default=DEFAULT_EXPANSION_SELECTION_SEED,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _argument_parser()
    args = parser.parse_args(argv)
    try:
        game_root = args.game_root.expanduser().resolve(strict=True)
        output_path = args.output.expanduser().resolve()
        if output_path.is_relative_to(game_root):
            raise ValueError("Expansion manifest output must be outside the game root.")
        exclusion_inputs = (
            *default_historical_manifest_paths(),
            args.baseline_corpus,
            *args.historical_manifest,
            *args.historical_corpus,
        )
        registry = load_visual_audit_exclusion_registry(exclusion_inputs)
        archive_paths = visual_audit_v2_archive_paths(game_root)
        archive_fingerprints_before = _archive_content_fingerprints(archive_paths)
        candidates = build_visual_audit_v2_candidates(game_root)
        archive_fingerprints_after = _archive_content_fingerprints(archive_paths)
        payload = build_visual_audit_expansion_manifest(
            candidates,
            registry,
            selection_seed=args.selection_seed,
            archive_fingerprints_before=archive_fingerprints_before,
            archive_fingerprints_after=archive_fingerprints_after,
        )
        result = write_visual_audit_expansion_manifest(output_path, payload)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    provenance = payload["selection_provenance"]
    assert isinstance(provenance, Mapping)
    print(
        "Generated expanded 120-PAC manifest: "
        f"new={provenance['new_path_count']} "
        f"excluded={provenance['excluded_path_count']} "
        f"sha256={result['manifest_sha256']} "
        f"path={result['manifest_path']}"
    )
    return 0


def _asset_virtual_paths(
    payload: Mapping[str, object],
    *,
    path: Path,
) -> set[str]:
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise ValueError(f"Visual-audit exclusion input has no assets array: {path}")
    result: set[str] = set()
    for index, row in enumerate(assets, 1):
        if not isinstance(row, Mapping):
            raise ValueError(
                f"Visual-audit exclusion input asset {index} is not an object: {path}"
            )
        virtual_path = str(row.get("virtual_path", "") or "").strip()
        if not virtual_path:
            raise ValueError(
                f"Visual-audit exclusion input asset {index} has no virtual_path: {path}"
            )
        result.add(normalize_visual_audit_virtual_path(virtual_path))
    return result


def _declared_excluded_paths(
    payload: Mapping[str, object],
    *,
    path: Path,
) -> set[str]:
    values = payload.get("excluded_virtual_paths", [])
    if not isinstance(values, list):
        raise ValueError(
            f"Visual-audit exclusion input excluded_virtual_paths must be an array: {path}"
        )
    return {
        normalize_visual_audit_virtual_path(str(value or ""))
        for value in values
        if str(value or "").strip()
    }


def _canonical_payload_sha256(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary_path.write_bytes(payload)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _path_sort_key(path: Path) -> str:
    return str(Path(path).resolve()).replace("\\", "/").casefold()


__all__ = [
    "DEFAULT_EXPANSION_SELECTION_SEED",
    "EXPANSION_REPEAT_PATHS",
    "VisualAuditExclusionRegistry",
    "build_visual_audit_expansion_manifest",
    "default_historical_manifest_paths",
    "load_visual_audit_exclusion_registry",
    "main",
    "write_visual_audit_expansion_manifest",
]
