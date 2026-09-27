"""Experimental controls recovered from material definitions and compiled shaders.

These are material-family contracts, not a list of interchangeable shader names.
Wing and New Item's EyeCover experiment accept plain equipment.
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

# Keep the native renderer's family IDs and Mesh Editor catalogue unchanged.
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
NEW_ITEM_FAMILIES = tuple(family for family in FAMILIES if family.shader != "Dissolve") + (EYE_COVER,)


def family_for(shader: str) -> ShaderFamily:
    for family in (*FAMILIES, EYE_COVER):
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
        fields = {field.name: field for field in family.fields}
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
                   if self.coverage_mapping != "raw" else {})}

    @classmethod
    def from_dict(cls, value):
        if (not isinstance(value, dict) or not {"shader", "values"} <= set(value)
                or set(value) - {"shader", "values", "transparency_mask", "surface_response_mask",
                                 "coverage_mapping", "colour_coverage", "cutout_mask"}
                or not isinstance(value["shader"], str) or not isinstance(value["values"], dict)):
            raise ValueError("Invalid experimental shader controls.")
        try:
            result = cls(value["shader"], tuple((name, tuple(values)) for name, values in value["values"].items()),
                         **{name: TransparencyMask.from_dict(value[name]) for name in
                            ("transparency_mask", "surface_response_mask", "cutout_mask") if name in value},
                         coverage_mapping=value.get("coverage_mapping", "raw"), colour_coverage=value.get("colour_coverage"))
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
        if equipment and controls.shader == "Dissolve":
            raise ValueError("Object dissolve requires a static object in Mesh Editor; it cannot be applied to New Item equipment.")


def catalogue_payload():
    return [{"shader": f.shader, "label": f.label, "note": f.note,
             "fields": [{"name": p.name, "label": p.label, "default": list(p.default),
                         "minimum": p.minimum, "maximum": p.maximum,
                         "integer": p.integer} for p in f.fields]} for f in FAMILIES]


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
    result = [float(FAMILIES.index(family) + 1), float(dye_active), float(flags & 1), 0.]
    for field in family.fields:
        numbers = values.get(field.name)
        if numbers is None:
            raw = authored.get(field.name)
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
                    numbers = field.default
            except (ValueError, TypeError, OverflowError):
                numbers = field.default
        result.extend(numbers)
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
