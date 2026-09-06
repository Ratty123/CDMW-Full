// Dedicated particle bindings; kept in Rust source so build provenance includes the shader.
pub(super) const SHADER: &str = r#"struct CameraUniform {
    view_projection: mat4x4<f32>,
    view_mode: u32,
    output_is_srgb: u32,
    lighting_preset: u32,
    _padding_2: u32,
    wire_colour: vec4<f32>,
    point_colour: vec4<f32>,
    view_direction: vec4<f32>,
    camera_right: vec4<f32>,
    camera_up: vec4<f32>,
    scene_model: mat4x4<f32>,
    scene_normal: mat4x4<f32>,
};


@group(0) @binding(0) var<uniform> camera: CameraUniform;
@group(1) @binding(0) var effect_sprite: texture_2d<f32>;
@group(1) @binding(1) var effect_sampler: sampler;

fn linear_to_srgb(value: vec3<f32>) -> vec3<f32> {
    let bounded = max(value, vec3<f32>(0.0));
    let lower = bounded * 12.92;
    let upper = 1.055 * pow(bounded, vec3<f32>(1.0 / 2.4)) - vec3<f32>(0.055);
    return select(upper, lower, bounded <= vec3<f32>(0.0031308));
}

fn srgb_to_linear(value: vec3<f32>) -> vec3<f32> {
    let bounded = clamp(value, vec3<f32>(0.0), vec3<f32>(1.0));
    let lower = bounded / 12.92;
    let upper = pow((bounded + vec3<f32>(0.055)) / 1.055, vec3<f32>(2.4));
    return select(upper, lower, bounded <= vec3<f32>(0.04045));
}

fn linear_to_srgb_scalar(value: f32) -> f32 {
    let bounded = max(value, 0.0);
    return select(1.055 * pow(bounded, 1.0 / 2.4) - 0.055, bounded * 12.92, bounded <= 0.0031308);
}

fn srgb_to_linear_scalar(value: f32) -> f32 {
    let bounded = clamp(value, 0.0, 1.0);
    return select(pow((bounded + 0.055) / 1.055, 2.4), bounded / 12.92, bounded <= 0.04045);
}

fn present(linear_rgb: vec3<f32>, alpha: f32) -> vec4<f32> {
    let bounded = max(linear_rgb, vec3<f32>(0.0));
    let rgb = select(linear_to_srgb(bounded), bounded, camera.output_is_srgb != 0u);
    return vec4<f32>(clamp(rgb, vec3<f32>(0.0), vec3<f32>(1.0)), alpha);
}

fn present_srgb(display_rgb: vec3<f32>, alpha: f32) -> vec4<f32> {
    return present(srgb_to_linear(display_rgb), alpha);
}

fn aces_tone_map(value: f32) -> f32 {
    let x = max(value, 0.0);
    return clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0);
}

struct EffectParticleOut {
    @builtin(position) position: vec4<f32>,
    @location(0) uv: vec2<f32>,
    @location(1) colour: vec4<f32>,
    @location(2) @interpolate(flat) uv_rect: vec4<f32>,
    @location(3) @interpolate(flat) sprite_options: vec3<f32>,
};

@vertex
fn vs_effect_particle(
    @location(0) corner: vec2<f32>,
    @location(1) uv: vec2<f32>,
    @location(2) center: vec3<f32>,
    @location(3) axis_right: vec3<f32>,
    @location(4) axis_up: vec3<f32>,
    @location(5) colour: vec4<f32>,
    @location(6) uv_rect: vec4<f32>,
    @location(7) sprite_options: vec4<f32>,
    @location(8) third_uv: vec2<f32>,
) -> EffectParticleOut {
    var out: EffectParticleOut;
    var world = center + axis_right * corner.x + axis_up * corner.y;
    out.position = camera.view_projection * vec4<f32>(world, 1.0);
    out.uv = uv;
    out.colour = colour;
    out.uv_rect = uv_rect;
    out.sprite_options = sprite_options.xyw;
    if sprite_options.z > 0.5 {
        // Quad vertices 0,1,2 become triangle vertices 0,1,2. The fourth
        // vertex coincides with vertex 2, so the second triangle is degenerate.
        let weights = vec2<f32>(uv.x * uv.y, 1.0 - uv.y);
        world = center + axis_right * weights.x + axis_up * weights.y;
        out.position = camera.view_projection * vec4<f32>(world, 1.0);
        out.uv = uv_rect.xy * (1.0 - weights.x - weights.y) + uv_rect.zw * weights.x + third_uv * weights.y;
        out.uv_rect = vec4<f32>(0.0,0.0,1.0,1.0);
        out.sprite_options.y = 0.0;
    }
    return out;
}

@fragment
fn fs_effect_particle(input: EffectParticleOut) -> @location(0) vec4<f32> {
    let cell = input.uv_rect.zw;
    let origin = input.uv_rect.xy;
    // Stay inside a flipbook cell: filtering must not pull in adjacent frames.
    let inset = min(0.5 / vec2<f32>(textureDimensions(effect_sprite)), cell * 0.49);
    let local_uv = clamp(input.uv * cell, inset, cell - inset);
    let columns = max(1.0, round(1.0 / cell.x));
    let rows = max(1.0, round(1.0 / cell.y));
    let frame = round(origin.y / cell.y) * columns + round(origin.x / cell.x);
    let next_frame = min(frame + 1.0, columns * rows - 1.0);
    let next_origin = vec2<f32>(next_frame % columns, floor(next_frame / columns)) * cell;
    var sprite = mix(textureSample(effect_sprite, effect_sampler, origin + local_uv),
        textureSample(effect_sprite, effect_sampler, next_origin + local_uv), input.sprite_options.y);
    if input.sprite_options.x >= 0.0 {
        // Only colour views applied an sRGB conversion. Scalar BC4/R8 masks
        // already contain linear coverage, as does the alpha channel.
        var masks = sprite;
        if input.sprite_options.z < 0.5 {
            masks = vec4<f32>(linear_to_srgb(sprite.rgb), sprite.a);
        }
        sprite = vec4<f32>(1.0, 1.0, 1.0, masks[u32(input.sprite_options.x)]);
    }
    let rgb = max(sprite.rgb * input.colour.rgb, vec3<f32>(0.0));
    let mapped = vec3<f32>(aces_tone_map(rgb.r), aces_tone_map(rgb.g), aces_tone_map(rgb.b));
    return present(mapped, clamp(sprite.a * input.colour.a, 0.0, 1.0));
}

"#;
