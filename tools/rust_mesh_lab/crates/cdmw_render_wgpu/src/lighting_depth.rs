//! Shadow and ambient-depth resources shared by window and headless recorders.
use super::*;
use std::cell::{Cell, RefCell};

pub(super) const SHADOW_SIZE: u32 = 4096;
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

    /// World-space bounds of the visible parts, as the shadow fit uses them.
    pub(super) fn world_bounds(
        &self,
        camera: &CameraUniform,
        visible: &[GpuMaterialRange],
    ) -> (Vec3, Vec3) {
        self.world(Mat4::from_cols_array_2d(&camera.scene_model), visible)
    }

    fn fit(
        &self,
        camera: &CameraUniform,
        visible: &[GpuMaterialRange],
        look: environment_ibl::StudioLookSettings,
    ) -> (Mat4, Vec3, f32) {
        let (low, high) = self.world(Mat4::from_cols_array_2d(&camera.scene_model), visible);
        let center = (low + high) * 0.5;
        let radius = ((high - low).length() * 0.6).max(0.1);
        let mut light = key_direction(camera);
        if camera.lighting_preset == 3 {
            light = look.rotate_world_direction(light);
        }
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
    if camera.lighting_preset == 3 {
        return Vec3::new(-0.45, 0.8, -0.55).normalize();
    }
    let view = Vec3::from_slice(&camera.view_direction).normalize_or(-Vec3::Z);
    let right = Vec3::from_slice(&camera.camera_right).normalize_or(Vec3::X);
    let up = Vec3::from_slice(&camera.camera_up).normalize_or(Vec3::Y);
    if camera.lighting_preset == 4 {
        return crate::icon_studio::key_direction(view);
    }
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

pub(super) fn env_ibl_supported(device: &wgpu::Device) -> bool {
    device.limits().max_sampled_textures_per_shader_stage >= 18
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
                binding: 4,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Buffer {
                    ty: wgpu::BufferBindingType::Uniform,
                    has_dynamic_offset: false,
                    min_binding_size: None,
                },
                count: None,
            },
            wgpu::BindGroupLayoutEntry {
                binding: 0,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Texture {
                    sample_type: wgpu::TextureSampleType::Depth,
                    view_dimension: wgpu::TextureViewDimension::D2Array,
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
        if env_ibl_supported(device) {
            entries.extend([
                wgpu::BindGroupLayoutEntry {
                    binding: 5,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Texture {
                        sample_type: wgpu::TextureSampleType::Float { filterable: true },
                        view_dimension: wgpu::TextureViewDimension::D2Array,
                        multisampled: false,
                    },
                    count: None,
                },
                wgpu::BindGroupLayoutEntry {
                    binding: 6,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
                    count: None,
                },
                wgpu::BindGroupLayoutEntry {
                    binding: 7,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Uniform,
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                    count: None,
                },
            ]);
        }
    }
    device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
        label: Some("preview shadow sampling"),
        entries: &entries,
    })
}

#[derive(Clone, Copy, PartialEq, Eq)]
struct ShadowCacheKey {
    mesh_id: u64,
    draw_revision: u64,
    topology_generation: u64,
    is_empty: bool,
    light_vp_bits: [[u32; 4]; 4],
    scene_model_bits: [[u32; 4]; 4],
    ranges_sig: u64,
}

#[derive(Clone, Copy, PartialEq, Eq)]
struct StudioDepthCacheKey {
    mesh_id: u64,
    draw_revision: u64,
    topology_generation: u64,
    is_empty: bool,
    view_vp_bits: [[u32; 4]; 4],
    scene_model_bits: [[u32; 4]; 4],
    ao_size_bits: [u32; 2],
    material_time_bits: u32,
    ranges_sig: u64,
}

pub(super) struct ShadowResources {
    _texture: wgpu::Texture,
    _view: wgpu::TextureView,
    shadow_attachment: wgpu::TextureView,
    studio_attachment: wgpu::TextureView,
    _sampler: wgpu::Sampler,
    env_ibl: Option<environment_ibl::GpuEnvironmentIbl>,
    pipeline: wgpu::RenderPipeline,
    fast_shadow_pipeline: wgpu::RenderPipeline,
    studio_depth_pipeline: wgpu::RenderPipeline,
    fast_depth_pipeline: wgpu::RenderPipeline,
    frame_bind_group: wgpu::BindGroup,
    shadow_uniform_buffer: wgpu::Buffer,
    studio_ao_uniform_buffer: Option<wgpu::Buffer>,
    env_uniform_buffer: Option<wgpu::Buffer>,
    last_env_look: Cell<Option<[u32; 4]>>,
    light_camera_buffer: wgpu::Buffer,
    light_camera_bind_group: wgpu::BindGroup,
    studio_camera_buffer: wgpu::Buffer,
    studio_camera_bind_group: wgpu::BindGroup,
    shadow_cache: RefCell<Option<ShadowCacheKey>>,
    studio_cache: RefCell<Option<StudioDepthCacheKey>>,
}

pub(super) struct ShadowFrame<'a> {
    pub(super) binding: &'a wgpu::BindGroup,
    pub(super) radius: f32,
}

impl ShadowResources {
    pub(super) fn new(
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        material_layout: &wgpu::BindGroupLayout,
        camera_layout: &wgpu::BindGroupLayout,
        shader: &wgpu::ShaderModule,
    ) -> Self {
        let texture = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("preview key shadow depth"),
            size: wgpu::Extent3d {
                width: SHADOW_SIZE,
                height: SHADOW_SIZE,
                depth_or_array_layers: 2,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: wgpu::TextureFormat::Depth32Float,
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::TEXTURE_BINDING,
            view_formats: &[],
        });
        let view = texture.create_view(&Default::default());
        let shadow_attachment = texture.create_view(&wgpu::TextureViewDescriptor {
            dimension: Some(wgpu::TextureViewDimension::D2),
            array_layer_count: Some(1),
            ..Default::default()
        });
        let studio_attachment = texture.create_view(&wgpu::TextureViewDescriptor {
            dimension: Some(wgpu::TextureViewDimension::D2),
            base_array_layer: 1,
            array_layer_count: Some(1),
            ..Default::default()
        });
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
        let fast_shadow_pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("preview key shadow caster (opaque depth-only)"),
            layout: Some(&pipeline_layout),
            vertex: wgpu::VertexState {
                module: shader,
                entry_point: Some("vs_main"),
                compilation_options: Default::default(),
                buffers: &[Some(GpuVertex::layout())],
            },
            fragment: None,
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
        let layer_layout = material_layers::layout(device);
        let mut studio_layouts = vec![Some(material_layout), Some(camera_layout)];
        if let Some(layer) = &layer_layout {
            studio_layouts.push(Some(layer));
        }
        let studio_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("fixed studio camera depth"),
            bind_group_layouts: &studio_layouts,
            immediate_size: 0,
        });
        let studio_shader=device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label:Some("fixed studio camera depth"),source:wgpu::ShaderSource::Wgsl(format!("{}\n@fragment fn fs_camera_depth(input:VertexOut,@builtin(front_facing) front_facing:bool) {{ let colour=shade_surface(input,front_facing,false,false); }}",material_layers::shader(device,false)).into()),
        });
        let studio_depth_pipeline =
            device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
                label: Some("fixed studio camera depth"),
                layout: Some(&studio_layout),
                vertex: wgpu::VertexState {
                    module: &studio_shader,
                    entry_point: Some("vs_main"),
                    compilation_options: Default::default(),
                    buffers: &[Some(GpuVertex::layout())],
                },
                fragment: Some(wgpu::FragmentState {
                    module: &studio_shader,
                    entry_point: Some("fs_camera_depth"),
                    compilation_options: Default::default(),
                    targets: &[],
                }),
                primitive: wgpu::PrimitiveState {
                    topology: wgpu::PrimitiveTopology::TriangleList,
                    cull_mode: None,
                    ..Default::default()
                },
                depth_stencil: Some(wgpu::DepthStencilState {
                    format: DEPTH_FORMAT,
                    depth_write_enabled: Some(true),
                    depth_compare: Some(wgpu::CompareFunction::LessEqual),
                    stencil: Default::default(),
                    bias: Default::default(),
                }),
                multisample: Default::default(),
                multiview_mask: None,
                cache: None,
            });
        let fast_depth_pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("fixed studio camera depth (opaque depth-only)"),
            layout: Some(&pipeline_layout),
            vertex: wgpu::VertexState {
                module: &studio_shader,
                entry_point: Some("vs_main"),
                compilation_options: Default::default(),
                buffers: &[Some(GpuVertex::layout())],
            },
            fragment: None,
            primitive: wgpu::PrimitiveState {
                topology: wgpu::PrimitiveTopology::TriangleList,
                cull_mode: None,
                ..Default::default()
            },
            depth_stencil: Some(wgpu::DepthStencilState {
                format: DEPTH_FORMAT,
                depth_write_enabled: Some(true),
                depth_compare: Some(wgpu::CompareFunction::LessEqual),
                stencil: Default::default(),
                bias: Default::default(),
            }),
            multisample: Default::default(),
            multiview_mask: None,
            cache: None,
        });
        let env_ibl = env_ibl_supported(device)
            .then(|| environment_ibl::GpuEnvironmentIbl::new(device, queue));
        let layout = shadow_layout(device);
        let shadow_uniform_buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("preview shadow parameters"),
            size: std::mem::size_of::<ShadowUniform>() as u64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let studio_ao_uniform_buffer = shadow_supported(device).then(|| {
            device.create_buffer(&wgpu::BufferDescriptor {
                label: Some("fixed studio ambient parameters"),
                size: (28 * std::mem::size_of::<f32>()) as u64,
                usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
                mapped_at_creation: false,
            })
        });
        let env_uniform_buffer = env_ibl.as_ref().map(|_| {
            environment_ibl::GpuEnvironmentIbl::create_uniform_buffer(
                device,
                environment_ibl::StudioLookSettings::default(),
            )
        });
        let mut frame_entries = vec![wgpu::BindGroupEntry {
            binding: 2,
            resource: shadow_uniform_buffer.as_entire_binding(),
        }];
        if let Some(ao_buffer) = &studio_ao_uniform_buffer {
            frame_entries.extend([
                wgpu::BindGroupEntry {
                    binding: 4,
                    resource: ao_buffer.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: wgpu::BindingResource::TextureView(&view),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: wgpu::BindingResource::Sampler(&sampler),
                },
            ]);
            if let (Some(env), Some(env_buffer)) = (&env_ibl, &env_uniform_buffer) {
                frame_entries.extend([
                    wgpu::BindGroupEntry {
                        binding: 5,
                        resource: wgpu::BindingResource::TextureView(&env.view),
                    },
                    wgpu::BindGroupEntry {
                        binding: 6,
                        resource: wgpu::BindingResource::Sampler(&env.sampler),
                    },
                    wgpu::BindGroupEntry {
                        binding: 7,
                        resource: env_buffer.as_entire_binding(),
                    },
                ]);
            }
        }
        let frame_bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("preview shadow frame"),
            layout: &layout,
            entries: &frame_entries,
        });
        let create_camera_uniform_and_group = |label: &str| {
            let buffer = device.create_buffer(&wgpu::BufferDescriptor {
                label: Some(label),
                size: std::mem::size_of::<CameraUniform>() as u64,
                usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
                mapped_at_creation: false,
            });
            let group = device.create_bind_group(&wgpu::BindGroupDescriptor {
                label: Some(label),
                layout: camera_layout,
                entries: &[wgpu::BindGroupEntry {
                    binding: 0,
                    resource: buffer.as_entire_binding(),
                }],
            });
            (buffer, group)
        };
        let (light_camera_buffer, light_camera_bind_group) =
            create_camera_uniform_and_group("preview shadow light camera");
        let (studio_camera_buffer, studio_camera_bind_group) =
            create_camera_uniform_and_group("fixed studio camera depth camera");
        let initial_look = env_uniform_buffer.as_ref().map(|_| {
            environment_ibl::StudioLookSettings::default()
                .look_uniform()
                .map(f32::to_bits)
        });
        Self {
            _texture: texture,
            _view: view,
            shadow_attachment,
            studio_attachment,
            _sampler: sampler,
            env_ibl,
            pipeline,
            fast_shadow_pipeline,
            studio_depth_pipeline,
            fast_depth_pipeline,
            frame_bind_group,
            shadow_uniform_buffer,
            studio_ao_uniform_buffer,
            env_uniform_buffer,
            last_env_look: Cell::new(initial_look),
            light_camera_buffer,
            light_camera_bind_group,
            studio_camera_buffer,
            studio_camera_bind_group,
            shadow_cache: RefCell::new(None),
            studio_cache: RefCell::new(None),
        }
    }

    #[allow(clippy::too_many_arguments)]
    pub(super) fn frame(
        &self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        encoder: &mut wgpu::CommandEncoder,
        mesh: &GpuMeshBuffers,
        default: &GpuMaterialBinding,
        materials: &BTreeMap<u32, GpuMaterialBinding>,
        camera: &CameraUniform,
        mode: ViewMode,
        settings: LightingDepthSettings,
        look: environment_ibl::StudioLookSettings,
        size: [u32; 2],
        viewport: Option<[f32; 4]>,
    ) -> ShadowFrame<'_> {
        let (light, center, radius) = mesh.lighting_bounds.fit(camera, &mesh.material_ranges, look);
        let enabled = settings.shadows && textured(mode) && shadow_supported(device);
        let studio_ao = camera.lighting_preset >= 3
            && settings.ambient_occlusion
            && textured(mode)
            && shadow_supported(device);
        let [x, y, w, h] = viewport.unwrap_or([0.0, 0.0, size[0] as f32, size[1] as f32]);
        let x = x.clamp(0.0, size[0].saturating_sub(1) as f32);
        let y = y.clamp(0.0, size[1].saturating_sub(1) as f32);
        let screen = [
            x,
            y,
            w.max(1.0).min(size[0] as f32 - x),
            h.max(1.0).min(size[1] as f32 - y),
        ];
        let ratio = (SHADOW_SIZE as f32 / screen[2].max(screen[3]).max(1.0)).min(1.0);
        let ao_width = (screen[2] * ratio).floor().max(1.0);
        let ao_height = (screen[3] * ratio).floor().max(1.0);
        let parameters = ShadowUniform {
            light_view_projection: light.to_cols_array_2d(),
            center_radius: center.extend(radius).to_array(),
            enabled: [
                u32::from(enabled),
                u32::from(settings.ambient_occlusion && textured(mode)),
                u32::from(studio_ao),
                0,
            ],
        };
        queue.write_buffer(&self.shadow_uniform_buffer, 0, bytemuck::bytes_of(&parameters));
        if let Some(ao_buffer) = &self.studio_ao_uniform_buffer {
            let inv_vp = Mat4::from_cols_array_2d(&camera.view_projection)
                .inverse()
                .to_cols_array();
            let mut ao_parameters = [0.0f32; 28];
            ao_parameters[..16].copy_from_slice(&inv_vp);
            ao_parameters[16] = 0.0;
            ao_parameters[17] = 0.0;
            ao_parameters[18] = ao_width;
            ao_parameters[19] = ao_height;
            ao_parameters[20] = radius;
            ao_parameters[24..28].copy_from_slice(&screen);
            queue.write_buffer(ao_buffer, 0, bytemuck::cast_slice(&ao_parameters));
        }
        if let (Some(_), Some(env_buffer)) = (&self.env_ibl, &self.env_uniform_buffer) {
            let look_key = look.look_uniform().map(f32::to_bits);
            if self.last_env_look.get() != Some(look_key) {
                let data = environment_ibl::cached_env_data();
                let uniform = environment_ibl::StudioEnvUniform {
                    sh_studio: data.sh_studio,
                    sh_outdoor: data.sh_outdoor,
                    look: look.look_uniform(),
                };
                queue.write_buffer(env_buffer, 0, bytemuck::bytes_of(&uniform));
                self.last_env_look.set(Some(look_key));
            }
        }
        let is_empty = mesh.vertex_count == 0 || mesh.triangle_index_count == 0;
        let mut shadow_hasher = DefaultHasher::new();
        let mut studio_hasher = DefaultHasher::new();
        let mut has_animated_discard = false;
        mesh.material_ranges.len().hash(&mut shadow_hasher);
        mesh.material_ranges.len().hash(&mut studio_hasher);
        for range in &mesh.material_ranges {
            let material = materials.get(&range.material).unwrap_or(default);
            if material.alpha_blend || material.translucent {
                continue;
            }
            range.material.hash(&mut shadow_hasher);
            range.first_index.hash(&mut shadow_hasher);
            range.index_count.hash(&mut shadow_hasher);
            range.part_id.hash(&mut shadow_hasher);
            material.id.hash(&mut shadow_hasher);
            material.flags.hash(&mut shadow_hasher);

            range.material.hash(&mut studio_hasher);
            range.first_index.hash(&mut studio_hasher);
            range.index_count.hash(&mut studio_hasher);
            range.part_id.hash(&mut studio_hasher);
            material.id.hash(&mut studio_hasher);
            material.flags.hash(&mut studio_hasher);
            material.can_discard.hash(&mut studio_hasher);
            if material.shader_discards {
                has_animated_discard = true;
            }
        }
        let scene_model_bits = camera.scene_model.map(|col| col.map(f32::to_bits));
        if enabled {
            let key = ShadowCacheKey {
                mesh_id: mesh.unique_id,
                draw_revision: mesh.draw_revision,
                topology_generation: mesh.topology_generation,
                is_empty,
                light_vp_bits: light.to_cols_array_2d().map(|col| col.map(f32::to_bits)),
                scene_model_bits,
                ranges_sig: shadow_hasher.finish(),
            };
            if *self.shadow_cache.borrow() != Some(key) {
                let mut light_camera = *camera;
                light_camera.view_projection = light.to_cols_array_2d();
                queue.write_buffer(&self.light_camera_buffer, 0, bytemuck::bytes_of(&light_camera));
                self.record_depth(
                    encoder,
                    mesh,
                    default,
                    materials,
                    &self.light_camera_bind_group,
                    &self.shadow_attachment,
                    false,
                    None,
                );
                *self.shadow_cache.borrow_mut() = Some(key);
            }
        } else {
            *self.shadow_cache.borrow_mut() = None;
        }
        if studio_ao {
            let key = StudioDepthCacheKey {
                mesh_id: mesh.unique_id,
                draw_revision: mesh.draw_revision,
                topology_generation: mesh.topology_generation,
                is_empty,
                view_vp_bits: camera.view_projection.map(|col| col.map(f32::to_bits)),
                scene_model_bits,
                ao_size_bits: [ao_width.to_bits(), ao_height.to_bits()],
                material_time_bits: if has_animated_discard {
                    camera.material_time.to_bits()
                } else {
                    0
                },
                ranges_sig: studio_hasher.finish(),
            };
            if *self.studio_cache.borrow() != Some(key) {
                let mut depth_camera = *camera;
                depth_camera.view_mode = ViewMode::BaseAlpha.shader_mode();
                queue.write_buffer(&self.studio_camera_buffer, 0, bytemuck::bytes_of(&depth_camera));
                self.record_depth(
                    encoder,
                    mesh,
                    default,
                    materials,
                    &self.studio_camera_bind_group,
                    &self.studio_attachment,
                    true,
                    Some([ao_width, ao_height]),
                );
                *self.studio_cache.borrow_mut() = Some(key);
            }
        } else {
            *self.studio_cache.borrow_mut() = None;
        }
        ShadowFrame {
            binding: &self.frame_bind_group,
            radius,
        }
    }

    #[allow(clippy::too_many_arguments)]
    fn record_depth(
        &self,
        encoder: &mut wgpu::CommandEncoder,
        mesh: &GpuMeshBuffers,
        default: &GpuMaterialBinding,
        materials: &BTreeMap<u32, GpuMaterialBinding>,
        camera_binding: &wgpu::BindGroup,
        view: &wgpu::TextureView,
        studio: bool,
        size: Option<[f32; 2]>,
    ) {
        let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
            label: Some(if studio {
                "fixed studio camera depth pass"
            } else {
                "preview key light shadow pass"
            }),
            color_attachments: &[],
            depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                view,
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
        // Still clear the old depth when every part has been hidden.
        if mesh.vertex_count == 0 || mesh.triangle_index_count == 0 {
            return;
        }
        let fast_pipeline = if studio {
            &self.fast_depth_pipeline
        } else {
            &self.fast_shadow_pipeline
        };
        let fragment_pipeline = if studio {
            &self.studio_depth_pipeline
        } else {
            &self.pipeline
        };
        if let Some([width, height]) = size {
            pass.set_viewport(0.0, 0.0, width, height, 0.0, 1.0);
        }
        pass.set_bind_group(1, camera_binding, &[]);
        pass.set_vertex_buffer(0, mesh.vertex.slice(..));
        pass.set_index_buffer(mesh.triangle_index.slice(..), wgpu::IndexFormat::Uint32);
        let mut using_fragment_pipeline: Option<bool> = None;
        for range in &mesh.material_ranges {
            let material = materials.get(&range.material).unwrap_or(default);
            if material.alpha_blend || material.translucent {
                continue;
            }
            let needs_fragment = if studio {
                material.can_discard
            } else {
                (material.flags & MATERIAL_ALPHA_CUTOUT) != 0
            };
            if using_fragment_pipeline != Some(needs_fragment) {
                pass.set_pipeline(if needs_fragment {
                    fragment_pipeline
                } else {
                    fast_pipeline
                });
                using_fragment_pipeline = Some(needs_fragment);
            }
            if studio && needs_fragment {
                material_layers::bind(&mut pass, material);
            } else {
                pass.set_bind_group(0, &material.bind_group, &[]);
            }
            pass.draw_indexed(
                range.first_index..range.first_index + range.index_count,
                0,
                range.part_id..range.part_id + 1,
            );
        }
    }
}

pub(super) struct AmbientOcclusion {
    layout: wgpu::BindGroupLayout,
    pipeline: wgpu::RenderPipeline,
    uniform_buffer: wgpu::Buffer,
    cached_binding: RefCell<Option<(u64, wgpu::BindGroup)>>,
}

impl AmbientOcclusion {
    pub(super) fn new(device: &wgpu::Device, format: wgpu::TextureFormat, samples: u32) -> Self {
        let layout = effect_depth::layout(device, samples);
        let source = include_str!("ambient_occlusion.wgsl")
            .replace("// AMBIENT_BINDINGS","@group(0) @binding(0) var scene_depth: DEPTH_TYPE;\n@group(0) @binding(1) var<uniform> ambient: AmbientParameters;")
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
            source: wgpu::ShaderSource::Wgsl(format!("{source}\n@fragment fn fs_ambient(@builtin(position) pixel:vec4<f32>,@builtin(sample_index) sample:u32) -> @location(0) vec4<f32> {{return vec4(vec3(ambient_visibility(pixel.xy,sample)),1.0);}}").into()),
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
        let uniform_buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("preview ambient parameters"),
            size: (28 * std::mem::size_of::<f32>()) as u64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        Self {
            layout,
            pipeline,
            uniform_buffer,
            cached_binding: RefCell::new(None),
        }
    }

    #[allow(clippy::too_many_arguments)]
    pub(super) fn record(
        &self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        encoder: &mut wgpu::CommandEncoder,
        color: &wgpu::TextureView,
        resolve: Option<&wgpu::TextureView>,
        depth: &wgpu::TextureView,
        depth_id: u64,
        camera: &CameraUniform,
        radius: f32,
        size: [u32; 2],
        viewport: Option<[f32; 4]>,
        mode: ViewMode,
        settings: LightingDepthSettings,
    ) {
        if !settings.ambient_occlusion
            || !textured(mode)
            || (camera.lighting_preset >= 3 && shadow_supported(device))
        {
            return;
        }
        let [x, y, w, h] = viewport.unwrap_or([0.0, 0.0, size[0] as f32, size[1] as f32]);
        let x = x.clamp(0.0, size[0].saturating_sub(1) as f32);
        let y = y.clamp(0.0, size[1].saturating_sub(1) as f32);
        let w = w.max(1.0).min(size[0] as f32 - x);
        let h = h.max(1.0).min(size[1] as f32 - y);
        let inv_vp = Mat4::from_cols_array_2d(&camera.view_projection)
            .inverse()
            .to_cols_array();
        let mut parameters = [0.0f32; 28];
        parameters[..16].copy_from_slice(&inv_vp);
        parameters[16] = x;
        parameters[17] = y;
        parameters[18] = w;
        parameters[19] = h;
        parameters[20] = radius;
        parameters[24] = x;
        parameters[25] = y;
        parameters[26] = w;
        parameters[27] = h;
        queue.write_buffer(&self.uniform_buffer, 0, bytemuck::cast_slice(&parameters));
        let mut cache = self.cached_binding.borrow_mut();
        if cache.as_ref().is_none_or(|(cached_id, _)| *cached_id != depth_id) {
            let group = device.create_bind_group(&wgpu::BindGroupDescriptor {
                label: Some("preview ambient depth"),
                layout: &self.layout,
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
        let binding = &cache.as_ref().expect("AO bind group cached").1;
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
        pass.set_bind_group(0, binding, &[]);
        pass.draw(0..3, 0..1);
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
                &queue,
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
    fn studio_key_stays_fixed_as_camera_orbits() {
        let mut camera = CameraUniform::new(true);
        camera.lighting_preset = LightingPreset::StudioFixed.shader_value();
        let expected = Vec3::new(-0.45, 0.8, -0.55).normalize();
        assert!(key_direction(&camera).abs_diff_eq(expected, 1e-6));
        camera.view_direction = [1.0, 0.0, 0.0, 0.0];
        camera.camera_right = [0.0, 0.0, 1.0, 0.0];
        assert!(key_direction(&camera).abs_diff_eq(expected, 1e-6));
        camera.lighting_preset = LightingPreset::NeutralStudio.shader_value();
        assert!(!key_direction(&camera).abs_diff_eq(expected, 0.1));
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
