"""Part selection and preview data for experimental New Item translucency."""

import copy
import hashlib
import math
import threading
from collections import OrderedDict
from dataclasses import replace

from cdmw.domain.cancellation import RunCancelled, raise_if_cancelled
from cdmw.domain.new_item.spec import MaterialRoute
from cdmw.domain.new_item.translucency import TranslucencyChoice
from cdmw.services.new_item_planning import NewItemPlanError


_BASE_CACHE_MAX_BYTES = 64 * 1024 * 1024
_BASE_CACHE_MAX_ENTRIES = 16
_BASE_CACHE: OrderedDict[tuple, bytes] = OrderedDict()
_BASE_CACHE_LOCK = threading.Lock()


def _encode_prepared_base(path, output, name, width, height, *, on_log, stop_event):
    from cdmw.core.texture_native import encode_dds_with_directxtex, native_texture_backend_identity
    from cdmw.domain.textures.output import max_mips_for_size

    mip_count = max_mips_for_size(width, height)
    # Hash the prepared image, including source factors, alpha and atlas baking.
    # Paths/stat stamps alone would miss edits and change on every temporary build.
    key = (hashlib.sha256(path.read_bytes()).digest(), width, height, mip_count,
           "BC7_UNORM", native_texture_backend_identity())
    raise_if_cancelled(stop_event)
    while not _BASE_CACHE_LOCK.acquire(timeout=0.05):
        raise_if_cancelled(stop_event)
    try:
        raise_if_cancelled(stop_event)
        if key in _BASE_CACHE:
            _BASE_CACHE.move_to_end(key)
            if on_log is not None:
                on_log(f"Reusing {name} translucent base colour (unchanged source and encoder).")
            return _BASE_CACHE[key]
        if on_log is not None:
            on_log(f"Encoding {name} translucent base colour from source (BC7, full mipmaps)")
        report = encode_dds_with_directxtex(
            path, output, dds_format="BC7_UNORM", width=width, height=height,
            mip_count=mip_count, on_log=on_log, stop_event=stop_event,
        )
        raise_if_cancelled(stop_event)
        if not report or not output.is_file() or not output.stat().st_size:
            raise NewItemPlanError(f"{name}: the DDS encoder produced nothing for the translucent base colour.")
        data = output.read_bytes()
        if len(data) <= _BASE_CACHE_MAX_BYTES:
            while _BASE_CACHE and (len(_BASE_CACHE) >= _BASE_CACHE_MAX_ENTRIES
                    or sum(map(len, _BASE_CACHE.values())) + len(data) > _BASE_CACHE_MAX_BYTES):
                _BASE_CACHE.popitem(last=False)
            _BASE_CACHE[key] = data
        return data
    finally:
        _BASE_CACHE_LOCK.release()


def encode_translucent_base(source, *, on_log=None, stop_event=None) -> bytes | None:
    """Encode glass colour from authored pixels, never from the Builder's BC1.

    Existing standalone DDS inputs keep their authored compression. Atlas inputs
    already require baking, so all tiles use their original pixels and factors.
    Missing source metadata (prebuilt imports) leaves the existing texture alone.
    """
    import tempfile
    from pathlib import Path

    from PIL import Image

    from cdmw.modding.material_texture_payloads import _source_slot_png_with_base_color_factor_path

    raise_if_cancelled(stop_event)
    atlas = source.atlas_section
    parts = source.atlas_sources if atlas is not None else (source,)
    if not any(part.base_slot is not None for part in parts):
        return None
    if atlas is None and source.base_slot.source_path.suffix.lower() == ".dds":
        return None
    with tempfile.TemporaryDirectory(prefix="cdmw_new_item_glass_") as directory:
        root = Path(directory)
        prepared = {}
        for index, part in enumerate(parts):
            raise_if_cancelled(stop_event)
            slot = part.base_slot
            if slot is None:
                raise NewItemPlanError(f"{part.name}: the source base colour for the translucent atlas is unavailable.")
            try:
                path = _source_slot_png_with_base_color_factor_path(slot, output_root=root, stop_event=stop_event)
                with Image.open(path) as original:
                    image = original.convert("RGBA")
                if slot.alpha_mode.upper() == "OPAQUE":
                    image.putalpha(255)
                path = root / f"base_{index}.png"
                image.save(path)
                image.close()
            except RunCancelled:
                raise
            except Exception as exc:
                raise NewItemPlanError(f"{part.name}: cannot prepare the source colour for translucency: {exc}") from exc
            prepared[part.name.lower()] = path
        if atlas is not None:
            from cdmw.modding.full_import_model_replacement import FULL_IMPORT_MODEL_REPLACEMENT_PROFILE
            from cdmw.modding.material_profiles import get_complete_swap_material_profile
            from cdmw.modding.material_rebuilt_payloads import _bake_complete_swap_material_atlas_png
            from cdmw.modding.material_replacer import ReplacementTextureSet, ReplacementTextureSlot, TextureReplacementReport

            report = TextureReplacementReport()
            path = _bake_complete_swap_material_atlas_png(
                target_name=f"{atlas.target_submesh_name}_plain_translucent", rects=atlas.atlas_rects,
                texture_sets={name: ReplacementTextureSet(name, slots={"base": ReplacementTextureSlot(name, "base", path)})
                              for name, path in prepared.items()},
                slot_kind="base", padding=int(getattr(atlas, "atlas_padding", 8)), report=report,
                material_profile=get_complete_swap_material_profile(FULL_IMPORT_MODEL_REPLACEMENT_PROFILE),
            )
            if path is None or report.errors:
                raise NewItemPlanError(f"{source.name}: translucent colour atlas could not be preserved: {'; '.join(report.errors)}")
        with Image.open(path) as image:
            width, height = image.size
        return _encode_prepared_base(
            path, root / "base.dds", source.name, width, height, on_log=on_log, stop_event=stop_event,
        )


def apply_prebuilt_translucency(files, route: MaterialRoute, choice: TranslucencyChoice | None, *, on_log=None):
    """Prebuilt materials already own their textures and glow; patch only the selection."""
    if choice is None:
        return files
    if route is not MaterialRoute.PLAIN_PBR:
        raise NewItemPlanError("Enable Plain PBR materials to export translucency.")
    choice.validate()
    xml_keys = [key for key in files.side_files if key.lower().endswith(".pac_xml")]
    if len(xml_keys) != 1:
        raise NewItemPlanError(f"the import carries {len(xml_keys)} .pac_xml sidecar(s), not one")
    key = xml_keys[0]
    try:
        text = files.side_files[key].decode("utf-8")
        from cdmw.services.translucency_surface import apply_translucency_surface
        sources = {path.replace("\\", "/").casefold(): data for path, data in files.side_files.items()}
        text, surface_files = apply_translucency_surface(text,
            {name: choice.values_for(name) for name in choice.parts},
            {name: choice.surface_for(name) for name in choice.parts}, key.removesuffix("_xml"),
            lambda path: sources.get(path.replace("\\", "/").casefold()))
    except (UnicodeDecodeError, ValueError) as exc:
        raise NewItemPlanError(str(exc)) from exc
    notes = []
    for name in choice.parts:
        thickness, extinction = choice.values_for(name)
        note = f"Translucency: {name} (thickness {thickness:g}, extinction {extinction:g})"
        notes.append(note)
        if on_log is not None:
            on_log(note)
    return replace(
        files, side_files={**files.side_files, **surface_files, key: text.encode("utf-8")}, material_route=route.value,
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
        choice.surface_for(*matches)
    except ValueError as exc:
        raise NewItemPlanError(f"{wrapper_name}: {exc}") from exc
    return matches


def translucency_preview_parameter_groups(mesh, choice: TranslucencyChoice | None = None, *, source_transmission=True):
    from cdmw.services.new_item_materials import appearance_preview_part_names

    if choice is not None:
        choice.validate()
    groups = []
    for index, part in enumerate(getattr(mesh, "submeshes", ())):
        names = appearance_preview_part_names(part)
        absorption = choice.values_for(*names) if choice else None
        if absorption is None:
            absorption = source_translucency(part) if source_transmission else None
        groups.append({
            "source_submesh_indices": [index],
            "editor_role": "replacement_preview",
            "translucency": list(absorption) if absorption is not None else None,
        })
        surface = choice.surface_for(*names) if choice else None
        if surface is not None:
            groups[-1]["translucency_surface"] = list(surface)
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
        if "translucency_surface" in group:
            clone.preview_native_material_overrides["translucency_surface"] = group["translucency_surface"]
        result.submeshes.append(clone)
    return result
