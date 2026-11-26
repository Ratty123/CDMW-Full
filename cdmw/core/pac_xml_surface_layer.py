"""Uniform roughness and metalness for imported materials on the traced shader families.

The shipped G-buffer pixel shaders of the Ver2 equipment families share one
surface path (``USE_COMMON_PIXEL_VER2``). Decoded from their DXIL:

* roughness is layer R's ``_detailMaterialMaskR`` green channel, metalness its
  blue channel, weighted by ``_dyeingGlobalOpacity`` byte 0 and switched on by
  ``_colorBlendingFlag`` bit 2 (DetailMaterialTextureMaskR). Layer R has no
  mask; layers G and B blend over it through ``_colorBlendingMaskTexture``.
* ``_materialTexture`` is not read by these shaders, and an unbound texture
  samples as zero, so a material without layers renders at roughness 0.
* layer UVs are rotated by at least 0.7 degrees, so only a uniform value lines
  up exactly; this writes a uniform texture.
* ``_detailDiffuseMaskR`` is sampled unconditionally by layer R before the
  ``_overlayColorTexture`` Photoshop Overlay pass. When dropped, it defaults to
  ``Texture/NoneTexture0x00000000.dds`` (black), crushing ``_overlayColorTexture``
  channels below 0.5 to black and ``>= 0.5`` to ``2*O - 1``. Binding the shipped
  2x2 uniform 0x80 grey ``texture/nonetexture0xff888888.dds`` passes
  ``_overlayColorTexture`` through uncrushed on exact mesh UVs (confirmed in
  game on replaced helmet ``cd_phm_00_hel_00_0415``).

Imported materials drop the target's layers, which leaves roughness 0 and
crushes ``_overlayColorTexture`` against black. Writing layer R's surface and
binding neutral grey ``_detailDiffuseMaskR`` restores both without changing
normals or adding UV-rotation artifacts.

The older SkinnedMeshStandard technique (Standard, Cloth, Emissive, Fur,
BlendHeight and StaticBlendHeight; most creatures use these) is different. Decoded from every G-buffer permutation of each:

* roughness is ``_materialTexture`` green and metalness its blue (the low byte of
  ``SV_Target0.y``, packed as in Ver2), with the colour-blend or height-blend
  layers mixed over it by ``_maskTexture``, ``_dyeingGlobalOpacity`` and, except
  for the BlendHeight pair, ``_colorBlendingFlag``.
* with the layers removed and their opacity at 0, as imported materials leave
  them, the surface is ``_materialTexture`` alone. The import writes none, and its
  declared default is ``NoneTexture0x00000000``, so roughness is again 0.

For these, a uniform ``_materialTexture`` sets the surface. Its red channel is
not read by the G-buffer shaders; it is written as 255, as every shipped ``_sp``
texture has it. SkinnedMeshAmplifiedGlare reads ``_materialTexture`` the same way,
but no shipped wrapper of it declares one, so the sliders skip it.

Wrappers outside SURFACE_SHADERS (eyes, hair, skin, the anisotropic coat,
AmplifiedGlare) are skipped, not refused; Mesh Editor gives them back the mean of
their own game surface texture instead (``bind_texture``).
"""
from __future__ import annotations

import struct

from cdmw.core.material_shader_controls import _write_parameter, edit_material_variants
from cdmw.core.pac_xml_standard_material import find_material_wrappers, wrapper_key

#: Shader families whose G-buffer shaders were traced to the layer-R surface path.
SURFACE_LAYER_SHADERS = frozenset({
    "SkinnedMeshStandard_Ver2",
    "SkinnedMeshCloth_Ver2",
    "SkinnedMeshEmissive_Ver2",
    "SkinnedMeshFur_Ver2",
    "SkinnedMeshTornCloth_Ver2",
    "SkinnedMeshAmplifiedGlare_Ver2",
    "SkinnedMeshSail_Ver2",
    "SkinnedMeshStaticStandard",
})

#: Shader families whose G-buffer shaders take the surface from _materialTexture once the layers are off.
MATERIAL_TEXTURE_SURFACE_SHADERS = frozenset({
    "SkinnedMeshStandard",
    "SkinnedMeshCloth",
    "SkinnedMeshEmissive",
    "SkinnedMeshFur",
    "SkinnedMeshBlendHeight",
    "SkinnedMeshStaticBlendHeight",
})
SURFACE_SHADERS = SURFACE_LAYER_SHADERS | MATERIAL_TEXTURE_SURFACE_SHADERS

#: Every shipped _detailDiffuseMaskR row (40,759 in Ver2 .pac_xml files) has ItemID 1028073018359806.
LAYER_DIFFUSE = ("_detailDiffuseMaskR", "Texture", "1028073018359806")
#: Shipped 2x2 uniform 0x80 grey: Overlay(O, 0.5) = O so _overlayColorTexture passes through uncrushed.
NEUTRAL_DIFFUSE_PATH = "texture/nonetexture0xff888888.dds"
LAYER_TEXTURE = ("_detailMaterialMaskR", "Texture", "3806852434362366")
#: Every shipped _materialTexture row of these shaders (39,349 in 13,338 .pac_xml files) has ItemID 6.
MATERIAL_TEXTURE = ("_materialTexture", "Texture", "6")
LAYER_FLAG = ("_colorBlendingFlag", "BitFlag32", "1263404788482046")
LAYER_OPACITY = ("_dyeingGlobalOpacity", "Byte4", "685773182468094")
#: DetailMaterialTextureMaskR in PartColorBlendingParameterSet.
LAYER_FLAG_BIT = 1 << 2


def surface_byte(value: float) -> int:
    return max(0, min(255, round(float(value) * 255)))


def surface_layer_dds(roughness: float, metallic: float) -> bytes:
    """A 4x4 B8G8R8A8 texture with its full mip chain: G roughness, B metalness."""
    return _uniform_dds(0, surface_byte(roughness), surface_byte(metallic))


def surface_material_dds(roughness: float, metallic: float) -> bytes:
    """The same as a _materialTexture, with red at 255 as in the game's own _sp textures."""
    return _uniform_dds(255, surface_byte(roughness), surface_byte(metallic))


def surface_rgb_dds(red: int, green: int, blue: int) -> bytes:
    """A uniform 4x4 B8G8R8A8 texture of the given bytes, for a game surface's own means."""
    return _uniform_dds(red, green, blue)


def bind_texture(text: str, material_names, parameter: str, path: str, item_id: str) -> tuple[str, int]:
    """Bind ``path`` as ``parameter`` (with the game row's ItemID) on every named wrapper."""
    names = {wrapper_key(name) for name in material_names}

    def edit(fragment):
        changed = 0
        for wrapper in reversed(find_material_wrappers(fragment)):
            if wrapper_key(wrapper.submesh_name) in names:
                block = _write_parameter(fragment[wrapper.start:wrapper.end], parameter, "Texture", path, item_id,
                                         static=False)
                fragment = fragment[:wrapper.start] + block + fragment[wrapper.end:]
                changed += 1
        return fragment, changed

    text, counts = edit_material_variants(text, edit)
    return text, sum(counts)


def _uniform_dds(red: int, green: int, blue: int) -> bytes:
    pixel = bytes((blue, green, red, 255))  # B, G, R, A
    header = bytearray(128)
    header[0:4] = b"DDS "
    # DDSD_CAPS | HEIGHT | WIDTH | PITCH | PIXELFORMAT | MIPMAPCOUNT
    struct.pack_into("<7I", header, 4, 124, 0x1 | 0x2 | 0x4 | 0x8 | 0x1000 | 0x20000, 4, 4, 16, 0, 3)
    # Pixel format: DDPF_RGB | DDPF_ALPHAPIXELS, 32 bit, BGRA masks.
    struct.pack_into("<2I4s5I", header, 76, 32, 0x40 | 0x1, b"\0\0\0\0", 32,
                     0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)
    # DDSCAPS_TEXTURE | DDSCAPS_MIPMAP | DDSCAPS_COMPLEX
    struct.pack_into("<I", header, 108, 0x1000 | 0x400000 | 0x8)
    return bytes(header) + pixel * (16 + 4 + 1)


def wrapper_shaders(text: str, material_names) -> dict[str, str]:
    """Shader of each named wrapper (folded name), across every model-property variant.

    One name can use a different shader in each variant (the last one wins
    here); use ``wrapper_shader_sets`` to see them all.
    """
    names = {wrapper_key(name) for name in material_names}
    return {wrapper_key(wrapper.submesh_name): wrapper.shader
            for wrapper in find_material_wrappers(text) if wrapper_key(wrapper.submesh_name) in names}


def wrapper_shader_sets(text: str, material_names) -> dict[str, frozenset[str]]:
    """Every shader each named wrapper (folded name) uses, across the model-property variants.

    A part can be ``SkinnedMeshStandard_Ver2`` in one variant and
    ``SkinnedMeshStandard`` in another, as ``cd_phm_00_ub_belt_0010_02`` is in
    ``cd_m0001_00_so_phm_ub_33005``; each reads its surface from a different texture.
    """
    names = {wrapper_key(name) for name in material_names}
    result: dict[str, set[str]] = {}
    for wrapper in find_material_wrappers(text):
        if wrapper_key(wrapper.submesh_name) in names:
            result.setdefault(wrapper_key(wrapper.submesh_name), set()).add(wrapper.shader)
    return {name: frozenset(shaders) for name, shaders in result.items()}


def material_texture_surface_needed(text: str, material_names) -> bool:
    """Whether any named wrapper takes its surface from _materialTexture."""
    return any(shaders & MATERIAL_TEXTURE_SURFACE_SHADERS for shaders in wrapper_shader_sets(text, material_names).values())


def layer_surface_needed(text: str, material_names) -> bool:
    """Whether any named wrapper takes its surface from layer R."""
    return any(shaders & SURFACE_LAYER_SHADERS for shaders in wrapper_shader_sets(text, material_names).values())


def _int_value(wrapper, name: str) -> int:
    for parameter in wrapper.parameters:
        if parameter.name == name:
            try:
                return int(parameter.value)
            except ValueError:
                return 0
    return 0


def apply_surface_layer(text: str, material_names, texture_path: str, material_texture_path: str = "") -> tuple[str, int]:
    """Bind the uniform surface on every named wrapper, by the path its shader reads.

    Ver2 wrappers get ``texture_path`` as layer R; Standard-technique wrappers get
    ``material_texture_path`` as their _materialTexture. Returns the edited text
    and the number of wrappers changed. Named wrappers on a shader outside
    SURFACE_SHADERS (an eye, hair) keep their own surface; only when none of
    the named wrappers can take it is the surface refused.
    """
    shaders = wrapper_shader_sets(text, material_names)
    names = {name for name, found in shaders.items() if found & SURFACE_SHADERS}
    if shaders and not names:
        raise ValueError("Roughness and Metallic are not available for this item's material shader.")
    if ((not material_texture_path and material_texture_surface_needed(text, names))
            or (not texture_path and layer_surface_needed(text, names))):
        raise ValueError("Roughness and Metallic found no material texture to write.")
    text, counts = edit_material_variants(
        text, lambda fragment: apply_surface_fragment(fragment, names, texture_path, material_texture_path))
    return text, sum(counts)


def apply_surface_fragment(fragment: str, material_names, texture_path: str, material_texture_path: str) -> tuple[str, int]:
    """``apply_surface_layer`` on one variant's wrappers, each by its own shader.

    Wrappers outside SURFACE_SHADERS are left alone even when their name is
    given. A wrapper whose path is empty is refused rather than bound to
    nothing, which the game reads as roughness 0.
    """
    names = {wrapper_key(name) for name in material_names}
    changed = 0
    for wrapper in reversed(find_material_wrappers(fragment)):
        if wrapper_key(wrapper.submesh_name) not in names or wrapper.shader not in SURFACE_SHADERS:
            continue
        block = fragment[wrapper.start:wrapper.end]
        material = wrapper.shader in MATERIAL_TEXTURE_SURFACE_SHADERS
        if not (material_texture_path if material else texture_path):
            raise ValueError("Roughness and Metallic found no material texture to write.")
        if material:
            name, kind, item_id = MATERIAL_TEXTURE
            block = _write_parameter(block, name, kind, material_texture_path, item_id, static=False)
            fragment = fragment[:wrapper.start] + block + fragment[wrapper.end:]
            changed += 1
            continue
        flag = _int_value(wrapper, LAYER_FLAG[0]) | LAYER_FLAG_BIT
        opacity = (_int_value(wrapper, LAYER_OPACITY[0]) & ~0xFF) | 0xFF
        writes = [(LAYER_TEXTURE, texture_path), (LAYER_FLAG, str(flag)), (LAYER_OPACITY, str(opacity))]
        if not wrapper.textures.get(LAYER_DIFFUSE[0]):
            writes.append((LAYER_DIFFUSE, NEUTRAL_DIFFUSE_PATH))
        for (name, kind, item_id), value in writes:
            block = _write_parameter(block, name, kind, value, item_id, static=False)
        fragment = fragment[:wrapper.start] + block + fragment[wrapper.end:]
        changed += 1
    return fragment, changed
