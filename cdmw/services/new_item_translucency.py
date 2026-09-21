"""Part selection and preview data for experimental New Item translucency."""

import copy
import math
from dataclasses import replace

from cdmw.domain.new_item.spec import MaterialRoute
from cdmw.domain.new_item.translucency import TranslucencyChoice
from cdmw.services.new_item_planning import NewItemPlanError


def apply_prebuilt_translucency(files, route: MaterialRoute, choice: TranslucencyChoice | None, *, on_log=None):
    """Prebuilt materials already own their textures and glow; patch only the selection."""
    if choice is None:
        return files
    if route is not MaterialRoute.PLAIN_PBR:
        raise NewItemPlanError("Enable Plain PBR materials to export translucency.")
    choice.validate()
    from cdmw.core.pac_xml_standard_material import PacXmlMaterialError, rewrite_translucency

    xml_keys = [key for key in files.side_files if key.lower().endswith(".pac_xml")]
    if len(xml_keys) != 1:
        raise NewItemPlanError(f"the import carries {len(xml_keys)} .pac_xml sidecar(s), not one")
    key = xml_keys[0]
    try:
        text = files.side_files[key].decode("utf-8")
        text = rewrite_translucency(text, {name: choice.values_for(name) for name in choice.parts})
    except (UnicodeDecodeError, PacXmlMaterialError) as exc:
        raise NewItemPlanError(str(exc)) from exc
    notes = []
    for name in choice.parts:
        thickness, extinction = choice.values_for(name)
        note = f"Translucency: {name} (thickness {thickness:g}, extinction {extinction:g})"
        notes.append(note)
        if on_log is not None:
            on_log(note)
    return replace(
        files, side_files={**files.side_files, key: text.encode("utf-8")}, material_route=route.value,
        notes=(*files.notes, *notes), warnings=(*files.warnings,
            "Experimental SkinnedMeshTranslucent: thickness and extinction control absorption. "
            "Viewport transmission is approximate; game refraction and lighting may differ."),
    )


def source_translucency(source) -> tuple[float, float] | None:
    """Map authored glass to the existing experimental absorption preset.

    glTF transmission is not ordinary alpha blending. Keep this separate from
    BLEND/MASK, which can describe decals and foliage as well as glass. The game
    controls are an approximation, not a conversion of transmission percentages.
    """
    atlas = tuple(getattr(source, "atlas_sources", ()) or ())
    if atlas:
        values = [source_translucency(part) for part in atlas]
        if any(value is not None for value in values) and any(value is None for value in values):
            raise NewItemPlanError(
                f"{source.name}: glass and opaque materials share one atlas. "
                "Import them as separate parts, or explicitly select the whole atlas for translucency."
            )
        return values[0]
    factor = getattr(source, "transmission_factor", 0.0)
    for parameter in tuple(getattr(source, "preview_material_parameters", ()) or ()):
        if getattr(parameter, "parameter_name", "") == "_transmissionFactor":
            factor = getattr(parameter, "value", 0.0)
            break
    try:
        factor = float(factor)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(factor) or factor <= 0:
        return None
    preset = TranslucencyChoice()
    return preset.thickness, preset.extinction


def selected_translucency(choice: TranslucencyChoice | None, wrapper_name: str, source) -> set[str]:
    """Resolve source names through Builder wrappers, refusing mixed opaque atlases."""
    if choice is None:
        return set()
    names = {wrapper_name.casefold(), str(getattr(source, "name", "")).casefold()}
    atlas = tuple(getattr(source, "atlas_sources", ()) or ())
    atlas_names = {part.name.casefold() for part in atlas}
    wanted = {name.casefold() for name in choice.parts}
    if atlas_names & wanted and not atlas_names <= wanted and not names & wanted:
        raise NewItemPlanError(
            f"{wrapper_name}: translucent and opaque parts share one atlas. "
            "Select all of its materials for translucency or import them as separate parts."
        )
    matches = wanted & (names | atlas_names)
    try:
        choice.values_for(*matches)
    except ValueError as exc:
        raise NewItemPlanError(f"{wrapper_name}: {exc}") from exc
    return matches


def translucency_preview_parameter_groups(mesh, choice: TranslucencyChoice | None = None, *, source_transmission=True):
    if choice is not None:
        choice.validate()
    groups = []
    for index, part in enumerate(getattr(mesh, "submeshes", ())):
        absorption = choice.values_for(getattr(part, "name", ""), getattr(part, "material", "")) if choice else None
        if absorption is None:
            absorption = source_translucency(part) if source_transmission else None
        groups.append({
            "source_submesh_indices": [index],
            "editor_role": "replacement_preview",
            "translucency": list(absorption) if absorption is not None else None,
        })
    return tuple(groups)


def translucency_preview_mesh(mesh, choice: TranslucencyChoice | None = None, *, source_transmission=True):
    """Copy authored inputs for Effects without changing the reusable import."""
    groups = translucency_preview_parameter_groups(mesh, choice, source_transmission=source_transmission)
    if choice is None and not any(group["translucency"] is not None for group in groups):
        return mesh
    result = copy.copy(mesh)
    result.submeshes = []
    for part, group in zip(mesh.submeshes, groups):
        clone = copy.copy(part)
        clone.preview_native_material_overrides = dict(getattr(part, "preview_native_material_overrides", {}) or {})
        if group["translucency"] is not None:
            clone.preview_native_material_overrides["translucency"] = group["translucency"]
        result.submeshes.append(clone)
    return result
