struct AmbientParameters {
    inverse_view_projection: mat4x4<f32>,
    viewport: vec4<f32>,
    radius: vec4<f32>,
};
@group(0) @binding(0) var scene_depth: DEPTH_TYPE;
@group(0) @binding(1) var<uniform> ambient: AmbientParameters;

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

@fragment fn fs_ambient(@builtin(position) pixel: vec4<f32>, @builtin(sample_index) sample_index: u32) -> @location(0) vec4<f32> {
    let p = vec2<i32>(pixel.xy);
    let depth = depth_at(p, sample_index);
    if depth >= 1.0 { return vec4(1.0); }
    let P = world_at(pixel.xy, depth);
    let left = depth_at(p + vec2(-1,0), sample_index);
    let right = depth_at(p + vec2(1,0), sample_index);
    let up = depth_at(p + vec2(0,-1), sample_index);
    let down = depth_at(p + vec2(0,1), sample_index);
    // Pick the nearer neighbour on each axis to avoid a normal across a silhouette.
    let dx = select(P-world_at(pixel.xy-vec2(1.0,0.0),left), world_at(pixel.xy+vec2(1.0,0.0),right)-P, abs(right-depth)<abs(left-depth));
    let dy = select(P-world_at(pixel.xy-vec2(0.0,1.0),up), world_at(pixel.xy+vec2(0.0,1.0),down)-P, abs(down-depth)<abs(up-depth));
    var N = cross(dx,dy);
    if dot(N,N) < 1e-20 { return vec4(1.0); }
    N = normalize(N);
    let toward_view = world_at(pixel.xy,0.0)-P;
    N = select(N,-N,dot(N,toward_view)<0.0);
    let r = max(ambient.radius.x*0.035,0.002);
    // World distance per screen pixel handles perspective and orthographic cameras.
    let pixel_world = length(world_at(pixel.xy+vec2(0.0,1.0),depth)-P);
    let px = clamp(r/max(pixel_world,1e-8),2.0,64.0);
    var occ = 0.0;
    for (var i = 0u; i < 12u; i++) {
        let a = f32(i)*2.39996323;
        let offset = vec2(cos(a),sin(a))*sqrt((f32(i)+0.5)/12.0)*px;
        let q = vec2<i32>(floor(pixel.xy+offset));
        let q_depth = depth_at(q,sample_index);
        if q_depth >= 1.0 { continue; }
        let Q = world_at(vec2<f32>(q)+vec2(0.5),q_depth);
        let v = Q-P;
        let d = length(v);
        if d > 0.01*r && d < 2.0*r {
            occ += clamp(dot(N,v/d)-0.08,0.0,1.0)*(1.0-clamp(d/(2.0*r),0.0,1.0));
        }
    }
    let ao = 1.0-clamp(occ/12.0*1.8,0.0,1.0)*0.6;
    return vec4(vec3(ao),1.0);
}
