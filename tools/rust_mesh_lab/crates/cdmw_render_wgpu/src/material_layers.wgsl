struct LayerEntry {
    dye: vec4<f32>, affine: vec4<f32>, offset: vec4<f32>, properties: vec4<f32>,
    // Grime of the same channel: its own tiling, (offset, ramp low, ramp high),
    // sRGB tint and strength, (intensity, presence, normal encoding, unused).
    grime_affine: vec4<f32>, grime_offset: vec4<f32>, grime_tint: vec4<f32>, grime: vec4<f32>,
    // Scratches: (roughness step, metal step, presence, unused), sRGB tint and strength.
    scratch: vec4<f32>, scratch_tint: vec4<f32>,
};
struct LayerUniform {
    layers: array<LayerEntry, 3>, seeds: array<vec4<f32>, 3>, base_color: vec4<f32>, control: vec4<u32>,
    // The Ver2 blend layer: sRGB dye and strength, placement, (UV offset, opacity, presence).
    blend_dye: vec4<f32>, blend_affine: vec4<f32>, blend_offset: vec4<f32>,
};
@group(2) @binding(0) var blend_mask: texture_2d<f32>;
@group(2) @binding(1) var layer_r_color: texture_2d<f32>;
@group(2) @binding(2) var layer_r_normal: texture_2d<f32>;
@group(2) @binding(3) var layer_r_sp: texture_2d<f32>;
@group(2) @binding(4) var layer_g_color: texture_2d<f32>;
@group(2) @binding(5) var layer_g_normal: texture_2d<f32>;
@group(2) @binding(6) var layer_g_sp: texture_2d<f32>;
@group(2) @binding(7) var layer_b_color: texture_2d<f32>;
@group(2) @binding(8) var layer_b_normal: texture_2d<f32>;
@group(2) @binding(9) var layer_b_sp: texture_2d<f32>;
@group(2) @binding(10) var<uniform> layer_uniform: LayerUniform;
// _detailMaskTexture: red marks scratches, green marks grime.
@group(2) @binding(11) var detail_mask: texture_2d<f32>;
@group(2) @binding(12) var grime_r_color: texture_2d<f32>;
@group(2) @binding(13) var grime_r_normal: texture_2d<f32>;
@group(2) @binding(14) var grime_r_sp: texture_2d<f32>;
@group(2) @binding(15) var grime_g_color: texture_2d<f32>;
@group(2) @binding(16) var grime_g_normal: texture_2d<f32>;
@group(2) @binding(17) var grime_g_sp: texture_2d<f32>;
@group(2) @binding(18) var grime_b_color: texture_2d<f32>;
@group(2) @binding(19) var grime_b_normal: texture_2d<f32>;
@group(2) @binding(20) var grime_b_sp: texture_2d<f32>;
// _overlayColorTexture (Ver2): linear data at the mesh UV.
@group(2) @binding(21) var overlay_color: texture_2d<f32>;
// _detailDiffuseBlend (Ver2): the blend layer's colour, placed once.
@group(2) @binding(22) var blend_color: texture_2d<f32>;

fn layer_uv(layer: LayerEntry, uv: vec2<f32>) -> vec2<f32> {
    return vec2<f32>(layer.affine.x*uv.x + layer.affine.z*uv.y,
                     layer.affine.y*uv.x + layer.affine.w*uv.y) + layer.offset.xy;
}

fn layer_dye(color: vec3<f32>, dye: vec4<f32>, mean: f32, opacity: f32) -> vec3<f32> {
    let luminance = dot(color, vec3<f32>(0.2126, 0.7152, 0.0722));
    return mix(color, clamp(dye.rgb * luminance / max(mean, 0.0001), vec3<f32>(0.0), vec3<f32>(1.0)), clamp(dye.a * opacity, 0.0, 1.0));
}

fn layer_normal(sampled: vec3<f32>, layer: LayerEntry) -> vec3<f32> {
    let signed = layer.properties.w == 2.0;
    let xy = select(sampled.xy * 2.0 - vec2<f32>(1.0), sampled.xy, signed);
    let z = select(sampled.z * 2.0 - 1.0, sqrt(max(1.0-dot(xy,xy),0.0)), layer.properties.w > 0.0);
    let rotated = vec2<f32>(dot(layer.affine.xy, xy), dot(layer.affine.zw, xy)) / max(length(layer.affine.xy), 0.00001);
    return safe_normalize(vec3<f32>(rotated,z), vec3<f32>(0.0,0.0,1.0));
}

fn grime_uv(layer: LayerEntry, uv: vec2<f32>) -> vec2<f32> {
    return vec2<f32>(layer.grime_affine.x*uv.x + layer.grime_affine.z*uv.y,
                     layer.grime_affine.y*uv.x + layer.grime_affine.w*uv.y) + layer.grime_offset.xy;
}

fn grime_normal(sampled: vec3<f32>, layer: LayerEntry) -> vec3<f32> {
    let signed = layer.grime.z == 2.0;
    let xy = select(sampled.xy * 2.0 - vec2<f32>(1.0), sampled.xy, signed);
    let z = select(sampled.z * 2.0 - 1.0, sqrt(max(1.0-dot(xy,xy),0.0)), layer.grime.z > 0.0);
    let rotated = vec2<f32>(dot(layer.grime_affine.xy, xy), dot(layer.grime_affine.zw, xy)) / max(length(layer.grime_affine.xy), 0.00001);
    return safe_normalize(vec3<f32>(rotated,z), vec3<f32>(0.0,0.0,1.0));
}

// Photoshop overlay on display-space values, as the game's shader applies its tints.
fn layer_overlay(base: vec3<f32>, blend: vec3<f32>) -> vec3<f32> {
    return select(vec3<f32>(1.0) - 2.0*(vec3<f32>(1.0)-base)*(vec3<f32>(1.0)-blend), 2.0*base*blend, base < vec3<f32>(0.5));
}

// The game's tint: desaturate 80%, overlay the tint in sRGB, mix in by its alpha.
fn layer_tint(color: vec3<f32>, tint: vec4<f32>) -> vec3<f32> {
    let grey = mix(color, vec3<f32>(dot(color, vec3<f32>(0.299, 0.587, 0.114))), 0.8);
    let tinted = srgb_to_linear(layer_overlay(linear_to_srgb(clamp(grey, vec3<f32>(0.0), vec3<f32>(1.0))), tint.rgb));
    return mix(color, tinted, clamp(tint.a, 0.0, 1.0));
}

// Where the game shows a layer's grime: a smoothstep ramp over the detail
// mask's green between the layer's two ramp edges, times its intensity.
fn grime_weight(layer: LayerEntry, detail_green: f32) -> f32 {
    let low = layer.grime_offset.z;
    let high = min(max(layer.grime_offset.w, low + 0.005), 1.0);
    let x = clamp((detail_green - low) / (high - low), 0.0, 1.0);
    return clamp(x*x*(3.0-2.0*x) * layer.grime.x, 0.0, 1.0) * step(0.5, layer.grime.y);
}

fn layer_rnm(base: vec3<f32>, detail: vec3<f32>) -> vec3<f32> {
    let t = base + vec3<f32>(0.0,0.0,1.0);
    let u = detail * vec3<f32>(-1.0,-1.0,1.0);
    return safe_normalize(t * dot(t,u) / max(t.z,0.00001) - u, base);
}

// control.w bit 1: the layer binding carries a colour rule only (the legacy dye
// of a part without colour layers). Normal, roughness, metal and occlusion then
// stay with the surface shader's own maps.
fn material_layers_colour_only() -> bool {
    return (material.flags & MATERIAL_GPU_LAYERS) != 0u && (layer_uniform.control.w & 2u) != 0u;
}

// The game's dye of the legacy families (Standard, Cloth, Fur, Emissive,
// AmplifiedGlare, Wing, Poster; permutation d2990a66b31f1efe):
//   c = dyeR * m.r;  c = lerp(c, dyeG, m.g);  c = lerp(c, dyeB, m.b)    (rgb and alpha)
//   albedo = lerp(base, srgb_to_linear(overlay(base = m.a, blend = c.rgb)), c.a)
// m is _maskTexture, the dyes are _dyeingColorMaskR/G/B as sRGB values. The
// mask's alpha is the overlay's base, so it shades the dye: 0.5 leaves it, 0 is
// black, 1 white (%404-%426 of the permutation's listing branch on the alpha).
fn legacy_dye(base: vec3<f32>, m: vec4<f32>) -> vec3<f32> {
    var c = layer_uniform.seeds[0] * m.r;
    c = mix(c, layer_uniform.seeds[1], m.g);
    c = mix(c, layer_uniform.seeds[2], m.b);
    let dyed = srgb_to_linear(layer_overlay(vec3<f32>(m.a), clamp(c.rgb, vec3<f32>(0.0), vec3<f32>(1.0))));
    return mix(base, dyed, clamp(c.a, 0.0, 1.0));
}

fn eye_tangent_normal(sampled: vec3<f32>, encoding: f32) -> vec3<f32> {
    var xy = select(sampled.xy * 2.0 - vec2<f32>(1.0), sampled.xy, encoding == 2.0);
    if (material.flags & MATERIAL_NORMAL_Y_INVERTED) != 0u { xy.y = -xy.y; }
    return vec3<f32>(xy, sqrt(max(1.0 - dot(xy, xy), 0.0)));
}

// SkinnedMeshEye (permutation a4b73dd211913bc3), without the parallax search,
// the scene-exposure DynamicEyeColor term and the camera-distance roughness:
//   uvP  = (2uv - 1)(1 - P1.b3/510) + 0.5                        EyeImageScale
//   uvI  = (2uvP - 1)(1 - P0.b3/255) + 0.5                       IrisSize
//   uvPu = (uvI - 0.5) s / pw + 0.5 (P1.b0, P1.b1 > 0)           pupil size and stretch
//   c = lerp(lerp(base(uvP), iris.rgb, iris.a), pupil.rgb, pupil.a);  albedo = min(1, c * _irisBrightness * 2)
//   rough = P1.b2 ? lerp(_materialTexture.g, _irisMaterialTexture.g, iris.a) : (1 - pupil.a) (r < 0.5 ? 0 : 0.1)
//   rough = max(rough, 0.1)          (the game adds 0.1 * saturate(distance * 2/3))
//   normal = lerp(sclera normal, iris normal, iris.a)
// Slot B's entry holds P0 (dye), P1 (affine) and (brightness, iris normal,
// iris material, normal encoding). The eye writes no metal and no occlusion map:
// its `_materialTexture.b` lerp lands in the G-buffer's subsurface slot.
fn evaluate_eye(uv: vec2<f32>) -> LayerSurface {
    let p0 = layer_uniform.layers[2].dye;
    let p1 = layer_uniform.layers[2].affine;
    let info = layer_uniform.layers[2].properties;
    let uvp = (2.0 * uv - vec2<f32>(1.0)) * (1.0 - p1.w / 510.0) + vec2<f32>(0.5);
    let r = length(2.0 * abs(uvp) - vec2<f32>(1.0));
    var pw = 1.0;
    if r < 0.5 {
        let stretch = clamp(2.0 * (p0.y / 255.0 + 0.05 + abs(p0.z - p0.y) / 255.0 * (p0.x / 255.0)), 0.0, 1.0);
        pw = pow(2.0 * r, 1.0 - 2.0 * stretch);
    }
    let uvi = (2.0 * uvp - vec2<f32>(1.0)) * (1.0 - p0.w / 255.0) + vec2<f32>(0.5);
    var uvpu = uvi;
    if p1.x > 0.0 && p1.y > 0.0 {
        let a = p1.xy * 2.0 / 255.0;
        let s = min(a, mix(a, vec2<f32>(1.0), p1.x / 255.0));
        uvpu = (uvi - vec2<f32>(0.5)) * s / max(pw, 1e-6) + vec2<f32>(0.5);
    }
    let sclera = textureSampleBias(base_texture, material_sampler, uvp, MATERIAL_MIP_LOD_BIAS);
    var iris = vec4<f32>(0.0);
    if layer_uniform.layers[0].properties.z > 0.5 {
        iris = textureSampleBias(layer_r_color, material_sampler, uvi, 0.0);
    }
    var pupil = vec4<f32>(0.0);
    if layer_uniform.layers[1].properties.z > 0.5 {
        pupil = textureSampleBias(layer_g_color, material_sampler, uvpu, 0.0);
    }
    var color = select(sclera.rgb, vec3<f32>(1.0), (layer_uniform.control.w & 1u) != 0u);
    color = mix(color, iris.rgb, clamp(iris.a, 0.0, 1.0));
    color = mix(color, pupil.rgb, clamp(pupil.a, 0.0, 1.0));
    color = min(color * info.x * 2.0, vec3<f32>(1.0));
    var sclera_sp = vec3<f32>(0.0);
    if (material.flags & MATERIAL_SURFACE) != 0u { sclera_sp = textureSampleBias(material_texture, material_sampler, uvpu, 0.0).rgb; }
    var iris_sp = vec3<f32>(0.0);
    if info.z > 0.5 { iris_sp = textureSampleBias(layer_r_sp, material_sampler, uvpu, 0.0).rgb; }
    var rough = (1.0 - pupil.a) * select(0.1, 0.0, r < 0.5);
    if p1.z > 0.0 { rough = mix(sclera_sp.g, iris_sp.g, iris.a); }
    rough = max(rough, 0.1);
    var sclera_n = vec3<f32>(0.0, 0.0, 1.0);
    if (material.flags & MATERIAL_NORMAL) != 0u {
        sclera_n = eye_tangent_normal(textureSampleBias(normal_texture, material_sampler, uvpu, 0.0).rgb, 0.0);
    }
    var iris_n = vec3<f32>(0.0, 0.0, 1.0);
    if info.y > 0.5 { iris_n = eye_tangent_normal(textureSampleBias(layer_r_normal, material_sampler, uvpu, 0.0).rgb, info.w); }
    let normal = safe_normalize(mix(sclera_n, iris_n, clamp(iris.a, 0.0, 1.0)), vec3<f32>(0.0, 0.0, 1.0));
    return LayerSurface(color, normal, vec3<f32>(1.0, clamp(rough, 0.0, 1.0), 0.0), vec3<f32>(iris.a, pupil.a, 0.0));
}

fn evaluate_material_layers(uv: vec2<f32>, sampled_base: vec4<f32>) -> LayerSurface {
    // control.w bit 0: no base colour map, so the surface beneath the layers is
    // white rather than the grey placeholder bound for untextured geometry.
    let base = vec4<f32>(select(sampled_base.rgb, vec3<f32>(1.0), (layer_uniform.control.w & 1u) != 0u), sampled_base.a);
    var out = LayerSurface(sampled_base.rgb, vec3<f32>(0.0,0.0,1.0), vec3<f32>(1.0,0.66,0.0), vec3<f32>(0.0));
    if (material.flags & MATERIAL_GPU_LAYERS) == 0u { return out; }
    // Mode 1 picks one layer per pixel, so its mask is read as sharply as the base
    // maps are: at a mip two levels coarser the thin trims and inlays fall below
    // their neighbours and vanish from the picture.
    let mask_texel = textureSampleBias(blend_mask, material_sampler, uv, select(0.0, MATERIAL_MIP_LOD_BIAS, layer_uniform.control.x == 1u));
    var mask = mask_texel.rgb;
    let raw_mask = mask;
    if (layer_uniform.control.w & 2u) != 0u {
        out.color = legacy_dye(base.rgb, mask_texel);
        out.mask = mask;
        return out;
    }
    let sum = dot(mask, vec3<f32>(1.0));
    if layer_uniform.control.x == 1u {
        mask = select(mask / max(sum,0.00001), vec3<f32>(1.0,0.0,0.0), sum < 0.00001);
    }
    out.mask = mask;
    var base_normal = vec3<f32>(0.0,0.0,1.0);
    if (material.flags & MATERIAL_NORMAL) != 0u {
        var xy = textureSampleBias(normal_texture, material_sampler, uv, 0.0).xy * 2.0 - vec2<f32>(1.0);
        if (material.flags & MATERIAL_NORMAL_Y_INVERTED) != 0u { xy.y = -xy.y; }
        base_normal = safe_normalize(vec3<f32>(xy,sqrt(max(1.0-dot(xy,xy),0.0))), base_normal);
    }
    var base_sp = vec3<f32>(1.0,0.66,0.0);
    if (material.flags & MATERIAL_SURFACE) != 0u { base_sp = textureSampleBias(material_texture, material_sampler, uv, 0.0).rgb; }
    if layer_uniform.control.x == 3u {
        return evaluate_eye(uv);
    }
    var colors: array<vec3<f32>,3>;
    var normals: array<vec3<f32>,3>;
    var responses: array<vec3<f32>,3>;
    // Statically named resources work without descriptor-indexing features.
    let ur = layer_uv(layer_uniform.layers[0], uv);
    let ug = layer_uv(layer_uniform.layers[1], uv);
    let ub = layer_uv(layer_uniform.layers[2], uv);
    let texel_r = textureSampleBias(layer_r_color, material_sampler, ur, 0.0);
    let texel_g = textureSampleBias(layer_g_color, material_sampler, ug, 0.0);
    let texel_b = textureSampleBias(layer_b_color, material_sampler, ub, 0.0);
    colors[0] = texel_r.rgb;
    colors[1] = texel_g.rgb;
    colors[2] = texel_b.rgb;
    let alphas = vec3<f32>(texel_r.a, texel_g.a, texel_b.a);
    // Mode 1 keeps each channel's own surface: the game draws one of them.
    var layer_colors: array<vec3<f32>,3>;
    var layer_normals: array<vec3<f32>,3>;
    var layer_responses: array<vec3<f32>,3>;
    var response_opacity = vec3<f32>(1.0);
    normals[0] = textureSampleBias(layer_r_normal, material_sampler, ur, 0.0).rgb;
    normals[1] = textureSampleBias(layer_g_normal, material_sampler, ug, 0.0).rgb;
    normals[2] = textureSampleBias(layer_b_normal, material_sampler, ub, 0.0).rgb;
    responses[0] = textureSampleBias(layer_r_sp, material_sampler, ur, 0.0).rgb;
    responses[1] = textureSampleBias(layer_g_sp, material_sampler, ug, 0.0).rgb;
    responses[2] = textureSampleBias(layer_b_sp, material_sampler, ub, 0.0).rgb;
    let detail_texel = textureSampleBias(detail_mask, material_sampler, uv, 0.0).rgb;
    // The blend layer is placed once: it draws where its own UV lies in 0.005 to
    // 0.995. Sampled here, outside the per-pixel choice below.
    let blend_uv = vec2<f32>(layer_uniform.blend_affine.x*uv.x + layer_uniform.blend_affine.z*uv.y,
                             layer_uniform.blend_affine.y*uv.x + layer_uniform.blend_affine.w*uv.y) + layer_uniform.blend_offset.xy;
    let blend_texel = textureSampleBias(blend_color, material_sampler, clamp(blend_uv, vec2<f32>(0.005), vec2<f32>(0.995)), 0.0);
    var grime_colors: array<vec3<f32>,3>;
    var grime_normals: array<vec3<f32>,3>;
    var grime_responses: array<vec3<f32>,3>;
    let gr = grime_uv(layer_uniform.layers[0], uv);
    let gg = grime_uv(layer_uniform.layers[1], uv);
    let gb = grime_uv(layer_uniform.layers[2], uv);
    grime_colors[0] = textureSampleBias(grime_r_color, material_sampler, gr, 0.0).rgb;
    grime_colors[1] = textureSampleBias(grime_g_color, material_sampler, gg, 0.0).rgb;
    grime_colors[2] = textureSampleBias(grime_b_color, material_sampler, gb, 0.0).rgb;
    grime_normals[0] = textureSampleBias(grime_r_normal, material_sampler, gr, 0.0).rgb;
    grime_normals[1] = textureSampleBias(grime_g_normal, material_sampler, gg, 0.0).rgb;
    grime_normals[2] = textureSampleBias(grime_b_normal, material_sampler, gb, 0.0).rgb;
    grime_responses[0] = textureSampleBias(grime_r_sp, material_sampler, gr, 0.0).rgb;
    grime_responses[1] = textureSampleBias(grime_g_sp, material_sampler, gg, 0.0).rgb;
    grime_responses[2] = textureSampleBias(grime_b_sp, material_sampler, gb, 0.0).rgb;
    var color = vec3<f32>(0.0);
    var normal = vec3<f32>(0.0);
    var orm = vec3<f32>(0.0);
    // Mode 4 is the game's rule for the legacy families; mode 2 keeps the older
    // weighted mix for the other families that read _maskTexture.
    let legacy = layer_uniform.control.x == 4u;
    if layer_uniform.control.x == 2u {
        color = base.rgb * layer_uniform.base_color.rgb;
        normal = base_normal;
        orm = base_sp;
    }
    if legacy {
        color = legacy_dye(base.rgb, mask_texel);
        normal = base_normal;
        orm = base_sp;
        // One detail layer per pixel, the largest mask channel: its colour,
        // dyed by the game's overlay, by its own alpha times the opacity byte.
        var slot = 2u;
        if mask.r >= mask.g && mask.r >= mask.b { slot = 0u; } else if mask.g >= mask.b { slot = 1u; }
        let chosen = layer_uniform.layers[slot];
        // offset.w marks a layer whose colour map the wrapper does not declare.
        if chosen.properties.z > 0.5 && chosen.offset.w < 0.5 {
            color = mix(color, layer_tint(colors[slot], chosen.dye), clamp(alphas[slot] * chosen.properties.x, 0.0, 1.0));
        }
    }
    for (var k = 0u; k < 3u; k += 1u) {
        let layer = layer_uniform.layers[k];
        if layer_uniform.control.x == 2u || legacy {
            if layer.properties.z > 0.5 {
                let weight = clamp(mask[k] * layer.properties.x, 0.0, 1.0);
                let flags = u32(layer.offset.z);
                if legacy {
                    // Colour is settled above.
                } else if (flags & 1u) != 0u {
                    color = mix(color, layer_dye(colors[k], layer.dye, layer.properties.y, 1.0) * layer_uniform.base_color.rgb, weight);
                } else {
                    color = mix(color, layer_dye(color, layer.dye, layer_uniform.base_color.a, 1.0), weight);
                }
                if (flags & 2u) != 0u {
                    let detail = safe_normalize(mix(vec3<f32>(0.0,0.0,1.0), layer_normal(normals[k], layer), weight), vec3<f32>(0.0,0.0,1.0));
                    normal = layer_rnm(normal, detail);
                }
                if (flags & 4u) != 0u { orm = mix(orm, responses[k], weight); }
            }
            continue;
        }
        var c = base.rgb;
        var n = vec3<f32>(0.0,0.0,1.0);
        var sp = base_sp;
        if layer.properties.z > 0.5 {
            // The game's dye: its alpha alone sets the strength; the layer
            // opacity byte belongs to normal and response, not to colour.
            c = layer_tint(colors[k], layer.dye);
            n = layer_normal(normals[k], layer);
            sp = responses[k];
        }
        if layer.properties.z > 0.5 {
            // The layer opacity byte, times the texel's alpha when flag bit 0 asks
            // for it, weighs the layer normal, which needs flag bit 1. The byte
            // alone weighs the response, which needs flag bit 2.
            let flags = u32(layer.offset.z);
            let opacity = clamp(layer.properties.x, 0.0, 1.0);
            let normal_opacity = opacity * select(1.0, alphas[k], (flags & 1u) != 0u) * select(0.0, 1.0, (flags & 2u) != 0u);
            n = safe_normalize(mix(vec3<f32>(0.0,0.0,1.0), n, normal_opacity), vec3<f32>(0.0,0.0,1.0));
            response_opacity[k] = opacity * select(0.0, 1.0, (flags & 4u) != 0u);
        }
        layer_colors[k] = c;
        layer_normals[k] = n;
        layer_responses[k] = sp;
        orm += sp * mask[k];
    }
    if layer_uniform.control.x == 1u {
        // The game draws one colour layer per pixel: the largest mask channel.
        // Its grime and scratches follow.
        var slot = 2u;
        if mask.r >= mask.g && mask.r >= mask.b { slot = 0u; } else if mask.g >= mask.b { slot = 1u; }
        let layer = layer_uniform.layers[slot];
        color = layer_colors[slot];
        normal = layer_normals[slot];
        // Roughness and metal start from layer R and move to G and B by their
        // mask channel times opacity, in that order.
        var response = layer_responses[0].gb * response_opacity.r;
        response = mix(response, layer_responses[1].gb, clamp(raw_mask.g * response_opacity.g, 0.0, 1.0));
        response = mix(response, layer_responses[2].gb, clamp(raw_mask.b * response_opacity.b, 0.0, 1.0));
        orm = vec3<f32>(orm.r, response);
        let weight = grime_weight(layer, detail_texel.g) * step(0.00001, mask[slot]);
        color = mix(color, layer_tint(grime_colors[slot], layer.grime_tint), weight);
        orm = vec3<f32>(orm.r, mix(orm.gb, grime_responses[slot].gb, weight));
        let soiled = safe_normalize(mix(vec3<f32>(0.0,0.0,1.0), grime_normal(grime_normals[slot], layer), weight), vec3<f32>(0.0,0.0,1.0));
        normal = select(normal, layer_rnm(safe_normalize(normal, vec3<f32>(0.0,0.0,1.0)), soiled), weight > 0.00001);
        // Scratches of the same layer, where the detail mask's red marks them:
        // roughness moves through its remaining range, metal by the plain step.
        let wear = detail_texel.r * step(0.5, layer.scratch.z);
        orm = vec3<f32>(orm.r, orm.g + (1.0 - orm.g) * layer.scratch.x * wear, orm.b + layer.scratch.y * wear);
        color = mix(color, srgb_to_linear(layer_overlay(vec3<f32>(detail_texel.r), layer.scratch_tint.rgb)), clamp(layer.scratch_tint.a * wear, 0.0, 1.0));
        // The game's overlay step, after grime and scratch on every pixel:
        // albedo = srgb_to_linear(overlay(base = O, blend = linear_to_srgb(albedo))),
        // O = _overlayColorTexture at the mesh UV (0.5 is neutral), its luma when the
        // drawn layer asks for it. A wrapper without the map reads the engine's
        // neutral grey there, which changes nothing: the bit is then not set.
        if (layer_uniform.control.w & 4u) != 0u {
            var over = textureSampleBias(overlay_color, material_sampler, uv, 0.0).rgb;
            if (layer_uniform.control.w & (16u << slot)) != 0u {
                over = vec3<f32>(dot(over, vec3<f32>(0.299, 0.587, 0.114)));
            }
            color = srgb_to_linear(layer_overlay(over, linear_to_srgb(clamp(color, vec3<f32>(0.0), vec3<f32>(1.0)))));
        }
        // The game's blend layer, after the overlay step and only with a non-zero
        // opacity byte: _detailDiffuseBlend dyed as a colour layer, laid over by
        // its own alpha times that byte.
        if layer_uniform.blend_offset.w > 0.5 {
            let inside = all(blend_uv >= vec2<f32>(0.005)) && all(blend_uv <= vec2<f32>(0.995));
            let amount = clamp(blend_texel.a * layer_uniform.blend_offset.z, 0.0, 1.0);
            color = mix(color, layer_tint(blend_texel.rgb, layer_uniform.blend_dye), select(0.0, amount, inside));
        }
    }
    out.color = color;
    out.normal = normal;
    if layer_uniform.control.x == 1u {
        out.color *= layer_uniform.base_color.rgb;
        out.normal = layer_rnm(base_normal, safe_normalize(vec3<f32>(normal.xy*0.7,normal.z), vec3<f32>(0.0,0.0,1.0)));
    }
    out.orm = vec3<f32>(clamp(orm.r,0.0,1.0),clamp(orm.g,0.045,1.0),clamp(orm.b,0.0,1.0));
    if layer_uniform.control.y != 0u { out.orm.x = 1.0; out.orm.z = 0.0; }
    if layer_uniform.control.z != 0u { out.orm.z = 0.0; }
    return out;
}
