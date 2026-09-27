//! Synthetic pixels for recovered material expressions, without game resources.
use super::*;

pub(super) fn verify(
    device: &wgpu::Device, queue: &wgpu::Queue, format: wgpu::TextureFormat,
    pipelines: &Pipelines, camera_binding: &wgpu::BindGroup,
    camera: &mut CameraUniform, camera_buffer: &wgpu::Buffer, default_binding: &wgpu::BindGroup,
    make_binding: impl Fn(&[u8], &[u8], MaterialPreviewFactors) -> Result<GpuMaterialBinding, RenderError>,
) -> Result<(), RenderError> {
    let saved = *camera;
    let mut mask = cdmw_texture::synthetic::rgba8_checker_dds();
    for pixel in mask[148..].chunks_exact_mut(4) { pixel.copy_from_slice(&[64, 204, 204, 255]); }
    let mut base = mask.clone();
    let width = u32::from_le_bytes(base[16..20].try_into().unwrap()) as usize;
    for (i, pixel) in base[148..].chunks_exact_mut(4).enumerate() {
        pixel.copy_from_slice(if i % width < width / 2 { &[220, 40, 20, 255] } else { &[20, 220, 40, 255] });
    }
    let mut cases: Vec<(&str, [f32; 32], [f32; 3], f32)> = Vec::new();
    let mut wing = [0.0; 32]; wing[0] = 1.0; wing[4] = 0.5;
    cases.push(("wing cut", wing, [1.0, 1.0, 1.0], 0.0));
    wing[4] = 2.0; cases.push(("wing visible", wing, [1.0, 1.0, 1.0], 0.0));
    wing[4] = 0.5; wing[5] = 1.0; cases.push(("wing inverse", wing, [1.0, 1.0, 1.0], 0.0));
    let mut torn = [0.0; 32]; torn[0] = 2.0; torn[5] = 1.0; torn[6] = 1.0;
    cases.push(("torn length", torn, [0.2, 1.0, 1.0], 0.0));
    cases.push(("torn white", torn, [1.0, 1.0, 1.0], 0.0));
    cases.push(("torn unknown", torn, [0.2, 0.2, 0.0], 0.0));
    torn[4] = 0.4; cases.push(("torn cross", torn, [1.0, 0.0, 1.0], 0.0));
    let mut hair = [0.0; 32]; hair[0] = 3.0; hair[4] = 1.0; hair[5] = 1.0; hair[6] = 1.0; hair[8] = 0.25;
    cases.push(("hair first", hair, [1.0, 0.0, 1.0], 0.0));
    cases.push(("hair second", hair, [1.0, 0.0, 1.0], std::f32::consts::PI));
    cases.push(("hair white first", hair, [1.0, 1.0, 1.0], 0.0));
    cases.push(("hair white second", hair, [1.0, 1.0, 1.0], std::f32::consts::PI));
    let mut poster = [0.0; 32]; poster[0] = 5.0; poster[5] = 0.3; poster[6] = 1.0; poster[9] = 1.0;
    cases.push(("poster off", poster, [1.0, 1.0, 1.0], 0.0));
    poster[8] = 0.125; cases.push(("poster sweep ratio zero", poster, [1.0, 1.0, 1.0], 0.0));
    poster[8] = 1.0; cases.push(("poster end", poster, [1.0, 1.0, 1.0], 0.0));
    let mut dissolve = [0.0; 32]; dissolve[0] = 6.0; dissolve[5] = 2.0; dissolve[6] = 1.0; dissolve[7] = 1.0;
    cases.push(("object retained", dissolve, [1.0, 1.0, 1.0], 0.0));
    dissolve[4] = 1.0; cases.push(("object cut", dissolve, [1.0, 1.0, 1.0], 0.0));
    dissolve[2] = 1.0; cases.push(("object inverse", dissolve, [1.0, 1.0, 1.0], 0.0));
    dissolve[2] = 0.0; dissolve[7] = 0.0; cases.push(("object player unavailable", dissolve, [1.0, 1.0, 1.0], 0.0));
    let mut anisotropy = [0.0; 32]; anisotropy[0] = 4.0; anisotropy[5] = 0.5; anisotropy[6] = 128.0;
    cases.push(("detail off", anisotropy, [1.0, 1.0, 1.0], 0.0));
    anisotropy[4] = 1.0; cases.push(("detail on", anisotropy, [1.0, 1.0, 1.0], 0.0));
    let mut eye = [0.0; 32]; eye[0] = 7.0; eye[7] = 0.4;
    cases.push(("eye clear", eye, [1.0, 1.0, 1.0], 0.0));
    eye[4] = 0.25; cases.push(("eye half", eye, [1.0, 1.0, 1.0], 0.0));
    eye[4] = 128.0 / 255.0; cases.push(("eye opaque", eye, [1.0, 1.0, 1.0], 0.0));
    eye[4] = 1.0; cases.push(("eye saturated", eye, [1.0, 1.0, 1.0], 0.0));
    eye[4] = 0.5; eye[6] = 0.5; cases.push(("eye red mask", eye, [1.0, 1.0, 1.0], 0.0));
    eye[4] = 0.0; eye[5] = 1.0; cases.push(("eye shine only", eye, [1.0, 1.0, 1.0], 0.0));
    eye[7] = 0.95; eye[8] = 1.0; cases.push(("eye rough metal", eye, [1.0, 1.0, 1.0], 0.0));
    eye[4] = 0.5; eye[5] = -1.0; eye[6] = -1.0;
    cases.push(("eye inherited maps", eye, [1.0, 1.0, 1.0], 0.0));
    eye[5] = 64.0 / 255.0; eye[6] = 64.0 / 255.0;
    cases.push(("eye explicit maps", eye, [1.0, 1.0, 1.0], 0.0));
    let mut cutout = [0.0; 32]; cutout[0] = 1.0; cutout[4] = 0.5; cutout[30] = 1.0;
    for name in ["painted cutout left", "painted cutout right", "painted cutout below", "painted cutout above"] {
        cases.push((name, cutout, [1.0; 3], 0.0));
    }
    let mut painted_eye = [0.0; 32]; painted_eye[0] = 7.0; painted_eye[4] = 127.0 / 255.0;
    painted_eye[6] = -1.0; painted_eye[7] = 0.4;
    for name in ["painted colour left", "painted colour right"] {
        cases.push((name, painted_eye, [1.0; 3], 0.0));
    }
    painted_eye[4] = 0.0; painted_eye[5] = -1.0; painted_eye[6] = 0.0;
    for name in ["painted surface left", "painted surface right"] {
        cases.push((name, painted_eye, [1.0; 3], 0.0));
    }
    let mut samples = BTreeMap::new();
    for (name, controls, vertex_mask, time) in cases {
        let mut active_mask = mask.clone();
        if name.starts_with("painted") {
            for (index, pixel) in active_mask[148..].chunks_exact_mut(4).enumerate() {
                let right = index % width >= width / 2;
                let blue = if name.ends_with("below") { 127 } else if name.ends_with("above") { 128 } else if right { 255 } else { 0 };
                let red = if name.starts_with("painted cutout") { 255 } else if right { 254 } else { 0 };
                pixel.copy_from_slice(&[red, 128, blue, 255]);
            }
        }
        let uv = if name.ends_with("right") { [0.75, 0.25] } else if name.starts_with("painted") { [0.25, 0.25] } else { [0.125, 0.125] };
        let snapshot = DrawSnapshot {
            mesh_identity: u64::MAX - 32, draw_revision: 1, topology_generation: 1,
            positions: vec![[-0.8, -0.8, 0.5], [0.8, -0.8, 0.5], [0.8, 0.8, 0.5], [-0.8, 0.8, 0.5]],
            normals: vec![[0.0, 0.0, -1.0]; 4], uvs: vec![uv; 4],
            shader_masks: vec![vertex_mask; 4], indices: vec![0, 1, 2, 0, 2, 3],
            triangle_materials: vec![0; 2], selected_vertices: Vec::new(), fingerprint: "shader-controls-proof".to_owned(),
        };
        let mesh = GpuMeshBuffers::upload(device, &snapshot)?;
        let eye_cover = controls[0] == 7.0;
        let factors = MaterialPreviewFactors { shader_controls: Some(controls), roughness: Some(0.4), specular: Some(0.5),
            // Conversion from glass/cutout must still use EyeCover coverage.
            translucency: eye_cover.then_some([0.8, 0.8]), alpha_cutoff: eye_cover.then_some(0.9),
            ..Default::default() };
        let binding = make_binding(&active_mask, &base, factors)?;
        if eye_cover && (!binding.alpha_blend || binding.translucent) {
            return Err(RenderError::Device("EyeCover did not select independent alpha blending".to_owned()));
        }
        let bindings = BTreeMap::from([(0, binding)]);
        camera.material_time = time;
        camera.scene_model = Mat4::IDENTITY.to_cols_array_2d();
        let (buffer, width, height) = render_headless_readback_at(device, queue, format, &mesh,
            default_binding, &bindings, camera_binding, pipelines, camera, camera_buffer,
            ViewMode::TexturedSolid, 64, 64, Mat4::IDENTITY, None, false, None);
        let pixels = read_headless_pixels(device, &buffer, width, height)?;
        let center = ((height / 2 * width + width / 2) * 4) as usize;
        samples.insert(name, <[u8; 4]>::try_from(&pixels[center..center + 4]).unwrap());
    }
    let close = |a, b| samples[a].iter().zip(samples[b]).all(|(x, y)| x.abs_diff(y) <= 2);
    if close("wing cut", "wing visible") || !close("wing inverse", "wing visible")
        || !close("wing cut", "torn length") || !close("wing cut", "torn cross")
        || !close("torn white", "torn unknown") || close("torn white", "torn length")
        || close("hair first", "hair second") || !close("hair white first", "hair white second")
        || close("poster off", "poster sweep ratio zero") || !close("poster off", "poster end")
        || close("object cut", "object retained") || !close("object inverse", "object retained")
        || !close("object player unavailable", "object retained") || close("detail off", "detail on")
        || !close("eye clear", "wing cut") || close("eye clear", "eye half")
        || close("eye half", "eye opaque") || !close("eye opaque", "eye saturated")
        || !close("eye half", "eye red mask") || close("eye clear", "eye shine only")
        || close("eye shine only", "eye rough metal") || !close("eye inherited maps", "eye explicit maps")
        || close("painted cutout left", "painted cutout right")
        || !close("painted cutout right", "wing cut") || !close("painted cutout above", "wing cut")
        || close("painted cutout below", "wing cut")
        || close("painted colour left", "painted colour right") || !close("painted colour right", "eye clear")
        || !close("painted surface left", "eye clear") || close("painted surface right", "eye clear") {
        return Err(RenderError::Device(format!("Shader-control pixel mismatch: {samples:?}")));
    }
    *camera = saved;
    queue.write_buffer(camera_buffer, 0, bytemuck::bytes_of(camera));
    eprintln!("Verified shader-control cutouts, vertex gates, animated UVs, detail normals, glow sweep, object clipping and independent EyeCover colour/surface weights using synthetic pixels.");
    Ok(())
}
