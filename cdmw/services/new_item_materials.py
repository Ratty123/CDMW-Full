"""The plain-PBR material route of the New Item Studio.

The Builder's Full Import gives an imported model the template's layered material,
which the game then draws its own detail layers over. This route rewrites the
wrappers the import owns into the game's texture-driven `SkinnedMeshStandard`
(`SkinnedMeshEmissive` where the source glows), see
:mod:`cdmw.core.pac_xml_standard_material`, and gives them a real `_sp` map (G
roughness, B metalness) encoded from the source's metallic/roughness texture when
the source is known, else the Builder's material mask (same channel layout, but its
roughness was clamped towards matte).

`ModelFiles` in, `ModelFiles` out; nothing here reads or writes an archive.
"""

from __future__ import annotations

import copy
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Mapping, Optional, Tuple

from cdmw.core.pac_xml_standard_material import (
    PacXmlMaterialError,
    PlainMaterial,
    find_material_wrappers,
    rewrite_materials,
)
from cdmw.domain.new_item.spec import MaterialRoute
from cdmw.services.new_item_planning import ModelFiles, NewItemPlanError

_BASE_NAME_RE = re.compile(r"(_basecolor|_base_[0-9a-f]+)?\.dds$", re.I)
_BOM = "\ufeff"


@dataclass(frozen=True, slots=True)
class SourceMaterialTextures:
    """The source (glTF) textures of one material, by role, as files on disk, and the
    scalar factors that stand in for a map the source does not carry."""

    name: str
    base: Optional[Path] = None
    normal: Optional[Path] = None
    #: the metallic/roughness map (glTF: G roughness, B metalness, the `_sp` layout)
    material: Optional[Path] = None
    emissive: Optional[Path] = None
    #: `#RRGGBBAA` from a glTF `emissiveFactor`, for a material that glows with no map
    emissive_color: str = ""
    #: the glTF's emissive strength. The shipped weapons' own `_emissiveIntensity` is
    #: 1.00 at the median (27 of the 32 that state one round to 1), so this carries across
    #: as it stands rather than through a scale nobody measured.
    emissive_intensity: float = 0.0
    #: glTF `roughnessFactor` / `metallicFactor` (1.0 when the source says nothing);
    #: without a metallic/roughness map they become a solid `_sp`
    roughness_factor: float = 1.0
    metallic_factor: float = 1.0


@dataclass(frozen=True, slots=True)
class PlainPbrRoute:
    files: ModelFiles
    #: submesh names rewritten
    rewritten: Tuple[str, ...]
    #: one line per rewritten wrapper, for the plan summary
    lines: Tuple[str, ...]
    warnings: Tuple[str, ...] = ()
    #: new `_sp` files this route encoded, game-relative
    encoded: Tuple[str, ...] = field(default_factory=tuple)


def source_materials_from_import(result: object, scene: object) -> Dict[str, SourceMaterialTextures]:
    """target submesh name (casefolded) -> the source material's textures.

    Read from the Builder result's source-owned draw sections (target submesh ->
    source material name) and the scene import's material bindings (material name
    -> texture slots). Either missing gives an empty map, and the route falls back
    to the Builder's masks.
    """

    bindings = {}
    submeshes = tuple(getattr(getattr(scene, "mesh", None), "submeshes", ()) or ())
    for binding in tuple(getattr(scene, "material_bindings", ()) or ()):
        name = str(getattr(binding, "material_name", "") or "")
        slots = {}
        # the scalar factors the importer keeps on the submesh's preview parameters
        index = int(getattr(binding, "submesh_index", -1))
        if 0 <= index < len(submeshes):
            for parameter in tuple(getattr(submeshes[index], "preview_material_parameters", ()) or ()):
                pname = str(getattr(parameter, "parameter_name", "") or "")
                raw = str(getattr(parameter, "value", "") or "")
                # A glTF material can glow with no map at all: an emissiveFactor is a
                # colour and the importer keeps it here beside the scalar factors. The
                # axe's blue gems are exactly that, and reading only the maps left them
                # to fall back on their dark base colour -- black in game.
                if pname == "_emissiveColor" and raw.startswith("#"):
                    hexed = raw[1:]
                    if len(hexed) == 6:
                        slots["emissive_color"] = f"#{hexed.upper()}FF"
                    elif len(hexed) == 8:
                        slots["emissive_color"] = f"#{hexed.upper()}"
                    continue
                try:
                    value = float(raw)
                except (TypeError, ValueError):
                    continue
                if pname == "_roughnessFactor":
                    slots["roughness_factor"] = max(0.0, min(1.0, value))
                elif pname == "_metallicFactor":
                    slots["metallic_factor"] = max(0.0, min(1.0, value))
                elif pname == "_emissiveIntensity":
                    slots["emissive_intensity"] = max(0.0, value)
        for slot_kind, path in tuple(getattr(binding, "texture_slots", ()) or ()):
            kind = str(slot_kind or "").strip().lower()
            candidate = Path(str(path))
            if kind in {"base", "basecolor", "base_color", "albedo", "diffuse"} and candidate.is_file():
                slots.setdefault("base", candidate)
            elif kind in {"normal"} and candidate.is_file():
                slots.setdefault("normal", candidate)
            elif kind in {"material", "metallic_roughness", "metallicroughness", "pbr", "orm"} and candidate.is_file():
                slots.setdefault("material", candidate)
            elif kind in {"emissive", "emission"} and candidate.is_file():
                slots.setdefault("emissive", candidate)
        if name:
            bindings.setdefault(name.casefold(), SourceMaterialTextures(name=name, **slots))
    out: Dict[str, SourceMaterialTextures] = {}
    for section in tuple(getattr(result, "source_owned_output_draw_sections", ()) or ()):
        target = str(getattr(section, "target_submesh_name", "") or "").casefold()
        source = str(getattr(section, "source_material_name", "") or "").casefold()
        if target and source in bindings:
            out.setdefault(target, bindings[source])
    return out


def _sp_path_for(base_path: str, source_name: str) -> str:
    """`.../<stem>_<material>_basecolor.dds` -> `.../<stem>_<material>_sp.dds`."""

    folder, _, name = base_path.replace("\\", "/").rpartition("/")
    if _BASE_NAME_RE.search(name):
        new_name = _BASE_NAME_RE.sub("_sp.dds", name, count=1)
    else:
        new_name = f"{name[:-4]}_sp.dds" if name.lower().endswith(".dds") else f"{name}_sp.dds"
    return f"{folder}/{new_name}" if folder else new_name


def encode_sp_from_png(png: Path, *, on_log: Optional[Callable[[str], None]] = None) -> bytes:
    """Encode a metallic/roughness PNG as the game's `_sp` DDS (BC1, full mip chain).

    glTF packs roughness in G and metalness in B, which is the `_sp` layout, so those
    two channels go through unchanged; the shipped `_sp` textures carry 255 in R (a
    steel sword's guard reads 255/59/255, its handle 255/111/43), and a glTF map's R
    is occlusion or nothing, so R is set to 255 the way the game's own are.
    """

    from PIL import Image

    from cdmw.core.texture_native import encode_dds_with_directxtex
    from cdmw.domain.textures.output import max_mips_for_size

    with Image.open(png) as image:
        width, height = image.size
        rgb = image.convert("RGB")
    _red, green, blue = rgb.split()
    rgb = Image.merge("RGB", (Image.new("L", rgb.size, 255), green, blue))
    with tempfile.TemporaryDirectory(prefix="cdmw_new_item_sp_") as temp:
        prepared = Path(temp) / f"{png.stem}_sp.png"
        rgb.save(prepared)
        produced = Path(temp) / f"{png.stem}_sp.dds"
        report = encode_dds_with_directxtex(
            prepared, produced, dds_format="BC1_UNORM", width=width, height=height,
            mip_count=max_mips_for_size(width, height), on_log=on_log,
        )
        if not report or not produced.is_file() or produced.stat().st_size == 0:
            raise NewItemPlanError(f"the DDS encoder produced nothing for {png.name}")
        return produced.read_bytes()


def encode_sp_from_factors(roughness: float, metallic: float, *, on_log: Optional[Callable[[str], None]] = None) -> bytes:
    """A solid `_sp` (16x16, BC1, full mips) from glTF `roughnessFactor` and `metallicFactor`,
    for a source material with no metallic/roughness map (the Buster Sword's, factors only)."""

    from PIL import Image

    from cdmw.core.texture_native import encode_dds_with_directxtex
    from cdmw.domain.textures.output import max_mips_for_size

    g = int(round(max(0.0, min(1.0, float(roughness))) * 255))
    b = int(round(max(0.0, min(1.0, float(metallic))) * 255))
    with tempfile.TemporaryDirectory(prefix="cdmw_new_item_sp_") as temp:
        prepared = Path(temp) / f"factors_r{g}_m{b}_sp.png"
        Image.new("RGB", (16, 16), (255, g, b)).save(prepared)
        produced = Path(temp) / f"factors_r{g}_m{b}_sp.dds"
        report = encode_dds_with_directxtex(prepared, produced, dds_format="BC1_UNORM", width=16, height=16, mip_count=max_mips_for_size(16, 16), on_log=on_log)
        if not report or not produced.is_file() or produced.stat().st_size == 0:
            raise NewItemPlanError("the DDS encoder produced nothing for the factor-only _sp")
        return produced.read_bytes()


def encode_emissive_from_png(png: Path, *, on_log: Optional[Callable[[str], None]] = None) -> Tuple[bytes, str]:
    """Encode an emissive PNG as the game's intensity map (BC4, the pixel's strongest
    channel, full mips) and return it with the `#RRGGBBFF` colour the lit pixels
    average to.

    The game's emissive is one intensity texture times one colour; a coloured
    source keeps its hue through the colour and its shape through the map. The map
    takes the strongest channel, not the luminance: a pure blue glow is as bright
    as a white one to the eye that reads it, and luminance would have made
    Frostmourne's runes a quarter as strong (seen in game 2026-08-18).
    """

    import numpy as np
    from PIL import Image

    from cdmw.core.texture_native import encode_dds_with_directxtex
    from cdmw.domain.textures.output import max_mips_for_size

    with Image.open(png) as image:
        width, height = image.size
        rgb = image.convert("RGB")
    pixels = np.asarray(rgb, dtype=np.float64).reshape(-1, 3)
    strength = pixels.max(axis=1)
    luminance = Image.fromarray(strength.reshape(height, width).astype(np.uint8), mode="L")
    # the colour: strength-weighted mean of the pixels that glow at all, scaled so
    # the strongest channel is full (the map carries the strength)
    weights = strength
    lit = weights > 8
    if lit.any():
        mean = (pixels[lit] * weights[lit, None]).sum(axis=0) / weights[lit].sum()
        peak = float(mean.max())
        scaled = mean * (255.0 / peak) if peak > 0 else mean
        color = "#%02X%02X%02XFF" % tuple(int(min(255, round(channel))) for channel in scaled)
    else:
        color = "#FFFFFFFF"
    with tempfile.TemporaryDirectory(prefix="cdmw_new_item_emi_") as temp:
        prepared = Path(temp) / f"{png.stem}_emi.png"
        luminance.save(prepared)
        produced = Path(temp) / f"{png.stem}_emi.dds"
        report = encode_dds_with_directxtex(
            prepared, produced, dds_format="BC4_UNORM", width=width, height=height,
            mip_count=max_mips_for_size(width, height), on_log=on_log,
        )
        if not report or not produced.is_file() or produced.stat().st_size == 0:
            raise NewItemPlanError(f"the DDS encoder produced nothing for {png.name}")
        return produced.read_bytes(), color


def _emi_path_for(base_path: str) -> str:
    """`.../<stem>_<material>_basecolor.dds` -> `.../<stem>_<material>_emi.dds`, for a part
    the reader asked to glow when the import generated no emissive slot for it."""

    folder, _, name = base_path.replace("\\", "/").rpartition("/")
    if _BASE_NAME_RE.search(name):
        new_name = _BASE_NAME_RE.sub("_emi.dds", name, count=1)
    else:
        new_name = f"{name[:-4]}_emi.dds" if name.lower().endswith(".dds") else f"{name}_emi.dds"
    return f"{folder}/{new_name}" if folder else new_name


def encode_emissive_solid(*, on_log: Optional[Callable[[str], None]] = None) -> bytes:
    """A solid intensity map (16x16, BC4, full mips): the whole part glows.

    The game's emissive is a map times a colour times a number, so "this part glows" is a
    map that is white everywhere; the colour and the number carry the rest. A part the
    reader picked has no mask of its own to cut, and inventing one would be guessing at
    which pixels they meant.
    """

    from PIL import Image

    from cdmw.core.texture_native import encode_dds_with_directxtex
    from cdmw.domain.textures.output import max_mips_for_size

    with tempfile.TemporaryDirectory(prefix="cdmw_new_item_glow_") as temp:
        prepared = Path(temp) / "glow_emi.png"
        Image.new("L", (16, 16), 255).save(prepared)
        produced = Path(temp) / "glow_emi.dds"
        report = encode_dds_with_directxtex(
            prepared, produced, dds_format="BC4_UNORM", width=16, height=16,
            mip_count=max_mips_for_size(16, 16), on_log=on_log,
        )
        if not report or not produced.is_file() or produced.stat().st_size == 0:
            raise NewItemPlanError("the DDS encoder produced nothing for the solid glow map")
        return produced.read_bytes()


def glow_preview_parameter_groups(mesh: object, glow: object = None) -> Tuple[Dict[str, object], ...]:
    """The Glow choice as resident material parameter groups for the studio's viewport.

    What the export writes as a solid map times a colour times a number, the resident
    renderer draws from the same three values sent as parameter overrides, so the
    preview and the shipped item agree by construction. `mesh` is the ParsedMesh the
    preview package was built from, so the group indices are the package's own submesh
    order. A ticked part (matched on the submesh's material or name, the two keys the
    export matches on) takes the reader's colour and strength; every other part goes
    back to the import's own emissive when it declares one, else its override is
    cleared outright (an explicit None, which the renderer reads as "unset").
    Every push is a complete statement over all submeshes: un-ticking needs no
    memory of what was sent before. Empty when the mesh has no submeshes.
    """

    from types import SimpleNamespace

    from cdmw.domain.textures.material_parameters import (
        evaluate_material_parameters,
        material_parameter_renderer_overrides,
        source_emissive_strength,
    )

    ticked = {str(name).casefold() for name in tuple(getattr(glow, "parts", ()) or ())}
    # floats defeat evaluate's byte-colour heuristic: (1, 1, 1) as ints would read as
    # near-black 1/255 channels
    color = tuple(float(channel) for channel in tuple(getattr(glow, "color", ()) or ())[:3])
    intensity = float(getattr(glow, "intensity", 0.0) or 0.0)
    buckets: Dict[tuple, Tuple[Dict[str, object], list]] = {}
    for index, submesh in enumerate(tuple(getattr(mesh, "submeshes", ()) or ())):
        names = {
            str(getattr(submesh, "material", "") or "").casefold(),
            str(getattr(submesh, "name", "") or "").casefold(),
        }
        wants_glow = bool(ticked & names)
        adjustment = (
            SimpleNamespace(material_role="glow", emissive_color_rgb=color, emissive_strength=intensity)
            if wants_glow
            else None
        )
        if wants_glow or source_emissive_strength(submesh) is not None:
            overrides = material_parameter_renderer_overrides(evaluate_material_parameters(
                source_slot=submesh, part_adjustment=adjustment, emissive_role=True,
            ))
            values: Dict[str, object] = {
                "emissive_intensity": overrides.get("emissive_intensity"),
                "emissive_color": overrides.get("emissive_color"),
                "emissive_color_authoritative": overrides.get("emissive_color") is not None,
            }
        else:
            values = {"emissive_intensity": None, "emissive_color": None, "emissive_color_authoritative": None}
        key = tuple((name, repr(value)) for name, value in sorted(values.items()))
        if key not in buckets:
            buckets[key] = (values, [])
        buckets[key][1].append(index)
    return tuple(
        {"source_submesh_indices": list(indices), "editor_role": "replacement_preview", **values}
        for values, indices in buckets.values()
    )


def glow_preview_mesh(mesh: object, glow: object = None) -> object:
    """Copy a preview mesh with the current Glow choice in its material authority.

    Effects builds a fresh resident package instead of sharing Model & Placement's live
    parameter channel. Put the same overrides on a copy of its input mesh so material
    synthesis carries the chosen parts, colour and strength into that package without
    changing the reusable imported source.
    """

    if glow is None or not tuple(getattr(glow, "parts", ()) or ()):
        return mesh
    updates: Dict[int, Dict[str, object]] = {}
    parameter_names = ("emissive_intensity", "emissive_color", "emissive_color_authoritative")
    for group in glow_preview_parameter_groups(mesh, glow):
        values = {name: group.get(name) for name in parameter_names}
        for index in group["source_submesh_indices"]:
            updates[int(index)] = values

    submeshes = []
    for index, source in enumerate(tuple(getattr(mesh, "submeshes", ()) or ())):
        submesh = copy.copy(source)
        overrides = getattr(source, "preview_native_material_overrides", {}) or {}
        overrides = dict(overrides) if isinstance(overrides, Mapping) else {}
        for name, value in updates[index].items():
            if value is None:
                overrides.pop(name, None)
            else:
                overrides[name] = value
        submesh.preview_native_material_overrides = overrides
        submeshes.append(submesh)

    result = copy.copy(mesh)
    result.submeshes = submeshes
    return result


def route_plain_pbr(
    files: ModelFiles,
    *,
    sources: Optional[Mapping[str, SourceMaterialTextures]] = None,
    encode: Callable[[Path], bytes] = encode_sp_from_png,
    encode_emissive: Callable[[Path], Tuple[bytes, str]] = encode_emissive_from_png,
    encode_factors: Callable[[float, float], bytes] = encode_sp_from_factors,
    encode_glow: Callable[[], bytes] = encode_emissive_solid,
    glow: object = None,
    on_log: Optional[Callable[[str], None]] = None,
) -> PlainPbrRoute:
    """Rewrite the wrappers the import owns to the plain shaders; see the module doc.

    A wrapper is the import's when one of its textures is among `files.side_files`.
    Its base colour is the Builder's (`_baseColorTexture`, else `_overlayColorTexture`),
    its normal the Builder's `_normalTexture`; its `_sp` is encoded from
    `sources[submesh].material` when given, else the Builder's `_detailMaskTexture`
    mask.

    Glow is not inherited. Its emissive is encoded from `sources[submesh].emissive` when
    the model brought one; else, for a submesh whose own name or whose source material's
    name is in `glow.parts`, a solid map in
    `glow`'s colour and strength; else nothing, and the wrapper goes back to the plain
    shader. The template's own emissive rides on a mask cut for the template's mesh, and
    what the importer generates in its place is flat, so inheriting it lights the whole
    model. Wrappers that share a base texture share a source. Side files no wrapper names
    any more are dropped.
    """

    sources = dict(sources or {})
    glow_parts = {str(name).casefold() for name in tuple(getattr(glow, "parts", ()) or ())}
    glow_color = str(getattr(glow, "hex_color", lambda: "#FFFFFFFF")() or "#FFFFFFFF")
    glow_intensity = float(getattr(glow, "intensity", 1.0) or 1.0)
    xml_keys = [key for key in files.side_files if key.lower().endswith(".pac_xml")]
    if len(xml_keys) != 1:
        raise NewItemPlanError(f"the import carries {len(xml_keys)} .pac_xml sidecar(s), not one")
    xml_key = xml_keys[0]
    raw = files.side_files[xml_key]
    text = raw.decode("utf-8", errors="replace")
    bom = text.startswith(_BOM)
    if bom:
        text = text[len(_BOM):]
    by_lower = {key.replace("\\", "/").casefold(): key for key in files.side_files}
    wrappers = find_material_wrappers(text)
    # a cloned section draws with its donor's textures; give it the donor's source too
    source_by_base: Dict[str, SourceMaterialTextures] = {}
    for wrapper in wrappers:
        source = sources.get(wrapper.submesh_name.casefold())
        base = wrapper.textures.get("_baseColorTexture") or wrapper.textures.get("_overlayColorTexture")
        if source is not None and base:
            source_by_base.setdefault(base.replace("\\", "/").casefold(), source)
    replacements: Dict[str, PlainMaterial] = {}
    new_files: Dict[str, bytes] = {}
    emissive_done: Dict[str, Tuple[str, str]] = {}
    lines = []
    warnings = []
    encoded = []
    for wrapper in wrappers:
        owned = {name: path for name, path in wrapper.textures.items() if path.replace("\\", "/").casefold() in by_lower}
        if not owned:
            continue
        base = owned.get("_baseColorTexture") or owned.get("_overlayColorTexture")
        if not base:
            warnings.append(f"{wrapper.submesh_name}: the import gave it no base colour texture, so its material is left as the Builder wrote it.")
            continue
        normal = owned.get("_normalTexture", "")
        source = sources.get(wrapper.submesh_name.casefold()) or source_by_base.get(base.replace("\\", "/").casefold())
        material = ""
        how = ""
        if source is not None and source.material is not None:
            sp_path = _sp_path_for(base, source.name)
            if sp_path.casefold() not in {k.casefold() for k in new_files}:
                if on_log:
                    on_log(f"Encoding {source.material.name} -> {sp_path.rsplit('/', 1)[-1]} (BC1, G roughness, B metalness)")
                new_files[sp_path] = encode(source.material)
                encoded.append(sp_path)
            material = sp_path
            how = f"_sp from {source.material.name}"
        elif source is not None:
            # a source with factors and no map: a solid _sp says what the factors say
            sp_path = _sp_path_for(base, source.name)
            if sp_path.casefold() not in {k.casefold() for k in new_files}:
                if on_log:
                    on_log(f"Encoding a solid _sp for {source.name} (roughness {source.roughness_factor:g}, metalness {source.metallic_factor:g}) -> {sp_path.rsplit('/', 1)[-1]}")
                new_files[sp_path] = encode_factors(source.roughness_factor, source.metallic_factor)
                encoded.append(sp_path)
            material = sp_path
            how = f"_sp from the source's factors (roughness {source.roughness_factor:g}, metalness {source.metallic_factor:g})"
        elif owned.get("_detailMaskTexture"):
            material = owned["_detailMaskTexture"]
            how = "_sp from the Builder's material mask (its roughness clamped towards matte)"
            warnings.append(f"{wrapper.submesh_name}: no source metallic/roughness map is known, so the Builder's mask stands in as _sp; its roughness was clamped towards matte.")
        else:
            how = "no _sp (the shader's default roughness and metalness)"
        emissive = owned.get("_emissiveIntensityTexture", "")
        color = wrapper.value("_emissiveColor") or "#FFFFFFFF"
        try:
            intensity = float(wrapper.value("_emissiveIntensity") or 1.0)
        except ValueError:
            intensity = 1.0
        # by the source material the reader picked, or by the wrapper name a caller used
        wants_glow = wrapper.submesh_name.casefold() in glow_parts or (
            source is not None and str(source.name or "").casefold() in glow_parts
        )
        factor_glow = (
            source is not None and source.emissive is None
            and bool(source.emissive_color) and source.emissive_intensity > 0.0
        )
        if factor_glow and not wants_glow:
            # the model's own glow, stated as a factor rather than a map: a solid map is
            # what "this whole material glows" means, and the colour and strength are the
            # source's own
            emissive = emissive or _emi_path_for(base)
            key = emissive.replace("\\", "/").casefold()
            if key not in emissive_done:
                if on_log:
                    on_log(f"Encoding a solid glow map for {source.name} -> {emissive.rsplit('/', 1)[-1]} "
                           f"(BC4, {source.emissive_color} x{source.emissive_intensity:g} from the source's emissive factor)")
                new_files[emissive] = encode_glow()
                encoded.append(emissive)
                emissive_done[key] = (emissive, source.emissive_color)
            emissive = emissive_done[key][0]
            color, intensity = source.emissive_color, source.emissive_intensity
        elif wants_glow and (source is None or source.emissive is None):
            # the reader asked for this part: a solid map, their colour, their strength
            emissive = emissive or _emi_path_for(base)
            key = emissive.replace("\\", "/").casefold()
            if key not in emissive_done:
                if on_log:
                    on_log(f"Encoding a solid glow map for {wrapper.submesh_name} -> {emissive.rsplit('/', 1)[-1]} (BC4)")
                new_files[emissive] = encode_glow()
                encoded.append(emissive)
                emissive_done[key] = (emissive, glow_color)
            emissive = emissive_done[key][0]
            color, intensity = glow_color, glow_intensity
        elif emissive and (source is None or source.emissive is None):
            # The template's material glows and the import brought nothing to glow with.
            # The map the Builder generates for that slot is a flat mid-grey -- "glow at
            # half strength everywhere" -- and the template's own intensity is up at 10 on
            # a magic sword, so an imported blade came out lit like a torch, its albedo
            # washed out under the colour the template glowed in. A model that did not ask
            # to glow does not glow: dropping the binding takes the shader back to
            # SkinnedMeshStandard and the flat map out of the payload with it.
            warnings.append(
                f"{wrapper.submesh_name}: the template's material glows and your model brought no emissive map, "
                "so the glow is off. Choose the parts that glow on the Model step if you want it."
            )
            emissive, color, intensity = "", "#FFFFFFFF", 1.0
        elif emissive and source is not None and source.emissive is not None:
            key = emissive.replace("\\", "/").casefold()
            if key not in emissive_done:
                if on_log:
                    on_log(f"Encoding {source.emissive.name} -> {emissive.rsplit('/', 1)[-1]} (BC4 intensity, colour from the source)")
                data, color = encode_emissive(source.emissive)
                new_files[emissive] = data
                encoded.append(emissive)
                emissive_done[key] = (emissive, color)
            emissive, color = emissive_done[key]
            if wants_glow:
                # the source glows and the reader also said how: the map is the source's,
                # the colour and the strength are theirs
                color, intensity = glow_color, glow_intensity
        replacements[wrapper.submesh_name] = PlainMaterial(
            base=base, normal=normal, material=material,
            emissive_texture=emissive, emissive_color=color, emissive_intensity=intensity,
        )
        parts = ["base", "normal" if normal else "no normal", how]
        if emissive:
            parts.append(f"emissive {color} x{intensity:g}")
        lines.append(f"{wrapper.submesh_name}: {replacements[wrapper.submesh_name].shader}, " + ", ".join(parts))
    if not replacements:
        raise NewItemPlanError("the import owns no material wrapper with a base colour texture; nothing to route")
    try:
        result = rewrite_materials(text, replacements)
    except PacXmlMaterialError as exc:
        raise NewItemPlanError(f"plain-PBR route: {exc}") from exc
    new_text = (_BOM if bom else "") + result.text
    referenced = {path.replace("\\", "/").casefold() for w in find_material_wrappers(result.text) for path in w.textures.values()}
    side: Dict[str, bytes] = {xml_key: new_text.encode("utf-8")}
    dropped = []
    for key, data in files.side_files.items():
        if key == xml_key:
            continue
        if key.lower().endswith(".dds") and key.replace("\\", "/").casefold() not in referenced:
            dropped.append(key)
            continue
        side[key] = data
    side.update(new_files)
    if dropped:
        lines.append(f"{len(dropped)} Builder texture(s) no wrapper names any more dropped")
    return PlainPbrRoute(
        files=ModelFiles(
            pac_data=files.pac_data, side_files=side, material_route=MaterialRoute.PLAIN_PBR.value,
            notes=tuple(lines), warnings=tuple(warnings),
        ),
        rewritten=tuple(result.rewritten),
        lines=tuple(lines),
        warnings=tuple(warnings),
        encoded=tuple(encoded),
    )


def route_model_files(
    files: ModelFiles,
    route: MaterialRoute,
    *,
    result: object = None,
    scene: object = None,
    glow: object = None,
    on_log: Optional[Callable[[str], None]] = None,
) -> ModelFiles:
    """`files` written the way `route` says: the Builder's as they are, or the plain-PBR
    rewrite with the source textures found through `result` and `scene` when given, and
    the parts `glow` names lit in its colour."""

    if route is MaterialRoute.PLAIN_PBR:
        sources = source_materials_from_import(result, scene) if result is not None and scene is not None else {}
        return route_plain_pbr(files, sources=sources, glow=glow, on_log=on_log).files
    return ModelFiles(
        pac_data=files.pac_data, side_files=files.side_files, material_route=MaterialRoute.BUILDER.value,
        notes=("the Builder's material sidecar as it came (Material Authority)",), warnings=files.warnings,
    )


__all__ = [
    "PlainPbrRoute",
    "encode_emissive_solid",
    "SourceMaterialTextures",
    "encode_emissive_from_png",
    "encode_sp_from_factors",
    "encode_sp_from_png",
    "route_model_files",
    "route_plain_pbr",
    "source_materials_from_import",
]
