"""Frozen archive dependencies and retained material-pipeline integration."""

from __future__ import annotations

from dataclasses import replace
from collections import defaultdict
import hashlib
import re
from pathlib import Path
from tempfile import TemporaryDirectory

from cdmw.core.common import raise_if_cancelled
from cdmw.domain.mesh.replacement import ReplacementFile
from cdmw.services.mesh_replacement_import import archive_entry, archive_location


def _sidecar_text(data):
    from cdmw.core.archive_binary_preview import try_decode_text_like_archive_data
    text = try_decode_text_like_archive_data(data)
    if not text:
        raise ValueError("Replacement material sidecar is not readable text.")
    return text


def material_binding_names(state):
    """Exact wrapper identities from the target's captured material documents."""
    from cdmw.core.material_shader_controls import control_material_sources
    from cdmw.core.pac_xml_standard_material import find_material_wrappers
    target = state.target_path.replace("\\", "/").casefold()
    pac_xml = target.replace("/model/", "/modelproperty/", 1) + "_xml"
    files = {file.path.replace("\\", "/").casefold(): file
             for file in (*state.dependencies, *state.companion_files)}
    names = set()
    for path, file in files.items():
        if path == pac_xml or (not target.endswith(".pac") and path.endswith(".pami")):
            text = _sidecar_text(file.data)
            if path.endswith(".pac_xml"):
                names.update(row.submesh_name.casefold() for row in find_material_wrappers(text))
            else:
                names.update(control_material_sources(text, static=True))
    return names


def material_binding_name(part, names):
    """PAC wrappers bind the part name, not a possibly unrelated texture label."""
    for value in (part.name, part.material):
        if value and value.casefold() in names:
            return value.casefold()
    # Retain an unmatched identity so the strict writer reports the missing part.
    return (part.name or part.material).casefold()


def _merge_material_rows(current, donor, names):
    from cdmw.core.material_shader_controls import material_variant_blocks
    from cdmw.modding.material_sidecar_patching import _find_sidecar_material_wrapper_exact

    variants = material_variant_blocks(current)
    donor_variants = material_variant_blocks(donor)
    if variants or donor_variants:
        def indexed(blocks):
            result = {}
            for block in blocks:
                index = re.search(r'\bIndex="(\d+)"', block.group().partition(">")[0])
                if index is None or int(index.group(1)) in result:
                    raise ValueError("Material mapping has an ambiguous model-property index.")
                result[int(index.group(1))] = block
            return result

        before_variants, after_variants = indexed(variants), indexed(donor_variants)
        if before_variants.keys() != after_variants.keys():
            raise ValueError("Material mapping changed the target model-property variants.")
        edits = []
        for index, before in before_variants.items():
            after = after_variants[index].group()
            start, end = before.start() + before.group().find(">") + 1, before.end() - len("</ModelProperty>")
            text, changed = _merge_material_rows(current[start:end], after[after.find(">") + 1:-len("</ModelProperty>")], names)
            if changed:
                edits.append((start, end, text))
        for start, end, text in sorted(edits, reverse=True):
            current = current[:start] + text + current[end:]
        return current, bool(edits)

    edits = []
    for name in names:
        before = _find_sidecar_material_wrapper_exact(current, name)
        after = _find_sidecar_material_wrapper_exact(donor, name)
        if before is None and after is None:
            continue
        if (before is None or after is None
                or _find_sidecar_material_wrapper_exact(current[before.end():], name)
                or _find_sidecar_material_wrapper_exact(donor[after.end():], name)):
            raise ValueError(f"Material mapping is not an unambiguous target wrapper: {name}")
        edits.append((before.start(), before.end(), after.group(0)))
    for start, end, text in sorted(set(edits), reverse=True):
        current = current[:start] + text + current[end:]
    return current, bool(edits)


def _target_material_names(pending, targets):
    from cdmw.modding.mesh_parser import parse_mesh
    original = parse_mesh(pending.snapshot.original_data, pending.state.target_path)
    selected = {part.target_index for part in pending.state.parts if part.part_id in targets}
    bindings = material_binding_names(pending.state)
    owners = {index: material_binding_name(part, bindings) for index, part in enumerate(original.submeshes)}
    names = {owners[index] for index in selected}
    if any(owner in names for index, owner in owners.items() if index not in selected):
        raise ValueError("Selected parts share a material with an untouched part. Select all parts using that material.")
    return names


def _prune_unreferenced_generated_files(files):
    sidecars = "\n".join(_sidecar_text(file.data).casefold() for file in files.values() if Path(file.path).suffix.lower() in {".pac_xml", ".pami"})
    return tuple(file for key, file in sorted(files.items())
                 if Path(file.path).suffix.lower() != ".dds" or key in sidecars)


def restore_original_materials(pending, targets):
    files = {file.path.casefold(): file for file in pending.state.companion_files}
    if not files or not any(part.material_choice == "imported" and part.part_id in targets for part in pending.state.parts):
        return pending.state.companion_files
    names = _target_material_names(pending, targets)
    for baseline in pending.state.dependencies:
        key = baseline.path.casefold()
        if key not in files or Path(key).suffix not in {".pac_xml", ".pami"}:
            continue
        text, changed = _merge_material_rows(_sidecar_text(files[key].data), _sidecar_text(baseline.data), names)
        if changed:
            if text == _sidecar_text(baseline.data):
                del files[key]
            else:
                files[key] = replace(files[key], data=text.encode("utf-8"))
    return _prune_unreferenced_generated_files(files)


def capture_replacement_dependencies(entry, context, stop_event=None):
    if entry is None or context is None:
        raise ValueError("The archive target and its dependency snapshot are required for replacement.")
    from cdmw.core.archive_extraction import read_archive_entry_data
    from cdmw.core.archive_model_references import (
        _find_archive_model_sidecar_entries, _extract_archive_model_sidecar_texture_references,
    )
    by_name = dict(context.entries_by_basename)
    by_path = context.entries_by_normalized_path
    selected = list(_find_archive_model_sidecar_entries(entry, by_name))
    bindings, _, _, _ = _extract_archive_model_sidecar_texture_references(
        entry, archive_entries_by_basename=by_name, stop_event=stop_event)
    for binding in bindings:
        path = str(binding.texture_path).replace("\\", "/").strip("/").casefold()
        matches = tuple(by_path.get(path, ())) or tuple(by_name.get(Path(path).name, ()))
        if len({match.path.casefold() for match in matches}) > 1:
            raise ValueError(f"Ambiguous original material dependency: {binding.texture_path}")
        if matches:
            selected.append(matches[0])
    if entry.extension == ".pam":
        selected.extend(by_path.get(Path(entry.path).with_suffix(".pamlod").as_posix().casefold(), ()))
    result, seen, total = [], set(), 0
    for dependency in selected:
        raise_if_cancelled(stop_event, "Replacement dependency capture cancelled.")
        key = dependency.path.replace("\\", "/").casefold()
        if key in seen:
            continue
        seen.add(key)
        data, _, _ = read_archive_entry_data(dependency, stop_event=stop_event)
        total += len(data)
        if total > 512 * 1024 * 1024:
            raise ValueError("Replacement dependencies exceed the 512 MiB snapshot limit.")
        result.append(ReplacementFile(dependency.path, bytes(data), archive_location(dependency)))
    return tuple(result)


def prepare_imported_materials(pending, targets, resource_root, stop_event=None, *, surface=None, skin_policy=None):
    """Use retained routing/conversion, but refuse every unresolved result.

    Only explicitly mapped target materials enter the retained generator.
    Global donor resets and pruning are disabled, including selected-part use.
    ``surface`` is an optional (roughness, metallic) pair in 0..1; when either
    is above 0 the replaced wrappers get it as a uniform layer R.
    ``skin_policy`` is the weights choice Apply will use. The materials are built
    over the same composed model, and a rig that cannot be kept has no default.
    """
    from cdmw.core.archive_mesh_import_build_state import MeshImportBuildState
    from cdmw.core.archive_mesh_import_build_stages import resolve_mesh_import_sidecars, collect_mesh_import_references
    from cdmw.core.archive_mesh_import_materials import configure_mesh_import_materials, build_static_texture_payloads
    from cdmw.core.archive_mesh_import_supplemental import _collect_original_mesh_sidecar_texts
    from cdmw.core.archive_mesh_import_preview import parsed_mesh_to_preview_model
    from cdmw.modding.mesh_parser import parse_mesh
    from cdmw.modding.static_mesh_replacer import StaticSubmeshMapping
    from cdmw.services.mesh_replacement_import import compose_import, verify_import_sources
    from cdmw.services.mesh_replacement_output import manual_replacement_options, prepare_replacement_output

    verify_import_sources(pending, include_materials=True)
    if len(targets) != len(pending.source.mesh.submeshes) or len(set(targets)) != len(targets):
        raise ValueError("Imported materials require one source material part per target part.")
    if not pending.state.dependencies:
        raise ValueError("Imported materials require the original material sidecar and texture dependencies.")
    names = _target_material_names(pending, targets)
    candidate, candidate_state = compose_import(pending, targets, material_choice="imported", companion_files=(),
                                                skin_policy=skin_policy)
    geometry = prepare_replacement_output(replace(pending.snapshot, mesh=candidate, replacement_state=candidate_state))
    original = parse_mesh(pending.snapshot.original_data, pending.state.target_path)
    bindings = material_binding_names(pending.state)
    rows = {part.part_id: part for part in pending.state.parts}
    mappings = [StaticSubmeshMapping(rows[key].target_index, material_binding_name(original.submeshes[rows[key].target_index], bindings),
                                   [index], rows[key].target_index) for index, key in enumerate(targets)]
    options = manual_replacement_options(mappings)
    options.rebuild_material_sidecar = True
    options.material_mapping_mode = "source_driven_materials"
    options.auto_brightness_balance = 0.0
    # The target's detail, grime, colour-blend and tint layers are painted for
    # the original UV layout. Left in, they draw over the imported texture on
    # the import's own UVs; Archive Browser's material replacements drop them too.
    options.neutralize_inherited_material_layers = True
    # A failed original-material lookup must never become a geometry-only success.
    with TemporaryDirectory(prefix="cdmw-replacement-materials-") as temporary:
        directory = Path(temporary)
        by_path, by_name = defaultdict(list), defaultdict(list)
        previous_files = {file.path.casefold(): file for file in pending.state.companion_files}
        for index, baseline in enumerate(pending.state.dependencies):
            file = previous_files.get(baseline.path.casefold(), baseline)
            item = archive_entry(baseline)
            path = directory / f"dependency-{index}{Path(file.path).suffix}"
            path.write_bytes(file.data)
            item = replace(item, prepared_path=path, prepared_sha256=hashlib.sha256(file.data).hexdigest(), prepared_size=len(file.data))
            by_path[file.path.replace("\\", "/").casefold()].append(item)
            by_name[Path(file.path).name.casefold()].append(item)
        target = archive_entry(ReplacementFile(pending.state.target_path, pending.snapshot.original_data, pending.state.target_location))
        if target is None:
            raise ValueError("Imported materials require a captured archive target identity.")
        state = MeshImportBuildState(
            target, Path(pending.source_path), "static_replacement", options, pending.source,
            Path(pending.source_path).name, by_path, by_path, by_name, "mesh_base_first", (), stop_event,
        )
        state.original_data = pending.snapshot.original_data
        state.original_mesh = original
        state.imported_mesh = state.effective_static_source_mesh = pending.source.mesh
        state.normalized_import_mode = "static_replacement"
        state.static_mappings = mappings
        state.rebuilt_data = geometry.data
        state.parsed_mesh = parse_mesh(geometry.data, pending.state.target_path)
        # The retained material builder routes by ``material``. Supply the exact
        # sidecar owner on this detached metadata copy, leaving PAC bytes intact.
        for part in state.parsed_mesh.submeshes:
            part.material = material_binding_name(part, bindings)
        state.preview_model = parsed_mesh_to_preview_model(state.parsed_mesh)
        state.original_sidecars_for_static = _collect_original_mesh_sidecar_texts(target, by_name, stop_event=stop_event)
        if not state.original_sidecars_for_static:
            raise ValueError("Imported materials require a readable target material sidecar (.pac_xml or .pami).")
        state.resolved_supplemental_files = tuple(pending.source.discovered_texture_files)
        for path in state.resolved_supplemental_files:
            if not Path(path).is_file():
                raise ValueError(f"Missing imported texture: {path}")
        resolve_mesh_import_sidecars(state)
        collect_mesh_import_references(state)
        state.texture_references = tuple(reference for reference in state.texture_references
                                         if reference.material_name.casefold() in names or reference.part_name.casefold() in names)
        configure_mesh_import_materials(state)
        payloads, report = build_static_texture_payloads(state, state.original_sidecars_for_static)
        raise_if_cancelled(stop_event, "Replacement material preparation cancelled.")
        if report is None or report.errors:
            raise ValueError("Imported material conversion failed: " + ("; ".join(report.errors) if report else "no representable source material textures"))
        if not payloads:
            raise ValueError("Imported materials produced no output textures or sidecars; original-material fallback is disabled.")
        outputs = {str(payload.target_path).casefold(): payload for payload in payloads}
        mapped_sources = {str(getattr(slot, "source_material_name", "") or "").casefold() for slot in report.slot_mappings}
        for part in pending.source.mesh.submeshes:
            if str(part.material or part.name).casefold() not in mapped_sources:
                raise ValueError(f"Imported material {part.material or part.name} has no proven target binding.")
        slots = [slot for slot in report.slot_mappings if slot.target_material_name.casefold() in names]
        for slot in slots:
            target_path = str(getattr(slot, "output_texture_path", "") or "").casefold()
            if not target_path or target_path not in outputs:
                raise ValueError(f"Missing required generated texture: {target_path or 'unresolved material slot'}")
        files = dict(previous_files)
        renames = {}
        for slot in slots:
            old = slot.output_texture_path
            payload = outputs[old.casefold()]
            identity = hashlib.sha256(("|".join(sorted(targets)) + old).encode() + payload.payload_data).hexdigest()[:16]
            new = str(Path(old).with_name(f"{Path(old).stem}_cdmw_{identity}.dds")).replace("\\", "/")
            renames[old] = new
            files[new.casefold()] = ReplacementFile(new, bytes(payload.payload_data))
        merged = False
        merged_keys = []
        for payload in payloads:
            if Path(payload.target_path).suffix.lower() not in {".pac_xml", ".pami"}:
                continue
            matches = by_path.get(str(payload.target_path).casefold(), ())
            item = matches[0] if matches else None
            baseline = next((text for entry, text in state.original_sidecars_for_static if entry.path.casefold() == str(payload.target_path).casefold()), None)
            if baseline is None:
                raise ValueError(f"Generated material sidecar has no captured target: {payload.target_path}")
            donor = _sidecar_text(payload.payload_data)
            for old, new in renames.items():
                donor = donor.replace(old, new)
            text, changed = _merge_material_rows(baseline, donor, names)
            merged |= changed
            if changed:
                files[str(payload.target_path).casefold()] = ReplacementFile(str(payload.target_path), text.encode("utf-8"),
                                                                             archive_location(item) if item else None)
                merged_keys.append(str(payload.target_path).casefold())
        if not merged:
            raise ValueError("Imported materials have no proven target sidecar wrapper mapping.")
        if surface is not None and any(float(value) > 0 for value in surface):
            _apply_imported_surface(files, merged_keys, names, pending.state.target_path, surface)
        return _prune_unreferenced_generated_files(files)


def _apply_imported_surface(files, sidecar_keys, names, target_path, surface):
    """Write the chosen roughness/metalness as the replaced wrappers' layer R."""
    from cdmw.core.pac_xml_surface_layer import apply_surface_layer, surface_byte, surface_layer_dds

    roughness, metallic = (surface_byte(value) for value in surface)
    model = target_path.replace("\\", "/")
    folder = "character/texture" if "/character/" in f"/{model}" else str(Path(model).parent).replace("\\", "/")
    path = f"{folder}/{Path(model).stem}_cdmw_surface_{roughness:03d}_{metallic:03d}.dds"
    applied = 0
    for key in sidecar_keys:
        if not key.endswith(".pac_xml"):
            continue
        file = files[key]
        text, changed = apply_surface_layer(_sidecar_text(file.data), names, path)
        if changed:
            files[key] = replace(file, data=text.encode("utf-8"))
            applied += changed
    if not applied:
        raise ValueError("Roughness and Metallic found no replaced equipment material to apply to.")
    files[path.casefold()] = ReplacementFile(path, surface_layer_dds(roughness / 255, metallic / 255))


def _image_channel_means(path, channels):
    from PIL import Image
    with Image.open(path) as image:
        image.thumbnail((256, 256))
        rgb = image.convert("RGB")
    stats = [sum(value * count for value, count in enumerate(rgb.getchannel(c).histogram())) / max(1, rgb.width * rgb.height)
             for c in "RGB"]
    return tuple(stats["RGB".index(c)] / 255 for c in channels)


def imported_surface_defaults(pending):
    """The imported model's own roughness and metalness, averaged, as slider starting values.

    Uses OBJ map_Pr/map_Pm (or Pr/Pm) and glTF roughness/metalness or packed
    metallic-roughness maps. Missing values stay None (the slider starts at 0).
    """
    used = {str(part.material or part.name or "").casefold() for part in pending.source.mesh.submeshes}
    found = {"roughness": [], "metallic": []}
    source = Path(pending.source_path)
    try:
        if source.suffix.lower() == ".obj":
            from cdmw.modding.scene_texture_discovery import _obj_material_parameters, _obj_material_texture_slots
            slots = {name.casefold(): value for name, value in _obj_material_texture_slots(source).items()}
            factors = {name.casefold(): value for name, value in _obj_material_parameters(source).items()}
            for material in used:
                kinds = {slot.slot_kind: slot.path for slot in slots.get(material, ())}
                values = {parameter.parameter_name: parameter.numeric_value for parameter in factors.get(material, ())}
                for key, kind, factor, channel in (("roughness", "roughness", "_roughnessFactor", "G"),
                                                   ("metallic", "metalness", "_metallicFactor", "B")):
                    if kind in kinds and Path(kinds[kind]).is_file():
                        found[key].append(_image_channel_means(kinds[kind], "R")[0])
                    elif "material" in kinds and Path(kinds["material"]).is_file():
                        found[key].append(_image_channel_means(kinds["material"], channel)[0])
                    elif values.get(factor) is not None:
                        found[key].append(float(values[factor]))
        else:
            for binding in getattr(pending.source, "material_bindings", ()) or ():
                if str(binding.material_name or "").casefold() not in used:
                    continue
                kinds = {str(role).casefold(): texture for role, texture in binding.texture_slots}
                for key, kind, channel in (("roughness", "roughness", "G"), ("metallic", "metalness", "B")):
                    if kind in kinds and Path(kinds[kind]).is_file():
                        found[key].append(_image_channel_means(kinds[kind], "R")[0])
                    elif "material" in kinds and Path(kinds["material"]).is_file():
                        found[key].append(_image_channel_means(kinds["material"], channel)[0])
    except (OSError, ValueError):
        return {"roughness": None, "metallic": None}
    return {key: (round(sum(values) / len(values), 3) if values else None) for key, values in found.items()}
