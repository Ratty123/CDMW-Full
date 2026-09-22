//! Synthetic pixel checks for emission animation through the production shader.
use super::*;

#[allow(clippy::too_many_arguments)]
pub(super) fn verify(
    device: &wgpu::Device,
    queue: &wgpu::Queue,
    format: wgpu::TextureFormat,
    pipelines: &Pipelines,
    camera_binding: &wgpu::BindGroup,
    camera: &mut CameraUniform,
    camera_buffer: &wgpu::Buffer,
    default_binding: &wgpu::BindGroup,
    make_binding: impl Fn(&[u8], MaterialPreviewFactors) -> Result<GpuMaterialBinding, RenderError>,
) -> Result<(), RenderError> {
    let saved_camera = *camera;
    let snapshot = DrawSnapshot {
        shader_masks: Vec::new(),
        mesh_identity: u64::MAX - 31,
        draw_revision: 1,
        topology_generation: 1,
        positions: vec![
            [-0.8, -0.8, 0.5],
            [0.8, -0.8, 0.5],
            [0.8, 0.8, 0.5],
            [-0.8, 0.8, 0.5],
        ],
        normals: vec![[0.0, 0.0, -1.0]; 4],
        uvs: vec![[0.125, 0.125]; 4],
        indices: vec![0, 1, 2, 0, 2, 3],
        triangle_materials: vec![0; 2],
        selected_vertices: Vec::new(),
        fingerprint: "emission-animation-proof".to_owned(),
    };
    let mesh = GpuMeshBuffers::upload(device, &snapshot)?;
    let mut samples = BTreeMap::new();
    for (case, time, flow, frequency, floor, reveal, inverse, alpha) in [
        ("static", 0.75, 0.0, 0.0, 0.0, -1.0, 0.0, 255),
        ("pulse peak", 0.25, 0.0, 2.0, 0.0, -1.0, 0.0, 255),
        ("pulse trough", 0.75, 0.0, 2.0, 0.0, -1.0, 0.0, 255),
        ("pulse floor", 0.75, 0.0, 2.0, 0.2, -1.0, 0.0, 255),
        ("static floor", 0.75, 0.0, 0.0, 0.0, -1.0, 0.0, 255),
        ("scroll start", 0.0, 0.5, 0.0, 0.0, -1.0, 0.0, 255),
        ("scroll moved", 1.0, 0.5, 0.0, 0.0, -1.0, 0.0, 255),
        ("RGB off", 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 255),
        ("RGB full", 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 255),
        ("RGB reveal", 0.0, 0.0, 0.0, 0.0, 0.5, 0.0, 255),
        ("RGB inverse", 0.0, 0.0, 0.0, 0.0, 0.5, 1.0, 255),
        ("RGB zero alpha", 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0),
    ] {
        let mut dds = cdmw_texture::synthetic::rgba8_checker_dds();
        let width = u32::from_le_bytes(dds[16..20].try_into().unwrap()) as usize;
        for (i, pixel) in dds[148..].chunks_exact_mut(4).enumerate() {
            let color = if flow > 0.0 && i % width >= width / 2 {
                [10, 200, 40, alpha]
            } else {
                [200, 40, 10, alpha]
            };
            pixel.copy_from_slice(&color);
        }
        let factors = MaterialPreviewFactors {
            texture_tint: Some([0.0; 3]),
            base_tint_strength: Some(0.0),
            emissive_color: Some([1.0; 3]),
            emissive_intensity: Some(if case == "static floor" { 0.2 } else { 1.0 }),
            emission_animation: Some([flow, 0.0, frequency, floor]),
            emission_reveal: (reveal >= 0.0).then_some([reveal, 0.1, inverse, 1.0]),
            specular: Some(0.0),
            roughness: Some(1.0),
            ..Default::default()
        };
        camera.material_time = time;
        camera.scene_model = Mat4::IDENTITY.to_cols_array_2d();
        let bindings = BTreeMap::from([(0, make_binding(&dds, factors)?)]);
        let (buffer, width, height) = render_headless_readback_at(
            device,
            queue,
            format,
            &mesh,
            default_binding,
            &bindings,
            camera_binding,
            pipelines,
            camera,
            camera_buffer,
            ViewMode::TexturedSolid,
            64,
            64,
            Mat4::IDENTITY,
            None,
            false,
            None,
        );
        let pixels = read_headless_pixels(device, &buffer, width, height)?;
        let center = ((height / 2 * width + width / 2) * 4) as usize;
        samples.insert(
            case,
            <[u8; 4]>::try_from(&pixels[center..center + 4]).unwrap(),
        );
    }
    let luma = |name| {
        samples[name][..3]
            .iter()
            .map(|v| u32::from(*v))
            .sum::<u32>()
    };
    let close = |a, b| {
        samples[a]
            .iter()
            .zip(samples[b])
            .all(|(a, b)| a.abs_diff(b) <= 2)
    };
    if !close("static", "pulse peak")
        || luma("pulse peak") <= luma("pulse trough") + 30
        || luma("pulse floor") <= luma("pulse trough") + 10
        || !close("pulse floor", "static floor")
        || samples["scroll start"][2] <= samples["scroll start"][1]
        || samples["scroll moved"][1] <= samples["scroll moved"][2]
        || luma("RGB full") <= luma("RGB off") + 30
        || !close("RGB full", "RGB reveal")
        || !close("RGB off", "RGB inverse")
        || !close("RGB off", "RGB zero alpha")
    {
        return Err(RenderError::Device(format!(
            "Emission animation/reveal pixel mismatch: {samples:?}"
        )));
    }
    *camera = saved_camera;
    queue.write_buffer(camera_buffer, 0, bytemuck::bytes_of(camera));
    eprintln!(
        "Verified glow UV scrolling, pulse peaks/floors, RGB reveal/inversion and zero-alpha pixels."
    );
    Ok(())
}
