struct LayerEntry {
    dye: vec4<f32>, affine: vec4<f32>, offset: vec4<f32>, properties: vec4<f32>,
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

fn layer_rnm(base: vec3<f32>, detail: vec3<f32>) -> vec3<f32> {
    let t = base + vec3<f32>(0.0,0.0,1.0);
    let u = detail * vec3<f32>(-1.0,-1.0,1.0);
    return safe_normalize(t * dot(t,u) / max(t.z,0.00001) - u, base);
}

fn evaluate_material_layers(uv: vec2<f32>, base: vec4<f32>) -> LayerSurface {
    var out = LayerSurface(base.rgb, vec3<f32>(0.0,0.0,1.0), vec3<f32>(1.0,0.66,0.0), vec3<f32>(0.0));
    if (material.flags & MATERIAL_GPU_LAYERS) == 0u { return out; }
    var mask = textureSampleBias(blend_mask, material_sampler, uv, 0.0).rgb;
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
    colors[0] = textureSampleBias(layer_r_color, material_sampler, ur, 0.0).rgb;
    colors[1] = textureSampleBias(layer_g_color, material_sampler, ug, 0.0).rgb;
    colors[2] = textureSampleBias(layer_b_color, material_sampler, ub, 0.0).rgb;
    normals[0] = textureSampleBias(layer_r_normal, material_sampler, ur, 0.0).rgb;
    normals[1] = textureSampleBias(layer_g_normal, material_sampler, ug, 0.0).rgb;
    normals[2] = textureSampleBias(layer_b_normal, material_sampler, ub, 0.0).rgb;
    responses[0] = textureSampleBias(layer_r_sp, material_sampler, ur, 0.0).rgb;
    responses[1] = textureSampleBias(layer_g_sp, material_sampler, ug, 0.0).rgb;
    responses[2] = textureSampleBias(layer_b_sp, material_sampler, ub, 0.0).rgb;
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
            c = layer_dye(colors[k], layer.dye, layer.properties.y, layer.properties.x);
            n = layer_normal(normals[k], layer);
            sp = responses[k];
        } else if layer_uniform.seeds[k].a > 0.0 {
            // Color-seed-only channels retain the base's local lightness.
            c = layer_dye(c, layer_uniform.seeds[k], layer_uniform.base_color.a, 1.0);
        }
        color += c * mask[k];
        normal += n * mask[k];
        orm += sp * mask[k];
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
