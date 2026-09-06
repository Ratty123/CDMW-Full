"""Dye assignments and material wiring use the same preparation for preview/export."""
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from types import MappingProxyType

from cdmw.core.item_dye_material import material_dye_bindings, has_dye_wiring, copy_dye_materials
from cdmw.core.partprefab_dye_table import parse_prefab_dye_table, encode_prefab_dye_row
from cdmw.core.structured_binary_editor import append_table_rows, parse_pabgh_table
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.services.new_item_acquisition_index import optional_pair
from cdmw.services.new_item_provenance import _stamp, StaleNewItemSource

_NO_REVISION = object()


@dataclass(frozen=True)
class DyeIndex:
    pair: object
    rows: object


def dye_mask_revision(path):
    return _stamp(Path(path))


def read_dye_mask(snapshot, path, *, expected_revision=_NO_REVISION):
    """Read one immutable worker input and pin it to the eventual export plan."""
    path = Path(path)
    before = dye_mask_revision(path)
    if expected_revision is not _NO_REVISION and before != expected_revision:
        raise StaleNewItemSource(f"Dye mask changed: {path}. Refresh the preview and build the plan again.")
    if snapshot.provenance:
        snapshot.provenance.pin_file(path)
    data = path.read_bytes()
    if dye_mask_revision(path) != before:
        raise StaleNewItemSource(f"Dye mask changed while reading: {path}.")
    if snapshot.provenance:
        snapshot.provenance.pin_file(path)
    from cdmw.core.dds_native import inspect_dds_native
    inspect_dds_native(data)
    return data


def load_dye_index(snapshot, *, stop_event=None):
    cached = snapshot._authoring_indexes.get("dyes")
    if cached is not None:
        return cached
    pair = optional_pair(snapshot,"partprefabdyeslotinfo")
    raise_if_cancelled(stop_event,"Dye index cancelled.")
    rows = parse_prefab_dye_table(pair.payload,pair.header)
    raise_if_cancelled(stop_event,"Dye index cancelled.")
    result = DyeIndex(pair,MappingProxyType({row.model_path.casefold():row for row in rows}))
    snapshot._authoring_indexes["dyes"] = result
    return result


def prepare_dye_assignments(source_row, material, source_material, assignments, *, imported, mask_paths=None):
    bindings = material_dye_bindings(material)
    targets = {name for _index,name in bindings}
    if assignments is None:
        for part in source_row.submeshes:
            if part.name not in targets or any(not has_dye_wiring(wrapper) for (index,name),wrapper in bindings.items() if name == part.name):
                raise ValueError("Map the imported dye parts explicitly or clear dye assignments; the template wiring is incompatible.")
        return source_row.submeshes,material
    if not assignments:
        return (),material
    if len({entry.target_submesh for entry in assignments}) != len(assignments):
        raise ValueError("A target submesh has more than one dye assignment.")
    sources = {part.name:part for part in source_row.submeshes}
    parts = []
    for assignment in assignments:
        if assignment.source_submesh not in sources or assignment.target_submesh not in targets:
            raise ValueError("A dye mapping must use exact source and target submesh names.")
        if len(assignment.slots) != 3 or any(not -1 <= slot <= 11 for slot in assignment.slots):
            raise ValueError("Dye channels require three supported slot indices.")
        if imported and assignment.target_submesh != assignment.source_submesh and not (mask_paths or {}).get(assignment.target_submesh):
            raise ValueError("A renamed imported dye part needs an explicit RGB mask for its UV layout.")
        parts.append(replace(sources[assignment.source_submesh], name=assignment.target_submesh,slots=assignment.slots))
    material = copy_dye_materials(material,source_material,assignments,mask_paths or {})
    return tuple(parts),material


def plan_variant_dye(planner,old_model,new_model,material,choice,imported):
    snapshot = planner.snapshot
    if snapshot.sources is None or "partprefabdyeslotinfo" not in snapshot.sources.tables:
        if choice is not None and choice.dyes is not None:
            raise ValueError("The active game generation has no complete dye table.")
        return material
    index = load_dye_index(snapshot,stop_event=planner.stop_event)
    source = index.rows.get(old_model.casefold())
    assignments = choice.dyes if choice else None
    if source is None:
        if assignments:
            raise ValueError("This variant has no shipped dye preset to copy.")
        return material
    from cdmw.services.new_item_variants import xml_path
    source_material = snapshot.payload(xml_path(old_model))
    masks = {}
    for ordinal,assignment in enumerate(assignments or ()):
        if not assignment.mask_path:
            continue
        data = read_dye_mask(snapshot, assignment.mask_path)
        target = f"character/texture/{PurePosixPath(new_model).stem}_dye{ordinal}.dds"
        planner.add(snapshot.entry(old_model),target,data,f"Dye mask: {target}")
        masks[assignment.target_submesh] = target
    submeshes,material = prepare_dye_assignments(source,material,source_material,assignments,imported=imported,mask_paths=masks)
    row = source.for_model(new_model,submeshes=submeshes)
    pair = index.pair
    body,header = planner.table_data(pair)
    keys = {directory.row_id for directory in parse_pabgh_table(header,payload=body).rows}
    if row.key in keys:
        raise ValueError("The new model's dye identity collides with an existing record.")
    body,header = append_table_rows(body,header,[encode_prefab_dye_row(row)])
    planner.patch(pair.payload_entry,body,"DyeInfo: owned model/channel assignments")
    planner.patch(pair.header_entry,header,"DyeInfo directory")
    planner.manifest.setdefault("dyes",[]).append({"source_model":old_model,"model":new_model,"key":row.key,
        "submeshes":[{"name":part.name,"slots":list(part.slots),"tags":list(part.default.tags),
                      "property_overrides":[value.property_index for value in part.overrides]} for part in submeshes],"masks":masks})
    return material
