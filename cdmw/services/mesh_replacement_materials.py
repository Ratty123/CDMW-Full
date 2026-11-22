"""Frozen archive dependencies and retained material-pipeline integration."""

from __future__ import annotations

from dataclasses import replace
from collections import defaultdict
import hashlib
import io
import re
from pathlib import Path
from tempfile import TemporaryDirectory

from cdmw.core.common import raise_if_cancelled
from cdmw.domain.mesh.replacement import ReplacementFile
from cdmw.services.mesh_replacement_import import archive_entry, archive_location


def _sidecar_text(data):
    from cdmw.core.archive_binary_preview import try_decode_text_like_archive_data
    text = try_decode_text_like_archive_data(data, limit=None)
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
                # A few shipped names carry a stray space; texture references do not.
                names.update(row.submesh_name.strip().casefold() for row in find_material_wrappers(text))
            else:
                names.update(control_material_sources(text, static=True))
    return names


def material_binding_name(part, names):
    """PAC wrappers bind the part name, not a possibly unrelated texture label."""
    for value in (part.name, part.material):
        if value and value.strip().casefold() in names:
            return value.strip().casefold()
    # Retain an unmatched identity so the strict writer reports the missing part.
    return (part.name or part.material).strip().casefold()


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


def helper_material_targets(pending, targets=None):
    """Target parts bound to a helper wrapper (``*_inside``, ``*_black``), by part id.

    Imported textures are never routed to these wrappers; they shade a helmet's
    inside and keep the game's own material.
    """
    from cdmw.modding.material_replacer import is_static_replacement_helper_material_name
    from cdmw.modding.mesh_parser import parse_mesh
    wanted = set(pending.target_part_ids if targets is None else targets)
    original = parse_mesh(pending.snapshot.original_data, pending.state.target_path)
    bindings = material_binding_names(pending.state)
    helpers = {}
    for part in pending.state.parts:
        if part.part_id not in wanted:
            continue
        source = original.submeshes[part.target_index]
        name = material_binding_name(source, bindings)
        if is_static_replacement_helper_material_name(name):
            helpers[part.part_id] = source.name or name
    return helpers


def _check_helper_targets(pending, targets):
    """Refuse an imported part whose only target is a helper wrapper, naming both."""
    helpers = helper_material_targets(pending, targets)
    if not helpers:
        return
    sources = pending.source.mesh.submeshes
    routed = {_folded(part.material or part.name)
              for part, target in zip(sources, targets) if target not in helpers}
    for part, target in zip(sources, targets):
        if target in helpers and _folded(part.material or part.name) not in routed:
            raise ValueError(
                f"{helpers[target]} is a helper material for the inside of the model and cannot take imported textures. "
                f"Map {part.name or part.material} to a main part, join it with one before exporting, "
                "or choose Keep Original Materials.")


_TEXTURE_REFERENCE = re.compile(r'<MaterialParameterTexture\b[^>]*>\s*<ResourceReferencePath_ITexture\b[^>]*\b_path="([^"]+)"')


def _folded(value):
    """A material or part name as the pipeline compares it: trimmed and case-folded."""
    return str(value or "").strip().casefold()


def _wrapper_texture_paths(pending):
    """Texture paths each target wrapper names in the game's material file, over all its variants."""
    from cdmw.core.pac_xml_standard_material import find_material_wrappers
    sidecar = target_sidecar(pending)
    paths = defaultdict(set)
    if sidecar is not None:
        text = _sidecar_text(sidecar.data)
        for wrapper in find_material_wrappers(text):
            # Any texture reference in the block counts, however its row is written.
            paths[_folded(wrapper.submesh_name)].update(_TEXTURE_REFERENCE.findall(text[wrapper.start:wrapper.end]))
    return paths


def _target_part_names(pending, targets=None):
    """part id -> (the game's part name, its material wrapper name) for the wanted target parts."""
    from cdmw.modding.mesh_parser import parse_mesh
    wanted = set(pending.target_part_ids if targets is None else targets)
    original = parse_mesh(pending.snapshot.original_data, pending.state.target_path)
    bindings = material_binding_names(pending.state)
    names = {}
    for part in pending.state.parts:
        if part.part_id in wanted:
            source = original.submeshes[part.target_index]
            wrapper = material_binding_name(source, bindings)
            names[part.part_id] = (source.name or wrapper, wrapper)
    return names


def untextured_material_targets(pending, targets=None):
    """Target parts whose game material binds no texture at all, by part id.

    A few shipped parts are drawn by a material without a single texture
    parameter (``SkinnedMeshGhost`` accessories, a helmet's ``mold``). Imported
    textures are written in the format of the textures they replace, and such a
    part has none to take it from.
    """
    paths = _wrapper_texture_paths(pending)
    return {part_id: name for part_id, (name, wrapper) in _target_part_names(pending, targets).items()
            if wrapper in paths and not paths[wrapper]}


def _check_untextured_targets(pending, targets):
    """Refuse an import whose target parts have no game texture between them, naming the first."""
    bare = untextured_material_targets(pending, targets)
    if not bare:
        return
    helpers = helper_material_targets(pending, targets)
    # A textured part replaced in the same import lends its texture format; that stays allowed.
    if all(target in bare or target in helpers for target in targets):
        part, target = next((part, target) for part, target in zip(pending.source.mesh.submeshes, targets)
                            if target in bare)
        raise ValueError(
            f"{bare[target]} has no textures in the game's material, so it cannot take imported textures. "
            f"Map {part.name or part.material} to another part, join it with one before exporting, "
            "or choose Keep Original Materials.")


def _check_one_part_per_target(pending, targets):
    """Imported materials go one imported part to one game part; say which part got several."""
    if len(targets) == len(pending.source.mesh.submeshes):
        shared = next((target for target in targets if targets.count(target) > 1), None)
        if shared is None:
            return
        name = _target_part_names(pending, (shared,)).get(shared, ("",))[0]
        if name:
            raise ValueError(
                f"{targets.count(shared)} imported parts are mapped to {name}. With Imported Materials & Textures "
                "each game part takes one imported part. Join them before exporting, map them to different parts, "
                "or choose Keep Original Materials.")
    raise ValueError("Imported materials require one source material part per target part.")


def _is_generated_filler(slot):
    """A neutral texture CDMW made itself (a flat normal), not one the import brought."""
    path = Path(str(getattr(slot, "source_path", "") or ""))
    return "_neutral_" in path.name.casefold() and "cdmw_synthetic_materials" in str(path.parent).casefold()


def _source_material_texture_names(pending, part):
    """File names of the textures the imported model's own material names for this part."""
    material = _folded(part.material or part.name)
    names = []
    source = Path(pending.source_path)
    try:
        if source.suffix.lower() == ".obj":
            from cdmw.modding.scene_texture_discovery import _obj_material_texture_slots
            for name, slots in _obj_material_texture_slots(source).items():
                if _folded(name) == material:
                    names.extend(Path(str(slot.path)).name for slot in slots)
        else:
            for binding in getattr(pending.source, "material_bindings", ()) or ():
                if _folded(binding.material_name) == material:
                    names.extend(Path(str(texture)).name for _role, texture in binding.texture_slots)
    except (OSError, ValueError):
        pass
    texture = str(getattr(part, "texture", "") or "").strip()
    if texture:
        names.append(Path(texture.replace("\\", "/")).name)
    return tuple(dict.fromkeys(name for name in names if name))


def _unbound_material_reason(pending, index, wrapper=""):
    """Why one imported part's material reached no texture slot of its target part."""
    parts = pending.source.mesh.submeshes
    part = parts[index]
    material = str(part.material or part.name).strip()
    piece = str(part.name or part.material).strip()
    own = ", ".join(_source_material_texture_names(pending, part))
    if own:
        # Imported textures take their format from the game textures they replace.
        # With none of those in the session's file set there is nothing to fit to.
        named = {Path(path.replace("\\", "/")).name.casefold() for path in _wrapper_texture_paths(pending).get(_folded(wrapper), ())}
        held = {Path(str(file.path).replace("\\", "/")).name.casefold() for file in pending.state.dependencies}
        if named and not named & held:
            return (f"The game's textures for {wrapper} were not loaded with this model, so the imported textures "
                    "cannot be fitted to it. Select the model in Browse Archives again, open it in Mesh Editor "
                    "as a new edit and import again. If that does not help, choose Keep Original Materials.")
        return (f"Imported material {material} has no proven target binding: none of its textures ({own}) fits a "
                f"texture slot of {wrapper or piece}. Map {piece} to another part, or choose Keep Original Materials.")
    # Images lying beside the model that no imported material names: another
    # model's files, or this one's when the exporter wrote no texture lines.
    claimed = {name.casefold() for other in parts for name in _source_material_texture_names(pending, other)}
    loose = sorted({Path(str(path)).name for path in getattr(pending.source, "discovered_texture_files", ()) or ()
                    if Path(str(path)).name.casefold() not in claimed}, key=str.casefold)
    if loose:
        found = ", ".join(loose[:4] + ["..."] * (len(loose) > 4))
        return (f"Imported material {material} has no textures of its own. The textures found beside the model "
                f"({found}) are not assigned to it, so they were not used. "
                "Assign them to the material before exporting, or choose Keep Original Materials.")
    return (f"Imported material {material} has no textures of its own (a plain colour is not imported), and "
            "Imported Materials & Textures needs a texture on every imported part. Give the material an image "
            "texture or put its faces on a textured material, export again, or choose Keep Original Materials.")


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
    # The shared reference reader keeps one wrapper per part name, so a part's
    # textures in a later model-property variant (another shader, another _sp)
    # were left out, and the default surface could not read that variant's own
    # game surface. Add every texture any variant names by its exact path.
    from cdmw.core.pac_xml_standard_material import find_material_wrappers
    for sidecar in tuple(selected):
        if not sidecar.path.casefold().endswith(".pac_xml"):
            continue
        text = _sidecar_text(read_archive_entry_data(sidecar, stop_event=stop_event)[0])
        for wrapper in find_material_wrappers(text):
            for parameter in wrapper.parameters:
                path = str(parameter.texture_path or "").replace("\\", "/").strip("/").casefold()
                matches = tuple(by_path.get(path, ())) if path else ()
                if len({match.path.casefold() for match in matches}) == 1:
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
    ``surface`` is an optional (roughness, metallic) pair in 0..1 that the
    replaced wrappers get as one uniform surface. Without it each gets its
    default surface (see ``_apply_default_surface``), never roughness 0.
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
    _check_one_part_per_target(pending, tuple(targets))
    if not pending.state.dependencies:
        raise ValueError("Imported materials require the original material sidecar and texture dependencies.")
    _check_helper_targets(pending, targets)
    _check_untextured_targets(pending, targets)
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
                                         if _folded(reference.material_name) in names or _folded(reference.part_name) in names)
        configure_mesh_import_materials(state)
        payloads, report = build_static_texture_payloads(state, state.original_sidecars_for_static)
        raise_if_cancelled(stop_event, "Replacement material preparation cancelled.")
        if report is None:
            # Not one texture came with the import, so nothing was converted.
            raise ValueError(_unbound_material_reason(
                pending, 0, material_binding_name(original.submeshes[rows[targets[0]].target_index], bindings)))
        if report.errors:
            details = "; ".join(report.errors)
            raise ValueError("Imported material conversion failed: " + details)
        outputs = {str(payload.target_path).casefold(): payload for payload in payloads}
        # Proof is a texture the import brought, bound under the part's own material
        # or object name (textures named after the object are routed by that name).
        # A flat normal CDMW generated for the target is not proof: with only that,
        # the part kept the game's colour texture on the import's UVs.
        mapped_sources = {_folded(getattr(slot, "source_material_name", ""))
                          for slot in report.slot_mappings if not _is_generated_filler(slot)}
        for index, part in enumerate(pending.source.mesh.submeshes):
            if not ({_folded(part.material), _folded(part.name)} - {""}) & mapped_sources:
                raise ValueError(_unbound_material_reason(
                    pending, index, material_binding_name(original.submeshes[rows[targets[index]].target_index], bindings)))
        if not payloads:
            raise ValueError("Imported materials produced no output textures or sidecars; original-material fallback is disabled.")
        slots = [slot for slot in report.slot_mappings if _folded(slot.target_material_name) in names]
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
        if surface is not None:
            _apply_imported_surface(files, merged_keys, names, pending.state.target_path, surface)
        else:
            _apply_default_surface(pending, targets, files, merged_keys, names, directory)
        _restore_own_surfaces(pending, files, merged_keys, names)
        return _prune_unreferenced_generated_files(files)


def _surface_folder(target_path):
    model = target_path.replace("\\", "/")
    folder = "character/texture" if "/character/" in f"/{model}" else str(Path(model).parent).replace("\\", "/")
    return folder, Path(model).stem


def _apply_imported_surface(files, sidecar_keys, names, target_path, surface):
    """Write the chosen roughness/metalness where each replaced wrapper's shader reads it.

    Ver2 wrappers get it as layer R, Standard-technique wrappers (most creatures)
    as their _materialTexture. A texture no wrapper names is pruned afterwards.
    """
    from cdmw.core.pac_xml_surface_layer import (
        apply_surface_layer, surface_byte, surface_layer_dds, surface_material_dds)

    roughness, metallic = (surface_byte(value) for value in surface)
    folder, stem = _surface_folder(target_path)
    path = f"{folder}/{stem}_cdmw_surface_{roughness:03d}_{metallic:03d}.dds"
    material_path = f"{folder}/{stem}_cdmw_surface_{roughness:03d}_{metallic:03d}_sp.dds"
    applied = 0
    for key in sidecar_keys:
        if not key.endswith(".pac_xml"):
            continue
        file = files[key]
        text, changed = apply_surface_layer(_sidecar_text(file.data), names, path, material_path)
        if changed:
            files[key] = replace(file, data=text.encode("utf-8"))
            applied += changed
    if not applied:
        raise ValueError("Roughness and Metallic found no replaced equipment material to apply to.")
    files[path.casefold()] = ReplacementFile(path, surface_layer_dds(roughness / 255, metallic / 255))
    files[material_path.casefold()] = ReplacementFile(material_path, surface_material_dds(roughness / 255, metallic / 255))


#: Used when neither the import nor the game part states a surface: matte, not metal.
_FALLBACK_SURFACE = {"roughness": 0.5, "metallic": 0.0}
#: Game surface textures read back from the target, by parameter.
_SURFACE_PARAMETERS = frozenset({"_materialTexture", "_detailMaterialMaskR", "_irisMaterialTexture"})
#: Surface textures the import drops that a shader outside SURFACE_SHADERS reads (eyes, hair, skin).
_OWN_SURFACE_PARAMETERS = ("_materialTexture", "_irisMaterialTexture")


def _restore_own_surfaces(pending, files, sidecar_keys, names):
    """Give wrappers that Roughness/Metallic skip their own game surface back, as its mean.

    The import strips every ``*materialTexture`` from the replaced wrappers, so an
    eye, hair, skin or horse-coat part would read roughness 0 (a mirror). Those
    shaders are not traced, so the slider value is not written there; instead
    each texture the game part declared comes back as a uniform texture of its
    own R, G and B means, with the game row's ItemID. The original texture is
    not kept: it is painted for the original UVs.
    """
    from cdmw.core.material_shader_controls import edit_material_variants_indexed
    from cdmw.core.pac_xml_standard_material import find_material_wrappers
    from cdmw.core.pac_xml_surface_layer import SURFACE_SHADERS, bind_texture, surface_rgb_dds, surface_byte

    originals = _original_surface_means(pending, names)
    folder, stem = _surface_folder(pending.state.target_path)

    def edit(index, fragment):
        for wrapper in find_material_wrappers(fragment):
            name = _folded(wrapper.submesh_name)
            if name not in names or wrapper.shader in SURFACE_SHADERS:
                continue
            present = {parameter.name for parameter in wrapper.parameters}
            for parameter in _OWN_SURFACE_PARAMETERS:
                original = _variant_means(originals, index).get(name, {}).get(parameter)
                if original is None or parameter in present:
                    continue
                red, green, blue = (surface_byte(original[kind]) for kind in ("red", "roughness", "metallic"))
                path = f"{folder}/{stem}_cdmw_surface_{red:03d}_{green:03d}_{blue:03d}_sp.dds"
                fragment, _ = bind_texture(fragment, {name}, parameter, path, original["item_id"])
                files[path.casefold()] = ReplacementFile(path, surface_rgb_dds(red, green, blue))
        return fragment, None

    for key in sidecar_keys:
        if not key.endswith(".pac_xml"):
            continue
        file = files[key]
        text, _ = edit_material_variants_indexed(_sidecar_text(file.data), edit)
        files[key] = replace(file, data=text.encode("utf-8"))


def _apply_default_surface(pending, targets, files, sidecar_keys, names, directory):
    """Give every replaced wrapper a surface when the sliders were left alone.

    The import drops the game part's layers and ``_materialTexture``, which left
    roughness at 0: a mirror, the "wet" creature. Each wrapper on a traced
    shader now gets, channel by channel, the imported model's own roughness or
    metallic map, else its ``Pr``/``Pm`` value, else the mean of the game part's
    own surface texture, else 0.5 roughness and no metal.

    The game part's texture itself is not kept: it is painted for the original
    UV layout, which the imported model does not share. Standard-technique
    wrappers take the maps per pixel as their ``_materialTexture`` (the import's
    UVs, as its colour map); Ver2 wrappers rotate their layer UVs, so they get
    the maps' mean as a uniform layer R.

    Each model-property variant is done on its own, wrapper by wrapper: one part
    can be Ver2 in one variant and Standard in another, each with its own game
    texture (``cd_phm_00_ub_belt_0010_02`` in ``cd_m0001_00_so_phm_ub_33005``).
    """
    from cdmw.core.material_shader_controls import edit_material_variants_indexed
    from cdmw.core.pac_xml_standard_material import find_material_wrappers
    from cdmw.core.pac_xml_surface_layer import (
        MATERIAL_TEXTURE_SURFACE_SHADERS, SURFACE_SHADERS, apply_surface_fragment, surface_byte,
        surface_layer_dds, surface_material_dds)

    sources = _wrapper_source_materials(pending, targets)
    inputs = _source_surface_inputs(pending)
    originals = _original_surface_means(pending, names)
    folder, stem = _surface_folder(pending.state.target_path)

    def surface(name, material, original):
        channels = _merged_surface_inputs(inputs, sources.get(name, ()))
        values = {}
        for kind in ("roughness", "metallic"):
            value = channels[kind]
            if value is None:
                value = ("value", original.get(kind, _FALLBACK_SURFACE[kind]))
            elif value[0] == "map" and not material:
                value = ("value", _map_mean(value))
            values[kind] = value
        if material and any(value[0] == "map" for value in values.values()):
            data = _packed_material_dds(values, original.get("format", ""), directory)
            path = f"{folder}/{stem}_cdmw_surface_{hashlib.sha256(data).hexdigest()[:12]}_sp.dds"
        else:
            roughness, metallic = (surface_byte(values[kind][1]) for kind in ("roughness", "metallic"))
            path = f"{folder}/{stem}_cdmw_surface_{roughness:03d}_{metallic:03d}{'_sp' if material else ''}.dds"
            data = (surface_material_dds if material else surface_layer_dds)(roughness / 255, metallic / 255)
        files[path.casefold()] = ReplacementFile(path, data)
        return path

    def edit(index, fragment):
        means = _variant_means(originals, index)
        paths = {}
        for wrapper in find_material_wrappers(fragment):
            name = _folded(wrapper.submesh_name)
            if name not in names or wrapper.shader not in SURFACE_SHADERS:
                continue
            material = wrapper.shader in MATERIAL_TEXTURE_SURFACE_SHADERS
            if (name, material) not in paths:
                original = means.get(name, {}).get("_materialTexture" if material else "_detailMaterialMaskR", {})
                paths[name, material] = surface(name, material, original)
        for name in sorted({name for name, _material in paths}):
            fragment, _ = apply_surface_fragment(fragment, {name}, paths.get((name, False), ""),
                                                 paths.get((name, True), ""))
        return fragment, None

    for key in sidecar_keys:
        if not key.endswith(".pac_xml"):
            continue
        file = files[key]
        text, _ = edit_material_variants_indexed(_sidecar_text(file.data), edit)
        files[key] = replace(file, data=text.encode("utf-8"))


def _wrapper_source_materials(pending, targets):
    """Folded source material names mapped onto each target wrapper."""
    from cdmw.modding.mesh_parser import parse_mesh
    original = parse_mesh(pending.snapshot.original_data, pending.state.target_path)
    bindings = material_binding_names(pending.state)
    rows = {part.part_id: part for part in pending.state.parts}
    result = defaultdict(set)
    for index, key in enumerate(targets):
        if key not in rows or index >= len(pending.source.mesh.submeshes):
            continue
        source = pending.source.mesh.submeshes[index]
        wrapper = material_binding_name(original.submeshes[rows[key].target_index], bindings)
        result[wrapper].add(_folded(source.material or source.name))
    return result


def _merged_surface_inputs(inputs, materials):
    """One material's inputs as they are; several only agree on a mean value."""
    found = [inputs[material] for material in sorted(materials) if material in inputs]
    if len(found) == 1:
        return found[0]
    merged = {}
    for kind in ("roughness", "metallic"):
        values = [entry[kind] for entry in found if entry[kind] is not None]
        merged[kind] = ("value", sum(_map_mean(value) for value in values) / len(values)) if values else None
    return merged


def _map_mean(value):
    if value[0] == "value":
        return float(value[1])
    return _image_channel_means(value[1], value[2])[0]


def _variant_means(originals, index):
    """One variant's entry of ``_original_surface_means``; {} when the game file has fewer."""
    return originals[index] if index < len(originals) else {}


def _original_surface_means(pending, names):
    """Per model-property variant and replaced wrapper: the game part's own surface textures, averaged.

    Read from the captured game files, never from an earlier edit, as one
    {name: {parameter: {"roughness": G, "metallic": B, "format": DXGI format}}}
    per variant in file order (one when the file has no variants), because a
    part can use another shader and other textures in each variant.
    """
    from cdmw.core.material_shader_controls import material_variant_fragments

    sidecar = target_sidecar(pending)
    if sidecar is None:
        return ()
    return tuple(_fragment_surface_means(pending, fragment, names)
                 for fragment in material_variant_fragments(_sidecar_text(sidecar.data)))


def _fragment_surface_means(pending, fragment, names):
    from PIL import Image
    from cdmw.core.pac_xml_standard_material import find_material_wrappers

    files = {file.path.replace("\\", "/").casefold(): file for file in pending.state.dependencies}
    result = {}
    for wrapper in find_material_wrappers(fragment):
        name = _folded(wrapper.submesh_name)
        if name not in names or name in result:
            continue
        means = {}
        for parameter in wrapper.parameters:
            if parameter.name not in _SURFACE_PARAMETERS or not parameter.texture_path:
                continue
            texture = files.get(parameter.texture_path.replace("\\", "/").casefold())
            if texture is None:
                continue
            try:
                with Image.open(io.BytesIO(texture.data)) as image:
                    image.thumbnail((256, 256))
                    rgb = image.convert("RGB")
            except (OSError, ValueError, NotImplementedError):
                # Pillow does not decode every DXGI format; such a surface is left unread.
                continue
            red, green, blue = (sum(value * count for value, count in enumerate(rgb.getchannel(c).histogram()))
                                / max(1, rgb.width * rgb.height) / 255 for c in "RGB")
            means[parameter.name] = {"red": red, "roughness": green, "metallic": blue,
                                     "format": _dds_format(texture.data), "item_id": parameter.item_id}
        result[name] = means
    return result


def _dds_format(data):
    """DXGI name of a DDS header's format, for the formats the game's ``_sp`` maps use."""
    if data[:4] != b"DDS " or len(data) < 128:
        return ""
    fourcc = data[84:88]
    if fourcc == b"DX10" and len(data) >= 148:
        return {71: "BC1_UNORM", 74: "BC2_UNORM", 77: "BC3_UNORM", 98: "BC7_UNORM", 28: "R8G8B8A8_UNORM",
                87: "B8G8R8A8_UNORM"}.get(int.from_bytes(data[128:132], "little"), "")
    return {b"DXT1": "BC1_UNORM", b"DXT3": "BC2_UNORM", b"DXT5": "BC3_UNORM"}.get(fourcc, "")


def _source_image(path, directory=None):
    """The imported texture as a loaded Pillow image.

    Pillow reads most DDS files, but not every DXGI format a texture tool can
    save (BC1/BC3 sRGB, B8G8R8A8 with a DX10 header). Those go through the
    app's own DDS decoder, and a file neither can read is named in the refusal.
    """
    from PIL import Image
    path = Path(path)
    try:
        with Image.open(path) as image:
            image.load()
            return image.copy()
    except (NotImplementedError, OSError, ValueError, SyntaxError) as error:
        reason = str(error) or error.__class__.__name__
    if path.suffix.lower() == ".dds":
        from cdmw.core.texture_native import decode_dds_preview_with_directxtex
        with TemporaryDirectory(prefix="cdmw-surface-source-", dir=directory) as temporary:
            png = Path(temporary) / "source.png"
            try:
                decoded = decode_dds_preview_with_directxtex(path, png, max_dimension=0, slot_kind="material")
            except (OSError, ValueError, RuntimeError):
                decoded = None
            if decoded and png.is_file():
                with Image.open(png) as image:
                    image.load()
                    return image.copy()
    raise ValueError(f"Imported texture {path.name} could not be read ({reason}). "
                     "Save it as BC7 or as PNG, then import again.")


def _packed_material_dds(values, dds_format, directory):
    """The imported roughness/metallic maps as a game ``_sp`` texture.

    G roughness, B metalness; R is 255 as in every shipped ``_sp`` (the
    G-buffer shaders do not read it) and alpha opaque. A channel without a map
    is its constant. Encoded in the game texture's own format (BC1 for _sp).
    """
    from PIL import Image
    from cdmw.core.texture_native import encode_dds_with_directxtex
    from cdmw.domain.textures.output import max_mips_for_size

    images = {}
    for kind, value in values.items():
        if value[0] == "map":
            images[kind] = _source_image(value[1], directory).convert("RGB").getchannel(value[2])
    size = max((image.size for image in images.values()), key=lambda size: size[0] * size[1])
    channels = []
    for kind in ("roughness", "metallic"):
        image = images.get(kind)
        if image is None:
            image = Image.new("L", size, max(0, min(255, round(float(values[kind][1]) * 255))))
        elif image.size != size:
            image = image.resize(size, Image.Resampling.BILINEAR)
        channels.append(image)
    packed = Image.merge("RGBA", (Image.new("L", size, 255), *channels, Image.new("L", size, 255)))
    source = directory / "cdmw_surface_sp.png"
    output = directory / "cdmw_surface_sp.dds"
    packed.save(source)
    if not encode_dds_with_directxtex(source, output, dds_format=dds_format or "BC1_UNORM", width=size[0],
                                      height=size[1], mip_count=max_mips_for_size(*size)) or not output.is_file():
        raise ValueError("The imported roughness and metallic maps could not be encoded as a game texture.")
    return output.read_bytes()


def _image_channel_means(path, channels):
    image = _source_image(path)
    image.thumbnail((256, 256))
    rgb = image.convert("RGB")
    stats = [sum(value * count for value, count in enumerate(rgb.getchannel(c).histogram())) / max(1, rgb.width * rgb.height)
             for c in "RGB"]
    return tuple(stats["RGB".index(c)] / 255 for c in channels)


def _source_surface_inputs(pending):
    """Each used source material's own roughness and metalness, by folded name.

    A channel is ``("map", path, "R"|"G"|"B")`` for an OBJ map_Pr/map_Pm or a
    glTF roughness/metalness map (R), or a packed metallic-roughness map (G
    roughness, B metal); ``("value", v)`` for OBJ Pr/Pm; or None.
    """
    used = {_folded(part.material or part.name) for part in pending.source.mesh.submeshes}
    result = {}
    source = Path(pending.source_path)
    if source.suffix.lower() == ".obj":
        from cdmw.modding.scene_texture_discovery import _obj_material_parameters, _obj_material_texture_slots
        slots = {_folded(name): value for name, value in _obj_material_texture_slots(source).items()}
        factors = {_folded(name): value for name, value in _obj_material_parameters(source).items()}
        materials = {material: ({slot.slot_kind: slot.path for slot in slots.get(material, ())},
                                {parameter.parameter_name: parameter.numeric_value for parameter in factors.get(material, ())})
                     for material in used}
    else:
        materials = {_folded(binding.material_name): (
            {str(role).casefold(): texture for role, texture in binding.texture_slots}, {})
            for binding in getattr(pending.source, "material_bindings", ()) or ()
            if _folded(binding.material_name) in used}
    for material, (kinds, values) in materials.items():
        entry = {}
        for key, kind, factor, channel in (("roughness", "roughness", "_roughnessFactor", "G"),
                                           ("metallic", "metalness", "_metallicFactor", "B")):
            if kind in kinds and Path(kinds[kind]).is_file():
                entry[key] = ("map", Path(kinds[kind]), "R")
            elif "material" in kinds and Path(kinds["material"]).is_file():
                entry[key] = ("map", Path(kinds["material"]), channel)
            elif values.get(factor) is not None:
                entry[key] = ("value", float(values[factor]))
            else:
                entry[key] = None
        result[material] = entry
    return result


def imported_surface_defaults(pending):
    """The imported model's own roughness and metalness, averaged, as slider starting values.

    Uses OBJ map_Pr/map_Pm (or Pr/Pm) and glTF roughness/metalness or packed
    metallic-roughness maps. Missing values stay None.
    """
    found = {"roughness": [], "metallic": []}
    try:
        for entry in _source_surface_inputs(pending).values():
            for key in found:
                if entry[key] is not None:
                    found[key].append(_map_mean(entry[key]))
    except (OSError, ValueError):
        return {"roughness": None, "metallic": None}
    return {key: (round(sum(values) / len(values), 3) if values else None) for key, values in found.items()}


def imported_surface_start(pending):
    """Where Roughness and Metallic start: the surface Apply writes when they are left alone.

    The imported model's own values (``imported_surface_defaults``), else the
    mean of the target parts' own game surface, else 0.5 and 0. Leaving the
    sliders there keeps per-pixel maps; moving one sets a uniform surface.
    """
    from cdmw.core.pac_xml_surface_layer import MATERIAL_TEXTURE_SURFACE_SHADERS, SURFACE_SHADERS
    from cdmw.modding.mesh_parser import parse_mesh

    start = imported_surface_defaults(pending)
    if all(value is not None for value in start.values()):
        return start
    original = parse_mesh(pending.snapshot.original_data, pending.state.target_path)
    bindings = material_binding_names(pending.state)
    names = {material_binding_name(original.submeshes[part.target_index], bindings)
             for part in pending.state.parts if part.part_id in pending.target_part_ids}
    wrappers = _target_variant_wrappers(pending, names)
    try:
        originals = _original_surface_means(pending, names)
    except (OSError, ValueError):
        originals = ()
    for kind, value in start.items():
        if value is not None:
            continue
        found = [_variant_means(originals, index).get(name, {}).get(
                     "_materialTexture" if shader in MATERIAL_TEXTURE_SURFACE_SHADERS else "_detailMaterialMaskR",
                     {}).get(kind, _FALLBACK_SURFACE[kind])
                 for index, name, shader in wrappers if shader in SURFACE_SHADERS]
        start[kind] = round(sum(found) / len(found), 3) if found else _FALLBACK_SURFACE[kind]
    return start


def target_sidecar(pending):
    """The target's captured game ``.pac_xml``, or None."""
    target = pending.state.target_path.replace("\\", "/").casefold()
    pac_xml = target.replace("/model/", "/modelproperty/", 1) + "_xml"
    sidecars = [file for file in pending.state.dependencies if file.path.casefold().endswith(".pac_xml")]
    return next((file for file in sidecars if file.path.replace("\\", "/").casefold() == pac_xml),
                sidecars[0] if len(sidecars) == 1 else None)


def _target_variant_wrappers(pending, names):
    """(variant index, folded name, shader) of each named wrapper in the target's captured ``.pac_xml``."""
    from cdmw.core.material_shader_controls import material_variant_fragments
    from cdmw.core.pac_xml_standard_material import find_material_wrappers
    sidecar = target_sidecar(pending)
    if sidecar is None:
        return ()
    return tuple((index, _folded(wrapper.submesh_name), wrapper.shader)
                 for index, fragment in enumerate(material_variant_fragments(_sidecar_text(sidecar.data)))
                 for wrapper in find_material_wrappers(fragment) if _folded(wrapper.submesh_name) in names)
