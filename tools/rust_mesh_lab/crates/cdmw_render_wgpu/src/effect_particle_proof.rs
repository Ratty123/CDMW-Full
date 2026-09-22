//! Pixel assertions for the same particle shader, vertex layout and draw path
//! used by the resident renderer. Synthetic data only; no files or windows.
use super::*;

pub(super) fn verify(device: &wgpu::Device, queue: &wgpu::Queue) -> Result<(), RenderError> {
    verify_samples(device, queue, 1)?;
    verify_samples(device, queue, 4)
}

fn verify_samples(
    device: &wgpu::Device,
    queue: &wgpu::Queue,
    samples: u32,
) -> Result<(), RenderError> {
    const SIZE: u32 = 64;
    let format = wgpu::TextureFormat::Bgra8UnormSrgb;
    let camera_layout = create_camera_bind_group_layout(device);
    let effect_layout = create_effect_texture_bind_group_layout(device);
    let depth_layout = effect_depth::layout(device, samples);
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
        &depth_layout,
        samples,
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
    let render_depth = |instance: GpuEffectBillboardInstance,
                        dds: &[u8],
                        opaque_depth: f32, indexed_mesh: Option<(&EffectMeshAsset, f32)>|
     -> Result<Vec<u8>, RenderError> {
        let uploaded = upload_dds_texture(device, queue, dds, TextureRole::BaseColor)?;
        let textures = [effect_texture_binding(
            device,
            &effect_layout,
            &sampler,
            uploaded.texture,
            uploaded.view_format,
            uploaded.source_sha256,
        )];
        let mut instance = instance;
        instance.sprite_options[3] = if textures[0].srgb { 0.0 } else { 1.0 };
        let buffer = Arc::new(
            device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
                label: Some("effect pixel proof instance"),
                contents: bytemuck::bytes_of(&instance),
                usage: wgpu::BufferUsages::VERTEX,
            }),
        );
        let batches = [GpuEffectBatch {
            depths: vec![0.],
            texture_index: 0,
            blend: EffectBlendMode::Alpha,
            instances: buffer,
            first_instance: 0,
            instance_count: 1,
        }];
        let mut meshes = indexed_mesh.map(|_| effect_mesh::MeshParticles::new(
            device, format, &camera_layout, &effect_layout, &depth_layout, samples));
        if let Some(meshes) = &mut meshes {
            let (asset, age) = indexed_mesh.expect("indexed mesh proof");
            meshes.add(device, asset)?;
            let transform = Mat4::from_cols(
                Vec3::from_array(instance.axis_right).extend(0.),
                Vec3::from_array(instance.axis_up).extend(0.), Vec3::Z.extend(0.),
                Vec3::from_array(instance.center).extend(1.));
            meshes.set(device, queue, &[EffectMeshInstance { mesh_index: 0, depth: 0.,
                particle: EffectMeshParticle { transform: transform.to_cols_array_2d(), colour: instance.colour,
                    scale_age: [0.5,0.25,1.,age], seed: [17,0,0,0],
                    parent_scale: [1.;4], parent_origin: [0.;4] },
            }], EffectMeshView { eye_height: [0.,0.,2.,SIZE as f32], fov_padding: [0.5,0.,0.,0.] })?;
        }
        let target = create_headless_color_target(device, format, SIZE, SIZE);
        let view = target.create_view(&wgpu::TextureViewDescriptor::default());
        let depth = create_depth_target_with_sample_count(device, SIZE, SIZE, samples);
        let multisample = create_multisample_target(device, format, SIZE, SIZE, samples);
        let colour = multisample.as_ref().map_or(&view, |target| &target.view);
        let depth_binding = effect_depth::binding(
            device,
            &depth_layout,
            &depth.view,
            &camera,
            [0., 0., SIZE as f32, SIZE as f32],
        );
        let readback = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("effect pixel proof readback"),
            size: u64::from(padded_headless_bytes_per_row(SIZE) * SIZE),
            usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
            mapped_at_creation: false,
        });
        let mut encoder = device.create_command_encoder(&wgpu::CommandEncoderDescriptor::default());
        {
            let pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("effect pixel proof"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: colour,
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
                        load: wgpu::LoadOp::Clear(opaque_depth),
                        store: wgpu::StoreOp::Store,
                    }),
                    stencil_ops: None,
                }),
                timestamp_writes: None,
                occlusion_query_set: None,
                multiview_mask: None,
            });
            drop(pass);
            let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("effect pixel proof sampled depth"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: colour,
                    resolve_target: multisample.as_ref().map(|_| &view),
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Load,
                        store: wgpu::StoreOp::Store,
                    },
                    depth_slice: None,
                })],
                depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                    view: &depth.view,
                    depth_ops: None,
                    stencil_ops: None,
                }),
                timestamp_writes: None,
                occlusion_query_set: None,
                multiview_mask: None,
            });
            if let Some(meshes) = &meshes {
                meshes.draw(&mut pass, 0, 0, 1, &camera_binding, &textures[0].bind_group, &depth_binding);
            } else { draw_effect_particles(
                &mut pass,
                &quad_buffer,
                &batches,
                &textures,
                &camera_binding,
                &depth_binding,
                &pipeline,
                &pipeline,
            ); }
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
    let render_dds = |instance, dds: &[u8]| render_depth(instance, dds, 1., None);
    let render = |instance, texels: [u8; 16]| {
        let mut dds = cdmw_texture::synthetic::rgba8_checker_dds();
        dds[148..164].copy_from_slice(&texels);
        render_dds(instance, &dds)
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
    let untextured = render(
        GpuEffectBillboardInstance {
            sprite_options: [-2., 0., 0., 0.],
            ..base
        },
        [0; 16],
    )?;
    require(
        center(&untextured) == center(&red),
        "untextured geometry was masked by the fallback sprite",
    )?;
    let plane_depth = |z| {
        let clip =
            Mat4::from_cols_array_2d(&camera.view_projection) * Vec3::new(0., 0., z).extend(1.);
        clip.z / clip.w
    };
    let mut white_dds = cdmw_texture::synthetic::rgba8_checker_dds();
    white_dds[148..164].copy_from_slice(&white);
    let soft = render_depth(base, &white_dds, plane_depth(-0.01), None)?;
    let occluded = render_depth(base, &white_dds, plane_depth(0.01), None)?;
    require(
        center(&soft)[0] > 0 && center(&soft)[0] < center(&red)[0] / 2,
        "particles did not fade against scene geometry",
    )?;
    require(
        visible(&occluded) == 0,
        "particles behind scene depth were visible",
    )?;
    require(
        center(&red)[0] > 180 && center(&red)[1] < 5 && center(&red)[2] < 5,
        "camera binding, vertex layout or colour lost the red particle",
    )?;
    require(
        (480..=544).contains(&visible(&red)),
        "particle axes or size changed",
    )?;
    let mut bc4 = cdmw_texture::synthetic::rgba8_checker_dds();
    bc4.resize(156, 0);
    for (offset, value) in [(12, 4_u32), (16, 4), (20, 8), (128, 80)] {
        bc4[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
    }
    bc4[148..].copy_from_slice(&[128, 0, 0, 0, 0, 0, 0, 0]);
    let intensity = render_dds(
        GpuEffectBillboardInstance {
            sprite_options: [0., 0., 0., 0.],
            ..base
        },
        &bc4,
    )?;
    require(
        (165..=175).contains(&center(&intensity)[0])
            && center(&intensity)[1] < 5
            && center(&intensity)[2] < 5,
        &format!(
            "BC4 particle mask must preserve linear half-intensity and authored colour: {:?}",
            center(&intensity)
        ),
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
    let mesh_asset = EffectMeshAsset {
        vertices: [[-1.,-1.,0.], [1.,-1.,0.], [0.,1.,0.]].map(|position|
            EffectMeshVertex { position, normal: [0.;3], uv: [0.5,0.], controls: [1.;4] }).to_vec(),
        indices: vec![0,1,2],
        lightning: EffectLightningMaterial { parameters: [[0.;4];11], curves: [[1.;128];13] },
    };
    let render_mesh = |asset: &EffectMeshAsset, age, colour| {
        render_depth(GpuEffectBillboardInstance { colour, ..base }, &white_dds, 1., Some((asset, age)))
    };
    let indexed = render_mesh(&mesh_asset, 0.5, base.colour)?;
    require((230..=300).contains(&visible(&indexed)) && center(&indexed)[0] > 180
        && center(&indexed)[2] < 5, &format!("indexed lightning mesh lost its geometry or colour: count={}, centre={:?}, samples={samples}", visible(&indexed), center(&indexed)))?;
    let transparent = render_mesh(&mesh_asset, 0.5, [1.,0.,0.,0.])?;
    require(visible(&transparent) == 0, "zero-alpha indexed lightning is visible")?;

    // Decoded VS/PS controls. These cases run through the real raster pipeline,
    // including interpolation, material storage bindings, tone mapping and MSAA.
    let mut shaped = mesh_asset.clone();
    shaped.lightning.parameters[8] = [2.,4.,1.,1.];
    shaped.lightning.parameters[9] = [0.5,1.,0.,1e8];
    shaped.lightning.parameters[10] = [1.,1.,0.,0.];
    shaped.lightning.curves[10] = std::array::from_fn(|i| i as f32 / 127.);
    require(visible(&render_mesh(&shaped, 0., base.colour)?) == 0,
        "lightning pulse lights vertices outside its authored progress window")?;
    require(visible(&render_mesh(&shaped, 1., base.colour)?) > 230,
        "lightning pulse failed to reveal the middle of the bolt")?;
    let mut endpoints = shaped.clone();
    for (vertex, u) in endpoints.vertices.iter_mut().zip([0.,1.,0.]) { vertex.uv[0] = u; }
    require(visible(&render_mesh(&endpoints, 1., base.colour)?) == 0,
        "lightning pulse was recomputed per fragment instead of interpolating vertex visibility")?;
    let mut zero_width = shaped.clone();
    zero_width.lightning.parameters[9][1] = 0.;
    require(visible(&render_mesh(&zero_width, 1., base.colour)?) == 0,
        "a zero-width lightning pulse rendered or divided by zero")?;
    let mut no_hide = shaped.clone();
    no_hide.lightning.parameters[10][0] = 0.;
    require(visible(&render_mesh(&no_hide, 0., base.colour)?) > 230,
        "lightning ignores the material's hide flag")?;

    let same_centre = |actual: &[u8], expected: &[u8]| {
        center(actual).into_iter().zip(center(expected)).all(|(a,b)| a.abs_diff(b) <= 2)
    };
    let mut narrow = shaped.clone();
    for v in &mut narrow.vertices { v.controls[2] = 0.5; }
    require(same_centre(&render_mesh(&narrow, 1., base.colour)?,
        &render_mesh(&mesh_asset, 1., [0.125,0.,0.,1.])?),
        "lightning emissive perimeter does not follow the packed mesh channel")?;
    let mut ramp = shaped.clone();
    for v in &mut ramp.vertices { v.controls[0] = 0.25; }
    ramp.lightning.curves[12] = std::array::from_fn(|i| i as f32 / 127.);
    require(same_centre(&render_mesh(&ramp, 1., base.colour)?,
        &render_mesh(&mesh_asset, 1., [0.5,0.,0.,1.])?),
        "lightning emissive spline uses particle age or UV instead of packed control X")?;
    let mut pulse_power = shaped.clone();
    pulse_power.lightning.parameters[8][3] = 2.;
    require(same_centre(&render_mesh(&pulse_power, 0.6, base.colour)?,
        &render_mesh(&mesh_asset, 1., [0.405,0.,0.,1.])?),
        "lightning hide exponent does not modulate emitted colour")?;
    let mut limited = shaped.clone();
    limited.lightning.parameters[8][2] = 0.;
    limited.lightning.parameters[9][3] = 0.5;
    let expected = (Vec3::new(4.,2.,1.).normalize() * 0.5).extend(1.).to_array();
    require(same_centre(&render_mesh(&limited, 1., [4.,2.,1.,1.])?,
        &render_mesh(&mesh_asset, 1., expected)?),
        "lightning emissive limits clipped RGB components and changed hue")?;
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
