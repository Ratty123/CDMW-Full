//! Shadow and ambient-depth resources shared by window and headless recorders.
use super::*;

pub(super) const SHADOW_SIZE: u32 = 2048;
pub(super) const SHADOW_FRAGMENT: &str = r#"
@fragment fn fs_shadow(input: VertexOut) {
    if (material.flags & MATERIAL_ALPHA_CUTOUT) != 0u {
        var uv = input.uv;
        if (material.flags & MATERIAL_FLIP_V) != 0u { uv.y = 1.0 - uv.y; }
        var alpha = material.opacity;
        if (material.flags & MATERIAL_BASE_COLOR) != 0u {
            alpha *= textureSampleBias(base_texture, material_sampler, uv, MATERIAL_MIP_LOD_BIAS).a;
        }
        if alpha < material.surface_factors.w { discard; }
    }
}
"#;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct LightingDepthSettings {
    pub shadows: bool,
    pub ambient_occlusion: bool,
}

impl Default for LightingDepthSettings {
    fn default() -> Self {
        Self {
            shadows: true,
            ambient_occlusion: true,
        }
    }
}

#[derive(Default)]
struct MaterialBounds {
    fixed: Option<(Vec3, Vec3)>,
    editable: Option<(Vec3, Vec3)>,
}

#[derive(Default)]
pub(super) struct SceneBounds(BTreeMap<u32, MaterialBounds>);

impl SceneBounds {
    pub(super) fn from_vertices(
        vertices: &[GpuVertex],
        indices: &[u32],
        materials: &[u32],
    ) -> Self {
        let mut result = Self::default();
        // Only indexed, visible geometry participates; unreferenced source
        // vertices must not expand the shadow camera after hiding a part.
        for (triangle, material) in indices.chunks_exact(3).zip(materials) {
            let range = result.0.entry(*material).or_default();
            for &index in triangle {
                let vertex = &vertices[index as usize];
                let bounds = if vertex.editable_role == 0 {
                    &mut range.fixed
                } else {
                    &mut range.editable
                };
                extend(bounds, Vec3::from_array(vertex.position));
            }
        }
        result
    }

    fn world(&self, transform: Mat4, visible: &[GpuMaterialRange]) -> (Vec3, Vec3) {
        let mut bounds = None;
        for range in visible {
            let Some(material) = self.0.get(&range.material) else {
                continue;
            };
            if let Some((low, high)) = material.fixed {
                extend(&mut bounds, low);
                extend(&mut bounds, high);
            }
            if let Some((low, high)) = material.editable {
                for x in [low.x, high.x] {
                    for y in [low.y, high.y] {
                        for z in [low.z, high.z] {
                            extend(&mut bounds, transform.transform_point3(Vec3::new(x, y, z)));
                        }
                    }
                }
            }
        }
        bounds.unwrap_or((Vec3::ZERO, Vec3::ZERO))
    }

    fn fit(&self, camera: &CameraUniform, visible: &[GpuMaterialRange]) -> (Mat4, Vec3, f32) {
        let (low, high) = self.world(Mat4::from_cols_array_2d(&camera.scene_model), visible);
        let center = (low + high) * 0.5;
        let radius = ((high - low).length() * 0.6).max(0.1);
        let light = key_direction(camera);
        let up = if light.dot(Vec3::Y).abs() > 0.98 {
            Vec3::Z
        } else {
            Vec3::Y
        };
        let view = Mat4::look_at_rh(center + light * (3.0 * radius), center, up);
        let half = 1.1 * radius;
        let projection = Mat4::orthographic_rh(-half, half, -half, half, 0.01, 8.0 * radius);
        (projection * view, center, radius)
    }
}

fn extend(bounds: &mut Option<(Vec3, Vec3)>, point: Vec3) {
    *bounds = Some(bounds.map_or((point, point), |(low, high)| {
        (low.min(point), high.max(point))
    }));
}

fn key_direction(camera: &CameraUniform) -> Vec3 {
    let view = Vec3::from_slice(&camera.view_direction).normalize_or(-Vec3::Z);
    let right = Vec3::from_slice(&camera.camera_right).normalize_or(Vec3::X);
    let up = Vec3::from_slice(&camera.camera_up).normalize_or(Vec3::Y);
    let neutral =
        camera.lighting_preset != 1 && camera.view_mode != ViewMode::GameOutdoor.shader_mode();
    let (horizontal, vertical) = if neutral { (0.72, 0.72) } else { (0.18, 0.35) };
    (view - right * horizontal + up * vertical).normalize_or(view)
}

pub(super) fn textured(mode: ViewMode) -> bool {
    matches!(mode, ViewMode::TexturedSolid | ViewMode::GameOutdoor)
}

#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
struct ShadowUniform {
    light_view_projection: [[f32; 4]; 4],
    center_radius: [f32; 4],
    enabled: [u32; 4],
}

pub(super) fn shadow_supported(device: &wgpu::Device) -> bool {
    device.limits().max_sampled_textures_per_shader_stage >= 17
}

pub(super) fn shadow_layout(device: &wgpu::Device) -> wgpu::BindGroupLayout {
    let mut entries = vec![wgpu::BindGroupLayoutEntry {
        binding: 2,
        visibility: wgpu::ShaderStages::FRAGMENT,
        ty: wgpu::BindingType::Buffer {
            ty: wgpu::BufferBindingType::Uniform,
            has_dynamic_offset: false,
            min_binding_size: None,
        },
        count: None,
    }];
    if shadow_supported(device) {
        entries.extend([
            wgpu::BindGroupLayoutEntry {
                binding: 0,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Texture {
                    sample_type: wgpu::TextureSampleType::Depth,
                    view_dimension: wgpu::TextureViewDimension::D2,
                    multisampled: false,
                },
                count: None,
            },
            wgpu::BindGroupLayoutEntry {
                binding: 1,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Comparison),
                count: None,
            },
        ]);
    }
    device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
        label: Some("preview shadow sampling"),
        entries: &entries,
    })
}

pub(super) struct ShadowResources {
    _texture: wgpu::Texture,
    view: wgpu::TextureView,
    sampler: wgpu::Sampler,
    layout: wgpu::BindGroupLayout,
    camera_layout: wgpu::BindGroupLayout,
    pipeline: wgpu::RenderPipeline,
}

pub(super) struct ShadowFrame {
    pub(super) binding: wgpu::BindGroup,
    pub(super) radius: f32,
}

impl ShadowResources {
    pub(super) fn new(
        device: &wgpu::Device,
        material_layout: &wgpu::BindGroupLayout,
        camera_layout: &wgpu::BindGroupLayout,
        shader: &wgpu::ShaderModule,
    ) -> Self {
        let texture = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("preview key shadow depth"),
            size: wgpu::Extent3d {
                width: SHADOW_SIZE,
                height: SHADOW_SIZE,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: wgpu::TextureFormat::Depth32Float,
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::TEXTURE_BINDING,
            view_formats: &[],
        });
        let view = texture.create_view(&Default::default());
        let sampler = device.create_sampler(&wgpu::SamplerDescriptor {
            label: Some("preview shadow comparison"),
            compare: Some(wgpu::CompareFunction::LessEqual),
            mag_filter: wgpu::FilterMode::Linear,
            min_filter: wgpu::FilterMode::Linear,
            ..Default::default()
        });
        // The depth pass uses a separate light-camera binding. It must never
        // bind the shadow texture while that same texture is its attachment.
        let pipeline_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("preview shadow depth layout"),
            bind_group_layouts: &[Some(material_layout), Some(camera_layout)],
            immediate_size: 0,
        });
        let pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("preview key shadow caster"),
            layout: Some(&pipeline_layout),
            vertex: wgpu::VertexState {
                module: shader,
                entry_point: Some("vs_main"),
                compilation_options: Default::default(),
                buffers: &[Some(GpuVertex::layout())],
            },
            fragment: Some(wgpu::FragmentState {
                module: shader,
                entry_point: Some("fs_shadow"),
                compilation_options: Default::default(),
                targets: &[],
            }),
            primitive: wgpu::PrimitiveState {
                topology: wgpu::PrimitiveTopology::TriangleList,
                cull_mode: None,
                ..Default::default()
            },
            depth_stencil: Some(wgpu::DepthStencilState {
                format: wgpu::TextureFormat::Depth32Float,
                depth_write_enabled: Some(true),
                depth_compare: Some(wgpu::CompareFunction::LessEqual),
                stencil: Default::default(),
                bias: wgpu::DepthBiasState {
                    constant: 2,
                    slope_scale: 1.5,
                    clamp: 0.0,
                },
            }),
            multisample: Default::default(),
            multiview_mask: None,
            cache: None,
        });
        Self {
            _texture: texture,
            view,
            sampler,
            layout: shadow_layout(device),
            camera_layout: camera_layout.clone(),
            pipeline,
        }
    }

    #[allow(clippy::too_many_arguments)]
    pub(super) fn frame(
        &self,
        device: &wgpu::Device,
        encoder: &mut wgpu::CommandEncoder,
        mesh: &GpuMeshBuffers,
        default: &GpuMaterialBinding,
        materials: &BTreeMap<u32, GpuMaterialBinding>,
        camera: &CameraUniform,
        mode: ViewMode,
        settings: LightingDepthSettings,
    ) -> ShadowFrame {
        let (light, center, radius) = mesh.lighting_bounds.fit(camera, &mesh.material_ranges);
        let enabled = settings.shadows && textured(mode) && shadow_supported(device);
        let parameters = ShadowUniform {
            light_view_projection: light.to_cols_array_2d(),
            center_radius: center.extend(radius).to_array(),
            enabled: [
                u32::from(enabled),
                u32::from(settings.ambient_occlusion && textured(mode)),
                0,
                0,
            ],
        };
        let buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("preview shadow parameters"),
            contents: bytemuck::bytes_of(&parameters),
            usage: wgpu::BufferUsages::UNIFORM,
        });
        let mut entries = vec![wgpu::BindGroupEntry {
            binding: 2,
            resource: buffer.as_entire_binding(),
        }];
        if shadow_supported(device) {
            entries.extend([
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: wgpu::BindingResource::TextureView(&self.view),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: wgpu::BindingResource::Sampler(&self.sampler),
                },
            ]);
        }
        let binding = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("preview shadow frame"),
            layout: &self.layout,
            entries: &entries,
        });
        if enabled {
            let mut light_camera = *camera;
            light_camera.view_projection = light.to_cols_array_2d();
            let camera_buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
                label: Some("preview shadow light camera"),
                contents: bytemuck::bytes_of(&light_camera),
                usage: wgpu::BufferUsages::UNIFORM,
            });
            let camera_binding = device.create_bind_group(&wgpu::BindGroupDescriptor {
                label: Some("preview shadow light camera"),
                layout: &self.camera_layout,
                entries: &[wgpu::BindGroupEntry {
                    binding: 0,
                    resource: camera_buffer.as_entire_binding(),
                }],
            });
            let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("preview key light shadow pass"),
                color_attachments: &[],
                depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                    view: &self.view,
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
            pass.set_pipeline(&self.pipeline);
            pass.set_bind_group(1, &camera_binding, &[]);
            pass.set_vertex_buffer(0, mesh.vertex.slice(..));
            pass.set_index_buffer(mesh.triangle_index.slice(..), wgpu::IndexFormat::Uint32);
            for range in &mesh.material_ranges {
                let material = materials.get(&range.material).unwrap_or(default);
                if material.alpha_blend || material.translucent {
                    continue;
                }
                pass.set_bind_group(0, &material.bind_group, &[]);
                pass.draw_indexed(
                    range.first_index..range.first_index + range.index_count,
                    0,
                    range.part_id..range.part_id + 1,
                );
            }
        }
        ShadowFrame { binding, radius }
    }
}

pub(super) struct AmbientOcclusion {
    layout: wgpu::BindGroupLayout,
    pipeline: wgpu::RenderPipeline,
}

impl AmbientOcclusion {
    pub(super) fn new(device: &wgpu::Device, format: wgpu::TextureFormat, samples: u32) -> Self {
        let layout = effect_depth::layout(device, samples);
        let source = include_str!("ambient_occlusion.wgsl")
            .replace(
                "DEPTH_TYPE",
                if samples > 1 {
                    "texture_depth_multisampled_2d"
                } else {
                    "texture_depth_2d"
                },
            )
            .replace(
                "LOAD_DEPTH",
                if samples > 1 {
                    "textureLoad(scene_depth,p,i32(sample_index))"
                } else {
                    "textureLoad(scene_depth,p,0)"
                },
            );
        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("preview ambient occlusion"),
            source: wgpu::ShaderSource::Wgsl(source.into()),
        });
        let pipeline_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("preview ambient occlusion"),
            bind_group_layouts: &[Some(&layout)],
            immediate_size: 0,
        });
        let pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("preview ambient occlusion"),
            layout: Some(&pipeline_layout),
            vertex: wgpu::VertexState {
                module: &shader,
                entry_point: Some("vs_ambient"),
                compilation_options: Default::default(),
                buffers: &[],
            },
            fragment: Some(wgpu::FragmentState {
                module: &shader,
                entry_point: Some("fs_ambient"),
                compilation_options: Default::default(),
                targets: &[Some(wgpu::ColorTargetState {
                    format,
                    write_mask: wgpu::ColorWrites::ALL,
                    blend: Some(wgpu::BlendState {
                        color: wgpu::BlendComponent {
                            src_factor: wgpu::BlendFactor::Zero,
                            dst_factor: wgpu::BlendFactor::Src,
                            operation: wgpu::BlendOperation::Add,
                        },
                        // Keep transparent icon backgrounds and material alpha intact.
                        alpha: wgpu::BlendComponent {
                            src_factor: wgpu::BlendFactor::Zero,
                            dst_factor: wgpu::BlendFactor::One,
                            operation: wgpu::BlendOperation::Add,
                        },
                    }),
                })],
            }),
            primitive: Default::default(),
            depth_stencil: None,
            multisample: wgpu::MultisampleState {
                count: samples,
                ..Default::default()
            },
            multiview_mask: None,
            cache: None,
        });
        Self { layout, pipeline }
    }

    #[allow(clippy::too_many_arguments)]
    pub(super) fn record(
        &self,
        device: &wgpu::Device,
        encoder: &mut wgpu::CommandEncoder,
        color: &wgpu::TextureView,
        resolve: Option<&wgpu::TextureView>,
        depth: &wgpu::TextureView,
        camera: &CameraUniform,
        radius: f32,
        size: [u32; 2],
        viewport: Option<[f32; 4]>,
        mode: ViewMode,
        settings: LightingDepthSettings,
    ) {
        if !settings.ambient_occlusion || !textured(mode) {
            return;
        }
        let [x, y, w, h] = viewport.unwrap_or([0.0, 0.0, size[0] as f32, size[1] as f32]);
        let x = x.clamp(0.0, size[0].saturating_sub(1) as f32);
        let y = y.clamp(0.0, size[1].saturating_sub(1) as f32);
        let w = w.max(1.0).min(size[0] as f32 - x);
        let h = h.max(1.0).min(size[1] as f32 - y);
        let mut parameters = Mat4::from_cols_array_2d(&camera.view_projection)
            .inverse()
            .to_cols_array()
            .to_vec();
        parameters.extend([x, y, w, h, radius, 0.0, 0.0, 0.0]);
        let buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("preview ambient parameters"),
            contents: bytemuck::cast_slice(&parameters),
            usage: wgpu::BufferUsages::UNIFORM,
        });
        let binding = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("preview ambient depth"),
            layout: &self.layout,
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
        });
        let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
            label: Some("preview ambient occlusion"),
            color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                view: color,
                resolve_target: resolve,
                depth_slice: None,
                ops: wgpu::Operations {
                    load: wgpu::LoadOp::Load,
                    store: wgpu::StoreOp::Store,
                },
            })],
            depth_stencil_attachment: None,
            timestamp_writes: None,
            occlusion_query_set: None,
            multiview_mask: None,
        });
        pass.set_viewport(x, y, w, h, 0.0, 1.0);
        pass.set_scissor_rect(
            x.floor() as u32,
            y.floor() as u32,
            ((x + w).ceil() - x.floor()) as u32,
            ((y + h).ceil() - y.floor()) as u32,
        );
        pass.set_pipeline(&self.pipeline);
        pass.set_bind_group(0, &binding, &[]);
        pass.draw(0..3, 0..1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn visible_bounds_follow_isolation_and_only_transform_editable_vertices() {
        let mut vertices = vec![GpuVertex::zeroed(); 6];
        for (index, vertex) in vertices.iter_mut().enumerate() {
            vertex.position = if index < 3 {
                [index as f32, 0.0, 0.0]
            } else {
                [100.0, index as f32, 0.0]
            };
            vertex.editable_role = u32::from(index < 3);
        }
        let bounds = SceneBounds::from_vertices(&vertices, &[0, 1, 2, 3, 4, 5], &[0, 1]);
        let range = |material| GpuMaterialRange {
            material,
            part_id: material,
            first_index: material * 3,
            index_count: 3,
        };
        let transform = Mat4::from_translation(Vec3::new(5.0, 0.0, 0.0));
        assert_eq!(
            bounds.world(transform, &[range(0)]),
            (Vec3::new(5.0, 0.0, 0.0), Vec3::new(7.0, 0.0, 0.0))
        );
        assert_eq!(
            bounds.world(transform, &[range(1)]),
            (Vec3::new(100.0, 3.0, 0.0), Vec3::new(100.0, 5.0, 0.0))
        );
    }

    #[test]
    fn depth_lighting_only_applies_to_lit_views() {
        assert!(textured(ViewMode::TexturedSolid) && textured(ViewMode::GameOutdoor));
        for mode in [
            ViewMode::BaseColor,
            ViewMode::NormalMap,
            ViewMode::MaterialResponse,
            ViewMode::PartId,
            ViewMode::BaseAlpha,
            ViewMode::UvChecker,
            ViewMode::LayerMask,
            ViewMode::Solid,
            ViewMode::SolidWire,
            ViewMode::Wireframe,
            ViewMode::Vertices,
            ViewMode::WireVertices,
            ViewMode::XRay,
        ] {
            assert!(!textured(mode));
        }
    }
}

/// Offscreen compatibility proof for single-sample/MSAA depth, orthographic
/// reconstruction, and the supported texture-binding limits.
#[doc(hidden)]
pub async fn verify_lighting_depth_compatibility(
    snapshot: &DrawSnapshot,
) -> Result<usize, RenderError> {
    let mut descriptor = wgpu::InstanceDescriptor::new_without_display_handle();
    descriptor.backends = wgpu::Backends::DX12;
    let instance = wgpu::Instance::new(descriptor);
    let adapter = instance
        .request_adapter(&wgpu::RequestAdapterOptions {
            power_preference: wgpu::PowerPreference::HighPerformance,
            compatible_surface: None,
            force_fallback_adapter: false,
            apply_limit_buckets: false,
        })
        .await
        .map_err(|_| RenderError::NoAdapter)?;
    let format = wgpu::TextureFormat::Rgba8UnormSrgb;
    let mut verified = 0;
    for limit in [16, 17, 32] {
        if adapter.limits().max_sampled_textures_per_shader_stage < limit {
            continue;
        }
        let (device, queue) = adapter
            .request_device(&wgpu::DeviceDescriptor {
                label: Some("lighting depth compatibility"),
                required_features: requested_renderer_features(adapter.features()),
                required_limits: wgpu::Limits {
                    max_sampled_textures_per_shader_stage: limit,
                    ..Default::default()
                },
                experimental_features: wgpu::ExperimentalFeatures::disabled(),
                memory_hints: wgpu::MemoryHints::MemoryUsage,
                trace: wgpu::Trace::Off,
            })
            .await
            .map_err(|error| RenderError::Device(error.to_string()))?;
        let scope = device.push_error_scope(wgpu::ErrorFilter::Validation);
        let textures = create_default_material_textures(&device, &queue);
        let texture_layout = create_texture_bind_group_layout(&device);
        let sampler = create_material_sampler(&device, 1);
        let material = create_material_bind_group(
            &device,
            &texture_layout,
            &sampler,
            &textures,
            &[],
            MaterialTextureIndices::default(),
            MaterialPreviewFactors::default(),
        );
        let camera_layout = create_camera_bind_group_layout(&device);
        let mut camera = CameraUniform::new(true);
        let camera_buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: None,
            contents: bytemuck::bytes_of(&camera),
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        });
        let camera_binding = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: None,
            layout: &camera_layout,
            entries: &[wgpu::BindGroupEntry {
                binding: 0,
                resource: camera_buffer.as_entire_binding(),
            }],
        });
        let mesh = GpuMeshBuffers::upload(&device, snapshot)?;
        let matrix = Mat4::orthographic_rh(-2.5, 2.5, -2.5, 2.5, 0.1, 20.0)
            * Mat4::look_at_rh(Vec3::new(0.0, 3.0, 6.0), Vec3::ZERO, Vec3::Y);
        for samples in [1, 4] {
            if !adapter
                .get_texture_format_features(format)
                .flags
                .sample_count_supported(samples)
            {
                continue;
            }
            let mut pipelines = create_pipelines_with_sample_count(
                &device,
                format,
                &texture_layout,
                &camera_layout,
                samples,
            );
            for mode in [ViewMode::TexturedSolid, ViewMode::BaseColor] {
                let mut images = Vec::new();
                for enabled in [false, true] {
                    pipelines.lighting_depth_settings = LightingDepthSettings {
                        shadows: enabled,
                        ambient_occlusion: enabled,
                    };
                    let (buffer, width, height) = render_headless_readback_at(
                        &device,
                        &queue,
                        format,
                        &mesh,
                        &material,
                        &BTreeMap::new(),
                        &camera_binding,
                        &pipelines,
                        &mut camera,
                        &camera_buffer,
                        mode,
                        128,
                        128,
                        matrix,
                        None,
                        false,
                        None,
                    );
                    images.push(read_headless_pixels(&device, &buffer, width, height)?);
                }
                let changed = changed_pixel_count(&images[0], &images[1])?;
                if (mode == ViewMode::TexturedSolid && changed == 0)
                    || (mode == ViewMode::BaseColor && changed != 0)
                {
                    return Err(RenderError::Device(format!(
                        "orthographic depth proof failed: limit={limit}, samples={samples}, mode={mode:?}, changed={changed}"
                    )));
                }
            }
            verified += 1;
        }
        if let Some(error) = scope.pop().await {
            return Err(RenderError::Device(error.to_string()));
        }
    }
    Ok(verified)
}
