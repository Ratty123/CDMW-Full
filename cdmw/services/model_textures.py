"""A model's textures for the Mesh Editor's Textures panel: the list, its grouping, whether
a texture is shared, and Make unique (decision 48, P6).

Pure Python over the material graph's slot rows (`PreviewMaterialTextureInput`, as the
preview model and `build_pac_material_graph_v1` give them) and the model's sidecar text.
Nothing here reads the game or writes a file; the Mesh Editor tab supplies the rows and
puts the results into the mod (see cdmw/resources/mesh_editor_texture_contract.json).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Container, Iterable, Optional, Sequence, Tuple

from cdmw.domain.textures.semantics import is_stock_or_shared_texture_path

#: The panel's groups, in the order they are shown. Labels are the UI's (localized there).
TEXTURE_GROUPS: Tuple[str, ...] = ("colour", "normal", "material_response", "masks", "detail", "emissive", "other")

_GROUP_BY_SLOT = {
    "base": "colour", "diffuse": "colour", "albedo": "colour", "color": "colour", "base_color": "colour",
    "normal": "normal",
    "material": "material_response", "glossiness": "material_response", "metallic": "material_response",
    "metal": "material_response", "metalness": "material_response", "roughness": "material_response",
    "specular": "material_response",
    "material_mask": "masks", "mask": "masks", "opacity_mask": "masks", "ao": "masks", "occlusion": "masks",
    "height": "masks",
    "detail_mask": "detail", "detail": "detail", "layer": "detail",
    "emissive": "emissive",
}
_DETAIL_PREFIXES = ("cd_texturelayer_",)


def _norm(path: str) -> str:
    return str(path or "").replace("\\", "/").strip().casefold()


def texture_group(slot) -> str:
    """Which group a slot row belongs to.

    The sidecar's own slot kind decides first (it is authoritative: the material
    graph reads it from the model's sidecar). A row from a graph layer other than the
    base layer is a detail or layer texture. The semantic type and the parameter name
    are fallbacks for rows with no slot kind, and anything left is "other".
    """
    slot_kind = str(getattr(slot, "slot_kind", "") or "").strip().lower()
    layer_role = str(getattr(slot, "layer_role", "") or "").strip().lower()
    path = _norm(getattr(slot, "source_texture_path", "") or getattr(slot, "texture_name", ""))
    if layer_role and layer_role not in {"base", "material_response"} and slot_kind not in {"normal", "emissive"}:
        return "detail"
    if PurePosixPath(path).name.startswith(_DETAIL_PREFIXES):
        return "detail"
    if slot_kind in _GROUP_BY_SLOT:
        return _GROUP_BY_SLOT[slot_kind]
    semantic = str(getattr(slot, "semantic_type", "") or "").strip().lower()
    if semantic in _GROUP_BY_SLOT:
        return _GROUP_BY_SLOT[semantic]
    parameter = str(getattr(slot, "parameter_name", "") or "").strip().lower()
    for needle, group in (("normal", "normal"), ("emissive", "emissive"), ("detail", "detail"), ("mask", "masks"),
                          ("diffuse", "colour"), ("basecolor", "colour"), ("color", "colour"), ("material", "material_response")):
        if needle in parameter:
            return group
    return "other"


@dataclass(frozen=True, slots=True)
class ModelTexture:
    path: str
    group: str
    slot_kinds: Tuple[str, ...]
    parameters: Tuple[str, ...]
    materials: Tuple[str, ...]
    #: Parts (wrapper sub-mesh names) whose materials read this texture.
    parts: Tuple[str, ...]
    #: True when the name marks a stock texture many materials share (`is_stock_or_shared_texture_path`).
    shared_name: bool


@dataclass(frozen=True, slots=True)
class ModelTextureGroup:
    key: str
    textures: Tuple[ModelTexture, ...]


def model_texture_list(slots: Iterable[object]) -> Tuple[ModelTextureGroup, ...]:
    """One row per texture file, grouped in panel order; empty groups are left out.

    A texture read by several slots or parts is listed once, in the group of its first
    slot, with every part and material that reads it.
    """
    order: list[str] = []
    rows: dict[str, dict] = {}
    for slot in slots:
        path = str(getattr(slot, "source_texture_path", "") or "").replace("\\", "/").strip()
        if not path:
            continue
        key = _norm(path)
        row = rows.get(key)
        if row is None:
            row = rows[key] = {"path": path, "group": texture_group(slot), "slot_kinds": [], "parameters": [],
                               "materials": [], "parts": []}
            order.append(key)
        for field, value in (("slot_kinds", getattr(slot, "slot_kind", "")), ("parameters", getattr(slot, "parameter_name", "")),
                             ("materials", getattr(slot, "material_name", "")), ("parts", getattr(slot, "part_name", ""))):
            value = str(value or "").strip()
            if value and value not in row[field]:
                row[field].append(value)
    textures = [ModelTexture(path=row["path"], group=row["group"], slot_kinds=tuple(row["slot_kinds"]),
                             parameters=tuple(row["parameters"]), materials=tuple(row["materials"]),
                             parts=tuple(row["parts"]), shared_name=is_stock_or_shared_texture_path(row["path"]))
                for row in (rows[key] for key in order)]
    return tuple(ModelTextureGroup(group, tuple(t for t in textures if t.group == group))
                 for group in TEXTURE_GROUPS if any(t.group == group for t in textures))


@dataclass(frozen=True, slots=True)
class TextureSharing:
    path: str
    #: Parts of this model, outside the ones being edited, whose materials read it.
    other_parts: Tuple[str, ...]
    shared_name: bool
    #: Other game files that reference it, from the on-request archive scan; None = not checked.
    other_files: Optional[Tuple[str, ...]]
    #: Editing it in place would change something else, so the edit needs Make unique.
    needs_unique: bool
    #: Why, as the sentence to show; "" when the texture is this model's own.
    reason: str


def texture_sharing(
    texture: ModelTexture,
    editing_parts: Iterable[str],
    *,
    other_files: Optional[Sequence[str]] = None,
    own_files: Iterable[str] = (),
) -> TextureSharing:
    """Decide whether editing `texture` for `editing_parts` would change anything else.

    Three tiers, each where it is cheap (decision 48): the model's own materials (exact),
    the stock-texture name rule, and the whole-archive scan, which runs only when asked and
    arrives here as `other_files` (the model's own files in `own_files` are ignored).
    """
    editing = {_norm(part) for part in editing_parts}
    other_parts = tuple(part for part in texture.parts if _norm(part) not in editing)
    own = {_norm(path) for path in own_files}
    others = None if other_files is None else tuple(path for path in other_files if _norm(path) not in own)
    if other_parts:
        reason = "Other parts of this model use this texture: " + ", ".join(other_parts) + "."
    elif texture.shared_name:
        reason = "This is a stock texture that many game materials share."
    elif others:
        shown = ", ".join(others[:3]) + (f" and {len(others) - 3} more" if len(others) > 3 else "")
        reason = f"Other game files use this texture: {shown}."
    else:
        reason = ""
    return TextureSharing(path=texture.path, other_parts=other_parts, shared_name=texture.shared_name,
                          other_files=others, needs_unique=bool(reason), reason=reason)


@dataclass(frozen=True, slots=True)
class MadeUnique:
    source_path: str
    new_path: str
    sidecar_path: str
    sidecar_data: bytes
    #: The parts whose wrappers now read `new_path`; every other wrapper still reads the source.
    parts: Tuple[str, ...]


_TEXTURE_ATTR_RE = re.compile(r'(?P<lead><ResourceReferencePath_ITexture\b[^>]*?\b_path=)(?P<q>["\'])(?P<path>[^"\']*)(?P=q)')


def unique_texture_path(source_path: str, stem: str) -> str:
    """The copy's path: beside the source, named for the model, keeping the role suffix
    (`_n`, `_sp`, ...) the texture registry and DMM read the kind from."""
    from cdmw.services.new_item_resource_copies import private_texture_path

    return private_texture_path(str(stem), _norm(source_path))


def make_texture_unique(
    source_path: str,
    *,
    sidecar_path: str,
    sidecar_data: bytes,
    parts: Iterable[str],
    stem: str,
    existing_paths: Container[str] = (),
) -> MadeUnique:
    """Point the edited parts' materials at a new copy of `source_path`.

    The copy is a new file in the mod (`unique_texture_path`); the shared original is
    never overwritten. Only the material wrappers of `parts` are rewritten, and only
    their exact references to the source; every other byte of the sidecar stays as it
    was. Refuses when the new path already exists in the game or the mod, or when none
    of the parts' materials reads the source.
    """
    from cdmw.core.pac_xml_standard_material import find_material_wrappers

    new_path = unique_texture_path(source_path, stem)
    if new_path in existing_paths or _norm(new_path) in existing_paths:
        raise ValueError(f"{new_path} already exists, so a unique copy cannot take that name.")
    try:
        text = bytes(sidecar_data).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("The model's material file is not readable text.") from exc
    wanted = {_norm(part) for part in parts}
    if not wanted:
        raise ValueError("Make unique needs at least one part.")
    source = _norm(source_path)
    pieces, previous, rewritten = [], 0, []
    for wrapper in find_material_wrappers(text):
        if _norm(wrapper.submesh_name) not in wanted:
            continue
        body = text[wrapper.start:wrapper.end]
        changed = False

        def swap(match: re.Match) -> str:
            nonlocal changed
            if _norm(match.group("path")) != source:
                return match.group(0)
            changed = True
            return f'{match.group("lead")}{match.group("q")}{new_path}{match.group("q")}'

        new_body = _TEXTURE_ATTR_RE.sub(swap, body)
        if changed:
            pieces.extend((text[previous:wrapper.start], new_body))
            previous = wrapper.end
            rewritten.append(wrapper.submesh_name)
    if not rewritten:
        raise ValueError(f"None of the chosen parts' materials uses {source_path}.")
    pieces.append(text[previous:])
    return MadeUnique(source_path=source_path, new_path=new_path, sidecar_path=sidecar_path,
                      sidecar_data="".join(pieces).encode("utf-8"), parts=tuple(rewritten))


__all__ = [
    "MadeUnique",
    "ModelTexture",
    "ModelTextureGroup",
    "TEXTURE_GROUPS",
    "TextureSharing",
    "make_texture_unique",
    "model_texture_list",
    "texture_group",
    "texture_sharing",
    "unique_texture_path",
]
