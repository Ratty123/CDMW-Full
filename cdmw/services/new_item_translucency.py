"""Part selection and preview data for experimental New Item translucency."""

import copy

from cdmw.domain.new_item.translucency import TranslucencyChoice
from cdmw.services.new_item_planning import NewItemPlanError


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
    return wanted & (names | atlas_names)


def translucency_preview_parameter_groups(mesh, choice: TranslucencyChoice | None = None):
    if choice is not None:
        choice.validate()
    return tuple(
        {
            "source_submesh_indices": [index],
            "editor_role": "replacement_preview",
            "translucency": [choice.thickness, choice.extinction]
            if choice is not None and choice.matches(getattr(part, "name", ""), getattr(part, "material", ""))
            else None,
        }
        for index, part in enumerate(getattr(mesh, "submeshes", ()))
    )


def translucency_preview_mesh(mesh, choice: TranslucencyChoice | None = None):
    """Copy authored inputs for Effects without changing the reusable import."""
    if choice is None:
        return mesh
    result = copy.copy(mesh)
    result.submeshes = []
    for part, group in zip(mesh.submeshes, translucency_preview_parameter_groups(mesh, choice)):
        clone = copy.copy(part)
        clone.preview_native_material_overrides = dict(getattr(part, "preview_native_material_overrides", {}) or {})
        if group["translucency"] is not None:
            clone.preview_native_material_overrides["translucency"] = group["translucency"]
        result.submeshes.append(clone)
    return result
