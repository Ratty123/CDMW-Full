"""Undoable experimental material edits in the existing Mesh Editor workflow."""
from dataclasses import replace
from pathlib import PurePosixPath
import xml.etree.ElementTree as ET

from cdmw.core.common import raise_if_cancelled
from cdmw.core.material_shader_controls import (control_material_variants, material_source_details,
                                                 rewrite_shader_controls, rewrite_texture_paths, validate_source)
from cdmw.domain.mesh.replacement import PART_ID_ATTRIBUTE
from cdmw.domain.mesh.shader_controls import (MESH_FAMILIES, ShaderControls, authored_values_payload, catalogue_payload,
                                             family_for, preview_factors)
from cdmw.services.mesh_replacement_materials import _sidecar_text, material_binding_name, material_binding_names


def shader_settings(state, original):
    if not any(part.shader_controls is not None for part in state.parts):
        return ()
    names = material_binding_names(state)
    settings = {}
    for part in state.parts:
        source = original.submeshes[part.target_index]
        name = material_binding_name(source, names)
        if name in settings and settings[name] != part.shader_controls:
            raise ValueError("Select all parts sharing this material and use the same shader controls.")
        if part.shader_controls is not None:
            part.shader_controls.validate()
            if part.translucency is not None or part.emission is not None:
                raise ValueError(f"{name}: restore Glow and Translucency before choosing another shader experiment.")
        settings[name] = part.shader_controls
    return tuple((name, value) for name, value in settings.items() if value is not None)


def build_shader_control_files(state, original, companion_files, *, stop_event=None):
    choices = shader_settings(state, original)
    if not choices:
        return tuple(companion_files)
    static = original.format.casefold() != "pac"
    files = {file.path.replace("\\", "/").casefold(): file for file in companion_files}
    sources = {file.path.replace("\\", "/").casefold(): file for file in state.dependencies}
    if len(files) != len(companion_files) or len(sources) != len(state.dependencies):
        raise ValueError("Shader material sources are ambiguous.")
    target = state.target_path.replace("\\", "/").casefold()
    paths = [str(PurePosixPath(target).with_suffix(".pami"))] if static else [target.replace("/model/", "/modelproperty/", 1) + "_xml"]
    # A static model can have several captured PAMI variants. Restrict to its
    # captured material documents; never search or edit unrelated archive files.
    if static:
        paths = [key for key in dict.fromkeys((*sources, *files)) if key.endswith(".pami")]
    found = set()
    for path in paths:
        raise_if_cancelled(stop_event)
        source = files.get(path, sources.get(path))
        if source is None:
            continue
        from cdmw.domain.pac_xml_editor import decode_pac_xml_payload
        source_text, source_format = decode_pac_xml_payload(source.data)
        if not static:
            from cdmw.domain.mesh.replacement import ReplacementFile
            from cdmw.services.new_item_template_materials import bake_equipment_glass
            def read_texture(texture):
                key = texture.replace("\\", "/").casefold()
                file = files.get(key, sources.get(key))
                return file.data if file is not None else None
            source_text, baked = bake_equipment_glass(source_text, choices, state.target_path,
                read_texture, stop_event=stop_event)
            for texture, data in baked.items():
                files[texture.casefold()] = ReplacementFile(texture, data)
        owned = owned_texture_files(choices, state.target_path)
        if owned and static:
            raise ValueError("Replacement textures are supported on equipment models only.")
        if owned:
            # Before the shader rewrite, so a rebuilt layout numbers a newly added texture row too.
            source_text, textured = rewrite_texture_paths(
                source_text, {name: {parameter: file.path for parameter, file in slots.items()}
                              for name, slots in owned.items()})
            for name in textured:
                files.update({file.path.casefold(): file for file in owned[name].values()})
        text, matches = rewrite_shader_controls(source_text, choices, static=static, allow_missing=True)
        if matches:
            found.update(matches)
            files[path] = replace(source, data=source_format.bom + text.encode(source_format.encoding))
    missing = {name for name, _ in choices} - found
    if missing:
        raise ValueError("The matching material sidecar is missing or incomplete for: " + ", ".join(sorted(missing)))
    return tuple(files.values())


def owned_texture_path(target_path, parameter, digest):
    """A private archive path for a user's texture, beside where baked ones go."""
    stem = str(PurePosixPath(target_path.replace("\\", "/").replace("character/model/", "character/texture/", 1)).with_suffix(""))
    role = parameter.strip("_").removesuffix("Texture").lower() or "texture"
    return f"{stem}_cdmw_tex_{digest[:10]}_{role}.dds"


def owned_texture_files(choices, target_path):
    """{casefolded material: {parameter: ReplacementFile}} for the chosen replacement textures."""
    from cdmw.core.shader_texture_store import read_texture
    from cdmw.domain.mesh.replacement import ReplacementFile
    return {name.casefold(): {parameter: ReplacementFile(owned_texture_path(target_path, parameter, digest), read_texture(digest))
                              for parameter, digest in controls.textures}
            for name, controls in choices if controls.textures}


def _shader_compatibility(shader, values, textures, *, static):
    parameters = {name: ET.Element("Parameter", {"_value": str(value)}) for name, value in values.items()}
    parameters.update({name: ET.Element("MaterialParameterTexture") for name, path in textures.items() if path})
    options = {}
    for family in MESH_FAMILIES:
        try:
            if not shader:
                raise ValueError("Source material information is unavailable; shader experiments are disabled.")
            validate_source(shader, ShaderControls(family.shader), parameters, static=static, allow_bake=True)
            options[family.shader] = ""
        except ValueError as exc:
            options[family.shader] = str(exc)
    return options


def _shader_source_options(session):
    """Use captured sidecars when present; otherwise inspect resolved preview metadata.

    No archive reads, texture decoding or baking may happen while composing UI state.
    """
    from cdmw.services.shader_controls_preview import source_inputs
    state = session.replacement_state
    static = session.mesh_format != "pac"
    sources, details, sidecar_path, error = {}, {}, "", ""
    if state is not None:
        target = state.target_path.replace("\\", "/").casefold().replace("/model/", "/modelproperty/", 1) + "_xml"
        files = {file.path.replace("\\", "/").casefold(): file
                 for file in (*state.dependencies, *state.companion_files)}
        for path, file in files.items():
            if path != target and not (static and path.endswith(".pami")):
                continue
            try:
                text = _sidecar_text(file.data)
                for variant in control_material_variants(text, static=static):
                    for name, source in variant.items():
                        sources.setdefault(name, []).append(source)
                if not static:
                    sidecar_path = file.path.replace("\\", "/")
                    for wrapper in material_source_details(text):
                        details.setdefault(wrapper["name"].casefold(), []).append(wrapper)
            except (ValueError, ET.ParseError) as exc:
                error = str(exc)
    result = {}
    bindings = {part.part_id: part for part in state.parts} if state is not None else {}
    for index, part in enumerate(session.working_mesh.submeshes):
        drawn = part
        binding = bindings.get(getattr(part, PART_ID_ATTRIBUTE, ""))
        # Target names survive replacement geometry and identify its companion wrapper.
        if binding is not None:
            part = session.base_mesh.submeshes[binding.target_index]
        name = material_binding_name(part, sources)
        candidates = sources.get(name, ())
        wrappers = details.get(name, ())
        owner = _owner_slot(drawn)
        if owner < 0:
            owner = _owner_slot(part)
        if len(wrappers) == len(candidates) and len(wrappers) > 1:
            # The variant the viewport draws leads, so the numbers shown first
            # are the ones on screen; the others stay selectable.
            lead = next((position for position, wrapper in enumerate(wrappers) if wrapper["slot"] == owner), 0)
            order = [lead, *(position for position in range(len(wrappers)) if position != lead)]
            candidates = [candidates[position] for position in order]
            wrappers = [wrappers[position] for position in order]
        elif len(wrappers) != len(candidates):
            wrappers = ()
        if state is None:
            values, textures = source_inputs(part, owner)
            inputs = getattr(part, "preview_material_texture_inputs", ()) or ()
            shaders = {str(item.get("shader_family", "") if isinstance(item, dict) else getattr(item, "shader_family", "")) for item in inputs}
            shaders.discard("")
            shader = str(getattr(part, "preview_sidecar_shader_family", "") or "")
            if not shader and len(shaders) == 1:
                shader = next(iter(shaders))
            candidates = ((shader, values, textures),)
            # Before the first edit only the preview's resolved wrapper is known.
            # A texture parameter also appears among the values with no value;
            # its row shows the resolved path instead of a blank.
            wrappers = ({"slot": owner, "variant_label": "", "rows": [
                *({"kind": "Texture" if textures.get(key) else "", "name": key, "item_id": "", "index": None,
                   "value": textures.get(key) or str(value)} for key, value in values.items()),
                *({"kind": "Texture", "name": key, "item_id": "", "index": None, "value": path}
                  for key, path in textures.items() if path and key not in values)]},)
            if not static and not sidecar_path:
                sidecar_path = str(getattr(session.working_mesh, "path", "") or "").replace("\\", "/").replace(
                    "/model/", "/modelproperty/", 1) + "_xml"
        options = _shader_compatibility("", {}, {}, static=static)
        if candidates and not error:
            variants = [_shader_compatibility(*source, static=static) for source in candidates]
            options = {family.shader: next((row[family.shader] for row in variants if row[family.shader]), "") for family in MESH_FAMILIES}
        if error:
            options = dict.fromkeys(options, error)
        if binding is not None and (binding.translucency is not None or binding.emission is not None):
            options = dict.fromkeys(options, "Restore Glow and Translucency before choosing another shader experiment.")
        result[index] = {"source_shader": ", ".join(dict.fromkeys(source[0] for source in candidates)), "shader_options": options,
                         "source": {"path": sidecar_path, "part": name, "viewport_slot": owner},
                         "preview_warning": _preview_warning(candidates),
                         **_authored_panel_state(candidates, options, wrappers)}
    return result


# The inspector shows its own localized sentence for each code.
_LAYERED_VEIL_WARNING = "layered_veil"


def _preview_warning(candidates):
    """A line for the inspector when the preview cannot show what this material draws."""
    for shader, values, textures in candidates:
        if shader != "SkinnedMeshTransparency":
            continue
        detail = any(name.startswith("_detail") and name.endswith(("MaskR", "MaskG", "MaskB")) and (textures.get(name) or values.get(name))
                     for name in (*values, *textures))
        try:
            flags = int(str(values.get("_colorBlendingFlag", "0") or "0"), 0)
        except ValueError:
            flags = 0
        if detail or flags & 0xFFF:
            return _LAYERED_VEIL_WARNING
    return ""


def _owner_slot(part):
    """Position of the PAC wrapper the preview drew this part from, or -1."""
    owner = getattr(part, "preview_pac_material_owner_slot_index", -1)
    if isinstance(owner, int) and not isinstance(owner, bool) and owner >= 0:
        return owner
    owners = set()
    for item in getattr(part, "preview_material_texture_inputs", ()) or ():
        value = item.get("owner_slot_index", -1) if isinstance(item, dict) else getattr(item, "owner_slot_index", -1)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            owners.add(value)
    return owners.pop() if len(owners) == 1 else -1


def _authored_panel_state(candidates, options, wrappers=()):
    """What the source material declares, for the inspector and its live preview.

    ``authored`` lists each distinct model variant's shader, parsed numbers and
    texture paths. ``preview_base`` holds, per compatible family, the factor
    vector the viewport draws when nothing is overridden; the inspector replaces
    single lanes of it while a slider moves. Pure parsing: no archive reads.

    ``wrappers`` (parallel to ``candidates``) adds where each came from: the
    model variants that share those numbers, the wrapper's position in the
    file and its rows as written, so a user can check them against the file.
    """
    variants, origins = [], []
    for position, (shader, values, textures) in enumerate(candidates):
        row = {"shader": shader, "fields": authored_values_payload(values),
               "textures": {name: path for name, path in textures.items() if path}}
        wrapper = wrappers[position] if position < len(wrappers) else None
        if row in variants:
            if wrapper is not None and wrapper.get("variant_label", "") != "":
                origins[variants.index(row)]["variants"].append(wrapper["variant_label"])
            continue
        variants.append(row)
        origins.append({"variants": [wrapper["variant_label"]] if wrapper is not None and wrapper.get("variant_label", "") != "" else [],
                        "slot": wrapper["slot"] if wrapper is not None else -1,
                        "rows": list(wrapper["rows"]) if wrapper is not None else []})
    variants = [{**row, **origin} for row, origin in zip(variants, origins)]
    base = {}
    if candidates:
        _, values, _ = candidates[0]
        for family in MESH_FAMILIES:
            if options.get(family.shader):
                continue
            try:
                base[family.shader] = list(preview_factors(ShaderControls(family.shader), values))
            except ValueError:
                continue
    return {"authored": variants, "preview_base": base}


def shader_controls_ui_state(authoring, replacement):
    session = authoring.shadow_service._session(authoring.shadow_session_id)
    reason = replacement["reason"]
    if session.hair_state is not None:
        reason = "Finish the hair workflow before changing shader controls."
    bindings = {part.part_id: part for part in session.replacement_state.parts} if session.replacement_state else {}
    diagnostics = {}
    if session.replacement_state is not None:
        from cdmw.services.mesh_rust_replacement_materials import replacement_material_key
        key = replacement_material_key(session.working_mesh, session.replacement_state)
        diagnostics = authoring.archive_refit_material_cache.get(key, {}).get("shader_diagnostics", {})
    options = _shader_source_options(session)
    return {"available": not reason, "reason": reason, "catalogue": catalogue_with_user_presets(),
            "static": session.mesh_format != "pac", "parts": [
                {**part, **options.get(part["index"], {}), "diagnostic": diagnostics.get(part["id"], ""),
                 "shader_controls": bindings[part["id"]].shader_controls.to_dict()
                 if part["id"] in bindings and bindings[part["id"]].shader_controls is not None else None}
                for part in replacement["parts"]]}


def catalogue_with_user_presets():
    """The shader catalogue with this computer's saved presets after the built-in ones."""
    from cdmw.core.shader_preset_store import user_presets
    saved = user_presets()
    return [{**family, "presets": [*family["presets"], *({"label": row["name"], "values": row["values"], "user": True}
                                                         for row in saved.get(family["shader"], ()))]}
            for family in catalogue_payload()]


def _change_user_preset(request):
    from cdmw.core.shader_preset_store import delete_user_preset, save_user_preset
    if not isinstance(request, dict) or request.get("action") not in {"save", "delete"}:
        raise ValueError("Invalid shader preset request.")
    if request["action"] == "save":
        save_user_preset(request.get("shader"), request.get("name"), request.get("values"))
    else:
        delete_user_preset(request.get("shader"), request.get("name"))


def set_shader_controls(authoring, snapshot, args, *, entry, dependencies, stop_event):
    from cdmw.modding.mesh_parser import parse_mesh
    from cdmw.services.mesh_replacement_import import initial_replacement_state, mesh_with_part_ids, commit_replacement
    from cdmw.services.mesh_rust_replacement import replacement_ui_state
    from cdmw.services.mesh_rust_replacement_materials import stage_replacement_materials

    ui = shader_controls_ui_state(authoring, replacement_ui_state(authoring))
    if not ui["available"]:
        raise ValueError(ui["reason"])
    if "preset" in args:
        # A saved preset is a preference of this computer, not an edit of the model.
        _change_user_preset(args["preset"])
        return authoring.shadow_service.session_view(authoring.shadow_session_id)
    keys, reset = args.get("part_ids"), args.get("reset", False)
    if (not isinstance(keys, (list, tuple)) or not keys or any(not isinstance(key, str) for key in keys)
            or len(set(keys)) != len(keys) or not set(keys) <= {part["id"] for part in ui["parts"]}):
        raise ValueError("Select at least one material part for shader controls.")
    if type(reset) is not bool:
        raise ValueError("Invalid shader-control reset request.")
    value = None if reset else ShaderControls.from_dict(args.get("shader_controls"))
    if value is not None:
        value = _with_chosen_textures(value, args.get("texture_files"), stop_event)
    state = snapshot.replacement_state or initial_replacement_state(snapshot, entry, dependencies)
    parts = tuple(replace(part, shader_controls=value) if part.part_id in keys else part for part in state.parts)
    if parts == state.parts:
        return authoring.shadow_service.session_view(authoring.shadow_session_id)
    state = replace(state, parts=parts, revision=state.revision + 1)
    original = parse_mesh(snapshot.original_data, state.target_path)
    prepared = build_shader_control_files(state, original, state.companion_files, stop_event=stop_event)
    if value is not None:
        state = _capture_control_textures(state, original, prepared, args.get("_archive_dependencies"), stop_event)
    mesh = mesh_with_part_ids(snapshot, state)
    stage_replacement_materials(authoring, mesh, state, stop_event)
    return commit_replacement(authoring.shadow_service, snapshot, mesh, state,
                              label="Restore shader controls" if reset else "Edit shader controls", stop_event=stop_event)


def import_shader_texture(path, *, stop_event=None):
    """Read a user's texture file as DDS bytes. A DDS is kept as it is; an image is encoded as BC7."""
    import tempfile
    from pathlib import Path
    from cdmw.core.shader_texture_store import DDS_MAGIC, MAX_TEXTURE_BYTES

    source = Path(str(path or "")).expanduser()
    if not source.is_file():
        raise ValueError("The chosen texture file does not exist.")
    if source.stat().st_size > MAX_TEXTURE_BYTES:
        raise ValueError("The chosen texture file exceeds the 256 MiB limit.")
    data = source.read_bytes()
    if data.startswith(DDS_MAGIC):
        return data
    from PIL import Image, UnidentifiedImageError
    from cdmw.core.texture_native import encode_dds_with_directxtex
    try:
        with Image.open(source) as image:
            pixels = image.convert("RGBA")
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("The chosen texture is not a DDS or a readable image file.") from exc
    width, height = pixels.size
    if not all(4 <= side <= 8192 and side & (side - 1) == 0 for side in (width, height)):
        raise ValueError(f"Texture sides must be powers of two between 4 and 8192; this image is {width}x{height}.")
    with tempfile.TemporaryDirectory(prefix="cdmw_shader_texture_") as directory:
        png, dds = Path(directory) / "texture.png", Path(directory) / "texture.dds"
        pixels.save(png)
        raise_if_cancelled(stop_event)
        try:
            report = encode_dds_with_directxtex(png, dds, dds_format="BC7_UNORM", width=width, height=height,
                                                mip_count=max(width, height).bit_length(), stop_event=stop_event)
        except Exception as exc:
            raise ValueError("The image could not be encoded as DDS. Choose a DDS file instead.") from exc
        if not report or not dds.is_file():
            raise ValueError("The image could not be encoded as DDS. Choose a DDS file instead.")
        return dds.read_bytes()


def _with_chosen_textures(controls, texture_files, stop_event):
    """Store newly chosen files and name them in the controls; an empty path restores the source texture."""
    from cdmw.core.shader_texture_store import store_texture
    if texture_files is None:
        return controls
    if not isinstance(texture_files, dict) or any(
            not isinstance(name, str) or not isinstance(path, str) for name, path in texture_files.items()):
        raise ValueError("Invalid replacement texture request.")
    textures = dict(controls.textures)
    for name, path in texture_files.items():
        if path:
            textures[name] = store_texture(import_shader_texture(path, stop_event=stop_event))
        else:
            textures.pop(name, None)
    result = replace(controls, textures=tuple(textures.items()))
    result.validate()
    return result


def _capture_control_textures(state, original, prepared, context, stop_event):
    from cdmw.core.archive_extraction import read_archive_entry_data
    from cdmw.domain.mesh.replacement import ReplacementFile
    from cdmw.services.mesh_replacement_import import archive_location
    from cdmw.core.material_shader_controls import control_material_variants
    from cdmw.services.shader_controls_preview import EFFECT_NORMAL_PARAMETER
    settings = dict(shader_settings(state, original))
    required, optional = set(), set()
    for file in prepared:
        if not file.path.casefold().endswith((".pac_xml", ".pami")):
            continue
        for variant in control_material_variants(_sidecar_text(file.data), static=file.path.casefold().endswith(".pami")):
            for name, (_, _, textures) in variant.items():
                controls = settings.get(name)
                if controls is not None:
                    required.add(textures.get(family_for(controls.shader).mask, ""))
                    if controls.shader == "SkinnedMeshAnisotropy":
                        required.add(textures.get(EFFECT_NORMAL_PARAMETER, ""))
                    if controls.textures:
                        # The preview is rebuilt from this material's own texture set.
                        optional.update(textures.values())
    captured = list(state.dependencies)
    existing = {file.path.casefold() for file in (*captured, *state.companion_files, *prepared)}
    total = sum(len(file.data) for file in captured)
    for path in sorted((required | optional) - {""}):
        if path.casefold() in existing:
            continue
        raise_if_cancelled(stop_event)
        matches = tuple(context.entries_by_normalized_path.get(path.casefold(), ())) if context is not None else ()
        if not matches and path not in required:
            continue
        if not matches:
            raise ValueError(f"The shader mask is unavailable: {path}. Reopen this mesh from Browse Archives.")
        data, _, _ = read_archive_entry_data(matches[0], stop_event=stop_event)
        total += len(data)
        if total > 512 * 1024 * 1024:
            raise ValueError("Shader dependencies exceed the 512 MiB snapshot limit.")
        captured.append(ReplacementFile(path, bytes(data), archive_location(matches[0])))
        existing.add(path.casefold())
    return replace(state, dependencies=tuple(captured))
