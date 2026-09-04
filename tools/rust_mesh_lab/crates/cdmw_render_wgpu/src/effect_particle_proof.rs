//! Pixel assertions for the same particle shader, vertex layout and draw path
//! used by the resident renderer. Synthetic data only; no files or windows.
use super::*;

pub(super) fn verify(device: &wgpu::Device, queue: &wgpu::Queue) -> Result<(), RenderError> {
    const SIZE: u32 = 64;
    let format = wgpu::TextureFormat::Bgra8UnormSrgb;
    let camera_layout = create_camera_bind_group_layout(device);
    let effect_layout = create_effect_texture_bind_group_layout(device);
    let mut camera = CameraUniform::new(true);
    camera.view_projection = (Mat4::orthographic_rh(-1., 1., -1., 1., 0.1, 10.)
        * Mat4::look_at_rh(Vec3::Z * 2., Vec3::ZERO, Vec3::Y))
    .to_cols_array_2d();
    let camera_buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
        label: Some("effect pixel proof camera"),
        contents: bytemuck::bytes_of(&camera),
        usage: wgpu::BufferUsages::UNIFORM,
    });
    let camera_binding = device.create_bind_group(&wgpu::BindGroupDescriptor {
        label: Some("effect pixel proof camera"),
        layout: &camera_layout,
        entries: &[wgpu::BindGroupEntry {
            binding: 0,
            resource: camera_buffer.as_entire_binding(),
        }],
    });
    let pipeline = create_effect_particle_pipeline(
        device,
        format,
        &camera_layout,
        &effect_layout,
        1,
        wgpu::BlendState::ALPHA_BLENDING,
        "effect pixel proof",
    );
    let quad = [
        ([-1., -1.], [0., 1.]),
        ([1., -1.], [1., 1.]),
        ([1., 1.], [1., 0.]),
        ([-1., -1.], [0., 1.]),
        ([1., 1.], [1., 0.]),
        ([-1., 1.], [0., 0.]),
    ]
    .map(|(corner, uv)| EffectQuadVertex { corner, uv });
    let quad_buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
        label: Some("effect pixel proof quad"),
        contents: bytemuck::cast_slice(&quad),
        usage: wgpu::BufferUsages::VERTEX,
    });
    let sampler = create_effect_sampler(device);
    let render = |instance: GpuEffectBillboardInstance,
                  texels: [u8; 16]|
     -> Result<Vec<u8>, RenderError> {
        let mut dds = cdmw_texture::synthetic::rgba8_checker_dds();
        dds[148..164].copy_from_slice(&texels);
        let uploaded = upload_dds_texture(device, queue, &dds, TextureRole::BaseColor)?;
        let textures = [effect_texture_binding(
            device,
            &effect_layout,
            &sampler,
            uploaded.texture,
            uploaded.view_format,
            uploaded.source_sha256,
        )];
        let buffer = Arc::new(
            device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
                label: Some("effect pixel proof instance"),
                contents: bytemuck::bytes_of(&instance),
                usage: wgpu::BufferUsages::VERTEX,
            }),
        );
        let batches = [GpuEffectBatch {
            texture_index: 0,
            blend: EffectBlendMode::Alpha,
            instances: buffer,
            first_instance: 0,
            instance_count: 1,
        }];
        let target = create_headless_color_target(device, format, SIZE, SIZE);
        let view = target.create_view(&wgpu::TextureViewDescriptor::default());
        let depth = create_depth_target_with_sample_count(device, SIZE, SIZE, 1);
        let readback = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("effect pixel proof readback"),
            size: u64::from(padded_headless_bytes_per_row(SIZE) * SIZE),
            usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
            mapped_at_creation: false,
        });
        let mut encoder = device.create_command_encoder(&wgpu::CommandEncoderDescriptor::default());
        {
            let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("effect pixel proof"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &view,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(wgpu::Color::BLACK),
                        store: wgpu::StoreOp::Store,
                    },
                    depth_slice: None,
                })],
                depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                    view: &depth.view,
                    depth_ops: Some(wgpu::Operations {
                        load: wgpu::LoadOp::Clear(1.),
                        store: wgpu::StoreOp::Store,
                    }),
                    stencil_ops: None,
                }),
                timestamp_writes: None,
                occlusion_query_set: None,
                multiview_mask: None,
            });
            draw_effect_particles(
                &mut pass,
                &quad_buffer,
                &batches,
                &textures,
                &camera_binding,
                &pipeline,
                &pipeline,
            );
        }
        encoder.copy_texture_to_buffer(
            wgpu::TexelCopyTextureInfo {
                texture: &target,
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            wgpu::TexelCopyBufferInfo {
                buffer: &readback,
                layout: wgpu::TexelCopyBufferLayout {
                    offset: 0,
                    bytes_per_row: Some(padded_headless_bytes_per_row(SIZE)),
                    rows_per_image: Some(SIZE),
                },
            },
            wgpu::Extent3d {
                width: SIZE,
                height: SIZE,
                depth_or_array_layers: 1,
            },
        );
        queue.submit([encoder.finish()]);
        read_headless_pixels(device, &readback, SIZE, SIZE)
    };
    let base = GpuEffectBillboardInstance {
        center: [0., 0., 0.],
        axis_right: [0.5, 0., 0.],
        axis_up: [0., 0.25, 0.],
        colour: [1., 0., 0., 1.],
        uv_rect: [0., 0., 1., 1.],
        sprite_options: [-1., 0., 0., 0.],
        third_uv: [0.; 2],
    };
    let white = [255; 16];
    let center = |pixels: &[u8]| -> [u8; 3] {
        let offset = ((SIZE / 2 * SIZE + SIZE / 2) * 4) as usize;
        [pixels[offset + 2], pixels[offset + 1], pixels[offset]]
    };
    let visible = |pixels: &[u8]| {
        pixels
            .chunks_exact(4)
            .filter(|p| p[..3].iter().any(|c| *c > 20))
            .count()
    };
    let require = |ok: bool, message: &str| -> Result<(), RenderError> {
        if ok {
            Ok(())
        } else {
            Err(RenderError::Device(format!(
                "effect pixel proof failed: {message}"
            )))
        }
    };
    let red = render(base, white)?;
    require(
        center(&red)[0] > 180 && center(&red)[1] < 5 && center(&red)[2] < 5,
        "camera binding, vertex layout or colour lost the red particle",
    )?;
    require(
        (480..=544).contains(&visible(&red)),
        "particle axes or size changed",
    )?;
    require(
        visible(&render(
            GpuEffectBillboardInstance {
                colour: [1., 0., 0., 0.],
                ..base
            },
            white,
        )?) == 0,
        "zero alpha still renders",
    )?;
    let mask = [0, 255, 0, 0, 0, 255, 0, 0, 0, 255, 0, 0, 0, 255, 0, 0];
    let masked = render(
        GpuEffectBillboardInstance {
            sprite_options: [1., 0., 0., 0.],
            ..base
        },
        mask,
    )?;
    require(
        center(&masked)[0] > 180,
        "packed green mask was treated as colour or texture alpha",
    )?;
    require(
        visible(&render(
            GpuEffectBillboardInstance {
                sprite_options: [0., 0., 0., 0.],
                ..base
            },
            mask,
        )?) == 0,
        "zero mask channel still renders",
    )?;
    let atlas = [
        255, 0, 0, 255, 0, 0, 255, 255, 255, 0, 0, 255, 0, 0, 255, 255,
    ];
    let blue = render(
        GpuEffectBillboardInstance {
            colour: [1.; 4],
            uv_rect: [0.5, 0., 0.5, 1.],
            ..base
        },
        atlas,
    )?;
    require(
        center(&blue)[2] > 180 && center(&blue)[0] < 5,
        "flipbook sampled the wrong cell",
    )?;
    let blended = render(
        GpuEffectBillboardInstance {
            colour: [1.; 4],
            uv_rect: [0., 0., 0.5, 1.],
            sprite_options: [-1., 0.5, 0., 0.],
            ..base
        },
        atlas,
    )?;
    require(
        center(&blended)[0] > 100 && center(&blended)[2] > 100,
        "flipbook frame interpolation is missing",
    )?;
    let triangle = render(
        GpuEffectBillboardInstance {
            center: [-0.5, -0.25, 0.],
            axis_right: [1., 0., 0.],
            axis_up: [0., 0.5, 0.],
            sprite_options: [-1., 0., 1., 0.],
            uv_rect: [0., 0., 1., 0.],
            third_uv: [0., 1.],
            ..base
        },
        white,
    )?;
    require(
        (230..=282).contains(&visible(&triangle)),
        "mesh triangle rendered as a quad or disappeared",
    )?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn particle_attributes_match_the_uploaded_struct() {
        let offsets = [
            std::mem::offset_of!(GpuEffectBillboardInstance, center),
            std::mem::offset_of!(GpuEffectBillboardInstance, axis_right),
            std::mem::offset_of!(GpuEffectBillboardInstance, axis_up),
            std::mem::offset_of!(GpuEffectBillboardInstance, colour),
            std::mem::offset_of!(GpuEffectBillboardInstance, uv_rect),
            std::mem::offset_of!(GpuEffectBillboardInstance, sprite_options),
            std::mem::offset_of!(GpuEffectBillboardInstance, third_uv),
        ];
        for (attribute, offset) in GpuEffectBillboardInstance::ATTRIBUTES.iter().zip(offsets) {
            assert_eq!(attribute.offset, offset as u64);
        }
    }
}
