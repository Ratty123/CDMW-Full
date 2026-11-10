struct View {
    viewport: vec2<f32>,
    image_size: vec2<f32>,
    pan: vec2<f32>,
    zoom: f32,
    mip: u32,
    channel: u32,
    signed: u32,
    reconstruct_z: u32,
    single_channel: u32,
};
@group(0) @binding(0) var source: texture_2d<f32>;
@group(0) @binding(1) var source_sampler: sampler;
@group(0) @binding(2) var<uniform> view: View;

@vertex fn vs(@builtin(vertex_index) index: u32) -> @builtin(position) vec4<f32> {
    let points = array<vec2<f32>, 3>(vec2(-1.0, -1.0), vec2(3.0, -1.0), vec2(-1.0, 3.0));
    return vec4(points[index], 0.0, 1.0);
}

@fragment fn fs(@builtin(position) position: vec4<f32>) -> @location(0) vec4<f32> {
    let size = max(floor(view.image_size / exp2(f32(view.mip))), vec2(1.0));
    let uv = (position.xy - view.viewport * 0.5 - view.pan) / (size * view.zoom) + 0.5;
    if any(uv < vec2(0.0)) || any(uv >= vec2(1.0)) { return vec4(0.10, 0.11, 0.13, 1.0); }
    var c = textureSampleLevel(source, source_sampler, uv, f32(view.mip));
    if view.signed != 0u { c = vec4(c.rgb * 0.5 + 0.5, c.a); }
    if view.single_channel != 0u && view.channel == 0u { c = vec4(c.rrr, c.a); }
    if view.reconstruct_z != 0u {
        let xy = c.xy * 2.0 - 1.0;
        c.b = sqrt(max(0.0, 1.0 - dot(xy, xy))) * 0.5 + 0.5;
    }
    if view.channel != 0u {
        // The source view and target are linear UNORM: channel values are never gamma transformed.
        return vec4(vec3(c[view.channel - 1u]), 1.0);
    }
    let checker = select(0.25, 0.35, (u32(position.x / 12.0) + u32(position.y / 12.0)) % 2u == 0u);
    return vec4(mix(vec3(checker), c.rgb, clamp(c.a, 0.0, 1.0)), 1.0);
}
