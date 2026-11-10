struct ShadowUniform {
    light_view_projection: mat4x4<f32>,
    center_radius: vec4<f32>,
    enabled: vec4<u32>,
};
@group(3) @binding(0) var shadow_depth: texture_depth_2d_array;
@group(3) @binding(1) var shadow_compare: sampler_comparison;
@group(3) @binding(2) var<uniform> shadow_parameters: ShadowUniform;

fn shadow_visibility(world: vec3<f32>, normal: vec3<f32>) -> f32 {
    if shadow_parameters.enabled.x == 0u { return 1.0; }
    let offset = normal * shadow_parameters.center_radius.w * 0.0004;
    let clip = shadow_parameters.light_view_projection * vec4<f32>(world + offset, 1.0);
    let point = clip.xyz / clip.w;
    let uv = vec2<f32>(point.x * 0.5 + 0.5, -point.y * 0.5 + 0.5);
    if any(uv < vec2<f32>(0.0)) || any(uv > vec2<f32>(1.0)) || point.z <= 0.0 || point.z >= 1.0 {
        return 1.0;
    }
    var visibility = 0.0;
    for (var y = -2; y <= 2; y += 1) {
        for (var x = -2; x <= 2; x += 1) {
            visibility += textureSampleCompareLevel(shadow_depth, shadow_compare,
                uv + vec2<f32>(f32(x), f32(y)) / 2048.0, 0, point.z - 0.0002);
        }
    }
    return visibility / 25.0;
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
