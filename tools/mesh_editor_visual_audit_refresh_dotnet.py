"""Refresh or reuse .NET packages for a completed visual-audit corpus.

Archive Browser packages are immutable capture inputs. Renderer-only .NET
changes can reuse a completed run's prepared packages directly, while material
translation changes can rebuild only the .NET packages from the same real PAC
payloads. The generated state is consumed by ``mesh_editor_visual_audit.py
--phase capture`` and retains the normal run, corpus, path, and
archive-fingerprint validation.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from uuid import uuid4

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.rendering.native_preview_package import read_isolated_d3d11_preview_manifest
from cdmw.services.mesh_dotnet_experiment import build_mesh_dotnet_experiment_package
from cdmw.services.mesh_dotnet_material_bindings import (
    apply_dotnet_native_material_batch_bindings,
)
from cdmw.services.mesh_service import MeshService
from tools.mesh_harness.archive_provenance import (
    _archive_content_fingerprints,
    _hydrate_real_archive_mesh_materials,
)
from tools.mesh_harness.real_common import (
    _archive_entry_indexes,
    _archive_key,
    _read_archive_payload,
)
from tools.mesh_harness.visual_audit_cli import (
    _atomic_write_json,
    _payload_sha256,
    _read_json,
    _validate_prepared_state,
    _visual_audit_temporary_root,
)
from tools.mesh_harness.visual_audit_package import stabilize_visual_audit_archive_package


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reuse Archive Browser packages and rebuild .NET packages for a visual-audit corpus."
    )
    parser.add_argument("--game-root", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True, help="Completed visual-audit evidence root.")
    parser.add_argument("--output", type=Path, required=True, help="New evidence root for refreshed capture state.")
    parser.add_argument(
        "--reuse-dotnet-packages",
        action="store_true",
        help="Reuse the completed run's immutable Archive and .NET packages for renderer-only recapture.",
    )
    args = parser.parse_args(argv)

    game_root = args.game_root.resolve()
    source_root = args.source.resolve()
    output_root = args.output.resolve()
    _validate_roots(parser, game_root=game_root, source_root=source_root, output_root=output_root)

    source_corpus = _read_json(source_root / "corpus.json")
    source_state = _read_json(source_root / "runtime" / "package-state.json")
    try:
        _validate_prepared_state(
            source_corpus,
            source_state,
            evidence_root=source_root,
            game_root=game_root,
        )
        fingerprint_paths = _validated_fingerprint_paths(
            source_root,
            source_state,
            game_root=game_root,
        )
        source_assets = _matching_source_assets(source_corpus, source_state)
    except ValueError as exc:
        parser.error(str(exc))

    run_id = uuid4().hex
    temporary_root = _visual_audit_temporary_root(output_root, run_id)
    output_root.mkdir(parents=True, exist_ok=False)
    runtime_root = output_root / "runtime"
    for path in (runtime_root, output_root / "final", output_root / "comparisons", temporary_root):
        path.mkdir(parents=True, exist_ok=True)

    runtime_assets: list[dict[str, object]] = []
    timings: list[dict[str, object]] = []
    if args.reuse_dotnet_packages:
        print(
            f"Reusing {len(source_assets)} prepared Archive/.NET packages for renderer recapture...",
            flush=True,
        )
        runtime_assets.extend(
            _reused_runtime_assets(
                source_assets,
                run_id=run_id,
                temporary_root=temporary_root,
            )
        )
        timings.extend(
            {"id": str(asset["id"]), "refresh_ms": 0.0}
            for asset in runtime_assets
        )
    else:
        entries = parse_archive_pamt(game_root / "0009" / "0.pamt")
        entries_by_path, entries_by_basename = _archive_entry_indexes(entries)
        package_root = temporary_root / "packages"
        archive_root = package_root / "archive-browser"
        dotnet_root = package_root / "mesh-editor"

        print(f"Refreshing {len(source_assets)} real PAC .NET packages...", flush=True)
        for current, source_asset in enumerate(source_assets, 1):
            asset_id = str(source_asset["id"])
            virtual_path = str(source_asset["virtual_path"])
            print(f"[{current:03d}/{len(source_assets):03d}] refresh {virtual_path}", flush=True)
            started = time.perf_counter()
            entry = next(iter(entries_by_path.get(_archive_key(virtual_path), ())), None)
            if entry is None:
                raise FileNotFoundError(f"Visual-audit PAC is missing: {virtual_path}")
            mesh = MeshService().load_mesh_bytes(_read_archive_payload(entry), entry.path)
            _hydrate_real_archive_mesh_materials(mesh, entry, entries_by_path, entries_by_basename)

            archive_source = Path(str(source_asset["archive_package_dir"])).resolve()
            archive_target = archive_root / archive_source.name
            _link_or_copy_tree(archive_source, archive_target)
            archive_package_stability = stabilize_visual_audit_archive_package(archive_target)
            archive_manifest = read_isolated_d3d11_preview_manifest(archive_target)
            apply_dotnet_native_material_batch_bindings(
                mesh,
                archive_manifest.get("batches", ()),
            )
            package = build_mesh_dotnet_experiment_package(
                mesh,
                output_root=dotnet_root,
                comparison_mode="replacement_only",
                interaction_mode="placement",
                scene_session_id=asset_id,
            )
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            runtime_assets.append(
                {
                    "id": asset_id,
                    "virtual_path": virtual_path,
                    "archive_package_dir": str(archive_target),
                    "dotnet_package_dir": str(package.package_dir),
                    "views": [dict(value) for value in tuple(source_asset.get("views", ()) or ())],
                    "run_id": run_id,
                    "archive_package_stability": archive_package_stability,
                }
            )
            timings.append({"id": asset_id, "refresh_ms": elapsed_ms})
            _atomic_write_json(
                runtime_root / "preparation-checkpoint.json",
                {
                    "schema": "cdmw_mesh_visual_audit_dotnet_refresh_checkpoint_v1",
                    "run_id": run_id,
                    "source_evidence_root": str(source_root),
                    "temporary_root": str(temporary_root),
                    "requested_asset_count": len(source_assets),
                    "prepared_asset_count": len(runtime_assets),
                    "runtime_assets": runtime_assets,
                    "timings": timings,
                    "updated_unix_seconds": time.time(),
                },
            )

    corpus = json.loads(json.dumps(source_corpus))
    corpus["run_id"] = run_id
    corpus["dotnet_refresh"] = {
        "schema": "cdmw_mesh_visual_audit_dotnet_refresh_v1",
        "source_evidence_root": str(source_root),
        "source_run_id": str(source_state.get("run_id", "") or ""),
        "archive_packages_reused": True,
        "archive_packages_rebased": not args.reuse_dotnet_packages,
        "dotnet_packages_rebuilt": not args.reuse_dotnet_packages,
        "dotnet_packages_reused": args.reuse_dotnet_packages,
        "asset_count": len(runtime_assets),
    }
    package_state = {
        "schema": "cdmw_mesh_visual_audit_package_state_v1",
        "run_id": run_id,
        "evidence_root": str(output_root),
        "temporary_root": str(temporary_root),
        "corpus_sha256": _payload_sha256(corpus),
        "asset_ids": [str(row["id"]) for row in runtime_assets],
        "runtime_assets": runtime_assets,
        "archive_fingerprint_paths": [str(path) for path in fingerprint_paths],
    }
    before = _archive_content_fingerprints(fingerprint_paths)
    _atomic_write_json(output_root / "corpus.json", corpus)
    _atomic_write_json(runtime_root / "package-state.json", package_state)
    _atomic_write_json(runtime_root / "archive-fingerprints-before.json", before)
    _atomic_write_json(
        runtime_root / "dotnet-refresh.json",
        {
            **dict(corpus["dotnet_refresh"]),
            "run_id": run_id,
            "temporary_root": str(temporary_root),
            "timings": timings,
            "archive_fingerprints_match_source": True,
        },
    )
    print(
        "Prepared refreshed state. Capture with:\n"
        f"  .\\.venv\\Scripts\\python.exe tools\\mesh_editor_visual_audit.py "
        f"--phase capture --game-root \"{game_root}\" --output \"{output_root}\"",
        flush=True,
    )
    return 0


def _validate_roots(
    parser: argparse.ArgumentParser,
    *,
    game_root: Path,
    source_root: Path,
    output_root: Path,
) -> None:
    if source_root == output_root:
        parser.error("Refresh output must differ from the source evidence root.")
    if source_root.is_relative_to(game_root) or output_root.is_relative_to(game_root):
        parser.error("Visual-audit evidence roots must be outside the game root.")
    if not source_root.is_dir():
        parser.error("Source visual-audit evidence root is missing.")
    if output_root.exists():
        parser.error("Refresh output already exists; choose a new evidence root.")


def _matching_source_assets(
    corpus: Mapping[str, object],
    package_state: Mapping[str, object],
) -> tuple[dict[str, object], ...]:
    corpus_rows = [
        row for row in tuple(corpus.get("assets", ()) or ()) if isinstance(row, Mapping)
    ]
    runtime_rows = [
        row
        for row in tuple(package_state.get("runtime_assets", ()) or ())
        if isinstance(row, Mapping)
    ]
    if len(corpus_rows) != len(runtime_rows):
        raise ValueError("Source corpus and runtime package counts do not match.")
    result: list[dict[str, object]] = []
    for corpus_row, runtime_row in zip(corpus_rows, runtime_rows):
        asset_id = str(corpus_row.get("asset_id", "") or "")
        virtual_path = str(corpus_row.get("virtual_path", "") or "")
        if asset_id != str(runtime_row.get("id", "") or ""):
            raise ValueError("Source corpus and runtime asset IDs do not match.")
        if _archive_key(virtual_path) != _archive_key(str(runtime_row.get("virtual_path", "") or "")):
            raise ValueError(f"Source virtual path mismatch for {asset_id}.")
        result.append(dict(runtime_row))
    return tuple(result)


def _reused_runtime_assets(
    source_assets: Sequence[Mapping[str, object]],
    *,
    run_id: str,
    temporary_root: Path,
) -> tuple[dict[str, object], ...]:
    runtime_assets: list[dict[str, object]] = []
    archive_root = temporary_root / "packages" / "archive-browser"
    dotnet_root = temporary_root / "packages" / "mesh-editor"
    for source_asset in source_assets:
        asset_id = str(source_asset.get("id", "") or "")
        archive_package = Path(
            str(source_asset.get("archive_package_dir", "") or "")
        ).resolve()
        dotnet_package = Path(
            str(source_asset.get("dotnet_package_dir", "") or "")
        ).resolve()
        if not (archive_package / "manifest.json").is_file():
            raise ValueError(
                f"Source Archive Browser package is incomplete for {asset_id}: {archive_package}"
            )
        required_dotnet_files = (
            "dotnet_scene.json",
            "net_materials.json",
            "scene.obj",
        )
        missing = [
            name for name in required_dotnet_files if not (dotnet_package / name).is_file()
        ]
        if missing:
            raise ValueError(
                f"Source .NET package is incomplete for {asset_id}: missing={missing}"
            )
        archive_target = archive_root / archive_package.name
        dotnet_target = dotnet_root / dotnet_package.name
        _link_or_copy_tree(archive_package, archive_target)
        _link_or_copy_tree(dotnet_package, dotnet_target)
        runtime_assets.append(
            {
                "id": asset_id,
                "virtual_path": str(source_asset.get("virtual_path", "") or ""),
                "archive_package_dir": str(archive_target),
                "dotnet_package_dir": str(dotnet_target),
                "views": [
                    dict(value)
                    for value in tuple(source_asset.get("views", ()) or ())
                    if isinstance(value, Mapping)
                ],
                "run_id": run_id,
                "archive_package_stability": dict(
                    source_asset.get("archive_package_stability", {}) or {}
                ),
                "package_reuse": "renderer_only_recapture",
            }
        )
    return tuple(runtime_assets)


def _validated_fingerprint_paths(
    source_root: Path,
    package_state: Mapping[str, object],
    *,
    game_root: Path,
) -> tuple[Path, ...]:
    integrity_path = source_root / "runtime" / "integrity.json"
    if not integrity_path.is_file() or _read_json(integrity_path).get("ok") is not True:
        raise ValueError("Source visual audit is not a completed integrity-passing run.")
    paths = tuple(
        Path(str(value)).resolve()
        for value in tuple(package_state.get("archive_fingerprint_paths", ()) or ())
    )
    if not paths or any(not path.is_file() or not path.is_relative_to(game_root) for path in paths):
        raise ValueError("Source archive fingerprint paths are missing or outside the game root.")
    expected = _read_json(source_root / "runtime" / "archive-fingerprints-before.json")
    after_path = source_root / "runtime" / "archive-fingerprints-after.json"
    if not after_path.is_file() or _read_json(after_path) != expected:
        raise ValueError("Source visual audit recorded changed archive fingerprints.")
    if _archive_content_fingerprints(paths) != expected:
        raise ValueError("Current game archive fingerprints differ from the source audit.")
    return paths


def _link_or_copy_tree(source: Path, target: Path) -> None:
    source = source.resolve()
    if not source.is_dir():
        raise ValueError(f"Visual-audit package is missing: {source}")
    if target.exists():
        raise FileExistsError(target)

    def link_or_copy(source_file: str, target_file: str) -> str:
        try:
            os.link(source_file, target_file)
        except OSError:
            shutil.copy2(source_file, target_file)
        return target_file

    shutil.copytree(source, target, copy_function=link_or_copy)


if __name__ == "__main__":
    raise SystemExit(main())
