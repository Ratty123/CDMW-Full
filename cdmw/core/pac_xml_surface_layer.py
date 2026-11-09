"""Uniform roughness and metalness for imported materials on Ver2 equipment shaders.

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

Imported materials drop the target's layers, which leaves roughness 0. Writing
layer R alone restores a chosen surface without changing colour or normals.
"""
from __future__ import annotations

import struct

from cdmw.core.material_shader_controls import _write_parameter, edit_material_variants
from cdmw.core.pac_xml_standard_material import find_material_wrappers

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

LAYER_TEXTURE = ("_detailMaterialMaskR", "Texture", "3806852434362366")
LAYER_FLAG = ("_colorBlendingFlag", "BitFlag32", "1263404788482046")
LAYER_OPACITY = ("_dyeingGlobalOpacity", "Byte4", "685773182468094")
#: DetailMaterialTextureMaskR in PartColorBlendingParameterSet.
LAYER_FLAG_BIT = 1 << 2


def surface_byte(value: float) -> int:
    return max(0, min(255, round(float(value) * 255)))


def surface_layer_dds(roughness: float, metallic: float) -> bytes:
    """A 4x4 B8G8R8A8 texture with its full mip chain: G roughness, B metalness."""
    pixel = bytes((surface_byte(metallic), surface_byte(roughness), 0, 255))  # B, G, R, A
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
    """Shader of each named wrapper (folded name), across every model-property variant."""
    names = {str(name).casefold() for name in material_names}
    return {wrapper.submesh_name.casefold(): wrapper.shader
            for wrapper in find_material_wrappers(text) if wrapper.submesh_name.casefold() in names}


def unsupported_surface_shaders(text: str, material_names) -> tuple[str, ...]:
    return tuple(sorted({shader for shader in wrapper_shaders(text, material_names).values()
                         if shader not in SURFACE_LAYER_SHADERS}))


def _int_value(wrapper, name: str) -> int:
    for parameter in wrapper.parameters:
        if parameter.name == name:
            try:
                return int(parameter.value)
            except ValueError:
                return 0
    return 0


def apply_surface_layer(text: str, material_names, texture_path: str) -> tuple[str, int]:
    """Bind the uniform surface texture as layer R on every named wrapper.

    Returns the edited text and the number of wrappers changed. A named wrapper
    on a shader outside SURFACE_LAYER_SHADERS is refused rather than skipped.
    """
    names = {str(name).casefold() for name in material_names}
    unsupported = unsupported_surface_shaders(text, names)
    if unsupported:
        raise ValueError("Roughness and Metallic need a Ver2 equipment material, which this item does not use.")

    def edit(fragment):
        changed = 0
        for wrapper in reversed(find_material_wrappers(fragment)):
            if wrapper.submesh_name.casefold() not in names:
                continue
            block = fragment[wrapper.start:wrapper.end]
            flag = _int_value(wrapper, LAYER_FLAG[0]) | LAYER_FLAG_BIT
            opacity = (_int_value(wrapper, LAYER_OPACITY[0]) & ~0xFF) | 0xFF
            for (name, kind, item_id), value in ((LAYER_TEXTURE, texture_path), (LAYER_FLAG, str(flag)),
                                                 (LAYER_OPACITY, str(opacity))):
                block = _write_parameter(block, name, kind, value, item_id, static=False)
            fragment = fragment[:wrapper.start] + block + fragment[wrapper.end:]
            changed += 1
        return fragment, changed

    text, counts = edit_material_variants(text, edit)
    return text, sum(counts)
