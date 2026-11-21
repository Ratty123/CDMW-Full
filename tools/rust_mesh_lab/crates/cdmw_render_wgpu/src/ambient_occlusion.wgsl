struct AmbientParameters {
    inverse_view_projection: mat4x4<f32>,
    viewport: vec4<f32>,
    radius: vec4<f32>,
    screen_viewport: vec4<f32>,
};
// AMBIENT_BINDINGS

@vertex fn vs_ambient(@builtin(vertex_index) index: u32) -> @builtin(position) vec4<f32> {
    let p = array<vec2<f32>, 3>(vec2(-1.0,-1.0), vec2(3.0,-1.0), vec2(-1.0,3.0));
    return vec4(p[index], 0.0, 1.0);
}

fn depth_at(p: vec2<i32>, sample_index: u32) -> f32 {
    let low = vec2<i32>(ambient.viewport.xy);
    let high = vec2<i32>(ambient.viewport.xy + ambient.viewport.zw) - vec2(1);
    if any(p < low) || any(p > high) { return 1.0; }
    return LOAD_DEPTH;
}

fn world_at(p: vec2<f32>, depth: f32) -> vec3<f32> {
    let uv = (p - ambient.viewport.xy) / ambient.viewport.zw;
    let h = ambient.inverse_view_projection * vec4(uv.x*2.0-1.0, 1.0-uv.y*2.0, depth, 1.0);
    return h.xyz / h.w;
}

fn ign(pixel: vec2<f32>) -> f32 {
    return fract(52.9829189 * fract(dot(pixel, vec2<f32>(0.06711056, 0.00583715))));
}

fn ambient_visibility(pixel: vec2<f32>, sample_index: u32) -> f32 {
    let p = vec2<i32>(pixel);
    let depth = depth_at(p, sample_index);
    if depth >= 1.0 { return 1.0; }
    let P = world_at(pixel, depth);
    let left = depth_at(p + vec2(-1,0), sample_index);
    let right = depth_at(p + vec2(1,0), sample_index);
    let up = depth_at(p + vec2(0,-1), sample_index);
    let down = depth_at(p + vec2(0,1), sample_index);
    // Pick the nearer neighbour on each axis to avoid a normal across a silhouette.
    let dx = select(P-world_at(pixel-vec2(1.0,0.0),left), world_at(pixel+vec2(1.0,0.0),right)-P, abs(right-depth)<abs(left-depth));
    let dy = select(P-world_at(pixel-vec2(0.0,1.0),up), world_at(pixel+vec2(0.0,1.0),down)-P, abs(down-depth)<abs(up-depth));
    var N = cross(dx,dy);
    if dot(N,N) < 1e-20 { return 1.0; }
    N = normalize(N);
    let toward_view = world_at(pixel,0.0)-P;
    N = select(N,-N,dot(N,toward_view)<0.0);
    let r_near = max(ambient.radius.x * 0.013, 0.0012);
    let r_far = max(ambient.radius.x * 0.046, 0.0038);
    // World distance per screen pixel handles perspective and orthographic cameras.
    let pixel_world = length(world_at(pixel+vec2(0.0,1.0),depth)-P);
    let px_near = clamp(r_near / max(pixel_world, 1e-8), 2.0, 32.0);
    let px_far = clamp(r_far / max(pixel_world, 1e-8), 4.0, 84.0);
    let spin = ign(pixel) * 6.28318530718;
    var occ = 0.0;
    for (var i = 0u; i < 24u; i++) {
        let is_near = i < 10u;
        let idx = select(f32(i - 10u), f32(i), is_near);
        let ring_count = select(14.0, 10.0, is_near);
        let r = select(r_far, r_near, is_near);
        let px = select(px_far, px_near, is_near);
        let a = spin + f32(i) * 2.39996323;
        let frac = sqrt((idx + 0.5) / ring_count);
        let offset = vec2(cos(a), sin(a)) * frac * px;
        let q = vec2<i32>(floor(pixel + offset));
        let q_depth = depth_at(q, sample_index);
        if q_depth >= 1.0 { continue; }
        let Q = world_at(vec2<f32>(q) + vec2(0.5), q_depth);
        let v = Q - P;
        let d = length(v);
        if d > 0.006 * r && d < 2.2 * r {
            let falloff = 1.0 - clamp(d / (2.2 * r), 0.0, 1.0);
            let horizon = clamp(dot(N, v / d) - 0.10, 0.0, 1.0);
            occ += horizon * falloff * falloff * select(0.85, 1.15, is_near);
        }
    }
    let ao = 1.0 - clamp(occ / 24.0 * 2.35, 0.0, 1.0) * 0.65;
    return clamp(ao, 0.32, 1.0);
}
