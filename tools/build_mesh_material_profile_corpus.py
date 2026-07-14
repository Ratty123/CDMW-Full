from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.services.asset_authoring_service import AssetAuthoringService
from cdmw.services.mesh_service import MeshService
from cdmw.services.mesh_workflow_service import import_scene_mesh_with_report
from tools.mesh_harness.archive_provenance import _hydrate_real_archive_mesh_materials
from tools.mesh_harness.material_profile_corpus import (
    material_asset_contract_row,
    material_profile_corpus_report,
)
from tools.mesh_harness.real_dotnet import _prepare_real_asset
from tools.mesh_harness.real_common import _archive_entry_indexes, _archive_key, _read_archive_payload


_REPRESENTATIVE_REAL_PACS = {
    "clothing": "character/model/1_pc/14_ptm/armor/9_upperbody/cd_ptm_01_ub_0001.pac",
    "hair": "character/model/1_pc/14_ptm/head/hair/cd_ptm_00_hair_00_0003.pac",
    "weapon": "character/model/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_sword_0001.pac",
    "emissive_weapon": "character/model/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0014.pac",
    "prop": "character/model/6_object/tools/cd_t0000_lantern_0001.pac",
    "layered_armor": "character/model/1_pc/14_ptm/armor/9_upperbody/cd_ptm_00_m0001_00_ub_belt_0001.pac",
    "fur": "character/model/2_mon/cd_m0001_00_twofeet/cd_m0001_00_beastman/cd_m0001_00_beastman_fur_0001.pac",
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _representative_real_asset_rows(
    game_root: Path,
    *,
    texture_probe: Callable[[Path], Mapping[str, object]] | None = None,
    texture_probe_cache: dict[str, Mapping[str, object]] | None = None,
) -> list[dict[str, object]]:
    entries = parse_archive_pamt(game_root / "0009" / "0.pamt")
    entries_by_path, entries_by_basename = _archive_entry_indexes(entries)
    rows: list[dict[str, object]] = []
    for category, virtual_path in _REPRESENTATIVE_REAL_PACS.items():
        entry = next(iter(entries_by_path.get(_archive_key(virtual_path), ())), None)
        if entry is None:
            raise RuntimeError(f"Representative {category} PAC is missing: {virtual_path}")
        payload = _read_archive_payload(entry)
        mesh = MeshService().load_mesh_bytes(payload, entry.path)
        textures, material_diagnostics = _hydrate_real_archive_mesh_materials(
            mesh,
            entry,
            entries_by_path,
            entries_by_basename,
        )
        if category == "hair" and not textures:
            raise RuntimeError(f"Representative hair PAC resolved no source DDS resources: {entry.path}")
        rows.append(
            material_asset_contract_row(
                mesh,
                asset_kind=f"representative_real_pac_{category}",
                source_identity={
                    "category": category,
                    "virtual_path": entry.path,
                    "payload_bytes": len(payload),
                    "payload_sha256": hashlib.sha256(payload).hexdigest(),
                    "resolved_texture_count": len(textures),
                    "material_resolution_diagnostics": list(material_diagnostics),
                },
                texture_provenance=textures,
                profile_assignment="material_authority_true_source",
                texture_probe=texture_probe,
                texture_probe_cache=texture_probe_cache,
            )
        )
    return rows


def build_report(
    *,
    game_root: Path | None,
    external_model: Path | None,
    openimageio_path: Path | None = None,
) -> dict[str, object]:
    assets: list[dict[str, object]] = []
    texture_probe = None
    texture_probe_cache: dict[str, Mapping[str, object]] = {}
    if openimageio_path is not None:
        service = AssetAuthoringService()
        configured_paths = {"openimageio": openimageio_path}
        texture_probe = lambda source: service.run_openimageio_metadata(  # noqa: E731
            source,
            configured_paths,
            timeout_s=60.0,
        )
    if game_root is not None:
        with tempfile.TemporaryDirectory(prefix="cdmw-material-corpus-") as temporary:
            prepared = _prepare_real_asset(game_root, Path(temporary), 120.0)
            if isinstance(prepared, dict):
                raise RuntimeError(str(prepared.get("error") or "Could not prepare canonical real PAC."))
            assets.append(
                material_asset_contract_row(
                    prepared.mesh,
                    asset_kind="canonical_real_pac",
                    source_identity={
                        "virtual_path": prepared.model_entry.path,
                        "payload_sha256": prepared.source_payload_sha256,
                        "material_resolution_diagnostics": list(
                            prepared.material_resolution_diagnostics
                        ),
                    },
                    texture_provenance=prepared.resolved_textures,
                    profile_assignment="material_authority_true_source",
                    texture_probe=texture_probe,
                    texture_probe_cache=texture_probe_cache,
                )
            )
        assets.extend(
            _representative_real_asset_rows(
                game_root,
                texture_probe=texture_probe,
                texture_probe_cache=texture_probe_cache,
            )
        )
    if external_model is not None:
        source = external_model.resolve()
        imported = import_scene_mesh_with_report(source)
        assets.append(
            material_asset_contract_row(
                imported.mesh,
                asset_kind="external_catalogue",
                source_identity={
                    "name": source.name,
                    "bytes": int(source.stat().st_size),
                    "sha256": _sha256_file(source),
                },
                profile_assignment="material_authority_true_source",
                texture_probe=texture_probe,
                texture_probe_cache=texture_probe_cache,
            )
        )
    return material_profile_corpus_report(asset_rows=assets)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--game-root", type=Path)
    parser.add_argument("--external-model", type=Path)
    parser.add_argument("--oiio-path", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = build_report(
        game_root=args.game_root,
        external_model=args.external_model,
        openimageio_path=args.oiio_path,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
