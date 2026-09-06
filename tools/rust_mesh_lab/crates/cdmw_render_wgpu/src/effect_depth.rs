//! Sample the completed opaque depth pass for soft particle intersections.
use super::*;

pub(super) fn layout(device: &wgpu::Device, samples: u32) -> wgpu::BindGroupLayout {
    device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
        label: Some("effect scene depth"),
        entries: &[
            wgpu::BindGroupLayoutEntry {
                binding: 0,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Texture {
                    sample_type: wgpu::TextureSampleType::Depth,
                    view_dimension: wgpu::TextureViewDimension::D2,
                    multisampled: samples > 1,
                },
                count: None,
            },
            wgpu::BindGroupLayoutEntry {
                binding: 1,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Buffer {
                    ty: wgpu::BufferBindingType::Uniform,
                    has_dynamic_offset: false,
                    min_binding_size: None,
                },
                count: None,
            },
        ],
    })
}

pub(super) fn binding(
    device: &wgpu::Device,
    layout: &wgpu::BindGroupLayout,
    depth: &wgpu::TextureView,
    camera: &CameraUniform,
    viewport: [f32; 4],
) -> wgpu::BindGroup {
    let mut parameters = Vec::from(
        Mat4::from_cols_array_2d(&camera.view_projection)
            .inverse()
            .to_cols_array(),
    );
    parameters.extend(viewport);
    let buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
        label: Some("effect depth reconstruction"),
        contents: bytemuck::cast_slice(&parameters),
        usage: wgpu::BufferUsages::UNIFORM,
    });
    device.create_bind_group(&wgpu::BindGroupDescriptor {
        label: Some("effect depth reconstruction"),
        layout,
        entries: &[
            wgpu::BindGroupEntry {
                binding: 0,
                resource: wgpu::BindingResource::TextureView(depth),
            },
            wgpu::BindGroupEntry {
                binding: 1,
                resource: buffer.as_entire_binding(),
            },
        ],
    })
}

#[allow(clippy::too_many_arguments)]
pub(super) fn render(
    renderer: &WindowRenderer,
    encoder: &mut wgpu::CommandEncoder,
    view: &wgpu::TextureView,
    depth: &wgpu::TextureView,
    multisample: Option<&MultisampleTarget>,
    width: u32,
    height: u32,
    viewport: Option<[f32; 4]>,
) {
    if renderer.effect_batches.is_empty() || renderer.mesh.is_none() {
        return;
    }
    let [x, y, w, h] = viewport.unwrap_or([0., 0., width as f32, height as f32]);
    let x = x.clamp(0., width.saturating_sub(1) as f32);
    let y = y.clamp(0., height.saturating_sub(1) as f32);
    let w = w.max(1.).min(width as f32 - x);
    let h = h.max(1.).min(height as f32 - y);
    let binding = binding(
        &renderer.device,
        &renderer.effect_depth_layout,
        depth,
        &renderer.camera_uniform,
        [x, y, w, h],
    );
    let (colour, resolve) = multisample.map_or((view, None), |target| (&target.view, Some(view)));
    let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
        label: Some("CDMW soft particles"),
        color_attachments: &[Some(wgpu::RenderPassColorAttachment {
            view: colour,
            resolve_target: resolve,
            ops: wgpu::Operations {
                load: wgpu::LoadOp::Load,
                store: wgpu::StoreOp::Store,
            },
            depth_slice: None,
        })],
        // No depth writes while the shader samples this same attachment.
        depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
            view: depth,
            depth_ops: None,
            stencil_ops: None,
        }),
        timestamp_writes: None,
        occlusion_query_set: None,
        multiview_mask: None,
    });
    pass.set_viewport(x, y, w, h, 0., 1.);
    pass.set_scissor_rect(
        x.floor() as u32,
        y.floor() as u32,
        ((x + w).ceil() - x.floor()) as u32,
        ((y + h).ceil() - y.floor()) as u32,
    );
    draw_effect_particles(
        &mut pass,
        &renderer.effect_quad,
        &renderer.effect_batches,
        &renderer.effect_textures,
        &renderer.camera_bind_group,
        &binding,
        &renderer.effect_particle_alpha_pipeline,
        &renderer.effect_particle_additive_pipeline,
    );
    renderer.face_selection.draw(
        &mut pass,
        &renderer.default_material_binding.bind_group,
        &renderer.camera_bind_group,
        renderer.face_selection_xray,
    );
}
