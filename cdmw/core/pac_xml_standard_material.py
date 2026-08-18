"""Rewrite material wrappers of a `.pac_xml` into the game's plain-PBR shader shape.

An imported glTF model brings PBR textures: an albedo, a normal map, a metallic/
roughness map, sometimes an emissive. The Builder's Full Import keeps the template's
layered `SkinnedMeshStandard_Ver2` material and smuggles those textures into it
(albedo through an overlay slot, roughness clamped to matte); the game then draws
its own detail layers over them. The shipped shader for texture-driven surfaces is
`SkinnedMeshStandard`: on 12,966 shipped `.pac_xml` files it carries

    _baseColorTexture   the albedo                (DXT1, or DXT5 with alpha)
    _normalTexture      the normal map            (BC5U)
    _materialTexture    the `_sp` map: G roughness, B metalness   (DXT1)
    _heightTexture, _maskTexture, _renderSettingFlag  (optional)

and nothing of the layer machinery (274 one-hand and 116 two-hand weapon materials
ship this way). `SkinnedMeshEmissive` is the same set plus `_emissiveIntensityTexture`,
`_emissiveColor` and `_emissiveIntensity` (140 shipped materials).

The `ItemID` of a well-known parameter is a small number counting down to the last
well-known one; shipped files disagree on the exact numbers for the same set (base
2 on 984 files, 7 on 158), so they cannot matter to the game and the most common
pattern is used. Everything else about a wrapper (its own attributes, its place in
the file, the file's newline convention and indentation) is kept.

This module is text in, text out; it reads no archives and knows no textures beyond
their paths. The `.pac` binary names no shader and no texture (checked on the
shipped swords), so the material a submesh draws with is this file's alone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Tuple

STANDARD_SHADER = "SkinnedMeshStandard"
EMISSIVE_SHADER = "SkinnedMeshEmissive"
LAYERED_SHADER = "SkinnedMeshStandard_Ver2"

#: `_emissiveIntensityTexture`, `_emissiveColor`, `_emissiveIntensity` on every shipped
#: emissive material (`_emissiveIntensity` also ships as 2620614880788478 on some).
_EMISSIVE_TEXTURE_ID = "1638159983050750"
_EMISSIVE_COLOR_ID = "2065176433000446"
_EMISSIVE_INTENSITY_ID = "3419583792807934"

_WRAPPER_RE = re.compile(
    r'<SkinnedMeshMaterialWrapper\b(?P<attrs>[^>]*)>(?P<body>.*?)</SkinnedMeshMaterialWrapper>',
    re.S,
)
_MATERIAL_RE = re.compile(
    r'(?P<indent>[ \t]*)<Material Name="_resourceMaterial" _materialName="(?P<shader>[^"]*)">(?P<body>.*?)</Material>',
    re.S,
)
_PARAM_RE = re.compile(
    r'<MaterialParameter(?P<kind>\w+) StringItemID="(?P<name>[^"]+)" ItemID="(?P<item_id>\d+)" _name="[^"]*"'
    r'(?: _value="(?P<value>[^"]*)")? Index="(?P<index>\d+)"\s*(?:/>|>(?P<inner>.*?)</MaterialParameter\w+>)',
    re.S,
)
_TEXTURE_PATH_RE = re.compile(r'<ResourceReferencePath_ITexture Name="_value" _path="(?P<path>[^"]*)"')
_SUBMESH_RE = re.compile(r'_subMeshName="(?P<name>[^"]*)"')


class PacXmlMaterialError(ValueError):
    """The text is not a `.pac_xml` this module can rewrite."""


@dataclass(frozen=True, slots=True)
class MaterialParameter:
    kind: str
    name: str
    item_id: str
    value: str
    index: int
    texture_path: str = ""


@dataclass(frozen=True, slots=True)
class MaterialWrapper:
    """One `<SkinnedMeshMaterialWrapper>` and the `<Material>` it draws with."""

    submesh_name: str
    shader: str
    parameters: Tuple[MaterialParameter, ...]
    #: character offsets of the `<Material ...>...</Material>` block in the text, the
    #: block's own indentation included
    start: int
    end: int
    indent: str

    @property
    def textures(self) -> Dict[str, str]:
        """parameter name -> texture path, for the texture parameters."""

        return {p.name: p.texture_path for p in self.parameters if p.kind == "Texture" and p.texture_path}

    def value(self, name: str) -> Optional[str]:
        for parameter in self.parameters:
            if parameter.name == name:
                return parameter.value
        return None


@dataclass(frozen=True, slots=True)
class PlainMaterial:
    """What a rewritten wrapper draws with. Paths are game-relative texture paths."""

    base: str
    normal: str = ""
    #: the `_sp` map (G roughness, B metalness)
    material: str = ""
    emissive_texture: str = ""
    #: `#RRGGBBAA` as the file writes colours; used only with an emissive texture
    emissive_color: str = "#FFFFFFFF"
    emissive_intensity: float = 1.0
    #: `_renderSettingFlag`; None leaves it out (as most shipped weapon materials do)
    render_flag: Optional[int] = None

    @property
    def shader(self) -> str:
        return EMISSIVE_SHADER if self.emissive_texture else STANDARD_SHADER


@dataclass(frozen=True, slots=True)
class RewriteResult:
    text: str
    rewritten: Tuple[str, ...]
    #: submesh names the caller named that the file has no wrapper for
    missing: Tuple[str, ...] = ()
    notes: Tuple[str, ...] = field(default_factory=tuple)


def find_material_wrappers(text: str) -> Tuple[MaterialWrapper, ...]:
    """Every material wrapper in the file, in file order."""

    out = []
    for wrapper in _WRAPPER_RE.finditer(text):
        submesh = _SUBMESH_RE.search(wrapper.group("attrs"))
        body_start = wrapper.start("body")
        material = _MATERIAL_RE.search(wrapper.group("body"))
        if material is None:
            continue
        parameters = []
        for param in _PARAM_RE.finditer(material.group("body")):
            inner = param.group("inner") or ""
            texture = _TEXTURE_PATH_RE.search(inner)
            parameters.append(MaterialParameter(
                kind=param.group("kind"),
                name=param.group("name"),
                item_id=param.group("item_id"),
                value=param.group("value") or "",
                index=int(param.group("index")),
                texture_path=texture.group("path") if texture else "",
            ))
        out.append(MaterialWrapper(
            submesh_name=submesh.group("name") if submesh else "",
            shader=material.group("shader"),
            parameters=tuple(parameters),
            start=body_start + material.start(),
            end=body_start + material.end(),
            indent=material.group("indent"),
        ))
    return tuple(out)


def _newline_of(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def plain_material_xml(material: PlainMaterial, *, indent: str = "", newline: str = "\n") -> str:
    """The `<Material>` block for `material`, indented like the block it replaces.

    Well-known parameters take the countdown `ItemID`s the most common shipped pattern
    uses (base first); the emissive ones the hashed ids every shipped emissive
    material carries. Indices run in file order.
    """

    if not material.base:
        raise PacXmlMaterialError("a plain material needs a base colour texture")
    known = [("_baseColorTexture", material.base)]
    if material.normal:
        known.append(("_normalTexture", material.normal))
    if material.material:
        known.append(("_materialTexture", material.material))
    lines = []
    tab = "\t"
    inner = indent + tab
    lines.append(f'{indent}<Material Name="_resourceMaterial" _materialName="{material.shader}">')
    lines.append(f'{inner}<Vector Name="_permutations"/>')
    lines.append(f'{inner}<Vector Name="_parameters">')
    p_indent = inner + tab
    t_indent = p_indent + tab
    index = 0
    # the countdown leaves 0 for the render flag when there is one, as the shipped files do
    count = len(known) + (1 if material.render_flag is not None else 0)
    for position, (name, path) in enumerate(known):
        item_id = count - 1 - position
        lines.append(f'{p_indent}<MaterialParameterTexture StringItemID="{name}" ItemID="{item_id}" _name="{name}" Index="{index}">')
        lines.append(f'{t_indent}<ResourceReferencePath_ITexture Name="_value" _path="{path}"/>')
        lines.append(f'{p_indent}</MaterialParameterTexture>')
        index += 1
    if material.render_flag is not None:
        lines.append(
            f'{p_indent}<MaterialParameterBitFlag32 StringItemID="_renderSettingFlag" ItemID="0" _name="_renderSettingFlag" '
            f'_value="{int(material.render_flag)}" Index="{index}"/>'
        )
        index += 1
    if material.emissive_texture:
        lines.append(
            f'{p_indent}<MaterialParameterTexture StringItemID="_emissiveIntensityTexture" ItemID="{_EMISSIVE_TEXTURE_ID}" '
            f'_name="_emissiveIntensityTexture" Index="{index}">'
        )
        lines.append(f'{t_indent}<ResourceReferencePath_ITexture Name="_value" _path="{material.emissive_texture}"/>')
        lines.append(f'{p_indent}</MaterialParameterTexture>')
        index += 1
        lines.append(
            f'{p_indent}<MaterialParameterColor StringItemID="_emissiveColor" ItemID="{_EMISSIVE_COLOR_ID}" '
            f'_name="_emissiveColor" _value="{material.emissive_color}" Index="{index}"/>'
        )
        index += 1
        lines.append(
            f'{p_indent}<MaterialParameterFloat StringItemID="_emissiveIntensity" ItemID="{_EMISSIVE_INTENSITY_ID}" '
            f'_name="_emissiveIntensity" _value="{float(material.emissive_intensity):.6f}" Index="{index}"/>'
        )
        index += 1
    lines.append(f'{inner}</Vector>')
    lines.append(f'{indent}</Material>')
    return newline.join(lines)


def rewrite_materials(text: str, replacements: Mapping[str, PlainMaterial]) -> RewriteResult:
    """Replace the `<Material>` of each named wrapper (by `_subMeshName`, case-insensitive)
    with the plain material given for it. Wrappers not named are left byte for byte."""

    wrappers = find_material_wrappers(text)
    if not wrappers:
        raise PacXmlMaterialError("no material wrappers were found in the sidecar")
    wanted = {name.casefold(): material for name, material in replacements.items()}
    newline = _newline_of(text)
    pieces = []
    cursor = 0
    rewritten = []
    for wrapper in wrappers:
        material = wanted.get(wrapper.submesh_name.casefold())
        if material is None:
            continue
        pieces.append(text[cursor:wrapper.start])
        pieces.append(plain_material_xml(material, indent=wrapper.indent, newline=newline))
        cursor = wrapper.end
        rewritten.append(wrapper.submesh_name)
    pieces.append(text[cursor:])
    seen = {name.casefold() for name in rewritten}
    missing = tuple(name for name in replacements if name.casefold() not in seen)
    return RewriteResult(text="".join(pieces), rewritten=tuple(rewritten), missing=missing)


__all__ = [
    "EMISSIVE_SHADER",
    "LAYERED_SHADER",
    "STANDARD_SHADER",
    "MaterialParameter",
    "MaterialWrapper",
    "PacXmlMaterialError",
    "PlainMaterial",
    "RewriteResult",
    "find_material_wrappers",
    "plain_material_xml",
    "rewrite_materials",
]
