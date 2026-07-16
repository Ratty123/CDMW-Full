from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from uuid import uuid4
from collections.abc import Mapping, Sequence
from pathlib import Path

from tools.mesh_harness.archive_provenance import _archive_content_fingerprints
from tools.mesh_harness.visual_audit_capture import (
    run_archive_browser_capture_batch,
    run_dotnet_capture_batch,
)
from tools.mesh_harness.visual_audit_corpus import (
    VisualAuditAssetSpec,
    default_visual_audit_specs,
    prepare_visual_audit_corpus,
)
from tools.mesh_harness.visual_audit_integrity import _capture_integrity
from tools.mesh_harness.visual_audit_report import build_visual_audit_composites


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture matched multi-angle real-PAC Archive Browser and .NET/Vortice evidence."
    )
    parser.add_argument("--game-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--phase", choices=("all", "prepare", "capture"), default="all")
    parser.add_argument("--resume-prepare", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--native-timeout", type=float, default=45.0)
    parser.add_argument("--dotnet-timeout", type=float, default=900.0)
    parser.add_argument("--dotnet-assembly", type=Path)
    return parser


def _initialize_evidence_roots(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
) -> tuple[Path, Path, Path]:
    game_root = args.game_root.resolve()
    evidence_root = args.output.resolve()
    if evidence_root.is_relative_to(game_root):
        parser.error("Evidence output must be outside the game root.")
    evidence_root.mkdir(parents=True, exist_ok=True)
    for path in (
        evidence_root / "final",
        evidence_root / "comparisons",
        evidence_root / "runtime",
    ):
        path.mkdir(parents=True, exist_ok=True)
    return game_root, evidence_root, evidence_root / "runtime"


def _dotnet_assembly_path(args: argparse.Namespace) -> Path:
    assembly_path = args.dotnet_assembly or (
        Path(__file__).resolve().parents[1]
        / "dotnet_mesh_editor_experiment"
        / "bin"
        / "Release"
        / "net8.0-windows"
        / "cdmw-mesh-dotnet-editor.dll"
    )
    if assembly_path.suffix.lower() != ".dll":
        raise ValueError(
            "--dotnet-assembly must point to cdmw-mesh-dotnet-editor.dll; "
            "the visual-audit runner invokes it through dotnet."
        )
    return assembly_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = _argument_parser()
    args = parser.parse_args(argv)
    game_root, evidence_root, runtime_root = _initialize_evidence_roots(args, parser)
    if args.resume_prepare and args.phase == "capture":
        parser.error("--resume-prepare requires the prepare or all phase.")
    final_root = evidence_root / "final"
    package_state_path = runtime_root / "package-state.json"
    corpus_path = evidence_root / "corpus.json"
    package_state: dict[str, object] = {}
    run_id = ""
    temporary_root = Path()

    if args.phase in {"all", "prepare"}:
        package_state, run_id, temporary_root = _prepare_visual_audit_run(
            args,
            parser,
            game_root=game_root,
            evidence_root=evidence_root,
            runtime_root=runtime_root,
        )
        if args.phase == "prepare":
            _write_commands(evidence_root, args, temporary_root)
            return 0
    else:
        package_state = _read_json(package_state_path)
        run_id = str(package_state.get("run_id", "") or "")
        temporary_root = Path(str(package_state.get("temporary_root", "") or "")).resolve()

    corpus = _read_json(corpus_path)
    if not package_state:
        package_state = _read_json(package_state_path)
    try:
        _validate_prepared_state(
            corpus,
            package_state,
            evidence_root=evidence_root,
            game_root=game_root,
        )
    except ValueError as exc:
        parser.error(str(exc))
    run_id = str(package_state["run_id"])
    temporary_root = Path(str(package_state["temporary_root"])).resolve()
    runtime_assets = [
        dict(row)
        for row in tuple(package_state.get("runtime_assets", ()) or ())
        if isinstance(row, Mapping)
    ]
    if not runtime_assets:
        parser.error("Capture phase requires a prepared runtime/package-state.json.")

    print("Capturing Archive Browser views in one resident native renderer process...", flush=True)
    archive_report = run_archive_browser_capture_batch(
        runtime_assets,
        temporary_root / "candidates" / "archive-browser",
        run_id=run_id,
        timeout_seconds=max(5.0, args.native_timeout),
        progress=lambda current, total, path: print(
            f"[{current:03d}/{total:03d}] archive capture {path}", flush=True
        ),
    )
    _atomic_write_json(runtime_root / "archive-browser-capture.json", archive_report)

    try:
        assembly_path = _dotnet_assembly_path(args)
    except ValueError as exc:
        parser.error(str(exc))
    if not assembly_path.is_file():
        parser.error(
            "The Release .NET renderer is not built. Run: "
            "dotnet build tools\\dotnet_mesh_editor_experiment\\Cdmw.MeshEditorExperiment.csproj -c Release"
        )
    print("Capturing Mesh Editor views in one resident .NET/Vortice batch process...", flush=True)
    dotnet_report = run_dotnet_capture_batch(
        runtime_assets,
        temporary_root / "candidates" / "mesh-editor",
        runtime_root,
        run_id=run_id,
        assembly_path=assembly_path,
        timeout_seconds=max(30.0, args.dotnet_timeout),
    )
    _atomic_write_json(runtime_root / "dotnet-capture.json", dotnet_report)
    composite_rows = build_visual_audit_composites(
        corpus,
        archive_report,
        dotnet_report,
        evidence_root,
        final_root,
    )
    _atomic_write_json(runtime_root / "composites.json", {"assets": composite_rows})
    fingerprint_paths = [Path(str(value)) for value in package_state.get("archive_fingerprint_paths", ())]
    after = _archive_content_fingerprints(fingerprint_paths)
    before = _read_json(runtime_root / "archive-fingerprints-before.json")
    unchanged = before == after and bool(before)
    _atomic_write_json(runtime_root / "archive-fingerprints-after.json", after)
    _write_draft_review(evidence_root, corpus, composite_rows, archive_report, dotnet_report, unchanged)
    _write_commands(evidence_root, args, temporary_root)
    expected_ids = [
        str(row.get("asset_id", ""))
        for row in tuple(corpus.get("assets", ()) or ())
        if isinstance(row, Mapping)
    ]
    integrity = _capture_integrity(
        run_id=run_id,
        expected_ids=expected_ids,
        archive_report=archive_report,
        dotnet_report=dotnet_report,
        composite_rows=composite_rows,
    )
    _atomic_write_json(runtime_root / "integrity.json", integrity)
    ok = (
        archive_report.get("ok") is True
        and dotnet_report.get("ok") is True
        and unchanged
        and integrity["ok"] is True
    )
    return 0 if ok else 1


def _prepare_visual_audit_run(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    *,
    game_root: Path,
    evidence_root: Path,
    runtime_root: Path,
) -> tuple[dict[str, object], str, Path]:
    specs = _load_specs(args.manifest) if args.manifest else default_visual_audit_specs()
    if args.limit > 0:
        specs = specs[: max(1, args.limit)]
    resume_checkpoint: Mapping[str, object] | None = None
    if args.resume_prepare:
        if args.limit > 0:
            parser.error("--resume-prepare cannot be combined with --limit.")
        try:
            run_id, temporary_root, resume_checkpoint = _load_preparation_resume(
                runtime_root,
                game_root=game_root,
            )
        except ValueError as exc:
            parser.error(str(exc))
    else:
        run_id = uuid4().hex
        temporary_root = _visual_audit_temporary_root(evidence_root, run_id)
    temporary_root.mkdir(parents=True, exist_ok=True)
    print(f"Preparing {len(specs)} real PAC assets through production preview paths...", flush=True)
    prepared = prepare_visual_audit_corpus(
        game_root,
        temporary_root,
        specs,
        progress=lambda current, total, path: print(
            f"[{current:03d}/{total:03d}] prepare {path}", flush=True
        ),
        checkpoint=lambda payload: _write_preparation_checkpoint(
            runtime_root,
            run_id=run_id,
            temporary_root=temporary_root,
            payload=payload,
        ),
        allow_partial=bool(args.limit > 0),
        resume_checkpoint=resume_checkpoint,
    )
    prepared["run_id"] = run_id
    runtime_assets = prepared.pop("runtime_assets")
    for row in runtime_assets:
        row["run_id"] = run_id
    archive_fingerprint_paths = prepared.pop("archive_fingerprint_paths")
    archive_fingerprints = prepared.pop("archive_fingerprints")
    package_state = {
        "schema": "cdmw_mesh_visual_audit_package_state_v1",
        "run_id": run_id,
        "evidence_root": str(evidence_root),
        "temporary_root": str(temporary_root),
        "corpus_sha256": _payload_sha256(prepared),
        "asset_ids": [str(row["id"]) for row in runtime_assets],
        "runtime_assets": runtime_assets,
        "archive_fingerprint_paths": archive_fingerprint_paths,
    }
    _atomic_write_json(evidence_root / "corpus.json", prepared)
    _atomic_write_json(runtime_root / "package-state.json", package_state)
    _atomic_write_json(runtime_root / "archive-fingerprints-before.json", archive_fingerprints)
    return package_state, run_id, temporary_root


def _validate_prepared_state(
    corpus: Mapping[str, object],
    package_state: Mapping[str, object],
    *,
    evidence_root: Path,
    game_root: Path,
) -> None:
    run_id = str(package_state.get("run_id", "") or "")
    if len(run_id) != 32 or any(character not in "0123456789abcdef" for character in run_id):
        raise ValueError("Prepared package state has no valid run ID.")
    if str(corpus.get("run_id", "")) != run_id:
        raise ValueError("Prepared corpus and package state run IDs do not match.")
    if Path(str(package_state.get("evidence_root", "") or "")).resolve() != evidence_root:
        raise ValueError("Prepared package state belongs to a different evidence root.")
    temporary_root = Path(str(package_state.get("temporary_root", "") or "")).resolve()
    if not temporary_root.is_dir() or temporary_root.is_relative_to(game_root):
        raise ValueError("Prepared temporary package root is missing or inside the game root.")
    expected_temp_parent = (Path(tempfile.gettempdir()) / "cdmw-mesh-editor-visual-audit").resolve()
    if not temporary_root.is_relative_to(expected_temp_parent):
        raise ValueError("Prepared temporary package root is outside the visual-audit temp owner.")
    if str(package_state.get("corpus_sha256", "")) != _payload_sha256(corpus):
        raise ValueError("Prepared corpus fingerprint does not match package state.")
    corpus_ids = [
        str(row.get("asset_id", ""))
        for row in tuple(corpus.get("assets", ()) or ())
        if isinstance(row, Mapping)
    ]
    state_ids = [str(value) for value in tuple(package_state.get("asset_ids", ()) or ())]
    runtime_assets = [
        row
        for row in tuple(package_state.get("runtime_assets", ()) or ())
        if isinstance(row, Mapping)
    ]
    runtime_ids = [str(row.get("id", "")) for row in runtime_assets]
    if not corpus_ids or corpus_ids != state_ids or corpus_ids != runtime_ids:
        raise ValueError("Prepared corpus and runtime asset order do not match.")
    for row in runtime_assets:
        if str(row.get("run_id", "")) != run_id:
            raise ValueError("Prepared runtime asset has a mismatched run ID.")
        for key in ("archive_package_dir", "dotnet_package_dir"):
            package_dir = Path(str(row.get(key, "") or "")).resolve()
            if not package_dir.is_dir() or not package_dir.is_relative_to(temporary_root):
                raise ValueError(f"Prepared runtime asset has an invalid {key}.")


def _write_preparation_checkpoint(
    runtime_root: Path,
    *,
    run_id: str,
    temporary_root: Path,
    payload: Mapping[str, object],
) -> None:
    checkpoint = {
        **dict(payload),
        "run_id": run_id,
        "temporary_root": str(temporary_root),
        "updated_unix_seconds": time.time(),
    }
    _atomic_write_json(runtime_root / "preparation-checkpoint.json", checkpoint)


def _load_preparation_resume(
    runtime_root: Path,
    *,
    game_root: Path,
) -> tuple[str, Path, dict[str, object]]:
    checkpoint_path = runtime_root / "preparation-checkpoint.json"
    if not checkpoint_path.is_file():
        raise ValueError("No visual-audit preparation checkpoint exists to resume.")
    checkpoint = _read_json(checkpoint_path)
    run_id = str(checkpoint.get("run_id", "") or "")
    if len(run_id) != 32 or any(character not in "0123456789abcdef" for character in run_id):
        raise ValueError("Visual-audit preparation checkpoint has no valid run ID.")
    temporary_root = Path(str(checkpoint.get("temporary_root", "") or "")).resolve()
    expected_temp_parent = (Path(tempfile.gettempdir()) / "cdmw-mesh-editor-visual-audit").resolve()
    if (
        not temporary_root.is_dir()
        or temporary_root.is_relative_to(game_root)
        or not temporary_root.is_relative_to(expected_temp_parent)
    ):
        raise ValueError("Visual-audit preparation checkpoint has an invalid temporary root.")
    runtime_assets = tuple(checkpoint.get("runtime_assets", ()) or ())
    if not runtime_assets:
        raise ValueError("Visual-audit preparation checkpoint contains no completed assets.")
    for row in runtime_assets:
        if not isinstance(row, Mapping):
            raise ValueError("Visual-audit preparation checkpoint contains an invalid runtime asset.")
        for key in ("archive_package_dir", "dotnet_package_dir"):
            package_dir = Path(str(row.get(key, "") or "")).resolve()
            if not package_dir.is_dir() or not package_dir.is_relative_to(temporary_root):
                raise ValueError(f"Visual-audit preparation checkpoint has an invalid {key}.")
    return run_id, temporary_root, checkpoint


def _payload_sha256(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_specs(path: Path) -> tuple[VisualAuditAssetSpec, ...]:
    payload = _read_json(path)
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise ValueError("Visual-audit corpus manifest must contain an assets array.")
    specs: list[VisualAuditAssetSpec] = []
    for index, row in enumerate(assets, 1):
        if not isinstance(row, Mapping):
            raise ValueError(f"Visual-audit manifest asset {index} is not an object.")
        category = str(row.get("model_category", "") or "model")
        virtual_path = str(row.get("virtual_path", "") or "")
        asset_id = str(row.get("asset_id", "") or f"{index:03d}-{category}-{Path(virtual_path).stem}")
        specs.append(
            VisualAuditAssetSpec(
                index=int(row.get("index", index) or index),
                asset_id=asset_id,
                virtual_path=virtual_path,
                model_category=category,
                coverage_tags=tuple(str(value) for value in tuple(row.get("coverage_tags", ()) or ())),
                selection_reason=str(row.get("selection_reason", "") or "User-supplied corpus manifest."),
            )
        )
    result = tuple(specs)
    _validate_manifest_constraints(payload, result)
    return result


def _validate_manifest_constraints(
    payload: Mapping[str, object],
    specs: Sequence[VisualAuditAssetSpec],
) -> None:
    raw_minimum = payload.get("minimum_asset_count", 0)
    try:
        minimum = int(raw_minimum or 0)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Visual-audit minimum_asset_count must be an integer.") from exc
    if minimum < 0:
        raise ValueError("Visual-audit minimum_asset_count cannot be negative.")
    if len(specs) < minimum:
        raise ValueError(
            f"Visual-audit manifest requires at least {minimum} assets; found {len(specs)}."
        )

    excluded = {
        str(value or "").replace("\\", "/").strip().casefold()
        for value in tuple(payload.get("excluded_virtual_paths", ()) or ())
        if str(value or "").strip()
    }
    overlap = sorted(
        spec.virtual_path
        for spec in specs
        if spec.virtual_path.replace("\\", "/").strip().casefold() in excluded
    )
    if overlap:
        raise ValueError(f"Visual-audit manifest reuses excluded PAC paths: {overlap}")

    raw_required = payload.get("required_coverage", {})
    if not isinstance(raw_required, Mapping):
        raise ValueError("Visual-audit required_coverage must be an object.")
    short: dict[str, tuple[int, int]] = {}
    for raw_tag, raw_count in raw_required.items():
        tag = str(raw_tag or "").strip()
        try:
            required_count = int(raw_count)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(
                f"Visual-audit coverage requirement for {tag or '<empty>'} must be an integer."
            ) from exc
        if not tag or required_count < 0:
            raise ValueError("Visual-audit coverage tags must be non-empty with non-negative counts.")
        actual_count = sum(tag in spec.coverage_tags for spec in specs)
        if actual_count < required_count:
            short[tag] = (actual_count, required_count)
    if short:
        raise ValueError(f"Visual-audit manifest coverage is incomplete: {short}")


def _write_draft_review(
    evidence_root: Path,
    corpus: Mapping[str, object],
    composites: Sequence[Mapping[str, object]],
    archive_report: Mapping[str, object],
    dotnet_report: Mapping[str, object],
    archives_unchanged: bool,
) -> None:
    composite_map = {str(row.get("id", "")): row for row in composites}
    lines = [
        "# Mesh Editor Visual Material-Parity Audit",
        "",
        "Status: captures complete; visual verdicts pending direct image inspection.",
        "",
        f"- Run ID: `{corpus.get('run_id', '')}`",
        f"- Corpus assets: {int(corpus.get('asset_count', 0) or 0)}",
        f"- Archive Browser batch: {'PASS' if archive_report.get('ok') else 'FAIL'}",
        f"- Mesh Editor .NET/Vortice batch: {'PASS' if dotnet_report.get('ok') else 'FAIL'}",
        f"- Game archive fingerprints unchanged: {archives_unchanged}",
        "",
    ]
    for asset in tuple(corpus.get("assets", ()) or ()):
        if not isinstance(asset, Mapping):
            continue
        asset_id = str(asset.get("asset_id", "") or "")
        composite = composite_map.get(asset_id, {})
        lines.extend(
            [
                f"## {int(asset.get('index', 0) or 0):03d} - {asset_id}",
                "",
                f"- PAC virtual path: `{asset.get('virtual_path', '')}`",
                f"- Archive provenance: `{asset.get('archive_provenance', {})}`",
                f"- Model category: `{asset.get('model_category', '')}`",
                f"- Material families: `{', '.join(asset.get('expected_material_families', ()) or ())}`",
                f"- Selected camera angle: `{composite.get('selected_camera_angle', '')}`",
                "- Archive Browser verdict: PENDING",
                "- Mesh Editor verdict: PENDING",
                "- Overall verdict: PENDING",
                "- Defect categories: `[]`",
                "- Visual observations: Pending direct multi-angle inspection.",
                "- Likely cause: Pending.",
                "- Confidence: Pending.",
                "- Code changes made: None assigned yet.",
                "- Targeted validation performed: paired six-angle direct renderer capture.",
                "- Remaining uncertainty: Visual adjudication pending.",
                f"- Primary comparison: `{composite.get('primary_final_png', '')}`",
                f"- Multi-angle contact sheet: `{composite.get('contact_sheet', '')}`",
                "",
            ]
        )
    (evidence_root / "review.md").write_text("\n".join(lines), encoding="utf-8")
    _atomic_write_json(
        evidence_root / "summary.json",
        {
            "schema": "cdmw_mesh_visual_audit_summary_v1",
            "run_id": str(corpus.get("run_id", "") or ""),
            "status": "pending_visual_review",
            "asset_count": int(corpus.get("asset_count", 0) or 0),
            "pass_count": 0,
            "concern_count": 0,
            "fail_count": 0,
            "unreviewed_count": int(corpus.get("asset_count", 0) or 0),
            "archive_browser_batch_ok": bool(archive_report.get("ok")),
            "dotnet_batch_ok": bool(dotnet_report.get("ok")),
            "archive_sources_unchanged": bool(archives_unchanged),
            "assets": [dict(row) for row in composites],
        },
    )


def _write_commands(evidence_root: Path, args: argparse.Namespace, temporary_root: Path) -> None:
    command = (
        ".\\.venv\\Scripts\\python.exe tools\\mesh_editor_visual_audit.py "
        f'--game-root "{args.game_root.resolve()}" --output "{evidence_root}"'
    )
    lines = [
        "# Rerun commands",
        "",
        "Build the authoritative .NET/Vortice renderer once:",
        "",
        "```powershell",
        "dotnet build tools\\dotnet_mesh_editor_experiment\\Cdmw.MeshEditorExperiment.csproj -c Release",
        "```",
        "",
        "Run the complete corpus:",
        "",
        "```powershell",
        command,
        "```",
        "",
        "Run one PAC through the same preparation and paired capture path:",
        "",
        "```powershell",
        command + " --limit 1",
        "```",
        "",
        "Finalize directly inspected verdicts and selected angles:",
        "",
        "```powershell",
        ".\\.venv\\Scripts\\python.exe tools\\mesh_editor_visual_audit_review.py "
        f'--evidence "{evidence_root}" --verdicts "{evidence_root / "verdicts.json"}"',
        "```",
        "",
        f"Temporary packages and camera candidates: `{temporary_root}`",
        "",
        "The game root is read-only. The tool rejects evidence or temporary output beneath it.",
    ]
    (evidence_root / "commands.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _visual_audit_temporary_root(evidence_root: Path, run_id: str) -> Path:
    evidence_key = hashlib.sha256(str(Path(evidence_root).resolve()).casefold().encode("utf-8")).hexdigest()[:12]
    return (
        Path(tempfile.gettempdir())
        / "cdmw-mesh-editor-visual-audit"
        / f"{evidence_key}-{str(run_id).strip()}"
    ).resolve()


def _atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


__all__ = ["main"]
