"""Corpus and phase gate commands.

Split out of `cli.py` so both stay under the repository's 1,000-line owner ceiling. `cli.py`
owns argument parsing and dispatch; every gate implementation lives here.
"""

from __future__ import annotations

import argparse
import json as json_module
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.placement_studio import ops, paac  # noqa: E402
from tools.placement_studio.corpus import (  # noqa: E402
    Baseline,
    GoldenMod,
    discover_golden_mods,
    golden_game_paths,
    golden_root,
    work_root,
)
from tools.placement_studio.gates_clipping import cmd_clipping  # noqa: E402
from tools.placement_studio.cli_support import (  # noqa: E402
    derive_all,
    chart_index,
    hash_index,
    socket_from_raw,
    log as _log,
    vanilla_based,
    combination_pairs,
    discover_body_meshes,
    HIP_RETARGET,
)

def cmd_paac(args: argparse.Namespace) -> int:
    """Report the length-prefix evidence that gates Tier C."""

    total = conforming = 0
    for path in sorted(Path(golden_root()).rglob("*.paac")):
        data = path.read_bytes()
        strings = paac.index_sockets(data)
        total += len(strings)
        conforming += sum(
            1 for s in strings if paac.is_length_prefixed(data, s.offset, s.length)
        )
        if args.verbose:
            names = sorted({s.value for s in strings})
            _log(f"{path.name:<38} {len(strings):>3} socket strings  {names}")
    _log("")
    _log(f"socket strings: {total}, length-prefixed: {conforming}, anomalies: {total - conforming}")
    _log("Tier C precondition holds" if total == conforming else "Tier C BLOCKED - anomalies present")
    return 0 if total == conforming else 1


def cmd_roundtrip(args: argparse.Namespace) -> int:
    """Phase 1 gate: every XML file must parse and re-emit byte-identically."""

    from tools.placement_studio import documents, xmldoc

    baseline = Baseline.load()
    checked = failed = 0
    failures: List[str] = []

    for game_path in baseline.paths():
        if not (documents.is_socket_file(game_path) or documents.is_descriptor_file(game_path)):
            continue
        checked += 1
        data = baseline.read(game_path)
        if not xmldoc.round_trips(data):
            failed += 1
            failures.append(f"vanilla:{game_path}")

    for mod in discover_golden_mods():
        for entry in mod.files:
            if not (
                documents.is_socket_file(entry.game_path)
                or documents.is_descriptor_file(entry.game_path)
            ):
                continue
            checked += 1
            if not xmldoc.round_trips(entry.disk_path.read_bytes()):
                failed += 1
                failures.append(f"{mod.key}:{entry.game_path}")

    _log(f"XML files checked: {checked:,}")
    _log(f"byte-identical round-trip: {checked - failed:,}")
    _log(f"failures: {failed:,}")
    for item in failures[: (None if args.verbose else 20)]:
        _log(f"  {item}")

    # Reading losslessly is not enough: an edit must change only what it targets. Nudge
    # every socket in every socket file and assert two things — exactly one attribute value
    # moved, and reverting the nudge returns the original bytes.
    #
    # Byte length is deliberately *not* asserted: vanilla stores negative zero, so a
    # legitimate edit can shorten the file ("-0.000000" -> "0.020000"). Length equality
    # looked like a stricter check but was simply the wrong invariant.
    from tools.placement_studio.documents import SocketDocument

    edited = drifted = 0
    drift: List[str] = []
    for game_path in baseline.paths():
        if not documents.is_socket_file(game_path):
            continue
        original = baseline.read(game_path)
        before = {s.name: s for s in SocketDocument.load(original, game_path).sockets()}
        for name, socket in before.items():
            document = SocketDocument.load(original, game_path)
            try:
                document.set_translation(name, socket.translation.offset(dy=0.02))
            except Exception as exc:  # noqa: BLE001
                drifted += 1
                drift.append(f"{game_path}:{name}: {exc}")
                continue
            produced = document.to_bytes()
            edited += 1

            after = {s.name: s for s in SocketDocument.load(produced, game_path).sockets()}
            changed = [
                key
                for key in before
                if key not in after
                or after[key].translation != before[key].translation
                or after[key].rotation != before[key].rotation
                or after[key].parent_bone != before[key].parent_bone
            ]
            restored = SocketDocument.load(produced, game_path)
            restored.set_translation(name, socket.translation)

            if changed != [name] or set(after) != set(before):
                drifted += 1
                drift.append(f"{game_path}:{name}: changed {changed}")
            elif restored.to_bytes() != original:
                drifted += 1
                drift.append(f"{game_path}:{name}: revert did not restore original bytes")

    _log("")
    _log(f"socket edits exercised: {edited:,}")
    _log(f"edits that disturbed anything else: {drifted:,}")
    for item in drift[: (None if args.verbose else 10)]:
        _log(f"  {item}")
    return 1 if (failed or drifted) else 0


def cmd_bindings(args: argparse.Namespace) -> int:
    """Resolve vanilla placements into bindings and report coverage."""

    from tools.placement_studio.resolver import KNOWN_MODELS, resolver_from_baseline

    baseline = Baseline.load()
    resolver = resolver_from_baseline(baseline)
    models = resolver.models()
    _log(f"character models: {', '.join(models) or '(none)'}")

    ok = True
    for model in models:
        if args.model and model != args.model:
            continue
        body = resolver.body_sockets(model)
        weapons = resolver.weapons(model=model)
        _log("")
        _log(f"=== {KNOWN_MODELS.get(model, model)} ({model}) ===")
        _log(f"  body sockets: {len(body)}   weapon files: {len(weapons)}")

        report = resolver.resolve(model=model)
        _log(f"  {report.summary()}")
        if report.missing_body_sockets:
            # Vanilla's own dangling references (Hand_Socket, ShieldDrone_Docking_Socket).
            # Worth surfacing so the UI can grey those rows out; not a harness failure.
            _log(f"  rows whose body socket is undefined ({len(report.missing_body_sockets)}):")
            for name, gaps in list(report.missing_body_sockets.items())[
                : (None if args.verbose else 8)
            ]:
                _log(f"    {name}: {', '.join(gaps)}")

        grouped = report.by_weapon_type()
        _log(f"  weapon types routed: {len(grouped)}")

        # Child sockets only mean anything once an item is named, so resolve per weapon.
        resolvable = 0
        for index, weapon in enumerate(weapons):
            per_item = resolver.resolve(model=model, weapon=weapon)
            usable = [b for b in per_item.bindings if b.complete]
            if usable:
                resolvable += 1
            if args.verbose or index < 4:
                _log(f"    {weapon.label:<44} {len(usable):>2} fully resolved row(s)")
            if args.verbose:
                for binding in usable:
                    _log(f"        {binding.describe()}")
        if len(weapons) > 4 and not args.verbose:
            _log(f"    ... and {len(weapons) - 4} more weapon file(s)")

        # The gate: every model must have body sockets and at least one weapon whose
        # child sockets complete a binding. Dangling vanilla refs do not fail it.
        if not body or not resolvable:
            ok = False
            _log(f"  FAIL: {len(body)} body sockets, {resolvable}/{len(weapons)} weapons resolvable")

        if report.warnings:
            _log(f"  warnings ({len(report.warnings)}):")
            for item in report.warnings[: (None if args.verbose else 5)]:
                _log(f"    {item}")

    return 0 if ok and models else 1


def cmd_uses(args: argparse.Namespace) -> int:
    """'What moves if I edit this socket?' - the core UI question, answered headlessly."""

    from tools.placement_studio.resolver import resolver_from_baseline

    baseline = Baseline.load()
    resolver = resolver_from_baseline(baseline)
    bindings = resolver.bindings_through(args.socket, model=args.model)
    _log(f"{args.socket}: {len(bindings)} part(s) route through it")
    for binding in bindings:
        roles = []
        if binding.part.in_socket == args.socket:
            roles.append("stowed")
        if binding.part.out_socket == args.socket:
            roles.append("held")
        if args.socket in (binding.part.in_child_socket, binding.part.out_child_socket):
            roles.append("child-offset")
        _log(f"  {binding.part_name:<34} as {'+'.join(roles)}")
    return 0


def cmd_reproduce(args: argparse.Namespace) -> int:
    """Phase 3 gate: can the editor author what was hand-made?

    For every socket file a golden mod changed, replay the derived edits through the *editor
    API* — not the Phase 0 replay — and compare the result against the shipped file.
    """

    from tools.placement_studio import ops as ops_module
    from tools.placement_studio.editing import EditError, EditSession

    baseline = Baseline.load()
    checked = matched = failed = 0
    failures: List[str] = []

    for mod in discover_golden_mods():
        if mod.external_base:
            continue
        for entry in mod.files:
            path = entry.game_path
            if not path.endswith(".sockets.xml") or path not in baseline:
                continue
            base = baseline.read(path)
            golden = entry.disk_path.read_bytes()
            derived = ops_module.derive_file(path, base, golden)
            if not derived:
                continue
            checked += 1

            session = EditSession({path: base})
            try:
                for operation in derived:
                    if operation.kind == "xml_attr":
                        attribute = str(operation.detail["attr"])
                        value = str(operation.detail["new"])
                        if attribute == "Translation":
                            from tools.placement_studio.model import Vec3

                            session.set_translation(path, operation.target, Vec3.parse(value))
                        elif attribute == "Rotation":
                            from tools.placement_studio.model import Quat

                            session.set_rotation_quaternion(path, operation.target, Quat.parse(value))
                        elif attribute == "Parent":
                            session.reparent(path, operation.target, value)
                        else:
                            raise EditError(f"unhandled attribute {attribute}")
                    elif operation.kind == "xml_element_add":
                        session.add_socket(path, socket_from_raw(str(operation.detail["raw"])))
                    else:
                        raise EditError(f"unhandled kind {operation.kind}")
            except Exception as exc:  # noqa: BLE001 - collect, keep sweeping
                failed += 1
                failures.append(f"{mod.key}:{path}: {exc}")
                continue

            produced = session.preview().get(path, base)
            if produced == golden or ops_module.canonical_text(produced) == ops_module.canonical_text(golden):
                matched += 1
            else:
                failed += 1
                failures.append(f"{mod.key}:{path}: output differs from the hand-made file")

            # The plan the editor emits must equal what Phase 0 derives from the golden.
            emitted = {op.conflict_key for op in session.to_plan().operations}
            expected = {op.conflict_key for op in derived}
            if emitted != expected:
                failed += 1
                failures.append(
                    f"{mod.key}:{path}: plan mismatch "
                    f"(+{sorted(emitted - expected)[:2]} -{sorted(expected - emitted)[:2]})"
                )

    _log(f"golden socket files with edits: {checked:,}")
    _log(f"reproduced by the editor: {matched:,}")
    _log(f"failures: {failed:,}")
    for item in failures[: (None if args.verbose else 12)]:
        _log(f"  {item}")
    return 1 if failed or not checked else 0


def cmd_charts(args: argparse.Namespace) -> int:
    """Report action charts by the sockets they reference."""

    baseline = Baseline.load()
    index = chart_index(baseline)
    _log(f"action charts indexed: {len(index)}")
    if not len(index):
        _log("No .paac files in the baseline. Run: extract --charts")
        return 1

    _log("")
    for chart in index.charts():
        _log(f"{chart.game_path}")
        _log(f"   {chart.size:>9,}B  group={chart.group or '?':<12} model={chart.model or '?'}")
        for name in chart.names:
            _log(f"      {name}  x{len(chart.offsets(name))}  at {list(chart.offsets(name))}")

    _log("")
    _log("socket -> charts referencing it:")
    for name, count in index.sockets_for(model=args.model).items():
        _log(f"   {name:<32} {count}")
    return 0


def cmd_retarget(args: argparse.Namespace) -> int:
    """Phase 4 gate: the 2H hip retarget, on current vanilla.

    The plan's original criterion — byte-identity against the golden `.paac` files — is
    unreachable and known to be so: the goldens were built on the pre-2026-07-24 game build,
    they differ from current vanilla from byte 0 and by up to 11 KB, and no vanilla `.paac` of
    matching size exists anywhere in the 33 packages (§0.1). Their *base bytes are gone*.

    What is provable is everything that actually matters about the mechanism, so that is what
    this gate checks:

      1. the retarget applies to current vanilla as a same-length patch,
      2. it changes nothing outside the patched spans,
      3. it is exactly reversible,
      4. the resulting socket set equals the golden's socket set, and
      5. reversing the *golden* yields vanilla's socket names — proving the shipped file really
         is a same-length retarget of the same intent.
    """

    from tools.placement_studio import paac as paac_module
    from tools.placement_studio.animation import (
        RetargetError,
        apply_retarget,
        plan_retarget,
        retarget_candidates,
        verify_retarget,
    )

    baseline = Baseline.load()
    index = chart_index(baseline)
    old_name, new_name = HIP_RETARGET

    if not len(index):
        _log("No action charts in the baseline. Run: extract")
        return 1

    # A retarget target usually does not exist in vanilla yet: the 2H hip mod *creates*
    # Pelvis_L_SubWeapon_Socket (Tier A2) and only then points the action charts at it
    # (Tier C). So Tier C depends on Tier A2, and the candidate set must be computed over the
    # edited state — the same invariant the Phase 3 route guard enforces.
    from tools.placement_studio.editing import session_from_baseline
    from tools.placement_studio.resolver import resolver_from_baseline

    body_path = "character/descriptors/socketbonedata/1_pc/1_phm/phm_01.pab.sockets.xml"
    resolver = resolver_from_baseline(baseline)
    vanilla_defined = set(resolver.body_sockets("1_phm")) | index.vocabulary()

    if new_name in vanilla_defined:
        edits = None
        defined = vanilla_defined
    else:
        _log(f"{new_name} is not defined in vanilla; creating the definition first (Tier A2)")
        from tools.placement_studio.model import Quat, Socket, Vec3

        edits = session_from_baseline(baseline, paths=[body_path])
        edits.add_socket(
            body_path,
            Socket(
                name=new_name,
                parent_bone="B_WeaponIn_R_00",
                rotation=Quat.parse("0.000000 0.216440 0.000000 0.976296"),
                translation=Vec3.parse("0.000000 0.000000 0.020000"),
            ),
        )
        defined = vanilla_defined | {new_name}
        _log("")

    # The candidate filter is the safety model: wrong-length names never appear.
    candidates = retarget_candidates(old_name, defined_sockets=defined)
    _log(f"same-length candidates for {old_name} ({len(old_name)} chars): {len(candidates)}")
    for name in candidates:
        _log(f"   {name}")
    if new_name not in candidates:
        _log(f"FAIL: {new_name} is not an offered candidate")
        return 1
    _log("")

    try:
        plan = plan_retarget(index, old_name, new_name, model="1_phm")
    except RetargetError as exc:
        _log(f"FAIL: {exc}")
        return 1

    _log(f"plan: {plan.describe()}")
    for site in plan.sites:
        _log(f"   {site.game_path}  x{site.count} at {list(site.offsets)}")
    if not plan.valid:
        _log("FAIL: empty or invalid plan")
        return 1

    source = {path: baseline.read(path) for path in plan.paths()}
    try:
        produced = apply_retarget(plan, source)
    except RetargetError as exc:
        _log(f"FAIL: {exc}")
        return 1

    problems = verify_retarget(plan, source, produced)
    _log("")
    _log(f"verified {len(produced)} file(s); {len(problems)} problem(s)")
    for item in problems:
        _log(f"   {item}")
    if problems:
        return 1

    # Compare against the golden's socket set, which is the part version drift leaves intact.
    goldens: Dict[str, bytes] = {}
    for mod in discover_golden_mods():
        for entry in mod.files:
            if entry.game_path in produced:
                goldens.setdefault(entry.game_path, entry.disk_path.read_bytes())

    _log("")
    mismatched = 0
    for path, patched in sorted(produced.items()):
        golden = goldens.get(path)
        ours = set(paac_module.socket_histogram(patched))
        if golden is None:
            _log(f"   {path.split('/')[-1]:<38} no golden to compare")
            continue
        theirs = set(paac_module.socket_histogram(golden))
        same = ours == theirs
        _log(
            f"   {path.split('/')[-1]:<38} socket set {'matches' if same else 'DIFFERS'} golden"
            f"   (ours={len(ours)} golden={len(theirs)})"
        )
        if not same:
            mismatched += 1
            _log(f"        ours only  : {sorted(ours - theirs)}")
            _log(f"        golden only: {sorted(theirs - ours)}")

        # The golden must itself reverse cleanly to vanilla's socket names.
        try:
            restored = paac_module.retarget(golden, new_name, old_name)
        except paac_module.PaacPatchError as exc:
            mismatched += 1
            _log(f"        golden is not a reversible same-length retarget: {exc}")
            continue
        if set(paac_module.socket_histogram(restored)) != set(
            paac_module.socket_histogram(source[path])
        ):
            mismatched += 1
            _log("        reversing the golden does not yield vanilla's socket names")

    _log("")
    if mismatched:
        _log(f"FAIL: {mismatched} file(s) disagree with the golden")
        return 1
    _log("Retarget mechanism verified against every golden action chart")
    _log("(byte-identity is not asserted: the goldens' base build no longer exists — see §0.1)")
    return 0


def cmd_package(args: argparse.Namespace) -> int:
    """Phase 5 gate: regenerate a golden mod's manager variants and compare.

    Byte-identity on the manifests is unreachable, and for a *second* reason independent of
    the `.paac` version drift: the app's own manifest schema has changed since the goldens were
    generated on 2026-06-06. Current code writes an `id` field the goldens lack and no longer
    writes `file_count`. Verified empirically, not assumed.

    So the gate checks what identity actually means here:

      1. the payload tree is byte-identical — every content file, right bytes, right place,
      2. `modinfo.json` is byte-identical,
      3. every manifest key present in *both* schemas holds an identical value,
      4. schema differences are enumerated rather than tolerated silently,
      5. `new_paths` is derived from the baseline and matches the golden's declaration,
      6. the JMM descriptor-alias rule holds: both descriptor paths, or neither.
    """

    import json as json_module
    import shutil

    from tools.placement_studio import ops as ops_module
    from tools.placement_studio.packaging import (
        MANAGER_PROFILES,
        PackageMetadata,
        build_package,
        derive_new_paths,
    )

    baseline = Baseline.load()
    target_group = args.group
    variants: Dict[str, GoldenMod] = {}
    for mod in discover_golden_mods():
        if mod.external_base or mod.group != target_group:
            continue
        if mod.manager in MANAGER_PROFILES and mod.manager not in variants:
            variants[mod.manager] = mod
    if not variants:
        _log(f"No vanilla-based golden variants in group {target_group!r}")
        return 1

    _log(f"group {target_group}: {', '.join(sorted(variants))}")
    _log("")

    out_root = work_root() / "packages"
    if out_root.exists():
        shutil.rmtree(out_root)

    failures = 0
    for manager, mod in sorted(variants.items()):
        golden_manifest_path = mod.root / "manifest.json"
        golden_manifest = (
            json_module.loads(golden_manifest_path.read_text(encoding="utf-8"))
            if golden_manifest_path.is_file()
            else {}
        )
        # Pin the timestamp so the only differences left are structural.
        created = str(golden_manifest.get("created_utc") or "") or None

        files = {entry.game_path: entry.disk_path.read_bytes() for entry in mod.files}

        # JMM ships no manifest.json, so its metadata lives in mod.json. Reading only the
        # manifest silently produced version 1.0.0 against the golden's 1.0.2.
        declared = dict(golden_manifest)
        for fallback in ("mod.json", "modinfo.json"):
            if declared:
                break
            candidate = mod.root / fallback
            if candidate.is_file():
                declared = json_module.loads(candidate.read_text(encoding="utf-8"))

        metadata = PackageMetadata(
            name=str(declared.get("name") or mod.name).rsplit(" - ", 1)[0],
            version=str(declared.get("version") or "1.0.0"),
            author=str(declared.get("author") or ""),
            description=str(declared.get("description") or ""),
        )

        plan, _warnings = ops_module.derive_mod(mod, baseline)
        result = build_package(
            manager,
            plan,
            files,
            metadata,
            out_root=out_root / f"{metadata.name} - {manager}",
            baseline=baseline,
            created_utc=created,
        )
        _log(result.describe())

        # 1. payload tree byte-identity
        wrapper = MANAGER_PROFILES[manager]["structure"] == "files_wrapper"
        payload_root = result.root / "files" if wrapper else result.root
        mismatched: List[str] = []
        for entry in mod.files:
            produced = payload_root.joinpath(*entry.game_path.split("/"))
            if not produced.is_file():
                mismatched.append(f"missing {entry.game_path}")
            elif produced.read_bytes() != entry.disk_path.read_bytes():
                mismatched.append(f"differs {entry.game_path}")
        _log(f"   payload: {len(mod.files) - len(mismatched)}/{len(mod.files)} byte-identical")
        for item in mismatched[: (None if args.verbose else 5)]:
            _log(f"      {item}")
        if mismatched:
            failures += 1

        # 2. modinfo.json byte-identity
        golden_modinfo = mod.root / "modinfo.json"
        ours_modinfo = result.root / "modinfo.json"
        if golden_modinfo.is_file() and ours_modinfo.is_file():
            same = ours_modinfo.read_bytes() == golden_modinfo.read_bytes()
            _log(f"   modinfo.json: {'byte-identical' if same else 'DIFFERS'}")
            if not same:
                failures += 1

        # 3 & 4. manifest values on shared keys, plus enumerated schema drift
        if golden_manifest and (result.root / "manifest.json").is_file():
            ours = json_module.loads((result.root / "manifest.json").read_text(encoding="utf-8"))
            shared = [k for k in golden_manifest if k in ours]
            differing = [k for k in shared if golden_manifest[k] != ours[k]]
            _log(
                f"   manifest: {len(shared) - len(differing)}/{len(shared)} shared keys identical"
                f"   (+{[k for k in ours if k not in golden_manifest]}"
                f" -{[k for k in golden_manifest if k not in ours]})"
            )
            for key in differing:
                _log(f"      {key}: golden={golden_manifest[key]!r} ours={ours[key]!r}")
            if differing:
                failures += 1

        # 4b. JMM mod.json — the only metadata that layout ships, so it must be checked.
        golden_mod_json = mod.root / "mod.json"
        ours_mod_json = result.root / "mod.json"
        if golden_mod_json.is_file() and ours_mod_json.is_file():
            gold_json = json_module.loads(golden_mod_json.read_text(encoding="utf-8"))
            our_json = json_module.loads(ours_mod_json.read_text(encoding="utf-8"))
            shared = [k for k in gold_json if k in our_json]
            differing = [k for k in shared if gold_json[k] != our_json[k]]
            _log(
                f"   mod.json: {len(shared) - len(differing)}/{len(shared)} shared keys identical"
                f"   (+{[k for k in our_json if k not in gold_json]})"
            )
            for key in differing:
                left, right = gold_json[key], our_json[key]
                if isinstance(left, list):
                    _log(
                        f"      {key}: golden {len(left)} vs ours {len(right)}; "
                        f"only-golden={sorted(set(left) - set(right))[:2]}"
                    )
                else:
                    _log(f"      {key}: golden={left!r} ours={right!r}")
            if differing:
                failures += 1

            # The guide's rule, checked on the emitted file rather than assumed.
            from tools.placement_studio.packaging import DESCRIPTOR_ALIAS_PAIRS

            declared_new = set(our_json.get("new_paths") or [])
            listed = set(our_json.get("files") or [])
            for left, right in DESCRIPTOR_ALIAS_PAIRS:
                pair = {left, right}
                if declared_new & pair and pair <= listed and not pair <= declared_new:
                    _log(f"      JMM new_paths rule VIOLATED for {left} / {right}")
                    failures += 1

        # 5. new_paths derived from the baseline vs the golden's declaration
        if golden_manifest:
            declared = sorted(golden_manifest.get("new_paths") or [])
            derived = derive_new_paths([e.game_path for e in mod.files], baseline)
            same = declared == derived
            _log(f"   new_paths: {'matches' if same else 'DIFFERS'} ({len(derived)} derived)")
            if not same:
                failures += 1
                _log(f"      golden : {declared}")
                _log(f"      derived: {derived}")

        # 6. the guide's JMM rule: both descriptor paths, or neither
        alias_pairs = [
            (
                "character/phm_description_player_kliff.xml",
                "character/descriptors/characterdescription/phm_description_player_kliff.xml",
            )
        ]
        shipped = {entry.game_path for entry in mod.files}
        for left, right in alias_pairs:
            if (left in shipped) != (right in shipped):
                # The golden itself may ship only one half; the studio must ship both.
                produced_paths = {
                    p.relative_to(payload_root).as_posix()
                    for p in payload_root.rglob("*")
                    if p.is_file()
                }
                if manager == "JMM" and (left in produced_paths) != (right in produced_paths):
                    _log(f"   JMM alias rule: DIFFERS ({left} / {right})")
                    failures += 1
                else:
                    _log(f"   JMM alias rule: golden ships one half only ({left.split('/')[-1]})")
        _log("")

    _log(f"packages written to {out_root}")
    if failures:
        _log(f"FAIL: {failures} check(s) failed")
        return 1
    _log("All manager variants regenerate with identical payloads and manifest values")
    _log("(manifest schema drift is enumerated above, not asserted away)")
    return 0



def cmd_phase4b(args: argparse.Namespace) -> int:
    gates = [("in-process geometry and clipping metric", cmd_clipping)]
    failures: List[str] = []
    for title, handler in gates:
        _log("=" * 72)
        _log(f"GATE: {title}")
        _log("=" * 72)
        if handler(args) != 0:
            failures.append(title)
        _log("")
    _log("=" * 72)
    if failures:
        _log(f"PHASE 4b INCOMPLETE - {len(failures)} gate(s) open:")
        for title in failures:
            _log(f"  - {title}")
        return 1
    _log("PHASE 4b COMPLETE - all gates pass")
    return 0


def cmd_phase5(args: argparse.Namespace) -> int:
    gates = [("manager packaging", cmd_package)]
    failures: List[str] = []
    for title, handler in gates:
        _log("=" * 72)
        _log(f"GATE: {title}")
        _log("=" * 72)
        if handler(args) != 0:
            failures.append(title)
        _log("")
    _log("=" * 72)
    if failures:
        _log(f"PHASE 5 INCOMPLETE - {len(failures)} gate(s) open:")
        for title in failures:
            _log(f"  - {title}")
        return 1
    _log("PHASE 5 COMPLETE - all gates pass")
    return 0


def cmd_phase4(args: argparse.Namespace) -> int:
    gates = [("Tier C retarget mechanism", cmd_retarget)]
    failures: List[str] = []
    for title, handler in gates:
        _log("=" * 72)
        _log(f"GATE: {title}")
        _log("=" * 72)
        if handler(args) != 0:
            failures.append(title)
        _log("")
    _log("=" * 72)
    if failures:
        _log(f"PHASE 4 INCOMPLETE - {len(failures)} gate(s) open:")
        for title in failures:
            _log(f"  - {title}")
        return 1
    _log("PHASE 4 COMPLETE - all gates pass")
    return 0


def cmd_phase3(args: argparse.Namespace) -> int:
    gates = [("editor reproduces golden socket edits", cmd_reproduce)]
    failures: List[str] = []
    for title, handler in gates:
        _log("=" * 72)
        _log(f"GATE: {title}")
        _log("=" * 72)
        if handler(args) != 0:
            failures.append(title)
        _log("")
    _log("=" * 72)
    if failures:
        _log(f"PHASE 3 INCOMPLETE - {len(failures)} gate(s) open:")
        for title in failures:
            _log(f"  - {title}")
        return 1
    _log("PHASE 3 COMPLETE - all gates pass")
    return 0


def cmd_phase1(args: argparse.Namespace) -> int:
    gates = [
        ("xml byte-identical round-trip", cmd_roundtrip),
        ("placement resolution", cmd_bindings),
    ]
    failures: List[str] = []
    for title, handler in gates:
        _log("=" * 72)
        _log(f"GATE: {title}")
        _log("=" * 72)
        if handler(args) != 0:
            failures.append(title)
        _log("")
    _log("=" * 72)
    if failures:
        _log(f"PHASE 1 INCOMPLETE - {len(failures)} gate(s) open:")
        for title in failures:
            _log(f"  - {title}")
        return 1
    _log("PHASE 1 COMPLETE - all gates pass")
    return 0


def cmd_phase0(args: argparse.Namespace) -> int:
    # The corpus commands live in `cli.py`; imported here to avoid a module-level cycle.
    from tools.placement_studio.cli import cmd_derive, cmd_merge, cmd_replay

    gates = [
        ("paac length-prefix evidence", cmd_paac),
        ("derive", cmd_derive),
        ("replay byte-identity", cmd_replay),
        ("composition (1H+2H == 2H-1H)", cmd_merge),
    ]
    failures: List[str] = []
    for title, handler in gates:
        _log("=" * 72)
        _log(f"GATE: {title}")
        _log("=" * 72)
        if handler(args) != 0:
            failures.append(title)
        _log("")
    _log("=" * 72)
    if failures:
        _log(f"PHASE 0 INCOMPLETE - {len(failures)} gate(s) open:")
        for title in failures:
            _log(f"  - {title}")
        return 1
    _log("PHASE 0 COMPLETE - all gates pass")
    return 0


