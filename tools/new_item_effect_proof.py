"""Explicit real-archive proof workflow for New Item visual effects.

``report`` and ``record`` only write evidence below the chosen system-temp output.
``install`` and ``remove`` require category-specific confirmation tokens and route all
game changes through the existing overlay and archive-mutation services.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cdmw.core.prefab_binary import decode_prefab_binary  # noqa: E402
from cdmw.core.prefab_component_graft import encode_transform  # noqa: E402
from cdmw.modding.mesh_parser import parse_pac  # noqa: E402
from cdmw.domain.new_item.spec import NewItemSpec  # noqa: E402
from cdmw.services.archive_mutation_service import ArchiveMutationService  # noqa: E402
from cdmw.services.archive_overlay_install import (  # noqa: E402
    is_cdmw_overlay_directory,
    restore_last_overlay_install,
)
from cdmw.services.effect_preview_model import preview_effect_from_snapshot  # noqa: E402
from cdmw.services.new_item_effect_targets import EffectTargetCompatibility  # noqa: E402
from cdmw.services.new_item_planning import NewItemPlan  # noqa: E402
from cdmw.services.new_item_service import NewItemService, game_is_running  # noqa: E402
from cdmw.services.new_item_snapshot import EFFECT_DONOR_PREFAB, NewItemSnapshot  # noqa: E402
from cdmw.workers.new_item_workers import list_archive_entries  # noqa: E402
from tools.placement_studio.corpus import game_root as default_game_root  # noqa: E402

EFFECT_STEM = "fx_cc_firesweapon_a__fire1"
EFFECT_REFERENCE = f"{EFFECT_STEM}.level.effect"
EFFECT_PATH = f"effect/binary__/releasebin/{EFFECT_STEM}.pae"
CATEGORIES = ("weapon", "armour", "accessory")

ARMOUR_TYPES = frozenset({"Cloak", "Foot", "Hand", "Helm", "Lowerbody", "Shoulder", "Underwear", "Upperbody"})
ACCESSORY_TYPES = frozenset({"BackPack", "Bracelet", "Earring", "Glass", "Mask", "Necklace", "Ring", "SprayBag"})


@dataclass(frozen=True, slots=True)
class Representative:
    category: str
    template_key: int
    internal_name: str
    equip_type: str
    compatibility: EffectTargetCompatibility


@dataclass(frozen=True, slots=True)
class PreparedCase:
    representative: Representative
    plan: NewItemPlan
    anchor: str
    item_bounds: tuple[tuple[float, float, float], tuple[float, float, float]]
    effect_bounds: tuple[tuple[float, float, float], tuple[float, float, float]]
    validated_prefabs: tuple[str, ...]


def _log(message: str) -> None:
    print(str(message), flush=True)


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, raw = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(raw)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _fingerprints(paths: Iterable[Path]) -> list[dict[str, object]]:
    rows = []
    for path in sorted({Path(item).resolve() for item in paths}, key=lambda item: str(item).casefold()):
        exists = path.is_file()
        rows.append({
            "path": str(path),
            "exists": exists,
            "size": path.stat().st_size if exists else 0,
            "sha256": _sha256(path) if exists else "",
        })
    return rows


def _refingerprint(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    return _fingerprints(Path(str(row["path"])) for row in rows)


def _family_kind(equip_type: str, paths: Sequence[str]) -> str:
    if any("/weapon/" in str(path).replace("\\", "/").casefold() for path in paths):
        return "weapon"
    if equip_type in ACCESSORY_TYPES:
        return "accessory"
    if equip_type in ARMOUR_TYPES:
        return "armour"
    return ""


def _candidate_rows(snapshot: NewItemSnapshot, category: str) -> list[tuple[str, str, int]]:
    rows: list[tuple[str, str, int]] = []
    for key, row in snapshot.rows.items():
        equip_type = snapshot.equip_type_name(row)
        try:
            family = snapshot.family(key)
        except Exception:  # noqa: BLE001 - an unreadable family simply cannot be a representative
            continue
        paths = tuple(item.path for item in family.files if item.exists)
        if _family_kind(equip_type, paths) == category:
            rows.append((equip_type, row.string_key, int(key)))
    return sorted(rows, key=lambda item: (item[0].casefold(), item[1].casefold(), item[2]))


def _compatibility(service: NewItemService, snapshot: NewItemSnapshot, key: int) -> EffectTargetCompatibility:
    return service.inspect_effect_targets(
        NewItemSpec(template_key=key, internal_name=f"CDMW_EffectProbe_{key}", effect=EFFECT_REFERENCE),
        snapshot,
    )


def select_representatives(snapshot: NewItemSnapshot, service: NewItemService) -> tuple[Representative, ...]:
    selected = []
    for category in CATEGORIES:
        candidates = _candidate_rows(snapshot, category)
        if category == "weapon":
            bekker = [item for item in candidates if item[1] == "Bekker_OneHandSword"]
            if bekker:
                candidates = bekker
        failures = []
        chosen: Optional[Representative] = None
        for equip_type, internal_name, key in candidates:
            compatibility = _compatibility(service, snapshot, key)
            if compatibility.supported:
                chosen = Representative(category, key, internal_name, equip_type, compatibility)
                break
            failures.append(f"{equip_type}/{internal_name}: {compatibility.message}")
            if category == "weapon" and internal_name == "Bekker_OneHandSword":
                break
        if chosen is None:
            detail = "; ".join(failures[:5]) or "no candidate equipment rows"
            raise RuntimeError(f"No compatible {category} representative: {detail}")
        selected.append(chosen)
    return tuple(selected)


def _template_mesh(snapshot: NewItemSnapshot, representative: Representative):
    family = snapshot.family(representative.template_key)
    stem = family.model_stem.casefold()
    entries = [item for item in family.files_for("pac") if item.exists]
    primary = next((item for item in entries if item.path.casefold().endswith(f"/{stem}.pac")), None)
    primary = primary or (entries[0] if entries else None)
    if primary is None:
        raise RuntimeError(f"{representative.internal_name} has no model PAC to fit against")
    return parse_pac(snapshot.payload(primary.path), primary.path)


def _fit_and_center(item_mesh: object, effect_preview: object) -> tuple[float, tuple[float, float, float]]:
    low = tuple(float(value) for value in item_mesh.bbox_min)
    high = tuple(float(value) for value in item_mesh.bbox_max)
    effect_low = tuple(float(value) for value in effect_preview.box_min)
    effect_high = tuple(float(value) for value in effect_preview.box_max)
    item_length = max(high[index] - low[index] for index in range(3))
    effect_length = max(effect_high[index] - effect_low[index] for index in range(3))
    if item_length <= 0 or effect_length <= 0:
        raise RuntimeError("Fit to item needs non-empty item and effect bounds")
    scale = round(max(0.01, min(10.0, item_length / effect_length)), 3)
    centre = tuple(round((low[index] + high[index]) / 2.0, 4) for index in range(3))
    return scale, centre


def prepare_case(snapshot: NewItemSnapshot, service: NewItemService, representative: Representative) -> PreparedCase:
    mesh = _template_mesh(snapshot, representative)
    effect = preview_effect_from_snapshot(snapshot, EFFECT_REFERENCE)
    scale, centre = _fit_and_center(mesh, effect)
    title = representative.category.title()
    spec = NewItemSpec(
        template_key=representative.template_key,
        internal_name=f"CDMW_EffectProof_{title}",
        display_names={"eng": f"CDMW Effect Proof - {title}"},
        descriptions={"eng": f"Temporary {representative.category} visual-effect proof item."},
        effect=EFFECT_REFERENCE,
        effect_scale=scale,
        effect_offset=centre,
    )
    plan = service.plan(spec, snapshot, on_log=_log)
    validated_prefabs = _validate_emitted_prefabs(plan)
    return PreparedCase(
        representative=representative,
        plan=plan,
        anchor="Center",
        item_bounds=(tuple(mesh.bbox_min), tuple(mesh.bbox_max)),
        effect_bounds=(tuple(effect.box_min), tuple(effect.box_max)),
        validated_prefabs=validated_prefabs,
    )


def _validate_emitted_prefabs(plan: NewItemPlan) -> tuple[str, ...]:
    manifest = plan.manifest.get("effect")
    if not isinstance(manifest, Mapping):
        raise RuntimeError("The real effect plan produced no effect manifest")
    paths = tuple(str(path) for path in manifest.get("prefabs", ()))
    additions = {request.path: request.payload_data for request in plan.additions}
    transform = encode_transform(
        scale=(plan.spec.effect_scale,) * 3,
        position=plan.spec.effect_offset,
    )
    validated = []
    for path in paths:
        payload = additions.get(path)
        if payload is None:
            raise RuntimeError(f"The effect manifest names no emitted prefab payload for {path}")
        document = decode_prefab_binary(payload)
        if not document.walk_complete:
            raise RuntimeError(f"The emitted prefab did not decode completely: {path}: {document.walk_note}")
        if "EffectComponent" not in {item.component_type for item in document.objects}:
            raise RuntimeError(f"The emitted prefab has no EffectComponent: {path}")
        if str(manifest.get("path") or "") not in {item.text for item in document.resource_strings()}:
            raise RuntimeError(f"The emitted prefab does not name the planned effect: {path}")
        if transform not in payload:
            raise RuntimeError(f"The emitted prefab does not carry the planned transform: {path}")
        validated.append(path)
    if len(validated) != len(paths) or len(validated) != len(plan.manifest["effect"]["prefabs"]):
        raise RuntimeError("Not every planned effect prefab was decoded and validated")
    return tuple(validated)


def _package_root(plan: NewItemPlan) -> Path:
    if plan.patches:
        return Path(plan.patches[0].entry.pamt_path).resolve().parent.parent
    if plan.additions:
        return Path(plan.additions[0].pamt_path).resolve().parent.parent
    raise RuntimeError("The proof plan names no archive package root")


def _source_archive_paths(snapshot: NewItemSnapshot, case: PreparedCase) -> tuple[Path, ...]:
    paths: set[Path] = set()
    entry_paths = {request.entry.path for request in case.plan.patches}
    entry_paths.update(case.representative.compatibility.target_prefabs)
    entry_paths.update((EFFECT_DONOR_PREFAB, EFFECT_PATH))
    for game_path in entry_paths:
        if not snapshot.has_entry(game_path):
            continue
        entry = snapshot.entry(game_path)
        paths.add(Path(entry.pamt_path).resolve())
        paths.add(Path(entry.paz_file).resolve())
    return tuple(sorted(paths))


def _metadata_paths(case: PreparedCase) -> tuple[Path, ...]:
    root = _package_root(case.plan)
    paths = {root / "meta" / "0.papgt"}
    paths.update(root / write.path for write in case.plan.meta_files)
    return tuple(sorted(paths))


def _public_case(case: PreparedCase) -> dict[str, object]:
    representative = case.representative
    return {
        "category": representative.category,
        "template_key": representative.template_key,
        "template_internal_name": representative.internal_name,
        "equipment_type": representative.equip_type,
        "effect_stem": EFFECT_STEM,
        "effect_reference": EFFECT_REFERENCE,
        "anchor": case.anchor,
        "fit_to_item_scale": case.plan.spec.effect_scale,
        "position": list(case.plan.spec.effect_offset),
        "rotation": list(case.plan.spec.effect_rotation_degrees),
        "item_bounds": [list(case.item_bounds[0]), list(case.item_bounds[1])],
        "effect_bounds": [list(case.effect_bounds[0]), list(case.effect_bounds[1])],
        "compatibility_targets": list(representative.compatibility.target_prefabs),
        "compatibility_errors": list(representative.compatibility.errors),
        "validated_emitted_prefabs": list(case.validated_prefabs),
        "plan_manifest": case.plan.manifest,
        "plan_summary": list(case.plan.summary_lines),
        "plan_warnings": list(case.plan.warnings),
        "plan_paths": list(case.plan.touched_paths),
    }


def _load_cases(game_root: Path) -> tuple[NewItemSnapshot, NewItemService, tuple[PreparedCase, ...]]:
    stop_event = threading.Event()
    entries = list_archive_entries(game_root, _log, stop_event)
    service = NewItemService()
    snapshot = service.build_snapshot(entries, on_log=_log, stop_event=stop_event)
    representatives = select_representatives(snapshot, service)
    return snapshot, service, tuple(prepare_case(snapshot, service, item) for item in representatives)


def _confirmation(action: str, category: str) -> str:
    return f"{action.upper()}-{category.upper()}-EFFECT-PROOF"


def _existing_overlay_state(package_root: Path) -> dict[str, object]:
    root = package_root.resolve()
    receipt = root / ".cdmw" / "last-overlay-install.json"
    owned = [
        str(child.resolve())
        for child in sorted(root.iterdir())
        if child.is_dir() and is_cdmw_overlay_directory(child)
    ]
    return {
        "receipt_path": str(receipt.resolve()) if receipt.is_file() else "",
        "owned_directories": owned,
        "proof_install_blocked": bool(receipt.is_file() or owned),
    }


def _system_temp_output(path: Path) -> Path:
    output = path.expanduser().resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    if output != temp_root and temp_root not in output.parents:
        raise ValueError(f"Proof evidence must stay under the system temp folder: {temp_root}")
    return output


def report(game_root: Path, output: Path) -> Path:
    _snapshot, _service, cases = _load_cases(game_root)
    package_root = _package_root(cases[0].plan)
    target = output / "compatibility_report.json"
    payload = {
        "schema": "cdmw_new_item_effect_proof_v1",
        "created_at": time.time(),
        "mode": "read_only_report",
        "game_root": str(game_root.resolve()),
        "package_root": str(package_root),
        "existing_overlay_state": _existing_overlay_state(package_root),
        "effect": EFFECT_REFERENCE,
        "cases": [_public_case(case) for case in cases],
        "confirmation_tokens": {
            category: {
                "install": _confirmation("install", category),
                "remove": _confirmation("remove", category),
            }
            for category in CATEGORIES
        },
    }
    _atomic_json(target, payload)
    return target


def _case_for(game_root: Path, category: str) -> tuple[NewItemSnapshot, NewItemService, PreparedCase]:
    snapshot, service, cases = _load_cases(game_root)
    return snapshot, service, next(case for case in cases if case.representative.category == category)


def install(game_root: Path, output: Path, category: str, confirmation: str) -> Path:
    expected = _confirmation("install", category)
    if confirmation != expected:
        raise PermissionError(f"Overlay install requires --confirm {expected}")
    snapshot, service, case = _case_for(game_root, category)
    root = _package_root(case.plan)
    overlay_state = _existing_overlay_state(root)
    if overlay_state["proof_install_blocked"]:
        raise RuntimeError("A CDMW overlay or receipt already exists; remove it before starting one proof case")
    source_before = _fingerprints(_source_archive_paths(snapshot, case))
    metadata_before = _fingerprints(_metadata_paths(case))
    mutation_service = ArchiveMutationService()
    _log(
        f"Confirmed {category} proof: {case.representative.internal_name}, "
        f"{len(case.representative.compatibility.target_prefabs)} prefab target(s), "
        f"{len(case.plan.touched_paths)} planned path(s)."
    )
    result = None
    evidence_path = output / f"{category}_evidence.json"
    try:
        result = service.install_overlay(
            case.plan,
            mutation_service=mutation_service,
            confirmed=True,
            on_log=_log,
            game_running=game_is_running,
        )
        source_after = _refingerprint(source_before)
        if source_after != source_before:
            raise RuntimeError("A source archive fingerprint changed during overlay installation")
        payload = {
            "schema": "cdmw_new_item_effect_proof_case_v1",
            "created_at": time.time(),
            "active": True,
            "restored": False,
            "case": _public_case(case),
            "package_root": str(root),
            "source_archives_before": source_before,
            "source_archives_after_install": source_after,
            "metadata_before": metadata_before,
            "metadata_after_install": _refingerprint(metadata_before),
            "overlay": {
                "directory": str(result.directory),
                "receipt_path": str(result.receipt_path or ""),
                "backup_dir": str(result.backup_dir or ""),
                "file_count": result.file_count,
                "payload_bytes": result.payload_bytes,
                "paths": list(result.paths),
            },
            "resident_screenshot": "",
            "in_game_screenshot": "",
            "in_game_observation": "",
        }
        _atomic_json(evidence_path, payload)
    except BaseException as error:
        if result is None or result.receipt_path is None or not result.receipt_path.is_file():
            raise
        try:
            restore_last_overlay_install(
                result.receipt_path,
                confirmed=True,
                restore_backup=lambda path: mutation_service.restore_backup(path, confirmed=True, on_log=_log),
                game_running=game_is_running,
            )
        except Exception as restore_error:
            raise RuntimeError(f"Proof install failed after publication and rollback failed: {restore_error}") from error
        raise
    return evidence_path


def remove(output: Path, category: str, confirmation: str) -> Path:
    expected = _confirmation("remove", category)
    if confirmation != expected:
        raise PermissionError(f"Overlay removal requires --confirm {expected}")
    evidence_path = output / f"{category}_evidence.json"
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    if not payload.get("active"):
        raise RuntimeError(f"The {category} proof overlay is not recorded as active")
    receipt = Path(str(payload["overlay"]["receipt_path"]))
    mutation_service = ArchiveMutationService()
    restore_last_overlay_install(
        receipt,
        confirmed=True,
        restore_backup=lambda path: mutation_service.restore_backup(path, confirmed=True, on_log=_log),
        game_running=game_is_running,
    )
    source_after = _refingerprint(payload["source_archives_before"])
    metadata_after = _refingerprint(payload["metadata_before"])
    payload["active"] = False
    payload["restored"] = True
    payload["restored_at"] = time.time()
    payload["source_archives_after_restore"] = source_after
    payload["metadata_after_restore"] = metadata_after
    errors = []
    if source_after != payload["source_archives_before"]:
        errors.append("A source archive fingerprint differs after overlay removal")
    if metadata_after != payload["metadata_before"]:
        errors.append("Overlay removal did not restore the original metadata fingerprints")
    payload["restore_verification_errors"] = errors
    _atomic_json(evidence_path, payload)
    if errors:
        raise RuntimeError("; ".join(errors))
    return evidence_path


def record(
    output: Path,
    category: str,
    *,
    observation: str = "",
    resident_screenshot: Optional[Path] = None,
    in_game_screenshot: Optional[Path] = None,
) -> Path:
    evidence_path = output / f"{category}_evidence.json"
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    for key, source in (("resident_screenshot", resident_screenshot), ("in_game_screenshot", in_game_screenshot)):
        if source is None:
            continue
        source = source.expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        target = output / f"{category}_{key}{source.suffix.lower() or '.png'}"
        shutil.copy2(source, target)
        payload[key] = str(target.resolve())
    if observation:
        payload["in_game_observation"] = str(observation).strip()
    payload["observation_updated_at"] = time.time()
    _atomic_json(evidence_path, payload)
    return evidence_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("report", "install", "remove", "record"))
    parser.add_argument("--game-root", type=Path, default=default_game_root())
    parser.add_argument("--output", type=Path, default=Path(tempfile.gettempdir()) / "cdmw-new-item-effect-proof")
    parser.add_argument("--category", choices=CATEGORIES)
    parser.add_argument("--confirm", default="")
    parser.add_argument("--observation", default="")
    parser.add_argument("--resident-screenshot", type=Path)
    parser.add_argument("--in-game-screenshot", type=Path)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    game_root = args.game_root.expanduser().resolve()
    output = _system_temp_output(args.output)
    if args.action == "report":
        path = report(game_root, output)
    else:
        if not args.category:
            raise SystemExit(f"{args.action} requires --category")
        if args.action == "install":
            path = install(game_root, output, args.category, args.confirm)
        elif args.action == "remove":
            path = remove(output, args.category, args.confirm)
        else:
            path = record(
                output,
                args.category,
                observation=args.observation,
                resident_screenshot=args.resident_screenshot,
                in_game_screenshot=args.in_game_screenshot,
            )
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
