"""Experimental controls recovered from material definitions and compiled shaders.

These are material-family contracts, not a list of interchangeable shader names.
Wing, translucent glass, the layered transparency families and New Item's EyeCover
accept compatible plain materials.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from cdmw.domain.textures.transparency_mask import TransparencyMask


@dataclass(frozen=True, slots=True)
class ShaderField:
    name: str
    label: str
    default: tuple[float, ...]
    minimum: float
    maximum: float
    kind: str = "Float"
    item_id: str = "0"

    @property
    def integer(self):
        return self.kind in {"Int", "Byte4", "BitFlag32", "ExportToggle"} or self.name in {"_wingFlowInverse", "_dissolvePositionType"}


@dataclass(frozen=True, slots=True)
class ShaderFamily:
    shader: str
    label: str
    note: str
    fields: tuple[ShaderField, ...]
    mask: str = ""
    default_mask: str = ""
    # Controls that are not one parameter row each and take no preview lane of
    # their own (see VEIL_LAYER_EXTRAS).
    extras: tuple[ShaderField, ...] = ()


# The detail layer's UV transform of a veil with Ver2 detail layers. The game
# packs it into two Byte4 rows shared by the three mask channels
# (_dyeingTransformProperty0/1/3: scale X, scale Y, offset X, offset Y bytes;
# _dyeingPropertyBlend: one rotation byte per channel), so these controls edit
# the bytes of the channel in use instead of owning a row each.
VEIL_REPEAT, VEIL_OFFSET, VEIL_ROTATION = "veilDetailRepeat", "veilDetailOffset", "veilDetailRotation"
VEIL_LAYER_EXTRAS = (
    ShaderField("veilDetailRepeat", "Lace repeat X / Y", (1., 1.), 1, 64),
    ShaderField("veilDetailOffset", "Lace offset X / Y", (0., 0.), 0, 1),
    ShaderField("veilDetailRotation", "Lace rotation (degrees)", (0.,), -180, 180),
)


def veil_transform_bytes(repeat=None, offset=None, rotation=None):
    """The bytes the game stores for a lace repeat, offset and rotation: the
    scale byte is 255 / repeat, the offset byte offset x 255 and the rotation
    byte (degrees + 180) / 360 x 255. None where a control was not edited."""
    byte = lambda number: min(max(int(round(number)), 0), 255)
    scale = tuple(max(byte(255.0 / value), 1) for value in repeat) if repeat is not None else None
    return (scale, tuple(byte(value * 255.0) for value in offset) if offset is not None else None,
            byte((rotation[0] + 180.0) / 360.0 * 255.0) if rotation is not None else None)


FAMILIES = (
    ShaderFamily("SkinnedMeshWing", "Patterned reveal", "Binary cutout, not glass. Higher progress reveals more of the surface. Uses the source mask, or the game's wing mask. Changing a Plain PBR shader is experimental.", (
        ShaderField("_wingFlowProgress", "Reveal progress", (-.1,), -1, 2),
        ShaderField("_wingFlowInverse", "Invert progress mask", (0.,), 0, 1),
    ), "_wingFlowTex1", "effect/texture/cdfx_wing_flowmap.dds"),
    ShaderFamily("SkinnedMeshTornCloth_Ver2", "Torn cloth", "Requires a TornCloth material and vertex colour R/G. White R/G disables the tears. Without decoded vertex colours the viewport leaves the shape unchanged.", (
        ShaderField("_tornCrossGrainPower", "Cross-grain tear", (0.,), 0, 1, item_id="1345291851661310"),
        ShaderField("_tornLengthGrainUVScale", "Length-grain scale", (1.,), .001, 1, item_id="2139607801004030"),
        ShaderField("_tornCrossGrainUVScale", "Cross-grain scale", (1.,), .001, 1, item_id="958757867618302"),
    ), "_tornPatternTexture", "character/texture/cd_texturelayer_endpattern_0001_tp.dds"),
    ShaderFamily("SkinnedMeshHairAnimatedUV", "Moving hair textures", "Requires HairAnimatedUV and decoded vertex green below white. Speed uses the raw shader time scale; preview timing and game shadows may differ. Zero amplitude stops motion.", (
        ShaderField("_frequencyU", "Spatial frequency U", (1.,), 1, 100, item_id="3539483756593150"),
        ShaderField("_frequencyV", "Spatial frequency V", (1.,), 1, 100),
        ShaderField("_speedU", "Speed U", (2.5,), 0, 100, item_id="2834014474862590"),
        ShaderField("_speedV", "Speed V", (3.5,), 0, 100, item_id="3525903971778558"),
        ShaderField("_curveHeightU", "Amplitude U", (.025,), 0, 100, item_id="2748424398045182"),
        ShaderField("_curveHeightV", "Amplitude V", (.025,), 0, 100, item_id="4065297996709886"),
    )),
    ShaderFamily("SkinnedMeshAnisotropy", "Surface detail and roughness", "Detail strength changes normals, not transparency. The roughness byte only acts when the source hair dye has nonzero alpha; editing it never enables or changes dye colour.", (
        ShaderField("_hairAnisotropyDetailOpacity", "Normal detail strength", (0.,), 0, 1, item_id="741201860886526"),
        ShaderField("_hairAnisotropyDetailScale", "Normal detail scale", (.5,), .0001, 1, item_id="984403626950654"),
        ShaderField("_hairDyeingProperty", "Dye roughness byte", (128.,), 0, 255, "Byte4", "2762362249543678"),
    ), "_hairAnisotropyDetailMaskTexture"),
    ShaderFamily("SkinnedMeshPoster", "Glowing band sweep", "Requires a Poster material. Progress drives a colour/glow sweep, not disappearance. Between 0.001 and 1 the sweep ignores glow ratio. The viewport approximates the band and lighting; game activation remains experimental.", (
        ShaderField("_posterGlowNoiseIntensity", "Noise strength", (.1,), 0, 1, item_id="3846762150232062"),
        ShaderField("_posterGlowThickness", "Band width", (.4,), 0, 1, item_id="3028446454218750"),
        ShaderField("_posterGlowExponent", "Band exponent", (5.,), 0, 50, item_id="1032243921289214"),
        ShaderField("_posterGlowRatio", "Glow ratio", (0.,), 0, 1),
        ShaderField("_posterGlowProgress", "Sweep progress", (0.,), 0, 1),
        ShaderField("_posterGlowColor", "Glow colour RGB", (33/255, 99/255, 240/255), 0, 1, "Color"),
    ), "_posterGlowNoiseTex", "effect/texture/uvnoise_1_n.dds"),
    ShaderFamily("Dissolve", "Object dissolve", "Static Dissolve materials only. Centre: 0 player, 1 object pivot, 2 world. Larger ratio removes more unless inverted. The viewport approximates noise and edge lighting; player-relative mode stays visible because no game player position is available.", (
        ShaderField("_dissolveRatio", "Dissolve ratio", (0.,), 0, 1),
        ShaderField("_dissolveRadius", "Radius", (6.,), 0, 500),
        ShaderField("_dissolveHardness", "Hardness", (2.,), .001, 20),
        ShaderField("_dissolvePositionType", "Centre mode (0/1/2)", (0.,), 0, 2),
        ShaderField("_dissolvePosition", "World centre XYZ", (0., 0., 0.), -500, 500, "Float3"),
        ShaderField("_dissolveNoiseScale", "Noise scale", (5.,), .001, 10),
        ShaderField("_dissolveNoiseSpeed", "Noise speed UV", (0., .5), -10, 10, "Float2"),
        ShaderField("_dissolveNoiseIntensity", "Noise strength", (2.,), 0, 10),
        ShaderField("_dissolveEmissiveColor", "Edge colour RGB", (162/255, 1., 109/255), 0, 1, "Color"),
        ShaderField("_dissolveEmissiveIntensity", "Edge glow", (.05,), 0, 1),
        ShaderField("_dissolveEmissiveWidth", "Edge width", (1.2,), 0, 20),
        ShaderField("_materialFlags", "Invert sphere mask", (0.,), 0, 1, "BitFlag32"),
    ), "_dissolveNoiseTex", "effect/texture/pafx_aura_noise_001a_hsu_bc7.dds"),
)

# Keep the native renderer's existing family IDs unchanged.
# These texture channels are authoring operations, not game scalar parameters.
EYE_COVER_TEXTURE_FIELDS = {
    "surface_alpha": ("_alphaTexture", 0),
    "material_red": ("_materialTexture", 0),
    "roughness": ("_materialTexture", 1),
    "metallic": ("_materialTexture", 2),
}
EYE_COVER_OVERLAP_FIELD = "global_overlap_test"
EYE_COVER = ShaderFamily("SkinnedMeshEyeCover", "Transparent surface blending (experimental)",
    "Blends this surface with what is behind it. Colour mixing and Colour reduction control colour coverage; "
    "Surface detail and shine controls highlights and normal-map detail separately. "
    "Approximate viewport preview; the game's projection-dependent surface weighting is not reproduced. "
    "Test lighting, depth and shadows in game.", (
        ShaderField("_eyeCoverDiffuseParameter", "Colour mixing", (.5,), 0, 1,
                    "NormalizedByte4", "3844829386637310"),
        ShaderField("surface_alpha", "Surface detail and shine", (1.,), 0, 1, "TextureChannel"),
        ShaderField("material_red", "Colour reduction", (0.,), 0, 1, "TextureChannel"),
        ShaderField("roughness", "Roughness", (.9,), 0, 1, "TextureChannel"),
        ShaderField("metallic", "Metallic", (0.,), 0, 1, "TextureChannel"),
        ShaderField(EYE_COVER_OVERLAP_FIELD, "Character visibility test (global, experimental)",
                    (0.,), 0, 1, "ExportToggle"),
    ))
GLASS_FAMILIES = tuple(ShaderFamily(shader, label, note, (
    ShaderField("_thickness", "Thickness", (.02,), 0, 1, item_id="3214133184954366"),
    ShaderField("_extinctionCoefficient", "Absorption", (.3,), 0, maximum, item_id="3161969463918590"),
    ShaderField("_extinctionTint", "Shadow colour strength", (0.,), 0, 1),
)) for shader, label, maximum, note in (
    ("Translucent", "World-object glass (experimental)", 10,
     "Existing Translucent or plain Standard static materials. The rose window uses thickness 0.02, absorption 10 and shadow colour strength 1. Base-colour alpha does not control absorption. Preview approximates absorption; coloured shadows and refraction require in-game testing."),
    ("SkinnedMeshTranslucent", "Equipment glass (experimental)", 1,
     "Existing translucent, plain opaque/glowing, or layered Standard/Emissive equipment materials. Layered colours and surface maps are baked up to 2048px; dye colours become fixed. Thickness and absorption control how much light passes through the colour texture; base-colour alpha also affects absorption. Shadow colour strength is exported but not shown in the preview. Restore separate Glow and Translucency overrides on this part first."),
))
GLASS_FIELD_HELP = {
    "_thickness": "Higher values absorb more light. Thin glass can use 0.02; the game stores thickness in 256 steps. Unchecked: retain the authored value.",
    "_extinctionCoefficient": "Higher values make glass less see-through. World objects support 0–10; equipment supports 0–1. This is absorption, not an opacity percentage.",
    "_extinctionTint": "0 gives neutral absorption in supported shadow passes; 1 uses the material colour. This does not tint the visible surface. Exported for in-game testing; the preview does not show coloured shadows.",
}
# Both families use the game's SkinnedMeshTransparency technique: a forward pass
# with premultiplied blending and no depth write, drawing back faces before front
# faces. Layers behind each other therefore stay visible, unlike the one-layer
# SkinnedMeshTranslucent G-buffer. Shipped use: eight helmet visors (glass) and
# cd_phw_00_hel_00_0219 (veil).
BLENDED_FAMILIES = (
    ShaderFamily("SkinnedMeshGlass", "Layered glass (experimental)",
        "Real see-through blending: glass behind glass and the far side of the same part stay visible. "
        "Opacity is Opacity × base-colour alpha × glass colour alpha, rising toward the edges with Edge opacity. "
        "Highlights stay visible on clear glass. Accepts plain opaque or glowing equipment, existing translucent "
        "equipment glass, or existing layered glass. Inside one part the game draws back faces, then front faces, "
        "in mesh order; the preview sorts triangles by depth, so heavily overlapping layers may blend in a different "
        "order. Test the result in game.", (
        ShaderField("_tintOpacity", "Opacity", (.1,), 0, 1, item_id="1809591378640894"),
        ShaderField("_thickness", "Edge opacity", (.5,), 0, 1, item_id="3214133184954366"),
        ShaderField("_roughness", "Roughness", (.05,), 0, 1, item_id="1406263355244542"),
        ShaderField("_refractiveIndex", "Reflectance (refractive index)", (1.52,), 1, 2.5, item_id="98498246606846"),
        ShaderField("_glassColor", "Glass colour RGB", (1., 1., 1.), 0, 1, "Color", "3337232596336638"),
    )),
    ShaderFamily("SkinnedMeshTransparency", "Sheer net veil (experimental)",
        "A procedural hexagonal net for veils, tulle and net lace, blended like Layered glass. Net spacing and Thread "
        "thickness set how much of the surface the threads cover; the height map's red channel varies the thread. "
        "Even fully covered, a front face hides only about 30% of what is behind it and a back face about 70%, so "
        "the veil mainly lightens. The game reads this colour texture without sRGB conversion, so converted colours "
        "look lighter. Net spacing also widens at lower game resolutions; the preview assumes 2560×1440. "
        "Backlight glow and sheen are approximated in the preview. Accepts plain opaque or glowing equipment, or an "
        "existing net veil. Test the result in game.", (
        ShaderField("_netPitch", "Net spacing", (.5,), 0, 1, item_id="2027176113209342"),
        ShaderField("_netThread", "Thread thickness", (.5,), 0, 1, item_id="3127355417559038"),
        ShaderField("_glow", "Backlight glow", (.65,), 0, 1, item_id="2839560803319806"),
        ShaderField("_sheen", "Sheen", (.22,), 0, 1, item_id="403124275642366"),
        ShaderField("_uvScale", "Thread map scale", (1.,), 0, 1, item_id="2292528656154622"),
        # Read only by a veil with Ver2 detail layers (see veil_layer_factors).
        ShaderField("_screenSpaceDisplacementScale", "Thread width scale", (1.,), 0, 4, item_id="3"),
        ShaderField("_detailScreenSpaceDisplacementScale", "Lace strength", (0.,), 0, 4, item_id="3900249546424318"),
        ShaderField("_dyeingColor", "Veil colour RGB", (1., 1., 1.), 0, 1, "Color", "2595737222250494"),
    ), extras=VEIL_LAYER_EXTRAS),
)
BLENDED_FIELD_HELP = {
    "_tintOpacity": "How much of the background the glass hides when seen straight on: 0 clear, 1 solid. Multiplied by base-colour alpha and the glass colour's alpha. Unchecked: retain the authored value, or 0.1.",
    "_thickness": "Raises opacity at grazing angles, like the edges of real glass. 0 keeps the same opacity at every angle. Unchecked: retain the authored value, or 0.5.",
    "_roughness": "Blur of reflections: 0 mirror-like, 1 matte. Replaces the material texture's roughness. Unchecked: retain the authored value, or 0.05.",
    "_refractiveIndex": "Sets reflection strength only (1.52 is ordinary glass, higher reflects more). The game does not bend the background through this glass. Unchecked: retain the authored value, or 1.52.",
    "_glassColor": "Tints the glass body; highlights stay white. The colour's alpha, kept from the source, also scales opacity. Unchecked: retain the authored colour, or white.",
    "_netPitch": "Distance between threads. Higher values make larger, more open cells. Unchecked: retain the authored value, or 0.5.",
    "_netThread": "Thread width, scaled by the height map's red channel. Back faces use four times this width. Unchecked: retain the authored value, or 0.5.",
    "_glow": "Light from behind the veil scattered toward the viewer. 0 none, 1 strongest. Approximated in the preview. Unchecked: retain the authored value, or 0.65.",
    "_sheen": "Soft highlight at grazing angles. Approximated in the preview. Unchecked: retain the authored value, or 0.22.",
    "_screenSpaceDisplacementScale": "Multiplies the whole thread width: thread thickness x 0.0003 x (height map + lace) x this value. 0 removes the net. Unchecked: retain the authored value, or 1.",
    "_detailScreenSpaceDisplacementScale": "How much the repeated lace texture thickens the threads on top of the height map. 0 leaves only the height map. Unchecked: retain the authored value, or 0.",
    "_uvScale": "Tiling of the height map that varies the thread width; smaller values repeat it more often. Unchecked: retain the authored value, or 1.",
    "_dyeingColor": "Multiplies the colour texture. Its alpha, kept from the source, scales coverage. Unchecked: retain the authored colour, or white.",
}
# Starting points taken from shipped materials and released community mods, so a
# slider session can begin from numbers that are known to work in game.
# Wedding veil: the two net wrappers of cd_phw_00_hel_00_0219 as the game ships
# them since the November 2026 patch (veil cloth, and the _01 part), then the
# same two wrappers before that patch, which also set _uvScale and _dyeingColor.
# Sheer fabric: Angel Teddy / Angel Outfit SkinnedMeshGlass cloth. The light
# preset folds that mod's 0xd7 glass-colour alpha into Opacity (0.40 x 0.843),
# because colour edits keep the source alpha.
SHADER_PRESETS = {
    "SkinnedMeshTransparency": (
        ("Wedding veil: cloth", (("_netPitch", (.142,)), ("_netThread", (.275,)), ("_glow", (.516,)), ("_sheen", (.901,)))),
        ("Wedding veil: _01 part", (("_netPitch", (.204,)), ("_netThread", (1.0,)), ("_glow", (.773,)), ("_sheen", (.551,)))),
        ("Wedding veil before the patch: cloth", (("_netPitch", (.3,)), ("_netThread", (.727,)), ("_glow", (.516,)),
                                                  ("_sheen", (.901,)), ("_uvScale", (.27,)),
                                                  ("_dyeingColor", (217/255, 217/255, 217/255)))),
        ("Wedding veil before the patch: _01 part", (("_netPitch", (.334,)), ("_netThread", (.538,)), ("_glow", (.443,)),
                                                     ("_sheen", (.625,)))),
        ("Lace veil (community mod)", (("_netPitch", (.3,)), ("_netThread", (.627,)), ("_glow", (.1,)),
                                       ("_sheen", (.901,)), ("_uvScale", (.27,)))),
    ),
    "SkinnedMeshGlass": (
        ("Sheer fabric: light", (("_tintOpacity", (.34,)), ("_thickness", (.2,)), ("_roughness", (.55,)),
                                 ("_refractiveIndex", (1.1,)))),
        ("Sheer fabric: medium", (("_tintOpacity", (.55,)), ("_thickness", (.64,)), ("_roughness", (.8,)),
                                  ("_refractiveIndex", (1.1,)))),
        ("Sheer fabric: dense", (("_tintOpacity", (.65,)), ("_thickness", (.72,)), ("_roughness", (.84,)),
                                 ("_refractiveIndex", (1.1,)))),
    ),
}
BLENDED_SHADERS = frozenset(family.shader for family in BLENDED_FAMILIES)
# Renderer family IDs: 1–6 effects, 7 EyeCover, 8–9 one-layer glass, 10–11 layered.
BLENDED_FAMILY_IDS = {"SkinnedMeshGlass": 10, "SkinnedMeshTransparency": 11}
# The complete row set of a material that already uses the shader, for writing a
# converted material the way that one is written instead of adding rows to the
# source's. Each row is (kind, name, ItemID, value when the source has none);
# None leaves the row out. Field rows take their ItemID and default from the family.
#   Net veil: shipped cd_phw_00_hel_00_0219 (wrapper 508). The released Lace Veil
#   mod converts a plain mask to exactly this set, and drops the source's
#   _renderSettingFlag and displacement scales.
#   Layered glass: the released Angel Teddy mod's cloth; no shipped visor was read.
SHADER_LAYOUTS = {
    "SkinnedMeshTransparency": (
        ("Texture", "_baseColorTexture", "7", None),
        ("Texture", "_normalTexture", "6", None),
        ("Texture", "_materialTexture", "5", None),
        ("Texture", "_heightTexture", "4", None),
        ("Texture", "_maskTexture", "2", "character/texture/Temp_r.dds"),
        ("Field", "_netPitch", "", None), ("Field", "_netThread", "", None), ("Field", "_glow", "", None),
        ("Field", "_sheen", "", None), ("Field", "_uvScale", "", None), ("Field", "_dyeingColor", "", None),
    ),
    "SkinnedMeshGlass": (
        ("Texture", "_baseColorTexture", "7", None),
        ("Texture", "_normalTexture", "6", None),
        ("Texture", "_heightTexture", "4", None),
        ("Float", "_screenSpaceDisplacementScale", "3", "0"),
        ("Texture", "_maskTexture", "2", None),
        ("Field", "_tintOpacity", "", None), ("Field", "_refractiveIndex", "", None), ("Field", "_roughness", "", None),
        ("Field", "_thickness", "", None), ("Field", "_glassColor", "", None),
    ),
}
LAYOUT_TEXTURE_LABELS = {"_normalTexture": "Normal texture", "_materialTexture": "Material texture",
                         "_heightTexture": "Height texture"}
# Both materials carry this permutation, with no value.
LAYOUT_PERMUTATIONS = (("Uint", "AlphaTest", "1921855275401214"),)
# Texture parameters the equipment shader reads, which a user may point at a
# texture of their own. The veil reads only these two; its thread width comes
# from the height map's red channel.
TEXTURE_SLOTS = {
    "SkinnedMeshTransparency": (("_baseColorTexture", "Base colour texture"),
                                ("_heightTexture", "Thread width texture (red channel)")),
    "SkinnedMeshGlass": (("_baseColorTexture", "Base colour texture"), ("_normalTexture", "Normal texture")),
    "SkinnedMeshTranslucent": (("_baseColorTexture", "Base colour texture"), ("_normalTexture", "Normal texture")),
}
MESH_FAMILIES = (*FAMILIES, *GLASS_FAMILIES, *BLENDED_FAMILIES)
NEW_ITEM_FAMILIES = tuple(family for family in MESH_FAMILIES if family.shader not in {"Dissolve", "Translucent"}) + (EYE_COVER,)


def family_for(shader: str) -> ShaderFamily:
    for family in (*MESH_FAMILIES, EYE_COVER):
        if family.shader == shader:
            return family
    raise ValueError("Unsupported experimental shader family.")


@dataclass(frozen=True, slots=True)
class ShaderControls:
    shader: str
    # Only explicitly edited fields are written. Omitted fields retain source values.
    values: tuple[tuple[str, tuple[float, ...]], ...] = ()
    transparency_mask: TransparencyMask | None = None
    surface_response_mask: TransparencyMask | None = None
    # Versioned mapping; omission always means the original raw red-channel mask.
    coverage_mapping: str = "raw"
    colour_coverage: float | None = None
    cutout_mask: TransparencyMask | None = None
    # (texture parameter, SHA-256 of a DDS in the shader texture store).
    textures: tuple[tuple[str, str], ...] = ()
    # Write the material with the shader's own row set (SHADER_LAYOUTS) instead
    # of adding the changed rows to the source's.
    rebuild: bool = False
    # Replace any equipment material, whatever its source shader: the source
    # checks and the appearance bake are skipped, and the rebuild keeps only the
    # textures it lists. Colours a source mixes in its shader (dye, layers) are lost.
    force: bool = False
    # Texture rows of the layout a rebuild does not take from the source.
    dropped_textures: tuple[str, ...] = ()

    @property
    def has_masks(self):
        return any(mask is not None for mask in (
            self.transparency_mask, self.surface_response_mask, self.cutout_mask))

    def effective_values(self):
        """Derived output values never replace the recoverable raw authoring values."""
        values = dict(self.values)
        if self.coverage_mapping == "calibrated_v1":
            values["_eyeCoverDiffuseParameter"] = (127 / 255,)
            values["material_red"] = ((254 - round(self.colour_coverage * 255)) / 255,)
        if self.cutout_mask is not None:
            values["_wingFlowProgress"] = (.5,)
            values["_wingFlowInverse"] = (0.,)
        return values

    def colour_mask_for_output(self):
        mask = self.transparency_mask
        if mask is None or self.coverage_mapping == "raw":
            return mask
        # q = coverage * (1 - fade); R = 254/255 - q. Quantize once.
        table = bytes(254 - round(self.colour_coverage * (255 - fade)) for fade in range(256))
        return TransparencyMask(mask.width, mask.height, mask.pixels.translate(table))

    def validate(self):
        family = family_for(self.shader)
        if self.transparency_mask is not None and (
                family != EYE_COVER or not isinstance(self.transparency_mask, TransparencyMask)):
            raise ValueError("Painted transparency requires Transparent surface blending.")
        if self.surface_response_mask is not None and (
                family != EYE_COVER or not isinstance(self.surface_response_mask, TransparencyMask)):
            raise ValueError("Surface response painting requires Transparent surface blending.")
        if self.cutout_mask is not None and (
                self.shader != "SkinnedMeshWing" or not isinstance(self.cutout_mask, TransparencyMask)):
            raise ValueError("Painted cutouts require Patterned reveal.")
        if self.coverage_mapping not in ("raw", "calibrated_v1"):
            raise ValueError("Unknown colour coverage mapping.")
        if self.coverage_mapping == "calibrated_v1":
            if (family != EYE_COVER or type(self.colour_coverage) not in (int, float)
                    or not math.isfinite(self.colour_coverage) or not 0 <= self.colour_coverage <= 254 / 255):
                raise ValueError("Calibrated colour coverage must be between 0 and 254/255.")
        elif self.colour_coverage is not None:
            raise ValueError("Colour coverage requires the calibrated mapping.")
        if type(self.rebuild) is not bool or (self.rebuild and self.shader not in SHADER_LAYOUTS):
            raise ValueError("This shader has no known parameter layout to rebuild from.")
        if type(self.force) is not bool or (self.force and not self.rebuild):
            raise ValueError("Replacing a material requires the shader's own parameter set.")
        droppable = {name for kind, name, _id, _default in SHADER_LAYOUTS.get(self.shader, ())
                     if kind == "Texture" and name != "_baseColorTexture"}
        if (not isinstance(self.dropped_textures, tuple) or (self.dropped_textures and not self.rebuild)
                or len(set(self.dropped_textures)) != len(self.dropped_textures)
                or not set(self.dropped_textures) <= droppable):
            raise ValueError("Unknown texture to leave out of the rebuilt material.")
        slots = {name for name, _label in TEXTURE_SLOTS.get(self.shader, ())}
        if (len({name for name, _digest in self.textures}) != len(self.textures)
                or any(name not in slots or not isinstance(digest, str) or len(digest) != 64
                       or any(c not in "0123456789abcdef" for c in digest) for name, digest in self.textures)):
            raise ValueError("Unknown or duplicate replacement texture.")
        fields = {field.name: field for field in (*family.fields, *family.extras)}
        seen = set()
        for name, values in self.values:
            if name not in fields or name in seen:
                raise ValueError("Unknown or duplicate experimental shader control.")
            seen.add(name)
            field = fields[name]
            if len(values) != len(field.default) or any(
                type(v) not in (int, float) or not math.isfinite(v) or not field.minimum <= v <= field.maximum
                for v in values
            ):
                raise ValueError(f"{field.label}: enter {len(field.default)} value(s) between {field.minimum:g} and {field.maximum:g}.")
            if field.integer and any(v != int(v) for v in values):
                raise ValueError(f"{field.label} requires whole numbers.")

    def to_dict(self):
        self.validate()
        return {"shader": self.shader, "values": {name: list(values) for name, values in self.values},
                **{name: mask.to_dict() for name in ("transparency_mask", "surface_response_mask", "cutout_mask")
                   if (mask := getattr(self, name)) is not None},
                **({"coverage_mapping": self.coverage_mapping, "colour_coverage": self.colour_coverage}
                   if self.coverage_mapping != "raw" else {}),
                **({"textures": dict(self.textures)} if self.textures else {}),
                **({"rebuild": True} if self.rebuild else {}),
                **({"force": True} if self.force else {}),
                **({"dropped_textures": list(self.dropped_textures)} if self.dropped_textures else {})}

    @classmethod
    def from_dict(cls, value):
        if (not isinstance(value, dict) or not {"shader", "values"} <= set(value)
                or set(value) - {"shader", "values", "transparency_mask", "surface_response_mask",
                                 "coverage_mapping", "colour_coverage", "cutout_mask", "textures", "rebuild",
                                 "force", "dropped_textures"}
                or not isinstance(value["shader"], str) or not isinstance(value["values"], dict)
                or not isinstance(value.get("textures", {}), dict)):
            raise ValueError("Invalid experimental shader controls.")
        try:
            result = cls(value["shader"], tuple((name, tuple(values)) for name, values in value["values"].items()),
                         **{name: TransparencyMask.from_dict(value[name]) for name in
                            ("transparency_mask", "surface_response_mask", "cutout_mask") if name in value},
                         coverage_mapping=value.get("coverage_mapping", "raw"), colour_coverage=value.get("colour_coverage"),
                         textures=tuple(value.get("textures", {}).items()), rebuild=value.get("rebuild", False),
                         force=value.get("force", False), dropped_textures=tuple(value.get("dropped_textures", ())))
            result.validate()
        except (TypeError, OverflowError) as exc:
            raise ValueError("Invalid experimental shader controls.") from exc
        return result


def validate_choices(choices, *, glow_parts=(), translucent_parts=(), equipment=False):
    seen = set()
    conflicts = {name.casefold() for name in (*glow_parts, *translucent_parts)}
    for name, controls in choices:
        if not isinstance(name, str) or not name.strip() or name.casefold() in seen:
            raise ValueError("Shader controls must name unique material parts.")
        seen.add(name.casefold())
        controls.validate()
        if name.casefold() in conflicts:
            raise ValueError(f"{name}: restore Glow and Translucency before choosing another shader experiment.")
        if equipment and controls.shader in {"Dissolve", "Translucent"}:
            raise ValueError("World-object shaders require a static object in Mesh Editor; they cannot be applied to New Item equipment.")


VEIL_EXTRA_HELP = {
    "veilDetailRepeat": "How many times the lace texture repeats across the mesh UV, horizontally and vertically. The game stores 255 / repeat as one byte, so the value snaps to what a byte can hold. Unchecked: retain the authored repeat.",
    "veilDetailOffset": "Slides the lace texture, as a fraction of the mesh UV. Unchecked: retain the authored offset.",
    "veilDetailRotation": "Turns the lace texture about the UV centre. Stored as one byte, in steps of about 1.4 degrees. Unchecked: retain the authored rotation.",
}


def catalogue_payload():
    return [{"shader": f.shader, "label": f.label, "note": f.note,
             "fields": [{"name": p.name, "label": p.label, "default": list(p.default),
                         "minimum": p.minimum, "maximum": p.maximum,
                         "integer": p.integer,
                         **({"note": GLASS_FIELD_HELP[p.name]} if f in GLASS_FAMILIES else
                            {"note": BLENDED_FIELD_HELP[p.name]} if f in BLENDED_FAMILIES else {})}
                        for p in f.fields],
             "extras": [{"name": p.name, "label": p.label, "default": list(p.default),
                         "minimum": p.minimum, "maximum": p.maximum, "note": VEIL_EXTRA_HELP[p.name]}
                        for p in f.extras],
             "presets": [{"label": label, "values": {name: list(numbers) for name, numbers in values}}
                         for label, values in SHADER_PRESETS.get(f.shader, ())],
             "textures": [{"name": name, "label": label} for name, label in TEXTURE_SLOTS.get(f.shader, ())],
             "rebuild": f.shader in SHADER_LAYOUTS,
             # Texture rows a rebuild can leave out, as (parameter, label).
             "layout_textures": [[name, LAYOUT_TEXTURE_LABELS[name]] for kind, name, _id, _default
                                 in SHADER_LAYOUTS.get(f.shader, ()) if kind == "Texture" and name in LAYOUT_TEXTURE_LABELS]}
            for f in MESH_FAMILIES]


def _colour_alpha(raw):
    """The packed colour's alpha byte; writers retain it, so readback must too."""
    raw = str(raw or "")
    if len(raw) == 9 and raw.startswith("#"):
        try:
            return int(raw[-2:], 16) / 255
        except ValueError:
            pass
    return 1.


def authored_field_numbers(field, raw):
    """Parse one authored parameter the way the preview reads it; None when absent or unusable.

    The inspector shows these numbers and the renderer draws from them, so both
    must come from this single parser.
    """
    numbers = None
    try:
        if field.kind == "Color" and isinstance(raw, str) and raw.startswith("#"):
            numbers = tuple(int(raw[i:i+2], 16)/255 for i in (1, 3, 5))
        elif raw is not None:
            numbers = tuple(float(n) for n in str(raw).replace(",", " ").split())
            if field.kind == "Byte4":
                numbers = (float(int(numbers[0]) & 255),)
            elif field.kind == "BitFlag32":
                numbers = (float(int(numbers[0]) & 1),)
        if numbers is None or len(numbers) != len(field.default) or any(not math.isfinite(n) for n in numbers):
            return None
    except (ValueError, TypeError, OverflowError, IndexError):
        return None
    return numbers


def authored_values_payload(authored):
    """Authored numbers per family for the inspector: {shader: {field: [numbers]}}.

    Only parameters the source material actually declares appear, so the panel
    can tell an authored value from a definition default.
    """
    result = {}
    for family in MESH_FAMILIES:
        fields = {}
        for field in family.fields:
            numbers = authored_field_numbers(field, (authored or {}).get(field.name))
            if numbers is not None:
                fields[field.name] = [min(max(n, field.minimum), field.maximum) for n in numbers]
        if fields:
            result[family.shader] = fields
    return result


# The November 2026 patch gave SkinnedMeshTransparency the Ver2 detail layers.
# These rows are read from the shipped pixel shader (DXIL variant ..._151cd770):
#   thread = _netThread * 0.0003 * (Hbase + Hdetail) * _screenSpaceDisplacementScale
#   Hdetail = opacity[ch] * mask[ch] * detailHeightMask[ch](detail UV).r * _detailScreenSpaceDisplacementScale
#   detail UV: q = ((u - 0.5 - Ox) / Sx, (v - 0.5 + Oy) / Sy), rotated by rotation byte * 2 pi / 255 - pi
#   alpha = coverage * _overlayColorTexture alpha * 0.99
# ch is the largest channel of _colorBlendingMaskTexture. The keys below carry
# what only the caller that knows the source material can tell preview_factors.
VEIL_LAYERS_KEY = "_cdmwVeilLayers"           # "r", "g" or "b": the detail channel in use
VEIL_LAYER_MASK_KEY = "_cdmwVeilLayerMask"    # that channel's mask value, 0-1
VEIL_OVERLAY_ALPHA_KEY = "_cdmwVeilOverlayAlpha"
VEIL_LAYER_TRANSFORMS = {"r": "_dyeingTransformProperty0", "g": "_dyeingTransformProperty1",
                         "b": "_dyeingTransformProperty3"}
# _screenSpaceDisplacementScale: the veil's .material declares 1 itself and 0 in the
# shared group; 0 would remove the net, so the field's default is 1.


def _authored_number(value, default):
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _authored_bytes(value):
    """A Byte4 row as four 0-1 numbers, lowest byte first; () when it is not one."""
    number = _authored_number(value, -1.0)
    if number < 0 or number > 0xFFFFFFFF or number != int(number):
        return ()
    return tuple(((int(number) >> (8 * index)) & 0xFF) / 255.0 for index in range(4))


def _texture_name(path):
    return str(path or "").replace("\\", "/").rsplit("/", 1)[-1].casefold()


def veil_layer_inputs(shader, values, textures):
    """Keys for preview_factors when a source net veil draws Ver2 detail layers, else {}.

    The channel is the one the mask texture names (the engine's Temp_r/g/b
    constants), otherwise the first channel with a detail height texture; the
    mask value is then taken as 1. A constant overlay (nonetexture0xAARRGGBB)
    gives its alpha; any other overlay is taken as opaque.
    """
    if shader != "SkinnedMeshTransparency":
        return {}
    heights = {channel: textures.get(f"_detailHeightMask{channel.upper()}", "") for channel in "rgb"}
    try:
        flags = int(str(values.get("_colorBlendingFlag", "0") or "0"), 0)
    except ValueError:
        flags = 0
    if not any(heights.values()) and not flags & 0xFFF:
        return {}
    mask = _texture_name(textures.get("_colorBlendingMaskTexture", ""))
    # An extracted copy keeps the name behind a hash prefix (a5793a90c178ccf0_temp_r.dds).
    channel = next((name for name in "rgb" if mask.endswith(f"temp_{name}.dds")), None)
    if channel is None:
        channel = next((name for name in "rgb" if heights[name]), "r")
    result = {VEIL_LAYERS_KEY: channel, VEIL_LAYER_MASK_KEY: "1"}
    overlay = _texture_name(textures.get("_overlayColorTexture", ""))
    constant = overlay[overlay.rfind("nonetexture0x") + 13:] if "nonetexture0x" in overlay else ""
    if len(constant) >= 8:
        try:
            result[VEIL_OVERLAY_ALPHA_KEY] = str(int(constant[:2], 16) / 255.0)
        except ValueError:
            pass
    return result


def veil_layer_texture(values, textures):
    """Path of the detail height texture the keys from veil_layer_inputs select, or ""."""
    channel = str(values.get(VEIL_LAYERS_KEY, "") or "")
    return textures.get(f"_detailHeightMask{channel.upper()}", "") if channel in ("r", "g", "b") else ""


# The two rows only a veil with Ver2 detail layers reads, and the two it no longer reads.
VEIL_LAYER_FIELDS = ("_screenSpaceDisplacementScale", "_detailScreenSpaceDisplacementScale")
VEIL_PRE_PATCH_FIELDS = ("_uvScale", "_dyeingColor")


def veil_layer_factors(authored, edits=None):
    """Lanes 15-22 for the Ver2 veil, or () for the veil before the patch.

    The family's own fields come first: 4 pitch, 5 thread, 6 glow, 7 sheen,
    8 map scale, 9 _screenSpaceDisplacementScale, 10 _detailScreenSpaceDisplacementScale,
    11-13 colour, 14 colour alpha. Then 15 on, 16 opacity x mask of the channel,
    17-20 scale X, scale Y, offset X, offset Y, 21 rotation in radians, 22 overlay alpha.
    """
    channel = str(authored.get(VEIL_LAYERS_KEY, "") or "")
    if channel not in ("r", "g", "b"):
        return ()
    index = "rgb".index(channel)
    clamp = lambda number, high: min(max(number, 0.0), high)
    opacity = _authored_bytes(authored.get("_dyeingGlobalOpacity"))
    transform = _authored_bytes(authored.get(VEIL_LAYER_TRANSFORMS[channel])) or (1.0, 1.0, 0.0, 0.0)
    rotation = _authored_bytes(authored.get("_dyeingPropertyBlend"))
    # An absent row takes the shader definition's default: opacity 0, scale 1,
    # offset 0 and rotation 0.5 (byte 128).
    gain = (opacity[index] if opacity else 0.0) * clamp(_authored_number(authored.get(VEIL_LAYER_MASK_KEY), 1.0), 1.0)
    turn = rotation[index] if rotation else 128 / 255
    # An edited control previews as the bytes the writer will store.
    edits = edits or {}
    scale, offset, turned = veil_transform_bytes(edits.get(VEIL_REPEAT), edits.get(VEIL_OFFSET), edits.get(VEIL_ROTATION))
    if scale is not None:
        transform = (scale[0] / 255, scale[1] / 255, *transform[2:])
    if offset is not None:
        transform = (*transform[:2], offset[0] / 255, offset[1] / 255)
    if turned is not None:
        turn = turned / 255
    angle = turn * 2.0 * math.pi - math.pi
    return (1.0, gain, max(transform[0], 1e-5), max(transform[1], 1e-5), transform[2], transform[3], angle,
            clamp(_authored_number(authored.get(VEIL_OVERLAY_ALPHA_KEY), 1.0), 1.0))


def preview_factors(controls, authored=None):
    """Eight vec4s shared with the renderer; source values precede explicit edits.

    Header: family ID, dye-alpha gate, material flag bit 0, reserved.
    Remaining values follow the family's declared field order. Unknown vertex
    masks are carried separately and never replaced with guessed colour means.
    Lane 30 selects authored Wing cutout mips; lane 31 belongs to the renderer's
    normal-texture presence flag and must never carry an authoring setting.
    """
    controls.validate()
    family = family_for(controls.shader)
    if family == EYE_COVER:
        # Family 7 uses independent colour coverage and surface weights. -1
        # inherits a sampled channel; it must not become an opacity override.
        values = controls.effective_values()
        try:
            colour = (int((authored or {}).get("_eyeCoverDiffuseParameter", 128)) & 255) / 255
        except (ValueError, TypeError, OverflowError):
            colour = 128 / 255
        if "_eyeCoverDiffuseParameter" in values:
            colour = round(values["_eyeCoverDiffuseParameter"][0] * 255) / 255
        channels = [round(values[name][0] * 255) / 255 if name in values else -1.
                    for name in ("surface_alpha", "material_red", "roughness", "metallic")]
        if controls.transparency_mask is not None:
            channels[1] = -1.  # Sample the painted red channel instead of the scalar.
        if controls.surface_response_mask is not None:
            channels[0] = -1.
        return tuple([7., 0., 0., 0., colour, *channels, *([0.] * 23)])
    authored = authored or {}
    values = controls.effective_values()
    dye = str(authored.get("_hairDyeingColor", ""))
    dye_active = len(dye) == 9 and dye.startswith("#") and dye[-2:] != "00"
    try:
        flags = int(float(authored.get("_materialFlags", 0)))
    except (ValueError, TypeError, OverflowError):
        flags = 0
    if "_materialFlags" in values:
        flags = int(values["_materialFlags"][0])
    family_id = (GLASS_FAMILIES.index(family) + 8 if family in GLASS_FAMILIES
                 else BLENDED_FAMILY_IDS[family.shader] if family in BLENDED_FAMILIES
                 else FAMILIES.index(family) + 1)
    # Layered families reuse header lane 1 as "base-colour alpha applies"; the
    # renderer clears it for glTF OPAQUE imports, whose export writes solid alpha.
    result = [float(family_id), 1. if family in BLENDED_FAMILIES else float(dye_active), float(flags & 1), 0.]
    for field in family.fields:
        numbers = values.get(field.name)
        if numbers is None:
            numbers = authored_field_numbers(field, authored.get(field.name)) or field.default
        if family in GLASS_FAMILIES and any(not field.minimum <= n <= field.maximum for n in numbers):
            raise ValueError(f"{field.label}: authored value is outside the supported {family.shader} range.")
        if family in BLENDED_FAMILIES:
            # Out-of-range authored numbers are the game's to interpret; the
            # preview clamps them rather than refusing an archive material.
            numbers = tuple(min(max(n, field.minimum), field.maximum) for n in numbers)
        result.extend(numbers)
    if family in BLENDED_FAMILIES:
        # The colour's alpha follows its RGB lanes. Edits only replace RGB and the
        # writer keeps the source alpha, so readback always uses the authored byte.
        colour = family.fields[-1].name
        result.append(_colour_alpha(authored.get(colour)))
    if family.shader == "SkinnedMeshTransparency":
        result.extend(veil_layer_factors(authored, values))
    result.extend([0.] * (32 - len(result)))
    result[30] = float(controls.cutout_mask is not None)
    return tuple(result)


def eye_cover_colour_range(controls, authored=None):
    """Unclamped nominal colour contribution; this is not final pixel visibility."""
    factors = preview_factors(controls, authored)
    mask = controls.transparency_mask
    if mask is not None:
        # This diagnostic is also displayed by Qt. Reduce in C without copying
        # or walking millions of pixels in Python on every control change.
        import numpy as np
        pixels = np.frombuffer(mask.pixels, dtype=np.uint8)
        low, high = int(pixels.min()), int(pixels.max())
        if controls.coverage_mapping == "calibrated_v1":
            low, high = (254 - round(controls.colour_coverage * (255 - value)) for value in (low, high))
        low, high = low / 255, high / 255
    elif factors[6] >= 0:
        low = high = factors[6]
    else:
        low, high = 0., 1.  # Source sampling can span the channel's entire range.
    return 2 * factors[4] - high, 2 * factors[4] - low
