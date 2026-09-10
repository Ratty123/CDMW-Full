"""Exact prefab/model variant ownership and independent imported builds."""
from dataclasses import dataclass, replace
import hashlib
from pathlib import PurePosixPath

from cdmw.core.item_model_family import FamilyFile
from cdmw.core.pappt_format import insert_part_prefabs, encode_pappt
from cdmw.core.prefab_binary_edit import rewrite_prefab_paths_any_length
from cdmw.core.stringinfo_table import append_stringinfo_strings, stringinfo_key
from cdmw.domain.new_item.spec import MaterialRoute


class _SkinPaletteBoundsError(ValueError):
    """A resolved palette cannot represent the imported influence rows."""


def xml_path(model_path):
    return model_path.replace("character/model/", "character/modelproperty/").removesuffix(".pac") + ".pac_xml"


def variant_bindings(family):
    return tuple((part, path) for part in family.parts if part.record is not None for path in part.pac_paths)


def variant_family(family, appearance):
    part = next((p for p, path in variant_bindings(family) if (p.prefab_path.casefold(), path.casefold()) == appearance.identity), None)
    if part is None:
        raise ValueError("The selected variant is not an exact prefab/model binding of this item.")
    path = appearance.model_path
    folder = path.removeprefix("character/model/").rsplit("/",1)[0]
    files = (FamilyFile("pac",path,True), FamilyFile("pac_xml",xml_path(path),True), FamilyFile("prefab",part.prefab_path,True))
    return replace(family, model_stem=PurePosixPath(path).stem, model_folder=folder, parts=(part,),files=files)


def _has_exact_socket_attachment(prefab_data, target_path):
    from cdmw.core.archive_attachment_patches import inspect_prefab_attachment_profile_fields

    if not prefab_data:
        return False
    profile = {field.field_name: field.value for field in inspect_prefab_attachment_profile_fields(prefab_data)}
    return (
        profile.get("_skinnedMeshFileName", "").replace("\\", "/").casefold()
        == target_path.replace("\\", "/").casefold()
        and all(profile.get(name) for name in ("_attachedSocketName", "_pivotSocketName", "_socketFileName"))
    )


def bind_static_import_to_attachment(mesh, target_path, prefab_data):
    """Keep an unrigged import on its exact socket instead of transferring accessory skin."""
    from cdmw.modding.mesh_deformer import copy_extra_submesh_attrs
    from cdmw.modding.mesh_skinning import SOURCE_VERTEX_MAP_TOPOLOGY

    if (mesh.has_bones or any(part.bone_indices or part.bone_weights or part.source_bone_palette
                             or part.source_skin_weight_layout for part in mesh.submeshes)
            or not _has_exact_socket_attachment(prefab_data, target_path)):
        return mesh
    bound_parts = []
    for part in mesh.submeshes:
        bound = replace(part)
        # Material factors and texture inputs live outside the dataclass fields.
        # Keep them when adding the socket weights so export sees the same source.
        copy_extra_submesh_attrs(part, bound)
        bound.bone_indices = [(0,)] * len(part.vertices)
        bound.bone_weights = [(1.0,)] * len(part.vertices)
        bound.source_vertex_map = []
        bound.source_vertex_map_authority = SOURCE_VERTEX_MAP_TOPOLOGY
        bound_parts.append(bound)
    return replace(mesh, has_bones=True, submeshes=bound_parts)


def prepare_variant_models(spec, snapshot, models, scenes, *, on_log=None, stop_event=None):
    from cdmw.domain.cancellation import raise_if_cancelled
    from cdmw.services.new_item_materials import route_model_files
    from cdmw.services.new_item_planning import ModelFiles, model_files_from_import
    result = {}
    for appearance in spec.variants or ():
        raise_if_cancelled(stop_event, "Variant preparation cancelled.")
        family = variant_family(snapshot.family(spec.template_key), appearance)
        model = models.get(appearance.identity)
        if not appearance.custom_model:
            continue
        if model is None:
            raise ValueError(f"Apply the imported model for {appearance.model_path} before planning.")
        if isinstance(model, ModelFiles):
            files = model
        else:
            files = model_files_from_import(model, family=family)
            files = route_model_files(files, MaterialRoute(appearance.material_route), result=model,
                                      scene=scenes.get(appearance.identity), glow=appearance.glow_choice(), on_log=on_log)
        try:
            validate_variant_rig(snapshot, appearance.model_path, files.pac_data, prefab_path=appearance.prefab_path)
        except _SkinPaletteBoundsError:
            source = getattr(scenes.get(appearance.identity), "mesh", None)
            if (isinstance(model, ModelFiles) or "/armor/" not in appearance.model_path.replace("\\", "/").casefold()
                    or source is None or source.has_bones or not source.submeshes
                    or any(part.bone_indices or part.bone_weights or part.source_bone_palette
                           or part.source_skin_weight_layout for part in source.submeshes)):
                raise
            if appearance.keep_template_physics:
                raise ValueError("Turn off Template cloth / physics to transfer this armour's weights from the character body.") from None
            from cdmw.services.new_item_skinning import rebind_armour_from_body
            files = rebind_armour_from_body(snapshot, appearance.model_path, files, stop_event=stop_event)
            validate_variant_rig(snapshot, appearance.model_path, files.pac_data, prefab_path=appearance.prefab_path)
        result[appearance.identity] = files
    return result


def validate_variant_rig(snapshot, target_path, payload, *, prefab_path=""):
    """Preserve an exact attachment or require the target's actual skin palette."""
    from cdmw.core.skeleton_resolver import resolve_skeleton_for_model
    from cdmw.modding.mesh_parser import parse_pac, resolve_pac_bone_palette
    from cdmw.modding.skeleton_parser import parse_pab
    original = snapshot.payload(target_path)
    mesh = parse_pac(payload, target_path)
    if not mesh.total_vertices:
        raise ValueError("The variant import contains no supported mesh geometry.")
    if payload == original:
        return "unchanged template binding"
    target_mesh = parse_pac(original, target_path)

    def rigid(value):
        return bool(value.submeshes) and all(
            len(part.bone_indices) == len(part.vertices) and len(part.bone_weights) == len(part.vertices)
            and all(tuple((index,weight) for index,weight in zip(indices,weights) if weight > 0) == ((0,1.0),)
                    for indices,weights in zip(part.bone_indices,part.bone_weights))
            for part in value.submeshes)

    if rigid(target_mesh):
        if not rigid(mesh):
            raise ValueError("The rigid target requires its single attachment slot; this import changes the skin binding.")
        return "rigid prefab attachment"
    if prefab_path and rigid(mesh):
        # A socket-attached weapon can contain weighted accessories without a
        # character PAB. A rigid replacement keeps the selected prefab's slot;
        # the discarded accessory weights do not give the import a body rig.
        if _has_exact_socket_attachment(snapshot.payload(prefab_path), target_path):
            return "rigid prefab attachment"
    by_path, by_basename = snapshot.archive_index_maps()
    selected, _report = resolve_skeleton_for_model(
        snapshot.entry(target_path), archive_entries_by_normalized_path=by_path,
        archive_entries_by_basename=by_basename, pac_data=original,
        read_entry_data=lambda entry: snapshot.payload(entry.path),
    )
    if selected is None:
        raise ValueError("The selected variant's skeleton is missing or ambiguous.")
    skeleton = parse_pab(snapshot.payload(selected.path), selected.path)
    palette = resolve_pac_bone_palette(original, skeleton)
    if skeleton.parser_mode != "fixed" or skeleton.parse_warning or not palette:
        raise ValueError("The selected variant's skeleton is missing or ambiguous.")
    if resolve_pac_bone_palette(payload, skeleton) != palette:
        raise ValueError("The import's skin palette differs from the selected variant's target rig.")
    limit = len(palette)
    for part in mesh.submeshes:
        for indices, weights in zip(part.bone_indices,part.bone_weights):
            if any(weight > 0 and not 0 <= index < limit for index,weight in zip(indices,weights)):
                raise _SkinPaletteBoundsError("The imported skin weights reference bones outside the target palette.")
    return selected.path


@dataclass
class VariantPlan:
    settings: tuple
    stem_map: dict
    models: dict


def _allocate_variant_stems(planner, parts):
    from cdmw.core.archive_format import hashlittle
    parts = tuple(parts)
    if not parts:
        return {}
    snapshot = planner.snapshot
    string_keys = set(snapshot.stringinfo_texts)
    names = set(snapshot.pappt.index())
    dye_keys = set()
    if snapshot.sources and "partprefabdyeslotinfo" in snapshot.sources.tables:
        from cdmw.services.new_item_dyes import load_dye_index
        dye_keys.update(row.key for row in load_dye_index(snapshot,stop_event=planner.stop_event).rows.values())
    mapping = {}
    for part in parts:
        suffix = hashlib.sha256(part.prefab_path.casefold().encode()).hexdigest()[:8]
        preferred = f"{planner.new_stem}_v{suffix}"
        for attempt in range(1000):
            planner.check()
            stem = preferred if attempt == 0 else f"{preferred}_{attempt+1}"
            models = tuple(str(PurePosixPath(path).with_name(f"{stem}_m{ordinal}.pac")) for ordinal,path in enumerate(part.pac_paths))
            hashes = {hashlittle(path.encode("utf-8"),0xC5EDE) for path in models}
            paths = [part.record.cloned(stem).prefab_path]
            for path in models:
                paths.extend((path,xml_path(path),path.replace("character/model/","character/bin__/meshphysics/").removesuffix(".pac")+".hkx"))
            if (stem in names or stringinfo_key(stem) in string_keys or hashes & dye_keys
                    or len(hashes) != len(models) or any(snapshot.has_entry(path) for path in paths)):
                continue
            mapping[part.stem] = stem
            names.add(stem)
            string_keys.add(stringinfo_key(stem))
            dye_keys.update(hashes)
            break
        else:
            raise ValueError("No collision-free identity is available for the selected variant.")
    return mapping


def prepare_variant_plan(planner):
    if planner.spec.variants is None:
        return None
    choices = tuple(planner.spec.variants)
    if len({value.identity for value in choices}) != len(choices):
        raise ValueError("A variant binding can be selected only once.")
    parts = {part.prefab_path.casefold():part for part in planner.family.parts if part.record is not None}
    selected_parts = {}
    for value in choices:
        variant_family(planner.family,value)
        part = parts[value.prefab_path.casefold()]
        selected_parts[part.stem] = part
    mapping = _allocate_variant_stems(planner,selected_parts.values())
    # Effects on other bindings remain explicit: the selected variants receive the
    # item effect and every unselected binding retains its shipped appearance.
    return VariantPlan(choices,mapping,dict(planner.variant_models))


def plan_variant_records(planner):
    variants = planner.variant_plan
    if not variants or not variants.stem_map:
        return
    texts = list(variants.stem_map.values())
    pair = planner.snapshot.stringinfo
    body, header, _keys = append_stringinfo_strings(*planner.table_data(pair),texts,name="stringinfo")
    planner.patch(pair.payload_entry,body,"StringInfo: variant identities")
    planner.patch(pair.header_entry,header,"Variant identity directory")
    index = planner.snapshot.pappt.index()
    rows = [index[old].cloned(new) for old,new in variants.stem_map.items()]
    table = insert_part_prefabs(planner.snapshot.pappt,rows,after_stem=next(iter(variants.stem_map)))
    planner.patch(planner.snapshot.pappt_entry,encode_pappt(table),"PartPrefab: selected variant copies")
    planner.manifest["pappt_records"] = dict(variants.stem_map)


def plan_variant_files(planner):
    from cdmw.services.new_item_dyes import plan_variant_dye
    variants, snapshot = planner.variant_plan, planner.snapshot
    by_prefab = {}
    for choice in variants.settings:
        by_prefab.setdefault(choice.prefab_path.casefold(),{})[choice.model_path.casefold()] = choice
    manifest, written = [], []
    donor = planner._effect_donor()
    for part in planner.family.parts:
        selected = by_prefab.get(part.prefab_path.casefold())
        if not selected:
            for path in part.pac_paths:
                manifest.append({"prefab_path":part.prefab_path,"model_path":path,"appearance":"template"})
            continue
        new_stem = variants.stem_map[part.stem]
        paths = {}
        for ordinal, old in enumerate(part.pac_paths):
            planner.check()
            choice = selected.get(old.casefold())
            stem = f"{new_stem}_m{ordinal}"
            new = str(PurePosixPath(old).with_name(stem+".pac"))
            paths[old] = new
            model = variants.models.get(choice.identity) if choice else None
            imported = choice is not None and choice.custom_model
            if imported and model is None:
                raise ValueError(f"No applied model for {old}")
            if imported:
                planner.summary.extend(f"  {old}: {note}" for note in model.notes)
                planner.warnings.extend(f"{old}: {warning}" for warning in model.warnings)
            payload = model.pac_data if imported else snapshot.payload(old)
            planner.add(snapshot.entry(old),new,payload,f"Variant model: {new}")
            written.append(new)
            source_xml, new_xml = xml_path(old),xml_path(new)
            side = dict(model.side_files) if model is not None else {}
            material = side.get(source_xml)
            if material is None and snapshot.has_entry(source_xml):
                material = snapshot.payload(source_xml)
            texture_map = {}
            for index,(path,data) in enumerate(side.items()):
                if not path.lower().endswith(".dds"):
                    continue
                target = str(PurePosixPath(path).with_name(f"{stem}_t{index}.dds"))
                planner.add(snapshot.entry(path) if snapshot.has_entry(path) else snapshot.entry(old),target,data,f"Variant texture: {target}")
                texture_map[path] = target
                written.append(target)
            if material is not None:
                for old_path,new_path in texture_map.items():
                    material = material.replace(old_path.encode(),new_path.encode())
                material = plan_variant_dye(planner,old,new,material,choice,imported)
                planner.add(snapshot.entry(source_xml) if snapshot.has_entry(source_xml) else snapshot.entry(old),new_xml,material,f"Variant material: {new_xml}")
                written.append(new_xml)
            elif choice is not None and choice.dyes:
                raise ValueError("Dye authoring requires a complete model material file.")
            physics = old.replace("character/model/","character/bin__/meshphysics/").removesuffix(".pac")+".hkx"
            if snapshot.has_entry(physics) and (not imported or choice.keep_template_physics):
                target = str(PurePosixPath(physics).with_name(stem+".hkx"))
                planner.add(snapshot.entry(physics),target,snapshot.payload(physics),f"Variant physics: {target}")
                written.append(target)
            manifest.append({"prefab_path":part.prefab_path,"model_path":old,"output_model":new,
                             "appearance":"custom model" if imported else "owned template copy",
                             "companion":choice is None,"material_route":model.material_route if model else "template"})
        target = part.record.cloned(new_stem).prefab_path
        result = rewrite_prefab_paths_any_length(snapshot.payload(part.prefab_path),paths)
        if not result.edits:
            raise ValueError("The selected variant prefab has no exact model binding to repoint.")
        payload = planner._graft_effect(result.data,donor,target) if donor is not None else result.data
        planner.add(snapshot.entry(part.prefab_path),target,payload,f"Variant prefab: {target}")
        written.append(target)
    planner.manifest["variants"] = manifest
    planner.manifest["model_files"] = written
