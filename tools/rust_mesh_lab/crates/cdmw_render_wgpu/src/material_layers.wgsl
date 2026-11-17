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

fn evaluate_material_layers(uv: vec2<f32>, sampled_base: vec4<f32>) -> LayerSurface {
    // control.w == 1: no base colour map, so the surface beneath the layers is
    // white rather than the grey placeholder bound for untextured geometry.
    let base = vec4<f32>(select(sampled_base.rgb, vec3<f32>(1.0), layer_uniform.control.w == 1u), sampled_base.a);
    var out = LayerSurface(sampled_base.rgb, vec3<f32>(0.0,0.0,1.0), vec3<f32>(1.0,0.66,0.0), vec3<f32>(0.0));
    if (material.flags & MATERIAL_GPU_LAYERS) == 0u { return out; }
    // Mode 1 picks one layer per pixel, so its mask is read as sharply as the base
    // maps are: at a mip two levels coarser the thin trims and inlays fall below
    // their neighbours and vanish from the picture.
    var mask = textureSampleBias(blend_mask, material_sampler, uv, select(0.0, MATERIAL_MIP_LOD_BIAS, layer_uniform.control.x == 1u)).rgb;
    let raw_mask = mask;
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
        var color = base.rgb * layer_uniform.base_color.rgb;
        let iris = textureSampleBias(layer_r_color, material_sampler, layer_uv(layer_uniform.layers[0], uv), 0.0);
        let pupil = textureSampleBias(layer_g_color, material_sampler, layer_uv(layer_uniform.layers[1], uv), 0.0);
        if layer_uniform.layers[0].properties.z > 0.5 {
            color = mix(color, iris.rgb * layer_uniform.base_color.rgb, clamp(iris.a * layer_uniform.layers[0].properties.x, 0.0, 1.0));
        }
        if layer_uniform.layers[1].properties.z > 0.5 {
            color = mix(color, pupil.rgb * layer_uniform.base_color.rgb, clamp(pupil.a * layer_uniform.layers[1].properties.x, 0.0, 1.0));
        }
        out.color = color;
        out.normal = base_normal;
        out.orm = vec3<f32>(base_sp.r, clamp(base_sp.g, 0.045, 1.0), 0.0);
        return out;
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
    if layer_uniform.control.x == 2u {
        color = base.rgb * layer_uniform.base_color.rgb;
        normal = base_normal;
        orm = base_sp;
    }
    for (var k = 0u; k < 3u; k += 1u) {
        let layer = layer_uniform.layers[k];
        if layer_uniform.control.x == 2u {
            if layer.properties.z > 0.5 {
                let weight = clamp(mask[k] * layer.properties.x, 0.0, 1.0);
                let flags = u32(layer.offset.z);
                if (flags & 1u) != 0u {
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
