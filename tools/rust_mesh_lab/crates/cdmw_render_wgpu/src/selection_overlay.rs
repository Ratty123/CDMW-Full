use super::*;

/// Face highlights share the mesh camera and depth buffer. Their geometry is uploaded only
/// when selection or geometry changes; orbiting does not require CPU visibility queries.
pub(super) struct FaceSelectionRenderer {
    visible: wgpu::RenderPipeline,
    xray: wgpu::RenderPipeline,
    depth: wgpu::RenderPipeline,
    vertices: Option<wgpu::Buffer>,
    vertex_count: u32,
}

/// Offscreen proof of the same selection draw path used by the resident editor.
pub async fn verify_face_selection_depth() -> Result<(), RenderError> {
    let mut descriptor = wgpu::InstanceDescriptor::new_without_display_handle();
    descriptor.backends = wgpu::Backends::DX12;
    let instance = wgpu::Instance::new(descriptor);
    let adapter = instance
        .request_adapter(&wgpu::RequestAdapterOptions {
            power_preference: wgpu::PowerPreference::HighPerformance,
            force_fallback_adapter: false,
            compatible_surface: None,
            apply_limit_buckets: false,
        })
        .await
        .map_err(|_| RenderError::NoAdapter)?;
    let (device, queue) = adapter
        .request_device(&wgpu::DeviceDescriptor {
            label: Some("CDMW selection depth proof"),
            ..Default::default()
        })
        .await
        .map_err(|error| RenderError::Device(error.to_string()))?;
    let format = wgpu::TextureFormat::Bgra8UnormSrgb;
    let texture_layout = create_texture_bind_group_layout(&device);
    let defaults = create_default_material_textures(&device, &queue);
    let sampler = create_material_sampler(&device, 1);
    let material = create_material_bind_group(
        &device,
        &texture_layout,
        &sampler,
        &defaults,
        &[],
        MaterialTextureIndices::default(),
        MaterialPreviewFactors::default(),
    );
    let camera_layout = create_camera_bind_group_layout(&device);
    let camera = CameraUniform::new(true);
    let camera_buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
        label: Some("selection proof camera"),
        contents: bytemuck::bytes_of(&camera),
        usage: wgpu::BufferUsages::UNIFORM,
    });
    let camera_binding = device.create_bind_group(&wgpu::BindGroupDescriptor {
        label: Some("selection proof camera binding"),
        layout: &camera_layout,
        entries: &[wgpu::BindGroupEntry {
            binding: 0,
            resource: camera_buffer.as_entire_binding(),
        }],
    });
    let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
        label: Some("selection proof occluder"),
        source: wgpu::ShaderSource::Wgsl(SHADER.into()),
    });
    let layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
        label: Some("selection proof occluder layout"),
        bind_group_layouts: &[Some(&texture_layout), Some(&camera_layout)],
        immediate_size: 0,
    });
    let occluder_pipeline = create_pipeline(
        &device,
        format,
        &layout,
        &shader,
        "selection occluder",
        wgpu::PrimitiveTopology::TriangleList,
        "fs_selection",
        None,
        PipelineDepth::Write,
        Some(wgpu::BlendState::REPLACE),
        1,
    );
    // An opaque green foreground covers the left half of the screen.
    let occluder_positions = [
        [-1., -1., 0.2],
        [0., -1., 0.2],
        [0., 1., 0.2],
        [-1., -1., 0.2],
        [0., 1., 0.2],
        [-1., 1., 0.2],
    ];
    let occluder = occluder_positions.map(|position| {
        let mut vertex = GpuVertex::overlay(Vec3::from_array(position));
        vertex.deformation = [0., 1., 0., 1.];
        vertex
    });
    let occluder_buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
        label: Some("selection proof foreground"),
        contents: bytemuck::cast_slice(&occluder),
        usage: wgpu::BufferUsages::VERTEX,
    });
    let mut selection =
        FaceSelectionRenderer::new(&device, format, &texture_layout, &camera_layout, 1);
    let colour = [1., 0., 0., 0.6];
    for (label, xray, depth, empty) in [
        ("visible", false, 0.6, false),
        ("wire", false, 0.6, false),
        ("xray", true, 0.6, false),
        ("same depth", false, 0.2, false),
        ("cleared", false, 0.6, true),
        ("weight gradient", false, 0.6, false),
    ] {
        let positions = [[-1., -1., depth], [1., -1., depth], [0., 1., depth]];
        selection.upload(
            &device,
            &queue,
            if empty { &[] } else { &positions },
            colour,
        )?;
        if label == "weight gradient" {
            selection.upload_coloured(
                &device,
                &queue,
                &positions,
                &[[1., 0., 0., 1.], [0., 0., 1., 1.], [0., 1., 0., 1.]],
            )?;
        }
        let color = create_headless_color_target(&device, format, 32, 32);
        let view = color.create_view(&wgpu::TextureViewDescriptor::default());
        let depth = create_depth_target_with_sample_count(&device, 32, 32, 1);
        let readback = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("selection proof readback"),
            size: 256 * 32,
            usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
            mapped_at_creation: false,
        });
        let mut encoder = device.create_command_encoder(&wgpu::CommandEncoderDescriptor::default());
        {
            let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("selection proof"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &view,
                    resolve_target: None,
                    depth_slice: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(wgpu::Color::BLACK),
                        store: wgpu::StoreOp::Store,
                    },
                })],
                depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                    view: &depth.view,
                    depth_ops: Some(wgpu::Operations {
                        load: wgpu::LoadOp::Clear(1.0),
                        store: wgpu::StoreOp::Store,
                    }),
                    stencil_ops: None,
                }),
                timestamp_writes: None,
                occlusion_query_set: None,
                multiview_mask: None,
            });
            pass.set_bind_group(0, &material.bind_group, &[]);
            pass.set_bind_group(1, &camera_binding, &[]);
            pass.set_pipeline(if label == "wire" {
                &selection.depth
            } else {
                &occluder_pipeline
            });
            pass.set_vertex_buffer(0, occluder_buffer.slice(..));
            pass.draw(0..6, 0..1);
            selection.draw(&mut pass, &material.bind_group, &camera_binding, xray);
        }
        encoder.copy_texture_to_buffer(
            wgpu::TexelCopyTextureInfo {
                texture: &color,
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            wgpu::TexelCopyBufferInfo {
                buffer: &readback,
                layout: wgpu::TexelCopyBufferLayout {
                    offset: 0,
                    bytes_per_row: Some(256),
                    rows_per_image: Some(32),
                },
            },
            wgpu::Extent3d {
                width: 32,
                height: 32,
                depth_or_array_layers: 1,
            },
        );
        queue.submit([encoder.finish()]);
        let pixels = read_headless_pixels(&device, &readback, 32, 32)?;
        let left_red = pixels[(24 * 32 + 10) * 4 + 2];
        let right_red = pixels[(24 * 32 + 22) * 4 + 2];
        if label == "weight gradient" {
            let right_blue = pixels[(24 * 32 + 22) * 4];
            let right_green = pixels[(24 * 32 + 22) * 4 + 1];
            if left_red > 10 || right_blue <= right_red.saturating_add(40) || right_green < 20 {
                return Err(RenderError::InvalidOverlay(format!(
                    "weight colours did not interpolate or respect depth: left red={left_red}, right rgb={right_red},{right_green},{right_blue}"
                )));
            }
            continue;
        }
        let should_cover_left = label == "xray" || label == "same depth";
        if (left_red > 100) != should_cover_left || (right_red > 100) == empty {
            return Err(RenderError::InvalidOverlay(format!(
                "{label} selection pixels were wrong: left red={left_red}, right red={right_red}"
            )));
        }
    }
    Ok(())
}

impl FaceSelectionRenderer {
    pub(super) fn new(
        device: &wgpu::Device,
        format: wgpu::TextureFormat,
        texture_layout: &wgpu::BindGroupLayout,
        camera_layout: &wgpu::BindGroupLayout,
        sample_count: u32,
    ) -> Self {
        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("CDMW face selection shader"),
            source: wgpu::ShaderSource::Wgsl(SHADER.into()),
        });
        let layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("CDMW face selection layout"),
            bind_group_layouts: &[Some(texture_layout), Some(camera_layout)],
            immediate_size: 0,
        });
        let pipeline = |depth, label| {
            create_pipeline(
                device,
                format,
                &layout,
                &shader,
                label,
                wgpu::PrimitiveTopology::TriangleList,
                "fs_selection",
                None,
                depth,
                Some(wgpu::BlendState::ALPHA_BLENDING),
                sample_count,
            )
        };
        Self {
            visible: pipeline(PipelineDepth::Test, "visible face selection"),
            xray: pipeline(PipelineDepth::Ignore, "xray face selection"),
            depth: pipeline(PipelineDepth::DepthOnly, "selection surface depth"),
            vertices: None,
            vertex_count: 0,
        }
    }

    pub(super) fn upload(
        &mut self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        positions: &[[f32; 3]],
        colour: [f32; 4],
    ) -> Result<(), RenderError> {
        self.upload_coloured(device, queue, positions, &vec![colour; positions.len()])
    }

    pub(super) fn upload_coloured(
        &mut self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        positions: &[[f32; 3]],
        colours: &[[f32; 4]],
    ) -> Result<(), RenderError> {
        if !positions.len().is_multiple_of(3)
            || positions.len() != colours.len()
            || positions
                .iter()
                .flatten()
                .chain(colours.iter().flatten())
                .any(|v| !v.is_finite())
        {
            return Err(RenderError::InvalidOverlay(
                "face selection must contain finite triangles and colour".into(),
            ));
        }
        let vertex_count =
            u32::try_from(positions.len()).map_err(|_| RenderError::ResourceLimit)?;
        if positions.is_empty() {
            self.vertex_count = 0;
            return Ok(());
        }
        let vertices = positions
            .iter()
            .zip(colours)
            .map(|(position, colour)| {
                let mut vertex = GpuVertex::overlay(Vec3::from_array(*position));
                vertex.deformation = *colour;
                vertex
            })
            .collect::<Vec<_>>();
        let bytes = bytemuck::cast_slice(&vertices);
        if let Some(buffer) = &self.vertices
            && buffer.size() >= bytes.len() as u64
        {
            queue.write_buffer(buffer, 0, bytes);
        } else {
            self.vertices = Some(
                device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
                    label: Some("CDMW selected faces"),
                    contents: bytes,
                    usage: wgpu::BufferUsages::VERTEX | wgpu::BufferUsages::COPY_DST,
                }),
            );
        }
        self.vertex_count = vertex_count;
        Ok(())
    }

    pub(super) fn prepare_depth<'a>(
        &'a self,
        pass: &mut wgpu::RenderPass<'a>,
        mesh: &'a GpuMeshBuffers,
        material: &'a wgpu::BindGroup,
        camera: &'a wgpu::BindGroup,
        mode: ViewMode,
        xray: bool,
    ) {
        if self.vertex_count == 0
            || xray
            || !matches!(
                mode,
                ViewMode::Wireframe | ViewMode::Vertices | ViewMode::WireVertices
            )
        {
            return;
        }
        // These display modes do not fill surfaces, but Visible highlights still need
        // those surfaces to occlude selected faces on the rear of the model.
        pass.set_bind_group(0, material, &[]);
        pass.set_bind_group(1, camera, &[]);
        pass.set_vertex_buffer(0, mesh.vertex.slice(..));
        draw_solid(pass, mesh, &self.depth);
    }

    pub(super) fn draw<'a>(
        &'a self,
        pass: &mut wgpu::RenderPass<'a>,
        material: &'a wgpu::BindGroup,
        camera: &'a wgpu::BindGroup,
        xray: bool,
    ) {
        if self.vertex_count == 0 {
            return;
        }
        if let Some(vertices) = &self.vertices {
            pass.set_bind_group(0, material, &[]);
            pass.set_bind_group(1, camera, &[]);
            pass.set_pipeline(if xray { &self.xray } else { &self.visible });
            pass.set_vertex_buffer(0, vertices.slice(..));
            pass.draw(0..self.vertex_count, 0..1);
        }
    }
}
