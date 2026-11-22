//! Sample the completed opaque depth pass for soft particle intersections.
use super::*;
use std::cell::RefCell;

pub(super) struct EffectDepthCache {
    uniform_buffer: wgpu::Buffer,
    cached_binding: RefCell<Option<(u64, wgpu::BindGroup)>>,
}

impl EffectDepthCache {
    pub(super) fn new(device: &wgpu::Device) -> Self {
        let uniform_buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("effect depth reconstruction"),
            size: (20 * std::mem::size_of::<f32>()) as u64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        Self {
            uniform_buffer,
            cached_binding: RefCell::new(None),
        }
    }

    fn resolve_binding<'a>(
        &'a self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        layout: &wgpu::BindGroupLayout,
        depth: &wgpu::TextureView,
        depth_id: u64,
        camera: &CameraUniform,
        viewport: [f32; 4],
    ) -> std::cell::Ref<'a, wgpu::BindGroup> {
        let inv_vp = Mat4::from_cols_array_2d(&camera.view_projection)
            .inverse()
            .to_cols_array();
        let mut parameters = [0.0f32; 20];
        parameters[..16].copy_from_slice(&inv_vp);
        parameters[16..20].copy_from_slice(&viewport);
        queue.write_buffer(&self.uniform_buffer, 0, bytemuck::cast_slice(&parameters));
        {
            let mut cache = self.cached_binding.borrow_mut();
            if cache.as_ref().is_none_or(|(cached_id, _)| *cached_id != depth_id) {
                let group = device.create_bind_group(&wgpu::BindGroupDescriptor {
                    label: Some("effect depth reconstruction"),
                    layout,
                    entries: &[
                        wgpu::BindGroupEntry {
                            binding: 0,
                            resource: wgpu::BindingResource::TextureView(depth),
                        },
                        wgpu::BindGroupEntry {
                            binding: 1,
                            resource: self.uniform_buffer.as_entire_binding(),
                        },
                    ],
                });
                *cache = Some((depth_id, group));
            }
        }
        std::cell::Ref::map(self.cached_binding.borrow(), |slot| {
            &slot.as_ref().expect("effect depth bind group cached").1
        })
    }
}

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
    depth: &DepthTarget,
    multisample: Option<&MultisampleTarget>,
    width: u32,
    height: u32,
    viewport: Option<[f32; 4]>,
) {
    if (renderer.effect_batches.is_empty() && renderer.effect_mesh.is_empty())
        || renderer.mesh.is_none()
    {
        return;
    }
    let [x, y, w, h] = viewport.unwrap_or([0., 0., width as f32, height as f32]);
    let x = x.clamp(0., width.saturating_sub(1) as f32);
    let y = y.clamp(0., height.saturating_sub(1) as f32);
    let w = w.max(1.).min(width as f32 - x);
    let h = h.max(1.).min(height as f32 - y);
    let binding = renderer.effect_depth_cache.resolve_binding(
        &renderer.device,
        &renderer.queue,
        &renderer.effect_depth_layout,
        &depth.view,
        depth.id,
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
            view: &depth.view,
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
    effect_mesh::draw_combined(renderer, &mut pass, &binding);
    renderer.face_selection.draw(
        &mut pass,
        &renderer.default_material_binding,
        &renderer.camera_bind_group,
        renderer.face_selection_xray,
    );
}
