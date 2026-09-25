"""Apply shader controls to already prepared, owned New Item material files."""
from dataclasses import replace
import xml.etree.ElementTree as ET

from cdmw.core.material_shader_controls import _rewrite_block
from cdmw.domain.mesh.shader_controls import EYE_COVER, validate_choices


def shader_control_bindings(files, choices, *, result=None, scene=None):
    """Resolve source names and whole atlases to exact output material owners."""
    if not choices:
        return {}
    validate_choices(choices, equipment=True)
    from cdmw.core.pac_xml_standard_material import find_material_wrappers
    from cdmw.services.new_item_materials import _plain_pbr_inputs, source_materials_from_import

    sources = source_materials_from_import(result, scene) if result is not None and scene is not None else {}
    source_by_base = {}
    if sources:
        inputs = _plain_pbr_inputs(files, sources)
        # Shared template textures do not prove source ownership. The Builder's
        # cloned wrappers may inherit only an import-owned base dependency.
        source_by_base = {path: source for path, source in inputs[-1].items() if path in inputs[3]}
    wanted = {name.casefold(): controls for name, controls in choices}
    bindings, found = {}, set()
    for path, data in files.side_files.items():
        if not path.casefold().endswith(".pac_xml"):
            continue
        text = data.decode("utf-8-sig")
        mapped, matched, unselected = {}, set(), set()
        for wrapper in find_material_wrappers(text):
            name = wrapper.submesh_name.casefold()
            base = wrapper.textures.get("_baseColorTexture") or wrapper.textures.get("_overlayColorTexture", "")
            source = sources.get(name) or source_by_base.get(base.replace("\\", "/").casefold())
            names = {name, str(getattr(source, "name", "")).casefold()}
            atlas = {part.name.casefold() for part in getattr(source, "atlas_sources", ())}
            selected = wanted.keys() & (names | atlas)
            if not selected:
                unselected.add(name)
                continue
            if atlas & wanted.keys() and not atlas <= wanted.keys() and not names & wanted.keys():
                raise ValueError("Shader controls affect a whole atlas material. Select all its parts or import them separately.")
            controls = wanted[next(iter(selected))]
            if atlas and controls.transparency_mask is not None:
                raise ValueError("Painted transparency needs separate material textures. Import these atlas parts separately before painting.")
            if any(wanted[alias] != controls for alias in selected):
                raise ValueError("Parts sharing an atlas material need the same shader controls.")
            if name in mapped and mapped[name][1] != controls:
                raise ValueError("Parts sharing an output material need the same shader controls.")
            # A single authored part can occur in several generated draw sections.
            # Choices are per part; the writer edits each occurrence separately.
            mapped.setdefault(name, (wrapper.submesh_name, controls))
            matched.update(selected)
        if mapped.keys() & unselected:
            raise ValueError("Parts sharing an output material must all use the same shader controls.")
        if mapped:
            bindings[path] = tuple(mapped.values())
            found.update(matched)
    missing = {name.casefold() for name, _ in choices} - found
    if missing:
        raise ValueError("Shader material bindings were not found: " + ", ".join(sorted(missing)))
    return bindings


def rewrite_new_item_shader_controls(text, choices, model_path, read_texture, *, stop_event=None, allow_missing=False, on_log=None):
    from cdmw.services.new_item_eye_cover import prepare_eye_cover_textures
    # Validate the material contract before decoding/encoding any textures.
    from cdmw.core.material_shader_controls import validate_source, _parameter_rows
    from cdmw.core.pac_xml_standard_material import find_material_wrappers
    if len(text) > 16 * 1024 * 1024:
        raise ValueError("Material sidecar exceeds the supported size limit.")
    validate_choices(choices, equipment=True)
    settings = {name.casefold(): controls for name, controls in choices}
    wrappers = [wrapper for wrapper in find_material_wrappers(text) if wrapper.submesh_name.casefold() in settings]
    matched = {wrapper.submesh_name.casefold() for wrapper in wrappers}
    if not allow_missing and settings.keys() - matched:
        raise ValueError("Shader material bindings were not found: " + ", ".join(sorted(settings.keys() - matched)))
    for wrapper in wrappers:
        validate_source(wrapper.shader, settings[wrapper.submesh_name.casefold()],
                        _parameter_rows(text[wrapper.start:wrapper.end]))
    paths, textures = prepare_eye_cover_textures(text, choices, model_path, read_texture, stop_event=stop_event, on_log=on_log)
    # Repeated names share the user's controls, but each section owns its source
    # maps and parameter metadata. Offset-keyed textures cannot overwrite another
    # section's inherited roughness/metallic channels.
    for wrapper in reversed(wrappers):
        try:
            block = _rewrite_block(text[wrapper.start:wrapper.end], wrapper.shader,
                settings[wrapper.submesh_name.casefold()], static=False, texture_paths=paths.get(wrapper.start, {}))
        except (ValueError, ET.ParseError) as exc:
            raise ValueError(f"{wrapper.submesh_name}: {exc}") from exc
        text = text[:wrapper.start] + block + text[wrapper.end:]
    return text, textures, matched


def apply_shader_controls(files, choices, *, result=None, scene=None, stop_event=None, on_log=None):
    if not choices:
        return files
    side = dict(files.side_files)
    sources = {path.replace("\\", "/").casefold(): data for path, data in side.items()}
    for path, mapped in shader_control_bindings(files, choices, result=result, scene=scene).items():
        data = side[path]
        text, textures, _ = rewrite_new_item_shader_controls(data.decode("utf-8-sig"), mapped, path,
            lambda texture: sources.get(texture.replace("\\", "/").casefold()), stop_event=stop_event, on_log=on_log)
        side.update(textures)
        side[path] = (b"\xef\xbb\xbf" if data.startswith(b"\xef\xbb\xbf") else b"") + text.encode("utf-8")
    notes = ("Experimental shader controls applied to selected materials; game validation is still required.",)
    if any(controls.shader == EYE_COVER.shader for _, controls in choices):
        notes += (EYE_COVER.note,)
    return replace(files, side_files=side, notes=(*files.notes, *notes))
