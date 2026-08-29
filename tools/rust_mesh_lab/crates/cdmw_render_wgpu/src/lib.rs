#![forbid(unsafe_code)]

use bytemuck::{Pod, Zeroable};
use cdmw_mesh::DrawSnapshot;
use cdmw_texture::{DdsFormat, TextureRole, plan_2d_upload};
use std::sync::Arc;
use thiserror::Error;
use wgpu::util::DeviceExt;
use winit::dpi::PhysicalSize;
use winit::window::Window;

const SHADER: &str = r#"
struct VertexOut {
    @builtin(position) position: vec4<f32>,
    @location(0) color: vec3<f32>,
    @location(1) uv: vec2<f32>,
};

@group(0) @binding(0) var base_texture: texture_2d<f32>;
@group(0) @binding(1) var base_sampler: sampler;

@vertex
fn vs_main(
    @location(0) position: vec3<f32>,
    @location(1) normal: vec3<f32>,
    @location(2) uv: vec2<f32>,
) -> VertexOut {
    var out: VertexOut;
    out.position = vec4<f32>(position, 1.0);
    out.color = normal * 0.35 + vec3<f32>(0.55, 0.58, 0.65);
    out.uv = uv;
    return out;
}

@fragment
fn fs_main(input: VertexOut) -> @location(0) vec4<f32> {
    let texel = textureSample(base_texture, base_sampler, input.uv);
    return vec4<f32>(texel.rgb * input.color, texel.a);
}
"#;

#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
struct GpuVertex {
    position: [f32; 3],
    normal: [f32; 3],
    uv: [f32; 2],
}

impl GpuVertex {
    const ATTRIBUTES: [wgpu::VertexAttribute; 3] =
        wgpu::vertex_attr_array![0 => Float32x3, 1 => Float32x3, 2 => Float32x2];

    fn layout() -> wgpu::VertexBufferLayout<'static> {
        wgpu::VertexBufferLayout {
            array_stride: std::mem::size_of::<Self>() as wgpu::BufferAddress,
            step_mode: wgpu::VertexStepMode::Vertex,
            attributes: &Self::ATTRIBUTES,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AdapterReport {
    pub name: String,
    pub backend: String,
    pub device_type: String,
    pub driver: String,
    pub driver_info: String,
}

#[derive(Debug, Error)]
pub enum RenderError {
    #[error("no Direct3D 12 adapter is available")]
    NoAdapter,
    #[error("wgpu device request failed: {0}")]
    Device(String),
    #[error("window surface creation failed: {0}")]
    Surface(String),
    #[error("window surface has no supported format")]
    SurfaceFormat,
    #[error("surface frame failed: {0}")]
    SurfaceFrame(String),
    #[error("draw snapshot exceeds GPU index limits")]
    ResourceLimit,
    #[error("DDS texture upload failed: {0}")]
    Texture(String),
}

pub struct GpuMeshBuffers {
    vertex: wgpu::Buffer,
    index: wgpu::Buffer,
    index_count: u32,
    pub draw_revision: u64,
}

impl GpuMeshBuffers {
    pub fn upload(device: &wgpu::Device, snapshot: &DrawSnapshot) -> Result<Self, RenderError> {
        let (center, scale) = normalization(snapshot);
        let vertices = snapshot
            .positions
            .iter()
            .enumerate()
            .map(|(index, position)| {
                let normal = snapshot
                    .normals
                    .get(index)
                    .copied()
                    .unwrap_or([0.0, 1.0, 0.0]);
                let uv = snapshot.uvs.get(index).copied().unwrap_or([0.0, 0.0]);
                GpuVertex {
                    position: [
                        (position[0] - center[0]) * scale,
                        (position[1] - center[1]) * scale,
                        (position[2] - center[2]) * scale * 0.1,
                    ],
                    normal,
                    uv,
                }
            })
            .collect::<Vec<_>>();
        let vertex = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("CDMW Rust Mesh Lab vertices"),
            contents: bytemuck::cast_slice(&vertices),
            usage: wgpu::BufferUsages::VERTEX,
        });
        let index = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("CDMW Rust Mesh Lab indices"),
            contents: bytemuck::cast_slice(&snapshot.indices),
            usage: wgpu::BufferUsages::INDEX,
        });
        Ok(Self {
            vertex,
            index,
            index_count: u32::try_from(snapshot.indices.len())
                .map_err(|_| RenderError::ResourceLimit)?,
            draw_revision: snapshot.draw_revision,
        })
    }
}

pub struct WindowRenderer {
    _instance: wgpu::Instance,
    surface: wgpu::Surface<'static>,
    adapter: wgpu::Adapter,
    device: wgpu::Device,
    queue: wgpu::Queue,
    config: wgpu::SurfaceConfiguration,
    pipeline: wgpu::RenderPipeline,
    mesh: Option<GpuMeshBuffers>,
    egui_renderer: egui_wgpu::Renderer,
    texture_bind_group_layout: wgpu::BindGroupLayout,
    texture_bind_group: wgpu::BindGroup,
    material_texture: wgpu::Texture,
    mesh_viewport: Option<[f32; 4]>,
}

impl WindowRenderer {
    pub async fn new(window: Arc<Window>) -> Result<Self, RenderError> {
        let mut instance_descriptor = wgpu::InstanceDescriptor::new_without_display_handle();
        instance_descriptor.backends = wgpu::Backends::DX12;
        let instance = wgpu::Instance::new(instance_descriptor);
        let surface = instance
            .create_surface(window.clone())
            .map_err(|error| RenderError::Surface(error.to_string()))?;
        let adapter = instance
            .request_adapter(&wgpu::RequestAdapterOptions {
                power_preference: wgpu::PowerPreference::HighPerformance,
                force_fallback_adapter: false,
                compatible_surface: Some(&surface),
                apply_limit_buckets: false,
            })
            .await
            .map_err(|_| RenderError::NoAdapter)?;
        let required_features = if adapter
            .features()
            .contains(wgpu::Features::TEXTURE_COMPRESSION_BC)
        {
            wgpu::Features::TEXTURE_COMPRESSION_BC
        } else {
            wgpu::Features::empty()
        };
        let (device, queue) = adapter
            .request_device(&wgpu::DeviceDescriptor {
                label: Some("CDMW Rust Mesh Lab device"),
                required_features,
                required_limits: wgpu::Limits::default(),
                experimental_features: wgpu::ExperimentalFeatures::disabled(),
                memory_hints: wgpu::MemoryHints::Performance,
                trace: wgpu::Trace::Off,
            })
            .await
            .map_err(|error| RenderError::Device(error.to_string()))?;
        let size = window.inner_size();
        let capabilities = surface.get_capabilities(&adapter);
        let format = capabilities
            .formats
            .iter()
            .copied()
            .find(|format| {
                matches!(
                    format,
                    wgpu::TextureFormat::Rgba8Unorm | wgpu::TextureFormat::Bgra8Unorm
                )
            })
            .or_else(|| capabilities.formats.first().copied())
            .ok_or(RenderError::SurfaceFormat)?;
        let present_mode = capabilities
            .present_modes
            .iter()
            .copied()
            .find(|mode| *mode == wgpu::PresentMode::Fifo)
            .or_else(|| capabilities.present_modes.first().copied())
            .ok_or(RenderError::SurfaceFormat)?;
        let alpha_mode = capabilities
            .alpha_modes
            .first()
            .copied()
            .ok_or(RenderError::SurfaceFormat)?;
        let config = wgpu::SurfaceConfiguration {
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT,
            format,
            color_space: wgpu::SurfaceColorSpace::Auto,
            width: size.width.max(1),
            height: size.height.max(1),
            present_mode,
            alpha_mode,
            view_formats: Vec::new(),
            desired_maximum_frame_latency: 2,
        };
        surface.configure(&device, &config);
        let texture_bind_group_layout = create_texture_bind_group_layout(&device);
        let (material_texture, texture_bind_group) =
            create_default_texture(&device, &queue, &texture_bind_group_layout);
        let pipeline = create_pipeline(&device, format, &texture_bind_group_layout);
        let egui_renderer =
            egui_wgpu::Renderer::new(&device, format, egui_wgpu::RendererOptions::default());
        Ok(Self {
            _instance: instance,
            surface,
            adapter,
            device,
            queue,
            config,
            pipeline,
            mesh: None,
            egui_renderer,
            texture_bind_group_layout,
            texture_bind_group,
            material_texture,
            mesh_viewport: None,
        })
    }

    #[must_use]
    pub fn adapter_report(&self) -> AdapterReport {
        let info = self.adapter.get_info();
        AdapterReport {
            name: info.name,
            backend: format!("{:?}", info.backend),
            device_type: format!("{:?}", info.device_type),
            driver: info.driver,
            driver_info: info.driver_info,
        }
    }

    pub fn set_snapshot(&mut self, snapshot: &DrawSnapshot) -> Result<(), RenderError> {
        self.mesh = Some(GpuMeshBuffers::upload(&self.device, snapshot)?);
        Ok(())
    }

    pub fn set_dds_texture(&mut self, bytes: &[u8], role: TextureRole) -> Result<(), RenderError> {
        let plan =
            plan_2d_upload(bytes, role).map_err(|error| RenderError::Texture(error.to_string()))?;
        let format = map_dds_format(&plan.metadata.format)?;
        if format.is_compressed()
            && !self
                .device
                .features()
                .contains(wgpu::Features::TEXTURE_COMPRESSION_BC)
        {
            return Err(RenderError::Texture(
                "selected adapter does not support BC texture upload".to_owned(),
            ));
        }
        let texture = self.device.create_texture(&wgpu::TextureDescriptor {
            label: Some("CDMW Rust Mesh Lab DDS"),
            size: wgpu::Extent3d {
                width: plan.metadata.width,
                height: plan.metadata.height,
                depth_or_array_layers: 1,
            },
            mip_level_count: plan.metadata.mip_count,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format,
            usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
            view_formats: &[],
        });
        for level in &plan.levels {
            let data = bytes
                .get(level.byte_offset..level.byte_offset.saturating_add(level.byte_length))
                .ok_or_else(|| RenderError::Texture("DDS upload slice is truncated".to_owned()))?;
            self.queue.write_texture(
                wgpu::TexelCopyTextureInfo {
                    texture: &texture,
                    mip_level: level.level,
                    origin: wgpu::Origin3d::ZERO,
                    aspect: wgpu::TextureAspect::All,
                },
                data,
                wgpu::TexelCopyBufferLayout {
                    offset: 0,
                    bytes_per_row: Some(level.bytes_per_row),
                    rows_per_image: Some(level.rows_per_image),
                },
                wgpu::Extent3d {
                    width: level.width,
                    height: level.height,
                    depth_or_array_layers: 1,
                },
            );
        }
        self.texture_bind_group =
            create_texture_bind_group(&self.device, &self.texture_bind_group_layout, &texture);
        self.material_texture = texture;
        Ok(())
    }

    pub fn reset_texture(&mut self) {
        let (texture, bind_group) =
            create_default_texture(&self.device, &self.queue, &self.texture_bind_group_layout);
        self.material_texture = texture;
        self.texture_bind_group = bind_group;
    }

    pub fn set_mesh_viewport(&mut self, viewport: Option<[f32; 4]>) {
        self.mesh_viewport = viewport;
    }

    pub fn resize(&mut self, size: PhysicalSize<u32>) {
        if size.width == 0 || size.height == 0 {
            return;
        }
        self.config.width = size.width;
        self.config.height = size.height;
        self.surface.configure(&self.device, &self.config);
    }

    pub fn render(&mut self) -> Result<(), RenderError> {
        self.render_frame(&[], None)
    }

    pub fn render_egui(
        &mut self,
        paint_jobs: &[egui::ClippedPrimitive],
        textures: &egui::TexturesDelta,
        pixels_per_point: f32,
    ) -> Result<(), RenderError> {
        self.render_frame(paint_jobs, Some((textures, pixels_per_point)))
    }

    fn render_frame(
        &mut self,
        paint_jobs: &[egui::ClippedPrimitive],
        egui_frame: Option<(&egui::TexturesDelta, f32)>,
    ) -> Result<(), RenderError> {
        let frame = match self.surface.get_current_texture() {
            wgpu::CurrentSurfaceTexture::Success(frame) => frame,
            wgpu::CurrentSurfaceTexture::Suboptimal(frame) => {
                self.surface.configure(&self.device, &self.config);
                frame
            }
            wgpu::CurrentSurfaceTexture::Timeout => {
                return Err(RenderError::SurfaceFrame("timeout".to_owned()));
            }
            wgpu::CurrentSurfaceTexture::Occluded => {
                return Err(RenderError::SurfaceFrame("occluded".to_owned()));
            }
            wgpu::CurrentSurfaceTexture::Outdated => {
                self.surface.configure(&self.device, &self.config);
                return Err(RenderError::SurfaceFrame("outdated".to_owned()));
            }
            wgpu::CurrentSurfaceTexture::Lost => {
                return Err(RenderError::SurfaceFrame("lost".to_owned()));
            }
            wgpu::CurrentSurfaceTexture::Validation => {
                return Err(RenderError::SurfaceFrame("validation".to_owned()));
            }
        };
        let view = frame
            .texture
            .create_view(&wgpu::TextureViewDescriptor::default());
        let mut encoder = self
            .device
            .create_command_encoder(&wgpu::CommandEncoderDescriptor {
                label: Some("CDMW Rust Mesh Lab frame"),
            });
        let screen_descriptor =
            egui_frame.map(|(_, pixels_per_point)| egui_wgpu::ScreenDescriptor {
                size_in_pixels: [self.config.width, self.config.height],
                pixels_per_point,
            });
        let mut command_buffers = Vec::new();
        if let Some((textures, _)) = egui_frame {
            for (id, deltas) in &textures.set {
                for delta in deltas {
                    self.egui_renderer
                        .update_texture(&self.device, &self.queue, *id, delta);
                }
            }
            if let Some(descriptor) = &screen_descriptor {
                command_buffers = self.egui_renderer.update_buffers(
                    &self.device,
                    &self.queue,
                    &mut encoder,
                    paint_jobs,
                    descriptor,
                );
            }
        }
        {
            let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("CDMW Rust Mesh Lab viewport"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &view,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(wgpu::Color {
                            r: 0.025,
                            g: 0.03,
                            b: 0.04,
                            a: 1.0,
                        }),
                        store: wgpu::StoreOp::Store,
                    },
                    depth_slice: None,
                })],
                depth_stencil_attachment: None,
                timestamp_writes: None,
                occlusion_query_set: None,
                multiview_mask: None,
            });
            if let Some(mesh) = &self.mesh {
                pass.set_pipeline(&self.pipeline);
                if let Some([x, y, width, height]) = self.mesh_viewport {
                    pass.set_viewport(x, y, width.max(1.0), height.max(1.0), 0.0, 1.0);
                    pass.set_scissor_rect(
                        x.max(0.0) as u32,
                        y.max(0.0) as u32,
                        width.max(1.0) as u32,
                        height.max(1.0) as u32,
                    );
                }
                pass.set_bind_group(0, &self.texture_bind_group, &[]);
                pass.set_vertex_buffer(0, mesh.vertex.slice(..));
                pass.set_index_buffer(mesh.index.slice(..), wgpu::IndexFormat::Uint32);
                pass.draw_indexed(0..mesh.index_count, 0, 0..1);
            }
            if let Some(descriptor) = &screen_descriptor {
                self.egui_renderer
                    .render(&mut pass.forget_lifetime(), paint_jobs, descriptor);
            }
        }
        command_buffers.push(encoder.finish());
        self.queue.submit(command_buffers);
        self.queue.present(frame);
        if let Some((textures, _)) = egui_frame {
            for id in &textures.free {
                self.egui_renderer.free_texture(id);
            }
        }
        Ok(())
    }
}

fn create_pipeline(
    device: &wgpu::Device,
    format: wgpu::TextureFormat,
    texture_layout: &wgpu::BindGroupLayout,
) -> wgpu::RenderPipeline {
    let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
        label: Some("CDMW Rust Mesh Lab shader"),
        source: wgpu::ShaderSource::Wgsl(SHADER.into()),
    });
    let layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
        label: Some("CDMW Rust Mesh Lab pipeline layout"),
        bind_group_layouts: &[Some(texture_layout)],
        immediate_size: 0,
    });
    device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
        label: Some("CDMW Rust Mesh Lab pipeline"),
        layout: Some(&layout),
        vertex: wgpu::VertexState {
            module: &shader,
            entry_point: Some("vs_main"),
            compilation_options: wgpu::PipelineCompilationOptions::default(),
            buffers: &[Some(GpuVertex::layout())],
        },
        primitive: wgpu::PrimitiveState {
            topology: wgpu::PrimitiveTopology::TriangleList,
            cull_mode: Some(wgpu::Face::Back),
            front_face: wgpu::FrontFace::Ccw,
            ..Default::default()
        },
        depth_stencil: None,
        multisample: wgpu::MultisampleState::default(),
        fragment: Some(wgpu::FragmentState {
            module: &shader,
            entry_point: Some("fs_main"),
            compilation_options: wgpu::PipelineCompilationOptions::default(),
            targets: &[Some(wgpu::ColorTargetState {
                format,
                blend: Some(wgpu::BlendState::REPLACE),
                write_mask: wgpu::ColorWrites::ALL,
            })],
        }),
        multiview_mask: None,
        cache: None,
    })
}

fn create_texture_bind_group_layout(device: &wgpu::Device) -> wgpu::BindGroupLayout {
    device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
        label: Some("CDMW Rust Mesh Lab texture layout"),
        entries: &[
            wgpu::BindGroupLayoutEntry {
                binding: 0,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Texture {
                    sample_type: wgpu::TextureSampleType::Float { filterable: true },
                    view_dimension: wgpu::TextureViewDimension::D2,
                    multisampled: false,
                },
                count: None,
            },
            wgpu::BindGroupLayoutEntry {
                binding: 1,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
                count: None,
            },
        ],
    })
}

fn create_default_texture(
    device: &wgpu::Device,
    queue: &wgpu::Queue,
    layout: &wgpu::BindGroupLayout,
) -> (wgpu::Texture, wgpu::BindGroup) {
    let texture = device.create_texture(&wgpu::TextureDescriptor {
        label: Some("CDMW Rust Mesh Lab default texture"),
        size: wgpu::Extent3d {
            width: 1,
            height: 1,
            depth_or_array_layers: 1,
        },
        mip_level_count: 1,
        sample_count: 1,
        dimension: wgpu::TextureDimension::D2,
        format: wgpu::TextureFormat::Rgba8UnormSrgb,
        usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
        view_formats: &[],
    });
    queue.write_texture(
        wgpu::TexelCopyTextureInfo {
            texture: &texture,
            mip_level: 0,
            origin: wgpu::Origin3d::ZERO,
            aspect: wgpu::TextureAspect::All,
        },
        &[210, 215, 225, 255],
        wgpu::TexelCopyBufferLayout {
            offset: 0,
            bytes_per_row: Some(4),
            rows_per_image: Some(1),
        },
        wgpu::Extent3d {
            width: 1,
            height: 1,
            depth_or_array_layers: 1,
        },
    );
    let bind_group = create_texture_bind_group(device, layout, &texture);
    (texture, bind_group)
}

fn create_texture_bind_group(
    device: &wgpu::Device,
    layout: &wgpu::BindGroupLayout,
    texture: &wgpu::Texture,
) -> wgpu::BindGroup {
    let view = texture.create_view(&wgpu::TextureViewDescriptor::default());
    let sampler = device.create_sampler(&wgpu::SamplerDescriptor {
        label: Some("CDMW Rust Mesh Lab texture sampler"),
        address_mode_u: wgpu::AddressMode::Repeat,
        address_mode_v: wgpu::AddressMode::Repeat,
        address_mode_w: wgpu::AddressMode::Repeat,
        mag_filter: wgpu::FilterMode::Linear,
        min_filter: wgpu::FilterMode::Linear,
        mipmap_filter: wgpu::MipmapFilterMode::Linear,
        ..Default::default()
    });
    device.create_bind_group(&wgpu::BindGroupDescriptor {
        label: Some("CDMW Rust Mesh Lab texture bind group"),
        layout,
        entries: &[
            wgpu::BindGroupEntry {
                binding: 0,
                resource: wgpu::BindingResource::TextureView(&view),
            },
            wgpu::BindGroupEntry {
                binding: 1,
                resource: wgpu::BindingResource::Sampler(&sampler),
            },
        ],
    })
}

fn map_dds_format(format: &DdsFormat) -> Result<wgpu::TextureFormat, RenderError> {
    let mapped = match format {
        DdsFormat::Bc1Unorm => wgpu::TextureFormat::Bc1RgbaUnorm,
        DdsFormat::Bc1Srgb => wgpu::TextureFormat::Bc1RgbaUnormSrgb,
        DdsFormat::Bc2Unorm => wgpu::TextureFormat::Bc2RgbaUnorm,
        DdsFormat::Bc2Srgb => wgpu::TextureFormat::Bc2RgbaUnormSrgb,
        DdsFormat::Bc3Unorm => wgpu::TextureFormat::Bc3RgbaUnorm,
        DdsFormat::Bc3Srgb => wgpu::TextureFormat::Bc3RgbaUnormSrgb,
        DdsFormat::Bc4Unorm => wgpu::TextureFormat::Bc4RUnorm,
        DdsFormat::Bc4Snorm => wgpu::TextureFormat::Bc4RSnorm,
        DdsFormat::Bc5Unorm => wgpu::TextureFormat::Bc5RgUnorm,
        DdsFormat::Bc5Snorm => wgpu::TextureFormat::Bc5RgSnorm,
        DdsFormat::Bc6hUnsignedFloat => wgpu::TextureFormat::Bc6hRgbUfloat,
        DdsFormat::Bc6hSignedFloat => wgpu::TextureFormat::Bc6hRgbFloat,
        DdsFormat::Bc7Unorm => wgpu::TextureFormat::Bc7RgbaUnorm,
        DdsFormat::Bc7Srgb => wgpu::TextureFormat::Bc7RgbaUnormSrgb,
        DdsFormat::R8Unorm => wgpu::TextureFormat::R8Unorm,
        DdsFormat::Rg8Unorm => wgpu::TextureFormat::Rg8Unorm,
        DdsFormat::Rgba8Unorm => wgpu::TextureFormat::Rgba8Unorm,
        DdsFormat::Rgba8Srgb => wgpu::TextureFormat::Rgba8UnormSrgb,
        DdsFormat::Bgra8Unorm => wgpu::TextureFormat::Bgra8Unorm,
        DdsFormat::Bgra8Srgb => wgpu::TextureFormat::Bgra8UnormSrgb,
        DdsFormat::Rgba16Float => wgpu::TextureFormat::Rgba16Float,
        DdsFormat::Rgba32Float => wgpu::TextureFormat::Rgba32Float,
        DdsFormat::Unknown { .. } => {
            return Err(RenderError::Texture(
                "DDS format is not mapped to wgpu".to_owned(),
            ));
        }
    };
    Ok(mapped)
}

fn normalization(snapshot: &DrawSnapshot) -> ([f32; 3], f32) {
    let mut minimum = [f32::INFINITY; 3];
    let mut maximum = [f32::NEG_INFINITY; 3];
    for position in &snapshot.positions {
        for axis in 0..3 {
            minimum[axis] = minimum[axis].min(position[axis]);
            maximum[axis] = maximum[axis].max(position[axis]);
        }
    }
    if snapshot.positions.is_empty() {
        return ([0.0; 3], 1.0);
    }
    let center = [
        (minimum[0] + maximum[0]) * 0.5,
        (minimum[1] + maximum[1]) * 0.5,
        (minimum[2] + maximum[2]) * 0.5,
    ];
    let extent = (maximum[0] - minimum[0])
        .max(maximum[1] - minimum[1])
        .max(maximum[2] - minimum[2])
        .max(1.0e-6);
    (center, 1.8 / extent)
}
