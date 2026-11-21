struct ShadowUniform {
    light_view_projection: mat4x4<f32>,
    center_radius: vec4<f32>,
    enabled: vec4<u32>,
};
@group(3) @binding(0) var shadow_depth: texture_depth_2d_array;
@group(3) @binding(1) var shadow_compare: sampler_comparison;
@group(3) @binding(2) var<uniform> shadow_parameters: ShadowUniform;

fn shadow_sample_vogel(world: vec3<f32>, normal: vec3<f32>, spin: f32) -> f32 {
    if shadow_parameters.enabled.x == 0u { return 1.0; }
    let offset = normal * shadow_parameters.center_radius.w * 0.00045;
    let clip = shadow_parameters.light_view_projection * vec4<f32>(world + offset, 1.0);
    let point = clip.xyz / clip.w;
    let uv = vec2<f32>(point.x * 0.5 + 0.5, -point.y * 0.5 + 0.5);
    if any(uv < vec2<f32>(0.0)) || any(uv > vec2<f32>(1.0)) || point.z <= 0.0 || point.z >= 1.0 {
        return 1.0;
    }
    var visibility = 0.0;
    let radius = 2.6 / 4096.0;
    for (var i = 0u; i < 16u; i++) {
        let r = sqrt((f32(i) + 0.5) / 16.0) * radius;
        let a = spin + f32(i) * 2.39996323;
        visibility += textureSampleCompareLevel(
            shadow_depth,
            shadow_compare,
            uv + vec2<f32>(cos(a), sin(a)) * r,
            0,
            point.z - 0.00014,
        );
    }
    return visibility / 16.0;
}

fn shadow_visibility(world: vec3<f32>, normal: vec3<f32>) -> f32 {
    return shadow_sample_vogel(world, normal, 0.0);
}

fn contact_shadow_visibility(world: vec3<f32>, normal: vec3<f32>, pixel: vec2<f32>, light_dir: vec3<f32>) -> f32 {
    if shadow_parameters.enabled.x == 0u || shadow_parameters.enabled.z == 0u {
        return 1.0;
    }
    let ndotl = dot(normal, light_dir);
    if ndotl <= 0.04 {
        return 1.0;
    }
    let march_len = clamp(shadow_parameters.center_radius.w * 0.020, 0.0025, 0.050);
    let thickness = march_len * 0.34;
    let jitter = ign(pixel);
    let start_pos = world + normal * (march_len * 0.07);
    var occ = 0.0;
    for (var step = 0u; step < 8u; step++) {
        let t = (f32(step) + 0.3 + jitter * 0.7) / 8.0;
        let sample_world = start_pos + light_dir * (t * march_len);
        let clip = camera.view_projection * vec4<f32>(sample_world, 1.0);
        if abs(clip.w) < 1e-6 { continue; }
        let ndc = clip.xyz / clip.w;
        if ndc.z <= 0.0 || ndc.z >= 1.0 || abs(ndc.x) > 1.0 || abs(ndc.y) > 1.0 {
            continue;
        }
        let uv = vec2<f32>(ndc.x * 0.5 + 0.5, 0.5 - ndc.y * 0.5);
        let q = vec2<i32>(floor(ambient.viewport.xy + uv * ambient.viewport.zw));
        let scene_z = depth_at(q, 0u);
        if scene_z >= 1.0 || scene_z >= ndc.z { continue; }
        let hit_world = world_at(vec2<f32>(q) + vec2<f32>(0.5), scene_z);
        let delta = length(sample_world - hit_world);
        if delta > march_len * 0.035 && delta < thickness {
            let fade = (1.0 - t * 0.65) * clamp((ndotl - 0.04) * 4.5, 0.0, 1.0);
            occ = max(occ, fade * 0.72);
        }
    }
    return 1.0 - occ;
}

fn shadow_visibility_screen(world: vec3<f32>, normal: vec3<f32>, pixel: vec2<f32>, light_dir: vec3<f32>) -> f32 {
    let map_vis = shadow_sample_vogel(world, normal, ign(pixel) * 6.28318530718);
    let contact_vis = contact_shadow_visibility(world, normal, pixel, light_dir);
    return min(map_vis, contact_vis);
}

fn studio_ambient_visibility(pixel: vec2<f32>) -> f32 {
    if shadow_parameters.enabled.z == 0u { return 1.0; }
    let mapped = (pixel-ambient.screen_viewport.xy)*ambient.viewport.zw/ambient.screen_viewport.zw;
    return ambient_visibility(mapped,0u);
}

fn studio_view_direction(world: vec3<f32>) -> vec3<f32> {
    // Inverse VP's third column is the perspective camera's homogeneous origin.
    // Its w is zero for an orthographic camera, whose rays stay parallel.
    let origin = ambient.inverse_view_projection[2];
    if abs(origin.w) > 1e-6 {
        return safe_normalize(origin.xyz/origin.w-world,camera.view_direction.xyz);
    }
    return safe_normalize(camera.view_direction.xyz,vec3(0.0,0.0,-1.0));
}
