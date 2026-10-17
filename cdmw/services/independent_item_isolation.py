"""Explain validated item contributions without granting a native loading claim.

These reports describe the current compiler's ownership and compatibility rules.
They are not package metadata and cannot enable another loading backend.
"""
from copy import deepcopy
from dataclasses import asdict
from pathlib import PurePosixPath

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.new_item.compilation import compiler_stamp
from cdmw.domain.new_item.independent import IndependentItemError


def _shared_integrations(changes):
    from cdmw.domain.archives.overlay_merge import _table

    result = []
    for path, change in sorted(changes.items()):
        family = PurePosixPath(path).name.split(".")[0]
        if family not in ("storeinfo", "itemgroupinfo") or not path.endswith((".staticinfobody", ".pabgb")):
            continue
        header = path.replace(".staticinfobody", ".staticinfoheader").replace(".pabgb", ".pabgh")
        before = dict(_table(change["before"], changes[header]["before"])[1])
        after = dict(_table(change["after"], changes[header]["after"])[1])
        for key, original in before.items():
            if after.get(key) != original:
                result.append({"table": family, "record": int.from_bytes(key, "little"),
                               "path": path, "operation": "additive-membership"})
    return result


def assess_contribution(package, plan, snapshot, changes, bindings, *, target, stop_event=None):
    """Called only after normal package, compiler, dependency and collision checks."""
    from cdmw.core.pathc_format import pathc_checksum
    from cdmw.core.stringinfo_table import stringinfo_key
    from cdmw.domain.archives.overlay_merge import owned_item_references
    from cdmw.domain.new_item.iteminfo_operations import decode_assignment
    from cdmw.domain.new_item.package_links import contract
    from cdmw.services.independent_item_compatibility import _required_keys
    from cdmw.services.independent_item_install import _added_keys
    from cdmw.services.independent_item_package import digest, package_metadata
    from cdmw.services.independent_mod_package import has_legacy_item, package_operations
    from cdmw.services.independent_texture_package import package_texture_requirements

    if target not in ("archive", "virtual"):
        raise IndependentItemError("Unknown isolation inspection backend.")
    raise_if_cancelled(stop_event)
    legacy = has_legacy_item(package)
    stock_edits = []
    for module in package_operations(package):
        for raw in module["operations"]:
            raise_if_cancelled(stop_event)
            assignment = decode_assignment(module["owner"], raw)
            stock_edits.append({"module": "item.fields", "owner": assignment.owner,
                                "symbol": assignment.identity, "record": assignment.record,
                                "field": list(assignment.field), "expected": assignment.expect,
                                "value": assignment.value})
    for row in package_texture_requirements(package):
        stock_edits.append({"module": "texture.replace", **row})
    links = contract(package)["links"]
    required = _required_keys(package, snapshot, changes)
    added = _added_keys(changes)
    resources, shared_outputs = [], []
    for path, change in sorted(changes.items()):
        raise_if_cancelled(stop_event)
        if change["before"] is None and change["after"] is not None:
            resources.append({"path": path, "bytes": len(change["after"]),
                              "sha256": digest(change["after"]), "path_checksum": pathc_checksum(path)})
        elif change["after"] is not None:
            shared_outputs.append({"path": path, "changes_bytes": change["before"] != change["after"],
                                   "metadata": bool(change["meta"])})
    graph = getattr(plan, "reference_assessment", None) if plan is not None else None
    reasons = [{"code": "shared-file-composition",
                "detail": "This backend composes shared game files. Native independent registration and resource discovery are not proven."}]
    if not legacy:
        reasons.append({"code": "no-new-item", "detail": "The package does not define a new inventory item."})
    if stock_edits:
        reasons.append({"code": "existing-content-edits",
                        "detail": "The package intentionally owns assignments to existing game content."})
    if links["packages"] or links["references"]:
        reasons.append({"code": "package-dependency",
                        "detail": "The contribution depends on other packages with exact installation pins."})
    if legacy and graph is None:
        reasons.append({"code": "unverified-resource-assessment",
                        "detail": "No final resource ownership assessment was captured."})
    borrowed_contribution = []
    if graph is not None:
        borrowed_contribution = sorted(row.path for row in graph.resources
            if row.ownership == "borrowed" and "contribution" in row.reachability)
        if borrowed_contribution:
            reasons.append({"code": "borrowed-contribution-resources",
                            "detail": "Decoded contribution references still reach borrowed source resources."})
        if graph.unresolved or not graph.graph_complete:
            reasons.append({"code": "unverified-resource-boundaries",
                            "detail": "The resource graph lists unverified boundaries or a partial edge inventory."})
    integrations = _shared_integrations(changes)
    if integrations:
        reasons.append({"code": "shared-integration",
                        "detail": "Acquisition changes add membership to existing shop or item-group records."})
    identifiers = None
    if plan is not None:
        identifiers = {"internal_name": plan.spec.internal_name, "stem": plan.spec.stem,
            "name_key": plan.spec.name_key, "description_key": plan.spec.desc_key,
            "strings": [{"text": text, "key": stringinfo_key(text)}
                        for text in plan.manifest.get("stringinfo_texts", ())],
            "localisation_keys": {language: sorted(entries)
                                  for language, entries in plan.manifest.get("localisation", {}).items()},
            "prefab_bindings": deepcopy(plan.manifest.get("pappt_records", {})),
            "sheathed_bindings": deepcopy(plan.manifest.get("sheathed_records", {})),
            "texture_registrations": list(plan.manifest.get("texture_registry", ())),
            "icon": deepcopy(plan.manifest.get("icon")),
            "effects": deepcopy(plan.manifest.get("effects", []))}
    metadata = package_metadata(package)
    return {
        "identity": package.identity, "title": package.title,
        "package_version": metadata["version"], "content_sha256": package.digest,
        "artifact_sha256": package.artifact_digest,
        "contribution_class": "mixed" if legacy and stock_edits else "new-item" if legacy else "stock-edits",
        "isolated_new_item": {"admitted": False, "reasons": reasons},
        "backend": target, "shared_file_composition": True,
        "proposed_bindings": {name: dict(sorted(values.items())) for name, values in sorted(bindings.values.items())},
        "proposed_paths": sorted(bindings.paths),
        "added_records": {name: sorted(keys) for name, keys in sorted(added.items()) if keys},
        "private_outputs": resources,
        "shared_outputs": shared_outputs,
        "shared_integrations": integrations,
        "compiled_identifiers": identifiers,
        "stock_edits": stock_edits,
        "package_dependencies": links,
        "protected_game_records": {name: sorted(keys) for name, keys in sorted(required.items()) if keys},
        "decoded_item_references": sorted(owned_item_references(changes)),
        "source_table_layouts": deepcopy(plan.manifest.get("tables", {})) if plan is not None else {},
        "authoring_template": plan.spec.template_key if plan is not None else None,
        "source_dependencies": [{"path": path, "sha256": checksum}
                                for path, checksum in sorted(package.dependencies.items())],
        "resource_graph": asdict(graph) if graph is not None else None,
        "borrowed_contribution_paths": borrowed_contribution,
        "evidence_scope": "validated per-package compiler output and source references; no combined deployment, game or save observation",
        "publication": "inspection only; newly proposed bindings and paths are not committed",
        "binding_scope": "proposed registry includes retained and retired reservations; current additions are listed separately",
        "lifetime": "installed and retired bindings use the existing registry; runtime object ownership and lifetime require native proof",
    }


def inspect_isolation(sources, root, *, target="virtual", folders=(), stop_event=None, read_entry=None):
    """Recompile selected inputs for inspection, without publishing any result."""
    from cdmw.services.independent_item_install import resolve_items

    sources = tuple(sources)
    if not 1 <= len(sources) <= 128:
        raise IndependentItemError("Select between one and 128 packages for isolation inspection.")
    resolved = resolve_items(sources, root, target=target, folders=folders, rebuild=True,
                             capture_isolation=True, stop_event=stop_event, read_entry=read_entry)
    for revision in resolved.revisions:
        revision.validate(stop_event)
    resolved.external.validate(stop_event)
    raise_if_cancelled(stop_event)
    reports = tuple(resolved.isolation_assessments)
    if len(reports) != len(resolved.contributions) or not reports:
        raise IndependentItemError("Isolation inspection did not assess every compiled contribution.")
    return {"format": "cdmw_isolation_assessment_v1", "compiler": compiler_stamp(),
            "backend": target, "isolated_new_item_admitted": False,
            "published": False, "packages": reports}
