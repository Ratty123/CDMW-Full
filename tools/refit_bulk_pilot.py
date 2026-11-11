"""Bulk body-swap pilot: refit one body's armour onto another and package each item, headless.

Stages, all read only against the game:

``fit``
    Every PAC an item owns is fitted onto the driver body (Kliff's nude by default)
    with the Morph & Refit harness (:mod:`tools.refit_reference_harness`): the
    authored-body ``reference`` method when the editor's lookup finds the body the
    PAC was made on, else the driver-only ``bound`` method, as Fit to body does.
    Each fit is scored with the harness's damage metrics (refusal, new inside
    vertices, new skin through cloth, new layer crossings, solid-piece bend) and,
    where the game ships the same piece for the driver's body with the same
    topology (``cd_phw_*`` beside ``cd_phm_*``), per-vertex error against it.
    The fitted LOD 0 positions and normals are written back through the editor's
    exact PAC writer (``build_pac``); garments keep their own skin weights and
    lower LODs keep their authored shape, which is what the writer does today.
    Pieces already made for the driver's body are left as they are.

``package``
    Each item becomes a New Item plan from its own row as the template, each fitted
    PAC the imported model of its prefab/mesh binding (:class:`ModelFiles`,
    materials as shipped; the template's cloth is kept where the planner allows)
    and, with ``--wearer``, its body prefab's tribe/gender selectors replaced by a
    driver-body item's so the driver's character can wear it. The plan is written
    as a .cdmw package; plan time, size and refusals are recorded.

``replan``
    Each written package read back and planned again, as Apply and Send to DMM do.

``summary``
    One row per item from the three stages and the inventory, plus totals.

``corpus``
    The harness's 27-outfit corpus onto ``--driver``, shown in ``--driver-variation``:
    the baseline for the other direction on the same terms.

The archive index includes the ``dlc`` packages, which hold DLC-only armour. Fit rows
are written as they finish, so a long run can be resumed (``--retry-errors`` runs
failed rows again); ``package --keys`` repackages chosen items and keeps the others.
Development evidence, not proof of in-game appearance.

Example::

    python tools/refit_bulk_inventory.py --game-root "<CD>" --body phw --output out/inventory_phw.json
    python tools/refit_bulk_pilot.py fit --game-root "<CD>" --inventory out/inventory_phw.json \\
        --equip Upperbody --output out
    python tools/refit_bulk_pilot.py package --game-root "<CD>" --inventory out/inventory_phw.json \\
        --equip Upperbody --output out --wearer 1004784
    python tools/refit_bulk_pilot.py summary --game-root "<CD>" --inventory out/inventory_phw.json --output out
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
import traceback
from pathlib import Path, PurePosixPath

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np

KLIFF = "character/model/1_pc/1_phm/nude/phm_00_nude_00_0001.pac"


def _items(args) -> list[dict]:
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    keys = {int(key) for key in args.keys.split(",") if key} if getattr(args, "keys", "") else set()
    rows = [row for row in inventory["rows"] if (not args.equip or row["equip_type"] == args.equip)
            and (not keys or row["item_key"] in keys)]
    return rows[: args.limit] if args.limit else rows


def _pac_name(path: str) -> str:
    return PurePosixPath(path).name


def _archive_index(game_root: Path):
    """The harness's archive index plus the DLC packages (``dlc/<name>/<nnnn>/0.pamt``).

    DLC-only armour lives only there; the harness reads the base packages alone.
    """
    from types import SimpleNamespace

    from cdmw.core.archive_format import parse_archive_pamt
    from tools.mesh_harness.real_common import (
        _archive_entry_indexes,
        _archive_key,
        _real_archive_all_pamt_entries,
    )

    entries, _pamts, errors = _real_archive_all_pamt_entries(game_root)
    if not entries:
        raise SystemExit(f"No archive entries under {game_root}: {errors[:1]}")
    entries = list(entries)
    for pamt in sorted(Path(game_root).glob("dlc/*/*/0.pamt")):
        entries.extend(parse_archive_pamt(pamt))
    by_path, by_basename = _archive_entry_indexes(entries)
    return SimpleNamespace(
        entries_by_normalized_path=by_path, entries_by_basename=by_basename,
        entry_for_path=lambda path: next(iter(by_path.get(_archive_key(path), ())), None),
    )


def _use_driver_variation(dependencies, driver: str, variation: str) -> None:
    """Show the driver in a chosen skeleton variation (``.pabc``) instead of its namesake.

    The appearance lookup picks the variation named like the body PAC; Kliff's own
    proportions are a different file (``phm_00_nude_01_0001.pabc``) over the same mesh.
    """
    from tools.mesh_harness.real_common import _archive_key

    chosen = dependencies.entry_for_path(variation)
    if chosen is None:
        raise SystemExit(f"{variation} is not in the game archive.")
    # The lookup falls back from ``<stem>.pabc`` to shorter names (Damiane's
    # ``phw_00_nude_00_0001_damian`` is shown in ``phw_00_nude_00_0001.pabc``).
    tokens = PurePosixPath(driver).stem.split("_")
    for count in range(len(tokens), 3, -1):
        name = "_".join(tokens[:count]) + ".pabc"
        dependencies.entries_by_normalized_path[_archive_key(str(PurePosixPath(variation).with_name(name)))] = (chosen,)
        dependencies.entries_by_basename[name] = (chosen,)


def _twin_error(fitted_parts, twin_mesh) -> dict | None:
    """Per-vertex error against the game's own version for the driver's body, when the topology matches."""
    if twin_mesh is None or len(twin_mesh.submeshes) != len(fitted_parts):
        return None
    errors = []
    for fitted, target in zip(fitted_parts, twin_mesh.submeshes):
        if len(fitted.vertices) != len(target.vertices) or list(fitted.faces) != list(target.faces):
            return None
        errors.append(np.linalg.norm(np.asarray(fitted.vertices, float) - np.asarray(target.vertices, float), axis=1))
    error = np.concatenate(errors) * 1000
    return {"median_mm": float(np.median(error)), "p95_mm": float(np.percentile(error, 95)), "max_mm": float(error.max())}


def _fitted_pac(entry, data: bytes, fitted_parts, appearance) -> bytes:
    """The PAC with fitted LOD 0 positions and normals, through the editor's exact writer."""
    from cdmw.modding.mesh_edit_ops import refresh_mesh_totals
    from cdmw.modding.mesh_pac_builder import build_pac
    from cdmw.modding.mesh_parser import parse_pac

    source = parse_pac(data, entry.path)
    mesh = copy.deepcopy(source)
    for part, fitted in zip(mesh.submeshes, fitted_parts, strict=True):
        part.vertices = [tuple(map(float, value)) for value in fitted.vertices]
        if len(fitted.normals) == len(part.vertices):
            part.normals = [tuple(map(float, value)) for value in fitted.normals]
    refresh_mesh_totals(mesh)
    if appearance is not None:
        mesh = appearance.to_source(mesh, source)
    return build_pac(mesh, data)


def fit_stage(args) -> int:
    from cdmw.core.archive_extraction import read_archive_entry_data
    from cdmw.core.archive_mesh_appearance import (
        UnresolvedPacBonePaletteError,
        apply_archive_mesh_appearance,
    )
    from cdmw.modding import mesh_native_core
    from cdmw.modding.mesh_parser import parse_pac
    from tools import refit_reference_benchmark as benchmark
    from tools import refit_reference_harness as harness

    harness._require_dev_dependencies(False, True)
    if not mesh_native_core.native_mesh_core_available():
        raise SystemExit("Build the native mesh core first, or set CDMW_MESH_CORE_BIN.")
    benchmark.memoise_skeleton_resolution()
    dependencies = _archive_index(args.game_root)
    if args.driver_variation:
        _use_driver_variation(dependencies, args.driver, args.driver_variation)
    pacs_dir = args.output / "pacs"
    pacs_dir.mkdir(parents=True, exist_ok=True)
    results_path = args.output / "fit_rows.jsonl"
    done = {}
    if results_path.exists():
        for line in results_path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("status") != "error" or not args.retry_errors:
                done[row["pac"]] = row
    pacs = []
    for item in _items(args):
        for path in item["pacs"]:
            if path not in pacs:
                pacs.append(path)
    driver_token = "_phm_" if "/1_phm/" in args.driver else "_phw_"
    started = time.perf_counter()
    with results_path.open("a", encoding="utf-8") as out:
        for index, path in enumerate(pacs):
            if path in done:
                continue
            row = {"pac": path}
            began = time.perf_counter()
            try:
                if driver_token in _pac_name(path):
                    row.update(status="native", note="already made for the driver's body")
                    raise StopIteration
                config = {"body": args.driver, "outfit": path, "clearance": 0.1, "tightness": 100.0, "skin_pull": 0.0}
                inputs = harness._archive_inputs(config, dependencies)
                row["load_seconds"] = time.perf_counter() - began
                row["reference"], row["reference_reason"] = inputs["provenance"]["reference"], inputs["reason"]
                row["weights_reason"] = inputs.get("weights_reason")
                row["driver_appearance"] = inputs["provenance"]["appearances"].get("body")
                method = "reference" if inputs["reference"] is not None else "bound"
                row["method"] = method
                run = harness.fit(inputs, config, method)
                row["status"], row["error"], row["fit_seconds"] = run["status"], run["error"], run["seconds"]
                analysed = time.perf_counter()
                summary = harness.analyse(run, config, inputs["reference"])["summary"]
                row["score_seconds"] = time.perf_counter() - analysed
                row["metrics"] = {key: summary[key] for key in (
                    "new_inside_vertices", "deepest_new_inside_mm", "new_skin_through_vertices",
                    "deepest_new_skin_through_mm", "skin_through_vertices", "skin_through_vertices_authored",
                    "new_layer_crossing_triangles", "new_crossing_triangles_on_clean_pairs",
                    "new_crossing_triangles_by_kind", "worst_solid_distortion_mm", "solid_pieces", "near_skin_gap_mm")}
                row["metrics"]["cloth_strain_p95"] = summary["cloth_strain"]["p95"]
                fitted_parts = run["fitted"].submeshes[run["body_count"]:]
                entry = dependencies.entry_for_path(path)
                data = read_archive_entry_data(entry)[0]
                source = parse_pac(data, entry.path)
                row["parts"], row["vertices"] = len(source.submeshes), sum(len(p.vertices) for p in source.submeshes)
                row["lods"] = max([1, *(int(p.source_lod_count or 0) for p in source.submeshes)])
                try:
                    shown, _notes = apply_archive_mesh_appearance(
                        entry, source, data, archive_entries_by_normalized_path=dependencies.entries_by_normalized_path,
                        archive_entries_by_basename=dependencies.entries_by_basename)
                    appearance = getattr(shown, "_cdmw_neutral_appearance", None)
                except UnresolvedPacBonePaletteError:
                    appearance = None
                row["appearance"] = getattr(appearance, "source", None)
                twin_path = (path.replace("/2_phw/", "/1_phm/").replace("/cd_m0001_02_phw/", "/cd_m0001_01_phm/")
                             .replace("_phw_", "_phm_"))
                twin_entry = dependencies.entry_for_path(twin_path) if twin_path != path else None
                if twin_entry is not None:
                    row["twin"] = twin_path
                    twin = parse_pac(read_archive_entry_data(twin_entry)[0], twin_entry.path)
                    row["twin_error"] = _twin_error(fitted_parts, twin)
                    row["twin_unfit_error"] = _twin_error(source.submeshes, twin)
                if run["status"] == "ok":
                    written = time.perf_counter()
                    try:
                        payload = _fitted_pac(entry, data, fitted_parts, appearance)
                        (pacs_dir / _pac_name(path)).write_bytes(payload)
                        # What the writer stored beside what Fit produced (quantisation, refused lanes).
                        back = parse_pac(payload, entry.path).submeshes
                        if appearance is None and len(back) == len(fitted_parts):
                            row["write_max_dev_mm"] = float(max(
                                np.abs(np.asarray(a.vertices, float) - np.asarray(b.vertices, float)).max(initial=0.0)
                                for a, b in zip(back, fitted_parts)) * 1000)
                        row["write_seconds"], row["pac_bytes"] = time.perf_counter() - written, len(payload)
                    except Exception as error:  # noqa: BLE001 - the writer's refusal is a result
                        row["write_error"] = f"{type(error).__name__}: {error}"
            except StopIteration:
                pass
            except Exception as error:  # noqa: BLE001 - one bad part must not end a long run
                row.update(status="error", error=f"{type(error).__name__}: {error}",
                           trace=traceback.format_exc(limit=4))
            row["seconds"] = time.perf_counter() - began
            out.write(json.dumps(row) + "\n")
            out.flush()
            metrics = row.get("metrics") or {}
            print(f"[{index + 1}/{len(pacs)}] {_pac_name(path)[:44]:<44} {row.get('status')} {row.get('method', '')} "
                  f"{row.get('fit_seconds', 0):5.1f}s cross {metrics.get('new_layer_crossing_triangles', '-')} "
                  f"skin {metrics.get('new_skin_through_vertices', '-')} "
                  f"twin {((row.get('twin_error') or {}).get('median_mm'))} "
                  f"{row.get('write_error') or row.get('error') or ''}"[:220], flush=True)
    print(f"fit stage {time.perf_counter() - started:.0f}s")
    return 0


def _tribe_keys(snapshot, item_key: int) -> list[int]:
    from cdmw.core.iteminfo_behavior import read_behavior_fields

    for prefab in read_behavior_fields(snapshot.row(item_key).raw)["prefabs"]:
        if prefab["tribe_genders"]:
            return list(prefab["tribe_genders"])
    raise SystemExit(f"item {item_key} has no tribe/gender selectors to copy")


def _wearer_settings(snapshot, item: dict, wearer: list[int]):
    """Behavior settings giving the item's body prefabs the driver character's selectors."""
    from cdmw.core.iteminfo_behavior import read_behavior_fields
    from cdmw.domain.new_item.item_behavior import ItemBehaviorSettings

    prefabs = copy.deepcopy(read_behavior_fields(snapshot.row(item["item_key"]).raw)["prefabs"])
    changed = 0
    for prefab in prefabs:
        if prefab["tribe_genders"]:
            prefab["tribe_genders"], changed = list(wearer), changed + 1
    return ItemBehaviorSettings({"prefabs": prefabs}) if changed else None


def _fitted_in_plan(plan, fitted: dict) -> int:
    """How many fitted PACs the plan writes with their fitted LOD 0 positions (under the item's own names)."""
    from cdmw.modding.mesh_parser import parse_pac

    def positions(data, path):
        return [np.asarray(part.vertices, float) for part in parse_pac(data, path).submeshes]

    written = [positions(data, path) for path, data in plan.loose_files.items() if path.lower().endswith(".pac")]
    found = 0
    for path, data in fitted.items():
        want = positions(data, path)
        found += any(len(have) == len(want) and all(a.shape == b.shape and np.array_equal(a, b) for a, b in zip(have, want))
                     for have in written)
    return found


def package_stage(args) -> int:
    from dataclasses import replace
    from uuid import uuid4

    from cdmw.domain.new_item.authoring import VariantAppearance
    from cdmw.domain.new_item.spec import (
        ModelSource,
        NewItemSpec,
        Placement,
        PlacementKind,
    )
    from cdmw.services.independent_item_package import (
        from_plan,
        stock_snapshot,
        write_package,
    )
    from cdmw.services.new_item_planning import ModelFiles
    from cdmw.services.new_item_service import NewItemService
    from cdmw.services.new_item_variants import variant_bindings

    fit_rows = {}
    for line in (args.output / "fit_rows.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        fit_rows[row["pac"]] = row
    began = time.perf_counter()
    service = NewItemService()
    snapshot = stock_snapshot(args.game_root, service=service, on_log=lambda _m: None)
    snapshot_seconds = time.perf_counter() - began
    wearer = _tribe_keys(snapshot, args.wearer) if args.wearer else None
    packages = args.output / "packages"
    packages.mkdir(parents=True, exist_ok=True)
    # Rows of an earlier run are kept unless this run packages the same item again.
    previous = args.output / "package_rows.json"
    kept = json.loads(previous.read_text(encoding="utf-8"))["rows"] if previous.exists() else []
    chosen = {item["item_key"] for item in _items(args)}
    rows = [row for row in kept if row["item_key"] not in chosen]
    reserved_keys, reserved_stems = [], []
    for number, item in enumerate(_items(args)):
        row = {"item_key": item["item_key"], "string_key": item["string_key"]}
        began = time.perf_counter()
        try:
            family = snapshot.family(item["item_key"])
            pac_paths = [entry.path for entry in family.files_for("pac") if entry.exists]
            fitted, missing = {}, []
            for path in pac_paths:
                fit = fit_rows.get(path)
                file = args.output / "pacs" / _pac_name(path)
                if fit is not None and fit.get("status") == "native":
                    continue
                if fit is None or not file.is_file():
                    missing.append(f"{_pac_name(path)}: {(fit or {}).get('write_error') or (fit or {}).get('error') or (fit or {}).get('status') or 'not fitted'}")
                    continue
                fitted[path] = file.read_bytes()
            row["family_pacs"], row["fitted_pacs"] = len(pac_paths), len(fitted)
            if missing:
                row.update(status="not fitted", missing=missing)
                raise StopIteration
            # One imported model per prefab/mesh binding, as the studio's variant picker
            # takes them; bindings not fitted (made for the driver already) keep the template's.
            bindings = [(part.prefab_path, path) for part, path in variant_bindings(family) if path in fitted]

            def variants(keep_cloth, bindings=bindings):
                return tuple(VariantAppearance(prefab, path, custom_model=True, keep_template_physics=keep_cloth)
                             for prefab, path in bindings)

            models = {VariantAppearance(prefab, path).identity: ModelFiles(pac_data=fitted[path]) for prefab, path in bindings}
            row["bindings"] = len(bindings)
            spec = NewItemSpec(template_key=item["item_key"], internal_name=f"CDI_BulkFit_{item['item_key']}",
                               display_names={"eng": f"Bulk Fit {item['string_key'][:40]}"},
                               descriptions={"eng": "Bulk refit pilot."}, model_source=ModelSource.IMPORTED,
                               # Same topology as the template, so its cloth and jiggle bindings still
                               # name the right vertices (the cloth's own rest shape is not refitted).
                               variants=variants(True),
                               placement=Placement(PlacementKind.INSERT, "Store_Camp_Equipment", stock_count=1))
            if wearer is not None:
                settings = _wearer_settings(snapshot, item, wearer)
                if settings is not None:
                    spec = replace(spec, behavior_settings=settings)
                row["wearer_selectors"] = settings is not None
            try:
                plan = service.plan(spec, snapshot, variant_models=models, capture_independent=True,
                                    reserved_keys=reserved_keys, reserved_stems=reserved_stems)
                row["cloth_kept"] = True
            except ValueError as error:
                # The planner keeps template cloth only on four-influence records whose
                # bindings it can prove unchanged; otherwise it is stripped, as New Item
                # does for any imported model.
                if "Template cloth" not in str(error) and "Copied template physics" not in str(error):
                    raise
                row["cloth_kept"], row["cloth_refusal"] = False, str(error)[:200]
                plan = service.plan(replace(spec, variants=variants(False)), snapshot, variant_models=models,
                                    capture_independent=True, reserved_keys=reserved_keys, reserved_stems=reserved_stems)
            row["plan_seconds"] = time.perf_counter() - began
            reserved_keys.append(plan.spec.item_key)
            reserved_stems.append(plan.spec.stem)
            row["warnings"] = list(getattr(plan, "warnings", ()))[:12]
            row["bone_offsets"] = plan.manifest.get("bone_offsets")
            row["dlc_part_copies"] = plan.manifest.get("dlc_part_copies")
            row["behavior_settings"] = plan.manifest.get("behavior_settings") is not None
            row["fitted_pacs_in_plan"] = _fitted_in_plan(plan, fitted)
            written = time.perf_counter()
            package = from_plan(plan, uuid4().hex, title=f"Bulk Fit {item['item_key']}")
            target = packages / f"{item['item_key']}.cdmw"
            target.unlink(missing_ok=True)
            write_package(package, target)
            row.update(status="packaged", package_seconds=time.perf_counter() - written, package_bytes=target.stat().st_size)
        except StopIteration:
            pass
        except Exception as error:  # noqa: BLE001 - a refused plan is a result
            row.update(status="refused", error=f"{type(error).__name__}: {error}"[:600])
        row["seconds"] = time.perf_counter() - began
        rows.append(row)
        print(f"[{number + 1}] {item['item_key']} {item['string_key'][:36]:<36} {row['status']} {row['seconds']:5.1f}s "
              f"{row.get('package_bytes', '')} {row.get('error') or '; '.join(row.get('missing', ()))}"[:260], flush=True)
        (args.output / "package_rows.json").write_text(
            json.dumps({"snapshot_seconds": snapshot_seconds, "wearer": args.wearer, "rows": rows}, indent=1), encoding="utf-8")
    return 0


def replan_stage(args) -> int:
    """Time what Apply / Send to DMM does per package: read it and plan its recipe again."""
    from cdmw.services.independent_item_package import (
        read_package,
        recipe_plan,
        stock_snapshot,
    )

    began = time.perf_counter()
    snapshot = stock_snapshot(args.game_root, on_log=lambda _m: None)
    rows = {"snapshot_seconds": time.perf_counter() - began, "rows": []}
    files = sorted((args.output / "packages").glob("*.cdmw"))
    for path in files[: args.limit] if args.limit else files:
        began = time.perf_counter()
        row = {"package": path.name, "bytes": path.stat().st_size}
        try:
            package = read_package(path)
            row["read_seconds"] = time.perf_counter() - began
            recipe_plan(package, snapshot)
            row["status"] = "ok"
        except Exception as error:  # noqa: BLE001 - a refused recipe is a result
            row.update(status="refused", error=f"{type(error).__name__}: {error}"[:400])
        row["seconds"] = time.perf_counter() - began
        rows["rows"].append(row)
        print(f"{path.name} {row['status']} {row['seconds']:.1f}s {row.get('error', '')}", flush=True)
        (args.output / "replan_rows.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    return 0


def summary_stage(args) -> int:
    """One row per item from the fit, package and inventory results, plus totals (``summary.json``)."""
    fits = {}
    for line in (args.output / "fit_rows.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        fits[row["pac"]] = row
    packaged_path = args.output / "package_rows.json"
    packaged = {row["item_key"]: row for row in json.loads(packaged_path.read_text(encoding="utf-8"))["rows"]}         if packaged_path.exists() else {}
    items = []
    for item in _items(args):
        rows = [fits[path] for path in item["pacs"] if path in fits]
        fitted = [row for row in rows if row.get("status") == "ok"]
        refused = [row for row in rows if row.get("status") not in ("ok", "native")]
        metrics = [row["metrics"] for row in fitted if "metrics" in row]
        package = packaged.get(item["item_key"], {})
        items.append({
            "item_key": item["item_key"], "string_key": item["string_key"], "pacs": len(item["pacs"]),
            "native_pacs": sum(row.get("status") == "native" for row in rows),
            "refused": [{"pac": _pac_name(row["pac"]), "method": row.get("method"), "reason": (row.get("error") or "")[-160:]}
                        for row in refused],
            "write_errors": [f"{_pac_name(row['pac'])}: {row['write_error'][:160]}" for row in fitted if row.get("write_error")],
            "methods": sorted({row.get("method") for row in fitted}),
            "fit_seconds": sum(row.get("fit_seconds", 0.0) for row in rows),
            "load_score_write_seconds": sum(row.get("seconds", 0.0) - row.get("fit_seconds", 0.0) for row in rows),
            "new_crossing_triangles": sum(m["new_layer_crossing_triangles"] for m in metrics),
            "new_crossing_triangles_on_clean_pairs": sum(m["new_crossing_triangles_on_clean_pairs"] for m in metrics),
            "new_skin_through": sum(m["new_skin_through_vertices"] for m in metrics),
            "deepest_new_skin_through_mm": max((m["deepest_new_skin_through_mm"] for m in metrics), default=0.0),
            "new_inside": sum(m["new_inside_vertices"] for m in metrics),
            "worst_solid_bend_mm": max((m["worst_solid_distortion_mm"] for m in metrics), default=0.0),
            "worst_strain_p95": max((m["cloth_strain_p95"] for m in metrics), default=0.0),
            "twin_error": {_pac_name(row["pac"]): row["twin_error"] for row in fitted if row.get("twin_error")},
            "twins_other_topology": [_pac_name(row["pac"]) for row in fitted if row.get("twin") and not row.get("twin_error")],
            "lower_lods": max((row.get("lods", 1) for row in fitted), default=1) > 1,
            "owned_dlc_only": item["owned_dlc_only"], "borrowed_dlc_only": item["borrowed_dlc_only"],
            "bone_offset_entry": item["bone_offset_entry"], "tribe_genders": item.get("tribe_genders"),
            "package": {key: package.get(key) for key in ("status", "error", "plan_seconds", "package_seconds",
                                                          "package_bytes", "cloth_kept", "fitted_pacs_in_plan", "bindings",
                                                          "bone_offsets", "dlc_part_copies")},
        })
    fitted_rows = [row for row in fits.values() if row.get("status") == "ok"]
    totals = {
        "items": len(items), "pacs": len(fits),
        "pac_status": {status: sum(row.get("status") == status for row in fits.values())
                       for status in sorted({row.get("status") for row in fits.values()})},
        "pac_methods": {method: sum(row.get("method") == method for row in fitted_rows)
                        for method in sorted({row.get("method") for row in fitted_rows})},
        "pac_write_errors": sum(bool(row.get("write_error")) for row in fitted_rows),
        "items_all_fitted": sum(not item["refused"] and not item["write_errors"] for item in items),
        "items_packaged": sum(item["package"]["status"] == "packaged" for item in items),
        "median_fit_seconds_per_pac": float(np.median([row["fit_seconds"] for row in fitted_rows])) if fitted_rows else 0.0,
        "fit_seconds_total": sum(row.get("fit_seconds", 0.0) for row in fits.values()),
        "wall_seconds_total": sum(row.get("seconds", 0.0) for row in fits.values()),
        "median_plan_seconds": float(np.median([item["package"]["plan_seconds"] for item in items
                                                if item["package"].get("plan_seconds")])) if packaged else 0.0,
        "package_bytes_total": sum(item["package"].get("package_bytes") or 0 for item in items),
    }
    (args.output / "summary.json").write_text(json.dumps({"totals": totals, "items": items}, indent=1), encoding="utf-8")
    print(json.dumps(totals, indent=1))
    return 0


def corpus_stage(args) -> int:
    """The harness's corpus (``--corpus``), with the driver shown in ``--driver-variation``."""
    from tools import refit_reference_harness as harness

    index = harness._archive_index

    def with_variation(game_root):
        dependencies = index(game_root)
        if args.driver_variation:
            _use_driver_variation(dependencies, args.driver, args.driver_variation)
        return dependencies

    harness._archive_index = with_variation
    argv = ["--game-root", str(args.game_root), "--corpus", str(args.corpus), "--driver", args.driver,
            "--method", "reference", "--output", str(args.output)]
    return harness.main(argv)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("stage", choices=("fit", "package", "replan", "summary", "corpus"))
    parser.add_argument("--game-root", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, help="JSON from tools/refit_bulk_inventory.py")
    parser.add_argument("--corpus", type=Path, default=ROOT / "tools" / "refit_reference_corpus.json",
                        help="corpus: outfit list for the harness")
    parser.add_argument("--equip", default="Upperbody", help="Equip type to keep (empty: all)")
    parser.add_argument("--driver", default=KLIFF, help="Body archive path to fit onto")
    parser.add_argument("--driver-variation", default="",
                        help="fit: skeleton variation (.pabc) to show the driver in, e.g. Kliff's "
                             "character/binary/skeletonvariation/1_pc/1_phm/nude/phm_00_nude_01_0001.pabc")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--keys", default="", help="Comma-separated item keys to keep")
    parser.add_argument("--wearer", type=int, default=0,
                        help="Item key of a driver-body item whose tribe/gender selectors the packages copy")
    parser.add_argument("--retry-errors", action="store_true", help="fit: run rows that errored again")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.stage != "corpus" and args.inventory is None:
        parser.error(f"{args.stage} needs --inventory")
    args.output.mkdir(parents=True, exist_ok=True)
    return {"fit": fit_stage, "package": package_stage, "replan": replan_stage, "summary": summary_stage,
            "corpus": corpus_stage}[args.stage](args)


if __name__ == "__main__":
    raise SystemExit(main())
