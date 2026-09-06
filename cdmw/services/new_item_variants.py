"""Exact prefab/model variant ownership and independent imported builds."""
from dataclasses import dataclass, replace
import hashlib
from pathlib import PurePosixPath

from cdmw.core.item_model_family import FamilyFile
from cdmw.core.pappt_format import insert_part_prefabs, encode_pappt
from cdmw.core.prefab_binary_edit import rewrite_prefab_paths_any_length
from cdmw.core.stringinfo_table import append_stringinfo_strings, stringinfo_key
from cdmw.domain.new_item.spec import MaterialRoute


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
        validate_variant_rig(snapshot, appearance.model_path, files.pac_data)
        result[appearance.identity] = files
    return result


def validate_variant_rig(snapshot, target_path, payload):
    """Require the target's actual skin palette; never borrow another character's rig."""
    from cdmw.modding.mesh_parser import parse_pac, pac_bone_palette_candidates, resolve_pac_bone_palette
    from cdmw.modding.skeleton_parser import parse_pab
    original = snapshot.payload(target_path)
    mesh = parse_pac(payload, target_path)
    if not mesh.total_vertices:
        raise ValueError("The variant import contains no supported mesh geometry.")
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
    parts = target_path.replace("\\", "/").split("/")
    if "1_pc" not in parts:
        raise ValueError("This skinned target has no proven playable-character rig binding.")
    marker = parts.index("1_pc")
    prefix = "/".join(parts[:marker+2]) + "/"
    matches = []
    for path in snapshot.entries:
        if path.startswith(prefix.casefold()) and path.endswith(".pab"):
            skeleton = parse_pab(snapshot.payload(path), path)
            if skeleton.parser_mode != "fixed" or skeleton.parse_warning:
                continue
            palette = resolve_pac_bone_palette(original,skeleton)
            if palette:
                if resolve_pac_bone_palette(payload,skeleton) != palette:
                    raise ValueError("The import's skin palette differs from the selected variant's target rig.")
                matches.append((path,palette))
    if len(matches) != 1:
        raise ValueError("The selected variant's skeleton is missing or ambiguous.")
    limit = len(matches[0][1])
    for part in mesh.submeshes:
        for indices, weights in zip(part.bone_indices,part.bone_weights):
            if any(weight > 0 and not 0 <= index < limit for index,weight in zip(indices,weights)):
                raise ValueError("The imported skin weights reference bones outside the target palette.")
    return matches[0][0]


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
