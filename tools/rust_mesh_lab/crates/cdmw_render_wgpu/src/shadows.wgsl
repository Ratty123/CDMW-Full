struct ShadowUniform {
    light_view_projection: mat4x4<f32>,
    center_radius: vec4<f32>,
    enabled: vec4<u32>,
};
@group(3) @binding(0) var shadow_depth: texture_depth_2d;
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
                uv + vec2<f32>(f32(x), f32(y)) / 2048.0, point.z - 0.0002);
        }
    }
    return visibility / 25.0;
}
