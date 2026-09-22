// Shader source stays in .rs so the helper's existing provenance covers it.
pub(super) const SHADER: &str = r#"
struct LightningMaterial {
    parameters: array<vec4<f32>, 8>,
    curves: array<array<f32, 128>, 10>,
};
struct MeshParticle {
    transform: mat4x4<f32>,
    colour: vec4<f32>,
    scale_age: vec4<f32>,
    seed: vec4<u32>,
    parent_scale: vec4<f32>,
    parent_origin: vec4<f32>,
};
struct LightningView {
    eye_height: vec4<f32>,
    fov_padding: vec4<f32>,
};
@group(3) @binding(0) var<storage, read> lightning: LightningMaterial;
@group(3) @binding(1) var<storage, read> mesh_particles: array<MeshParticle>;
@group(3) @binding(2) var<uniform> lightning_view: LightningView;

fn lightning_curve(index: u32, progress: f32) -> f32 {
    let at = clamp(progress, 0.0, 1.0) * 127.0;
    let low = u32(floor(at));
    return mix(lightning.curves[index][low], lightning.curves[index][min(low + 1u, 127u)], fract(at));
}
fn lightning_phase(age: f32, speed: f32) -> f32 {
    return select(trunc((age - 0.01) * speed), age * speed, lightning.parameters[5].w > 0.5);
}
fn lightning_normalize(v: vec3<f32>) -> vec3<f32> {
    let length_squared = dot(v,v);
    if length_squared > 1e-30 { return v * inverseSqrt(length_squared); }
    return vec3<f32>(0.0);
}
fn lightning_mod(value: f32, divisor: f32) -> f32 {
    return value - floor(value / divisor) * divisor;
}
fn lightning_mod3(value: vec3<f32>, divisor: f32) -> vec3<f32> {
    return value - floor(value / divisor) * divisor;
}
fn lightning_permute_bcc(v: f32) -> f32 { return v * (v * 34.0 + 133.0); }
fn lightning_bcc_gradient(hash: f32) -> vec3<f32> {
    let cube = lightning_mod3(floor(vec3<f32>(hash) / vec3<f32>(1.0,2.0,4.0)),2.0) * 2.0 - 1.0;
    let axis = u32(hash / 16.0);
    let cuboct = cube * select(vec3<f32>(1.0), vec3<f32>(0.0),
        vec3<u32>(0u,1u,2u) == vec3<u32>(axis));
    let kind = lightning_mod(floor(hash / 8.0), 2.0);
    let rhomb = (1.0 - kind) * cube + kind * (cuboct + cross(cube, cuboct));
    return (cuboct * 1.2247449 + rhomb) * (32.802013 - 1.4085984 * kind);
}
fn lightning_bcc_noise(input: vec3<f32>) -> vec3<f32> {
    var result = vec3<f32>(0.0);
    for (var lattice = 0u; lattice < 2u; lattice++) {
        let point = input + f32(lattice) * 144.5;
        let nearest = round(point);
        let delta = point - nearest;
        let score = abs(delta);
        let greater = score > max(score.yzx, score.zxy);
        let signs = select(vec3<f32>(1.0), vec3<f32>(-1.0), delta < vec3<f32>(0.0));
        let side = select(vec3<f32>(0.0), signs, greater);
        for (var corner = 0u; corner < 2u; corner++) {
            let vertex = nearest + f32(corner) * side;
            let d = point - vertex;
            let h0 = lightning_permute_bcc(lightning_mod(vertex.x, 289.0));
            let h1 = lightning_permute_bcc(lightning_mod(h0 + vertex.y, 289.0));
            let hash = lightning_mod(lightning_permute_bcc(lightning_mod(h1 + vertex.z, 289.0)), 48.0);
            let gradient = lightning_bcc_gradient(hash);
            let weight = max(0.5 - dot(d,d), 0.0);
            let square = weight * weight;
            result += gradient * (square * square) - d * (8.0 * square * weight * dot(d,gradient));
        }
    }
    return result;
}
fn lightning_permute_simplex(v: f32) -> f32 { return lightning_mod(v * (v * 34.0 + 1.0), 289.0); }
fn lightning_simplex_noise(point: vec3<f32>) -> vec3<f32> {
    let lattice = floor(point + dot(point, vec3<f32>(1.0 / 3.0)));
    let delta = point - lattice + dot(lattice, vec3<f32>(1.0 / 6.0));
    let order = select(vec3<f32>(0.0), vec3<f32>(1.0), delta >= delta.yzx);
    let previous = (1.0 - order).zxy;
    let first = min(order, previous);
    let second = max(order, previous);
    let cell = lightning_mod3(lattice, 289.0);
    let steps = array<vec3<f32>, 4>(vec3<f32>(0.0), first, second, vec3<f32>(1.0));
    let deltas = array<vec3<f32>, 4>(delta, delta - first + 1.0 / 6.0, delta - second + 1.0 / 3.0, delta - 0.5);
    var result = vec3<f32>(0.0);
    for (var corner = 0u; corner < 4u; corner++) {
        let step = steps[corner];
        let d = deltas[corner];
        let h0 = lightning_permute_simplex(cell.z + step.z);
        let h1 = lightning_permute_simplex(h0 + cell.y + step.y);
        let hash = lightning_mod(lightning_permute_simplex(h1 + cell.x + step.x), 49.0);
        let grid_x = floor(hash / 7.0);
        let grid_y = floor(hash - grid_x * 7.0);
        var x = grid_x * (2.0 / 7.0) - 0.9285714;
        var y = grid_y * (2.0 / 7.0) - 0.9285714;
        let z = 1.0 - abs(x) - abs(y);
        if z <= 0.0 { x -= floor(x) * 2.0 + 1.0; y -= floor(y) * 2.0 + 1.0; }
        let raw = vec3<f32>(x,y,z);
        let gradient = raw * (1.7928429 - 0.85373473 * dot(raw,raw));
        let weight = max(0.6 - dot(d,d), 0.0);
        let square = weight * weight;
        result += gradient * (square * square) - d * (6.0 * square * weight * dot(d,gradient));
    }
    return result;
}
fn lightning_large_noise(point: vec3<f32>) -> vec3<f32> {
    var result = vec3<f32>(0.0);
    var frequency = 1.0;
    var amplitude = -42.0;
    for (var octave = 0u; octave < 3u; octave++) {
        result += lightning_simplex_noise((point + f32(3u - octave)) * frequency) * amplitude;
        frequency *= 2.0; amplitude *= -0.5;
    }
    return result / 3.0;
}

fn lightning_deform(position: vec3<f32>, source_normal: vec3<f32>, uv: vec2<f32>, controls: vec3<f32>, particle: MeshParticle) -> vec3<f32> {
    let scale = particle.scale_age.xyz;
    let age = particle.scale_age.w;
    let seed = particle.seed.x;
    let normal = lightning_normalize(source_normal / scale);
    let pivot = position + normal * 0.001;
    let ratio = 1.0 - uv.x;
    let first = seed * 54787328u + 221680323u;
    let second = first * 214013u + 2531011u;
    let bits = ((second & 0xffff0000u) | (first >> 16u)) % 32767u;
    let random = f32(bits) / 32766.0;
    let random_offset = f32(bits) * 0.03051944;
    let is_main = controls.y >= 0.9;
    let perimeter = pow(max(controls.z, 0.0), lightning.parameters[0].w);
    var main_width = mix(lightning.parameters[0].x, lightning.parameters[0].y, random)
        * lightning_curve(0u,ratio) * lightning.parameters[0].z * lightning_curve(1u,age) * perimeter;
    var sub_width = mix(lightning.parameters[1].x, lightning.parameters[1].y, random)
        * lightning_curve(2u,ratio) * lightning.parameters[1].z * lightning_curve(3u,age) * perimeter;
    if lightning.parameters[6].w > 0.5 {
        let distance = length(particle.parent_origin.xyz - lightning_view.eye_height.xyz);
        let amount = clamp((distance - lightning.parameters[6].x) / max(lightning.parameters[6].y - lightning.parameters[6].x, 1e-6), 0.0, 1.0);
        let multiple = 1.0 + (lightning.parameters[6].z - 1.0) * amount;
        main_width *= multiple; sub_width *= multiple;
    }
    sub_width = min(max(sub_width, lightning.parameters[7].x), lightning.parameters[7].y);
    let world_position = (particle.transform * vec4<f32>(position,1.0)).xyz;
    let distance = length(world_position - lightning_view.eye_height.xyz);
    let scale_length = length(scale);
    let minimum = (0.0042 + 0.0378 * clamp(distance * 0.01, 0.0, 1.0)) / max(2.0 * scale_length, 1.0);
    let width = max(select(sub_width, main_width, is_main), minimum);
    var expansion = -normal * width;
    let parent_scale = particle.parent_scale.xyz;
    if max(max(parent_scale.x,parent_scale.y),parent_scale.z) > 1.0 {
        expansion /= max(parent_scale,vec3<f32>(1e-8));
    }
    let v_width = 1.0 - clamp(abs(uv.y - 0.5) * 2.0, 0.0, 1.0);
    let pixel_width = tan(min(lightning_view.fov_padding.x, 1.2217305)) * distance / max(lightning_view.eye_height.w,1.0)
        * (0.5 + 0.5 * v_width) / max(scale_length, 1e-8);
    expansion = lightning_normalize(expansion) * max(length(expansion),pixel_width);
    let deform = lightning.parameters[4];
    let angle = deform.z * uv.x + f32(seed) + lightning.parameters[5].z + lightning_phase(age,deform.w);
    var amplitude = deform.x * deform.y * lightning_curve(8u,ratio) * lightning_curve(9u,age);
    if !is_main { amplitude *= lightning.parameters[1].w + (1.0 - lightning.parameters[1].w) * (1.0 - uv.y); }
    let bend = vec3<f32>(sin(angle),0.0,cos(angle)) * amplitude;
    let small = lightning.parameters[2];
    let big = lightning.parameters[3];
    let small_point = pivot * small.z + vec3<f32>(0.0,lightning.parameters[5].x + random_offset + lightning_phase(age,small.w),0.0);
    let big_point = pivot * big.z + vec3<f32>(23.0,43.0 + random_offset + lightning.parameters[5].y + lightning_phase(age,big.w),11.0);
    return position + expansion + bend
        + lightning_bcc_noise(small_point) * (small.x * small.y * lightning_curve(4u,ratio) * lightning_curve(5u,age))
        + lightning_large_noise(big_point) * (big.x * big.y * lightning_curve(6u,ratio) * lightning_curve(7u,age));
}

@vertex
fn vs_effect_mesh(@location(0) position: vec3<f32>, @location(1) normal: vec3<f32>,
    @location(2) uv: vec2<f32>, @location(3) controls: vec4<f32>,
    @builtin(instance_index) instance: u32) -> EffectParticleOut {
    let particle = mesh_particles[instance];
    let local = lightning_deform(position,normal,uv,controls.xyz,particle);
    let world = (particle.transform * vec4<f32>(local,1.0)).xyz;
    var out: EffectParticleOut;
    out.position = camera.view_projection * vec4<f32>(world,1.0);
    out.world = world; out.uv = uv; out.colour = particle.colour;
    out.uv_rect = vec4<f32>(0.0,0.0,1.0,1.0);
    out.sprite_options = vec3<f32>(-2.0,0.0,1.0);
    out.soft_range = max(min(particle.scale_age.x,particle.scale_age.y) * 0.25,0.0001);
    return out;
}
"#;
