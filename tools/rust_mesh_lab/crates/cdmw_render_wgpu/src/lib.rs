#![forbid(unsafe_code)]

use bytemuck::{Pod, Zeroable};
use cdmw_mesh::DrawSnapshot;
use cdmw_texture::{ColorSpace, DdsFormat, TextureRole, plan_2d_upload};
use glam::{Mat4, Vec3};
use std::collections::HashSet;
use std::sync::Arc;
use thiserror::Error;
use wgpu::util::DeviceExt;
use winit::dpi::PhysicalSize;
use winit::window::Window;

const SHADER: &str = r#"
struct CameraUniform {
    view_projection: mat4x4<f32>,
    solid_mode: u32,
    _padding_0: u32,
    _padding_1: u32,
    _padding_2: u32,
};

struct VertexOut {
    @builtin(position) position: vec4<f32>,
    @location(0) color: vec3<f32>,
    @location(1) uv: vec2<f32>,
};

@group(0) @binding(0) var base_texture: texture_2d<f32>;
@group(0) @binding(1) var base_sampler: sampler;
@group(1) @binding(0) var<uniform> camera: CameraUniform;

@vertex
fn vs_main(
    @location(0) position: vec3<f32>,
    @location(1) normal: vec3<f32>,
    @location(2) uv: vec2<f32>,
) -> VertexOut {
    var out: VertexOut;
    out.position = camera.view_projection * vec4<f32>(position, 1.0);
    out.color = normal * 0.35 + vec3<f32>(0.55, 0.58, 0.65);
    out.uv = uv;
    return out;
}

@fragment
fn fs_solid(input: VertexOut) -> @location(0) vec4<f32> {
    if camera.solid_mode == 1u {
        return vec4<f32>(input.color, 1.0);
    }
    let texel = textureSample(base_texture, base_sampler, input.uv);
    return vec4<f32>(texel.rgb * input.color, texel.a);
}

@fragment
fn fs_wire(_input: VertexOut) -> @location(0) vec4<f32> {
    return vec4<f32>(0.72, 0.78, 0.88, 1.0);
}

@fragment
fn fs_point(_input: VertexOut) -> @location(0) vec4<f32> {
    return vec4<f32>(0.92, 0.94, 1.0, 1.0);
}

@fragment
fn fs_xray(_input: VertexOut) -> @location(0) vec4<f32> {
    return vec4<f32>(0.20, 0.55, 0.92, 0.24);
}

@fragment
fn fs_normal(_input: VertexOut) -> @location(0) vec4<f32> {
    return vec4<f32>(0.15, 0.90, 0.75, 1.0);
}

@fragment
fn fs_bounds(_input: VertexOut) -> @location(0) vec4<f32> {
    return vec4<f32>(1.0, 0.70, 0.15, 1.0);
}
"#;

const DEPTH_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Depth32Float;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ViewMode {
    TexturedSolid,
    Solid,
    SolidWire,
    Wireframe,
    Vertices,
    WireVertices,
    XRay,
}

impl ViewMode {
    #[must_use]
    pub const fn label(self) -> &'static str {
        match self {
            Self::TexturedSolid => "Textured",
            Self::Solid => "Solid Faces",
            Self::SolidWire => "Solid + Wire",
            Self::Wireframe => "Wireframe",
            Self::Vertices => "Vertices",
            Self::WireVertices => "Wire + Vertices",
            Self::XRay => "X-Ray",
        }
    }
}

#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
struct CameraUniform {
    view_projection: [[f32; 4]; 4],
    solid_mode: u32,
    _padding: [u32; 3],
}

impl CameraUniform {
    fn new() -> Self {
        Self {
            view_projection: Mat4::IDENTITY.to_cols_array_2d(),
            solid_mode: 0,
            _padding: [0; 3],
        }
    }
}

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

    fn overlay(position: Vec3) -> Self {
        Self {
            position: position.to_array(),
            normal: Vec3::Y.to_array(),
            uv: [0.0, 0.0],
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

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HeadlessRenderReport {
    pub adapter: AdapterReport,
    pub frames_rendered: u32,
    pub modes_rendered: u32,
    pub viewport_sizes_rendered: u32,
    pub dds_textures_uploaded: u32,
    pub non_background_pixels: usize,
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
    triangle_index: wgpu::Buffer,
    wire_index: wgpu::Buffer,
    normal_lines: wgpu::Buffer,
    bounds_lines: wgpu::Buffer,
    triangle_index_count: u32,
    wire_index_count: u32,
    vertex_count: u32,
    normal_line_vertex_count: u32,
    bounds_line_vertex_count: u32,
    mesh_identity: u64,
    pub draw_revision: u64,
    pub topology_generation: u64,
}

impl GpuMeshBuffers {
    pub fn upload(device: &wgpu::Device, snapshot: &DrawSnapshot) -> Result<Self, RenderError> {
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
                    position: *position,
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
        let triangle_index = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("CDMW Rust Mesh Lab triangle indices"),
            contents: bytemuck::cast_slice(&snapshot.indices),
            usage: wgpu::BufferUsages::INDEX,
        });
        let wire_indices = unique_wire_indices(&snapshot.indices);
        let wire_index = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("CDMW Rust Mesh Lab wire indices"),
            contents: bytemuck::cast_slice(&wire_indices),
            usage: wgpu::BufferUsages::INDEX,
        });
        let normal_line_vertices = normal_line_vertices(snapshot);
        let normal_lines = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("CDMW Rust Mesh Lab normal lines"),
            contents: bytemuck::cast_slice(&normal_line_vertices),
            usage: wgpu::BufferUsages::VERTEX,
        });
        let bounds_line_vertices = bounds_line_vertices(&snapshot.positions);
        let bounds_lines = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("CDMW Rust Mesh Lab bounds lines"),
            contents: bytemuck::cast_slice(&bounds_line_vertices),
            usage: wgpu::BufferUsages::VERTEX,
        });
        Ok(Self {
            vertex,
            triangle_index,
            wire_index,
            normal_lines,
            bounds_lines,
            triangle_index_count: u32::try_from(snapshot.indices.len())
                .map_err(|_| RenderError::ResourceLimit)?,
            wire_index_count: u32::try_from(wire_indices.len())
                .map_err(|_| RenderError::ResourceLimit)?,
            vertex_count: u32::try_from(vertices.len()).map_err(|_| RenderError::ResourceLimit)?,
            normal_line_vertex_count: u32::try_from(normal_line_vertices.len())
                .map_err(|_| RenderError::ResourceLimit)?,
            bounds_line_vertex_count: u32::try_from(bounds_line_vertices.len())
                .map_err(|_| RenderError::ResourceLimit)?,
            mesh_identity: snapshot.mesh_identity,
            draw_revision: snapshot.draw_revision,
            topology_generation: snapshot.topology_generation,
        })
    }

    fn matches_snapshot(&self, snapshot: &DrawSnapshot) -> bool {
        self.mesh_identity == snapshot.mesh_identity
            && self.draw_revision == snapshot.draw_revision
            && self.topology_generation == snapshot.topology_generation
    }
}

struct DepthTarget {
    _texture: wgpu::Texture,
    view: wgpu::TextureView,
}

pub struct WindowRenderer {
    _instance: wgpu::Instance,
    surface: wgpu::Surface<'static>,
    adapter: wgpu::Adapter,
    device: wgpu::Device,
    queue: wgpu::Queue,
    config: wgpu::SurfaceConfiguration,
    solid_pipeline: wgpu::RenderPipeline,
    wire_pipeline: wgpu::RenderPipeline,
    point_pipeline: wgpu::RenderPipeline,
    xray_pipeline: wgpu::RenderPipeline,
    normal_pipeline: wgpu::RenderPipeline,
    bounds_pipeline: wgpu::RenderPipeline,
    mesh: Option<GpuMeshBuffers>,
    egui_renderer: egui_wgpu::Renderer,
    texture_bind_group_layout: wgpu::BindGroupLayout,
    texture_bind_group: wgpu::BindGroup,
    material_texture: wgpu::Texture,
    mesh_viewport: Option<[f32; 4]>,
    depth_target: DepthTarget,
    camera_uniform: CameraUniform,
    camera_buffer: wgpu::Buffer,
    camera_bind_group: wgpu::BindGroup,
    view_mode: ViewMode,
    show_normals: bool,
    show_bounds: bool,
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
        let camera_bind_group_layout = create_camera_bind_group_layout(&device);
        let camera_uniform = CameraUniform::new();
        let camera_buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("CDMW Rust Mesh Lab camera uniform"),
            contents: bytemuck::bytes_of(&camera_uniform),
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        });
        let camera_bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("CDMW Rust Mesh Lab camera bind group"),
            layout: &camera_bind_group_layout,
            entries: &[wgpu::BindGroupEntry {
                binding: 0,
                resource: camera_buffer.as_entire_binding(),
            }],
        });
        let pipelines = create_pipelines(
            &device,
            format,
            &texture_bind_group_layout,
            &camera_bind_group_layout,
        );
        let depth_target = create_depth_target(&device, config.width, config.height);
        let egui_renderer =
            egui_wgpu::Renderer::new(&device, format, egui_wgpu::RendererOptions::default());
        Ok(Self {
            _instance: instance,
            surface,
            adapter,
            device,
            queue,
            config,
            solid_pipeline: pipelines.solid,
            wire_pipeline: pipelines.wire,
            point_pipeline: pipelines.point,
            xray_pipeline: pipelines.xray,
            normal_pipeline: pipelines.normal,
            bounds_pipeline: pipelines.bounds,
            mesh: None,
            egui_renderer,
            texture_bind_group_layout,
            texture_bind_group,
            material_texture,
            mesh_viewport: None,
            depth_target,
            camera_uniform,
            camera_buffer,
            camera_bind_group,
            view_mode: ViewMode::TexturedSolid,
            show_normals: false,
            show_bounds: false,
        })
    }

    #[must_use]
    pub fn adapter_report(&self) -> AdapterReport {
        adapter_report(&self.adapter)
    }

    pub fn set_snapshot(&mut self, snapshot: &DrawSnapshot) -> Result<(), RenderError> {
        if self
            .mesh
            .as_ref()
            .is_some_and(|mesh| mesh.matches_snapshot(snapshot))
        {
            return Ok(());
        }
        self.mesh = Some(GpuMeshBuffers::upload(&self.device, snapshot)?);
        Ok(())
    }

    pub fn set_camera(&mut self, view_projection: Mat4) {
        self.camera_uniform.view_projection = view_projection.to_cols_array_2d();
        self.queue.write_buffer(
            &self.camera_buffer,
            0,
            bytemuck::bytes_of(&self.camera_uniform),
        );
    }

    pub fn set_view_mode(&mut self, view_mode: ViewMode) {
        if self.view_mode == view_mode {
            return;
        }
        self.view_mode = view_mode;
        self.camera_uniform.solid_mode = u32::from(view_mode != ViewMode::TexturedSolid);
        self.queue.write_buffer(
            &self.camera_buffer,
            0,
            bytemuck::bytes_of(&self.camera_uniform),
        );
    }

    pub fn set_overlays(&mut self, show_normals: bool, show_bounds: bool) {
        self.show_normals = show_normals;
        self.show_bounds = show_bounds;
    }

    pub fn set_dds_texture(&mut self, bytes: &[u8], role: TextureRole) -> Result<(), RenderError> {
        let texture = upload_dds_texture(&self.device, &self.queue, bytes, role)?;
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
        self.depth_target = create_depth_target(&self.device, size.width, size.height);
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
                depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                    view: &self.depth_target.view,
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
            if let Some(mesh) = &self.mesh {
                if let Some([x, y, width, height]) = self.mesh_viewport {
                    let maximum_x = self.config.width.saturating_sub(1) as f32;
                    let maximum_y = self.config.height.saturating_sub(1) as f32;
                    let x = x.clamp(0.0, maximum_x);
                    let y = y.clamp(0.0, maximum_y);
                    let width = width.max(1.0).min(self.config.width as f32 - x);
                    let height = height.max(1.0).min(self.config.height as f32 - y);
                    pass.set_viewport(x, y, width, height, 0.0, 1.0);
                    let scissor_x = x.floor() as u32;
                    let scissor_y = y.floor() as u32;
                    let scissor_right = (x + width).ceil().min(self.config.width as f32) as u32;
                    let scissor_bottom = (y + height).ceil().min(self.config.height as f32) as u32;
                    pass.set_scissor_rect(
                        scissor_x,
                        scissor_y,
                        scissor_right.saturating_sub(scissor_x).max(1),
                        scissor_bottom.saturating_sub(scissor_y).max(1),
                    );
                }
                draw_mesh(
                    &mut pass,
                    mesh,
                    &self.texture_bind_group,
                    &self.camera_bind_group,
                    &self.solid_pipeline,
                    &self.wire_pipeline,
                    &self.point_pipeline,
                    &self.xray_pipeline,
                    &self.normal_pipeline,
                    &self.bounds_pipeline,
                    self.view_mode,
                    self.show_normals,
                    self.show_bounds,
                );
            }
        }
        if let Some(descriptor) = &screen_descriptor {
            let ui_pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("CDMW Rust Mesh Lab egui"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &view,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Load,
                        store: wgpu::StoreOp::Store,
                    },
                    depth_slice: None,
                })],
                depth_stencil_attachment: None,
                timestamp_writes: None,
                occlusion_query_set: None,
                multiview_mask: None,
            });
            self.egui_renderer
                .render(&mut ui_pass.forget_lifetime(), paint_jobs, descriptor);
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

pub async fn run_headless_render_smoke(
    snapshot: &DrawSnapshot,
) -> Result<HeadlessRenderReport, RenderError> {
    let mut instance_descriptor = wgpu::InstanceDescriptor::new_without_display_handle();
    instance_descriptor.backends = wgpu::Backends::DX12;
    let instance = wgpu::Instance::new(instance_descriptor);
    let adapter = instance
        .request_adapter(&wgpu::RequestAdapterOptions {
            power_preference: wgpu::PowerPreference::HighPerformance,
            force_fallback_adapter: false,
            compatible_surface: None,
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
            label: Some("CDMW Rust Mesh Lab headless device"),
            required_features,
            required_limits: wgpu::Limits::default(),
            experimental_features: wgpu::ExperimentalFeatures::disabled(),
            memory_hints: wgpu::MemoryHints::Performance,
            trace: wgpu::Trace::Off,
        })
        .await
        .map_err(|error| RenderError::Device(error.to_string()))?;
    let error_scope = device.push_error_scope(wgpu::ErrorFilter::Validation);
    let format = wgpu::TextureFormat::Bgra8Unorm;
    let texture_layout = create_texture_bind_group_layout(&device);
    let material_texture = upload_dds_texture(
        &device,
        &queue,
        &cdmw_texture::synthetic::rgba8_checker_dds(),
        TextureRole::BaseColor,
    )?;
    let texture_bind_group = create_texture_bind_group(&device, &texture_layout, &material_texture);
    let camera_layout = create_camera_bind_group_layout(&device);
    let mut camera_uniform = CameraUniform::new();
    let camera_buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
        label: Some("CDMW Rust Mesh Lab headless camera uniform"),
        contents: bytemuck::bytes_of(&camera_uniform),
        usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
    });
    let camera_bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
        label: Some("CDMW Rust Mesh Lab headless camera bind group"),
        layout: &camera_layout,
        entries: &[wgpu::BindGroupEntry {
            binding: 0,
            resource: camera_buffer.as_entire_binding(),
        }],
    });
    let pipelines = create_pipelines(&device, format, &texture_layout, &camera_layout);
    let mesh = GpuMeshBuffers::upload(&device, snapshot)?;
    if !mesh.matches_snapshot(snapshot) {
        return Err(RenderError::Device(
            "headless mesh cache rejected its current snapshot".to_owned(),
        ));
    }
    let mut different_mesh = snapshot.clone();
    different_mesh.mesh_identity = different_mesh.mesh_identity.wrapping_add(1);
    if mesh.matches_snapshot(&different_mesh) {
        return Err(RenderError::Device(
            "headless mesh cache reused buffers for a different mesh with equal revisions"
                .to_owned(),
        ));
    }
    let modes = [
        ViewMode::TexturedSolid,
        ViewMode::Solid,
        ViewMode::SolidWire,
        ViewMode::Wireframe,
        ViewMode::Vertices,
        ViewMode::WireVertices,
        ViewMode::XRay,
    ];
    let sizes = [(640_u32, 480_u32), (480, 640), (1_280, 720)];
    let mut frames_rendered = 0_u32;
    for (width, height) in sizes {
        let color = create_headless_color_target(&device, format, width, height);
        let view = color.create_view(&wgpu::TextureViewDescriptor::default());
        let depth = create_depth_target(&device, width, height);
        for mode in modes {
            camera_uniform.view_projection =
                headless_view_projection(snapshot, width, height).to_cols_array_2d();
            camera_uniform.solid_mode = u32::from(mode != ViewMode::TexturedSolid);
            queue.write_buffer(&camera_buffer, 0, bytemuck::bytes_of(&camera_uniform));
            let mut encoder = device.create_command_encoder(&wgpu::CommandEncoderDescriptor {
                label: Some("CDMW Rust Mesh Lab headless frame"),
            });
            record_headless_pass(
                &mut encoder,
                &view,
                &depth.view,
                &mesh,
                &texture_bind_group,
                &camera_bind_group,
                &pipelines,
                mode,
            );
            queue.submit([encoder.finish()]);
            frames_rendered = frames_rendered.saturating_add(1);
        }
    }
    let (readback, readback_width, readback_height) = render_headless_readback(
        &device,
        &queue,
        format,
        &mesh,
        &texture_bind_group,
        &camera_bind_group,
        &pipelines,
        snapshot,
        &mut camera_uniform,
        &camera_buffer,
    );
    frames_rendered = frames_rendered.saturating_add(1);
    device
        .poll(wgpu::PollType::wait_indefinitely())
        .map_err(|error| RenderError::Device(format!("headless GPU wait failed: {error}")))?;
    if let Some(error) = error_scope.pop().await {
        return Err(RenderError::Device(format!(
            "headless GPU validation failed: {error}"
        )));
    }
    let non_background_pixels =
        read_non_background_pixels(&device, &readback, readback_width, readback_height)?;
    if non_background_pixels == 0 {
        return Err(RenderError::Device(
            "headless GPU frame contained only the clear color".to_owned(),
        ));
    }
    Ok(HeadlessRenderReport {
        adapter: adapter_report(&adapter),
        frames_rendered,
        modes_rendered: u32::try_from(modes.len()).map_err(|_| RenderError::ResourceLimit)?,
        viewport_sizes_rendered: u32::try_from(sizes.len())
            .map_err(|_| RenderError::ResourceLimit)?,
        dds_textures_uploaded: 1,
        non_background_pixels,
    })
}

fn adapter_report(adapter: &wgpu::Adapter) -> AdapterReport {
    let info = adapter.get_info();
    AdapterReport {
        name: info.name,
        backend: format!("{:?}", info.backend),
        device_type: format!("{:?}", info.device_type),
        driver: info.driver,
        driver_info: info.driver_info,
    }
}

fn create_headless_color_target(
    device: &wgpu::Device,
    format: wgpu::TextureFormat,
    width: u32,
    height: u32,
) -> wgpu::Texture {
    device.create_texture(&wgpu::TextureDescriptor {
        label: Some("CDMW Rust Mesh Lab headless color target"),
        size: wgpu::Extent3d {
            width,
            height,
            depth_or_array_layers: 1,
        },
        mip_level_count: 1,
        sample_count: 1,
        dimension: wgpu::TextureDimension::D2,
        format,
        usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC,
        view_formats: &[],
    })
}

fn headless_view_projection(snapshot: &DrawSnapshot, width: u32, height: u32) -> Mat4 {
    let (minimum, maximum) =
        mesh_bounds(&snapshot.positions).unwrap_or((Vec3::splat(-1.0), Vec3::ONE));
    let target = (minimum + maximum) * 0.5;
    let radius = ((maximum - minimum) * 0.5).length().max(1.0e-4);
    let field_of_view = 45.0_f32.to_radians();
    let aspect = (width as f32 / height.max(1) as f32).max(1.0e-4);
    let half_vertical = field_of_view * 0.5;
    let half_horizontal = (half_vertical.tan() * aspect).atan();
    let fit_half_angle = half_vertical.min(half_horizontal).max(1.0e-4);
    let distance = (radius / fit_half_angle.tan() * 1.25).max(radius * 1.5);
    let near = (distance * 0.001).max(1.0e-4);
    let far = (distance + radius * 8.0).max(near + 1.0);
    Mat4::perspective_rh(field_of_view, aspect, near, far)
        * Mat4::look_at_rh(target + Vec3::Z * distance, target, Vec3::Y)
}

#[allow(clippy::too_many_arguments)]
fn record_headless_pass(
    encoder: &mut wgpu::CommandEncoder,
    color: &wgpu::TextureView,
    depth: &wgpu::TextureView,
    mesh: &GpuMeshBuffers,
    texture_bind_group: &wgpu::BindGroup,
    camera_bind_group: &wgpu::BindGroup,
    pipelines: &Pipelines,
    mode: ViewMode,
) {
    let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
        label: Some("CDMW Rust Mesh Lab headless viewport"),
        color_attachments: &[Some(wgpu::RenderPassColorAttachment {
            view: color,
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
        depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
            view: depth,
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
    draw_mesh(
        &mut pass,
        mesh,
        texture_bind_group,
        camera_bind_group,
        &pipelines.solid,
        &pipelines.wire,
        &pipelines.point,
        &pipelines.xray,
        &pipelines.normal,
        &pipelines.bounds,
        mode,
        true,
        true,
    );
}

#[allow(clippy::too_many_arguments)]
fn render_headless_readback(
    device: &wgpu::Device,
    queue: &wgpu::Queue,
    format: wgpu::TextureFormat,
    mesh: &GpuMeshBuffers,
    texture_bind_group: &wgpu::BindGroup,
    camera_bind_group: &wgpu::BindGroup,
    pipelines: &Pipelines,
    snapshot: &DrawSnapshot,
    camera_uniform: &mut CameraUniform,
    camera_buffer: &wgpu::Buffer,
) -> (wgpu::Buffer, u32, u32) {
    let width = 640_u32;
    let height = 480_u32;
    let color = create_headless_color_target(device, format, width, height);
    let view = color.create_view(&wgpu::TextureViewDescriptor::default());
    let depth = create_depth_target(device, width, height);
    camera_uniform.view_projection =
        headless_view_projection(snapshot, width, height).to_cols_array_2d();
    camera_uniform.solid_mode = 1;
    queue.write_buffer(camera_buffer, 0, bytemuck::bytes_of(camera_uniform));
    let bytes_per_row = width * 4;
    let readback = device.create_buffer(&wgpu::BufferDescriptor {
        label: Some("CDMW Rust Mesh Lab headless readback"),
        size: u64::from(bytes_per_row) * u64::from(height),
        usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
        mapped_at_creation: false,
    });
    let mut encoder = device.create_command_encoder(&wgpu::CommandEncoderDescriptor {
        label: Some("CDMW Rust Mesh Lab headless readback frame"),
    });
    record_headless_pass(
        &mut encoder,
        &view,
        &depth.view,
        mesh,
        texture_bind_group,
        camera_bind_group,
        pipelines,
        ViewMode::SolidWire,
    );
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
                bytes_per_row: Some(bytes_per_row),
                rows_per_image: Some(height),
            },
        },
        wgpu::Extent3d {
            width,
            height,
            depth_or_array_layers: 1,
        },
    );
    queue.submit([encoder.finish()]);
    (readback, width, height)
}

fn read_non_background_pixels(
    device: &wgpu::Device,
    readback: &wgpu::Buffer,
    width: u32,
    height: u32,
) -> Result<usize, RenderError> {
    let (sender, receiver) = std::sync::mpsc::channel();
    readback
        .slice(..)
        .map_async(wgpu::MapMode::Read, move |result| {
            let _ = sender.send(result);
        });
    device
        .poll(wgpu::PollType::wait_indefinitely())
        .map_err(|error| RenderError::Device(format!("headless readback wait failed: {error}")))?;
    receiver
        .recv()
        .map_err(|error| {
            RenderError::Device(format!("headless readback callback failed: {error}"))
        })?
        .map_err(|error| {
            RenderError::Device(format!("headless readback mapping failed: {error}"))
        })?;
    let mapped = readback.slice(..).get_mapped_range().map_err(|error| {
        RenderError::Device(format!("headless readback access failed: {error}"))
    })?;
    let expected_len = usize::try_from(u64::from(width) * u64::from(height) * 4)
        .map_err(|_| RenderError::ResourceLimit)?;
    if mapped.len() != expected_len || mapped.len() < 4 {
        return Err(RenderError::Device(format!(
            "headless readback size mismatch: expected {expected_len}, got {}",
            mapped.len()
        )));
    }
    let background = &mapped[..4];
    let changed = mapped
        .chunks_exact(4)
        .filter(|pixel| *pixel != background)
        .count();
    drop(mapped);
    readback.unmap();
    Ok(changed)
}

struct Pipelines {
    solid: wgpu::RenderPipeline,
    wire: wgpu::RenderPipeline,
    point: wgpu::RenderPipeline,
    xray: wgpu::RenderPipeline,
    normal: wgpu::RenderPipeline,
    bounds: wgpu::RenderPipeline,
}

fn create_pipelines(
    device: &wgpu::Device,
    format: wgpu::TextureFormat,
    texture_layout: &wgpu::BindGroupLayout,
    camera_layout: &wgpu::BindGroupLayout,
) -> Pipelines {
    let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
        label: Some("CDMW Rust Mesh Lab shader"),
        source: wgpu::ShaderSource::Wgsl(SHADER.into()),
    });
    let layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
        label: Some("CDMW Rust Mesh Lab pipeline layout"),
        bind_group_layouts: &[Some(texture_layout), Some(camera_layout)],
        immediate_size: 0,
    });
    Pipelines {
        solid: create_pipeline(
            device,
            format,
            &layout,
            &shader,
            "solid",
            wgpu::PrimitiveTopology::TriangleList,
            "fs_solid",
            Some(wgpu::Face::Back),
            true,
            Some(wgpu::BlendState::REPLACE),
        ),
        wire: create_pipeline(
            device,
            format,
            &layout,
            &shader,
            "wire",
            wgpu::PrimitiveTopology::LineList,
            "fs_wire",
            None,
            true,
            Some(wgpu::BlendState::ALPHA_BLENDING),
        ),
        point: create_pipeline(
            device,
            format,
            &layout,
            &shader,
            "points",
            wgpu::PrimitiveTopology::PointList,
            "fs_point",
            None,
            true,
            Some(wgpu::BlendState::ALPHA_BLENDING),
        ),
        xray: create_pipeline(
            device,
            format,
            &layout,
            &shader,
            "xray",
            wgpu::PrimitiveTopology::TriangleList,
            "fs_xray",
            None,
            false,
            Some(wgpu::BlendState::ALPHA_BLENDING),
        ),
        normal: create_pipeline(
            device,
            format,
            &layout,
            &shader,
            "normal overlay",
            wgpu::PrimitiveTopology::LineList,
            "fs_normal",
            None,
            true,
            Some(wgpu::BlendState::ALPHA_BLENDING),
        ),
        bounds: create_pipeline(
            device,
            format,
            &layout,
            &shader,
            "bounds overlay",
            wgpu::PrimitiveTopology::LineList,
            "fs_bounds",
            None,
            false,
            Some(wgpu::BlendState::ALPHA_BLENDING),
        ),
    }
}

#[allow(clippy::too_many_arguments)]
fn create_pipeline(
    device: &wgpu::Device,
    format: wgpu::TextureFormat,
    layout: &wgpu::PipelineLayout,
    shader: &wgpu::ShaderModule,
    label: &str,
    topology: wgpu::PrimitiveTopology,
    fragment_entry: &str,
    cull_mode: Option<wgpu::Face>,
    depth_write_enabled: bool,
    blend: Option<wgpu::BlendState>,
) -> wgpu::RenderPipeline {
    device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
        label: Some(format!("CDMW Rust Mesh Lab {label} pipeline").as_str()),
        layout: Some(layout),
        vertex: wgpu::VertexState {
            module: shader,
            entry_point: Some("vs_main"),
            compilation_options: wgpu::PipelineCompilationOptions::default(),
            buffers: &[Some(GpuVertex::layout())],
        },
        primitive: wgpu::PrimitiveState {
            topology,
            cull_mode,
            front_face: wgpu::FrontFace::Ccw,
            ..Default::default()
        },
        depth_stencil: Some(wgpu::DepthStencilState {
            format: DEPTH_FORMAT,
            depth_write_enabled: Some(depth_write_enabled),
            depth_compare: Some(if depth_write_enabled {
                wgpu::CompareFunction::LessEqual
            } else {
                wgpu::CompareFunction::Always
            }),
            stencil: wgpu::StencilState::default(),
            bias: wgpu::DepthBiasState::default(),
        }),
        multisample: wgpu::MultisampleState::default(),
        fragment: Some(wgpu::FragmentState {
            module: shader,
            entry_point: Some(fragment_entry),
            compilation_options: wgpu::PipelineCompilationOptions::default(),
            targets: &[Some(wgpu::ColorTargetState {
                format,
                blend,
                write_mask: wgpu::ColorWrites::ALL,
            })],
        }),
        multiview_mask: None,
        cache: None,
    })
}

fn create_camera_bind_group_layout(device: &wgpu::Device) -> wgpu::BindGroupLayout {
    device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
        label: Some("CDMW Rust Mesh Lab camera layout"),
        entries: &[wgpu::BindGroupLayoutEntry {
            binding: 0,
            visibility: wgpu::ShaderStages::VERTEX_FRAGMENT,
            ty: wgpu::BindingType::Buffer {
                ty: wgpu::BufferBindingType::Uniform,
                has_dynamic_offset: false,
                min_binding_size: None,
            },
            count: None,
        }],
    })
}

fn create_depth_target(device: &wgpu::Device, width: u32, height: u32) -> DepthTarget {
    let texture = device.create_texture(&wgpu::TextureDescriptor {
        label: Some("CDMW Rust Mesh Lab depth target"),
        size: wgpu::Extent3d {
            width: width.max(1),
            height: height.max(1),
            depth_or_array_layers: 1,
        },
        mip_level_count: 1,
        sample_count: 1,
        dimension: wgpu::TextureDimension::D2,
        format: DEPTH_FORMAT,
        usage: wgpu::TextureUsages::RENDER_ATTACHMENT,
        view_formats: &[],
    });
    let view = texture.create_view(&wgpu::TextureViewDescriptor::default());
    DepthTarget {
        _texture: texture,
        view,
    }
}

fn draw_solid<'a>(
    pass: &mut wgpu::RenderPass<'a>,
    mesh: &'a GpuMeshBuffers,
    pipeline: &'a wgpu::RenderPipeline,
) {
    pass.set_pipeline(pipeline);
    pass.set_index_buffer(mesh.triangle_index.slice(..), wgpu::IndexFormat::Uint32);
    pass.draw_indexed(0..mesh.triangle_index_count, 0, 0..1);
}

fn draw_wire<'a>(
    pass: &mut wgpu::RenderPass<'a>,
    mesh: &'a GpuMeshBuffers,
    pipeline: &'a wgpu::RenderPipeline,
) {
    pass.set_pipeline(pipeline);
    pass.set_index_buffer(mesh.wire_index.slice(..), wgpu::IndexFormat::Uint32);
    pass.draw_indexed(0..mesh.wire_index_count, 0, 0..1);
}

fn draw_points<'a>(
    pass: &mut wgpu::RenderPass<'a>,
    mesh: &'a GpuMeshBuffers,
    pipeline: &'a wgpu::RenderPipeline,
) {
    pass.set_pipeline(pipeline);
    pass.draw(0..mesh.vertex_count, 0..1);
}

fn draw_overlay_lines<'a>(
    pass: &mut wgpu::RenderPass<'a>,
    vertices: &'a wgpu::Buffer,
    vertex_count: u32,
    pipeline: &'a wgpu::RenderPipeline,
) {
    if vertex_count == 0 {
        return;
    }
    pass.set_pipeline(pipeline);
    pass.set_vertex_buffer(0, vertices.slice(..));
    pass.draw(0..vertex_count, 0..1);
}

#[allow(clippy::too_many_arguments)]
fn draw_mesh<'a>(
    pass: &mut wgpu::RenderPass<'a>,
    mesh: &'a GpuMeshBuffers,
    texture_bind_group: &'a wgpu::BindGroup,
    camera_bind_group: &'a wgpu::BindGroup,
    solid_pipeline: &'a wgpu::RenderPipeline,
    wire_pipeline: &'a wgpu::RenderPipeline,
    point_pipeline: &'a wgpu::RenderPipeline,
    xray_pipeline: &'a wgpu::RenderPipeline,
    normal_pipeline: &'a wgpu::RenderPipeline,
    bounds_pipeline: &'a wgpu::RenderPipeline,
    view_mode: ViewMode,
    show_normals: bool,
    show_bounds: bool,
) {
    pass.set_bind_group(0, texture_bind_group, &[]);
    pass.set_bind_group(1, camera_bind_group, &[]);
    pass.set_vertex_buffer(0, mesh.vertex.slice(..));
    match view_mode {
        ViewMode::TexturedSolid | ViewMode::Solid => draw_solid(pass, mesh, solid_pipeline),
        ViewMode::SolidWire => {
            draw_solid(pass, mesh, solid_pipeline);
            draw_wire(pass, mesh, wire_pipeline);
        }
        ViewMode::Wireframe => draw_wire(pass, mesh, wire_pipeline),
        ViewMode::Vertices => draw_points(pass, mesh, point_pipeline),
        ViewMode::WireVertices => {
            draw_wire(pass, mesh, wire_pipeline);
            draw_points(pass, mesh, point_pipeline);
        }
        ViewMode::XRay => {
            draw_solid(pass, mesh, xray_pipeline);
            draw_wire(pass, mesh, wire_pipeline);
        }
    }
    if show_normals {
        draw_overlay_lines(
            pass,
            &mesh.normal_lines,
            mesh.normal_line_vertex_count,
            normal_pipeline,
        );
    }
    if show_bounds {
        draw_overlay_lines(
            pass,
            &mesh.bounds_lines,
            mesh.bounds_line_vertex_count,
            bounds_pipeline,
        );
    }
}

fn normal_line_vertices(snapshot: &DrawSnapshot) -> Vec<GpuVertex> {
    let Some((minimum, maximum)) = mesh_bounds(&snapshot.positions) else {
        return Vec::new();
    };
    let normal_length = (maximum - minimum).length().max(1.0e-3) * 0.015;
    let mut lines = Vec::with_capacity(snapshot.positions.len().saturating_mul(2));
    for (index, position) in snapshot.positions.iter().copied().enumerate() {
        let origin = Vec3::from_array(position);
        if !origin.is_finite() {
            continue;
        }
        let normal = snapshot
            .normals
            .get(index)
            .copied()
            .map(Vec3::from_array)
            .filter(|normal| normal.is_finite())
            .and_then(Vec3::try_normalize)
            .unwrap_or(Vec3::Y);
        lines.push(GpuVertex::overlay(origin));
        lines.push(GpuVertex::overlay(origin + normal * normal_length));
    }
    lines
}

fn bounds_line_vertices(positions: &[[f32; 3]]) -> Vec<GpuVertex> {
    let Some((minimum, maximum)) = mesh_bounds(positions) else {
        return Vec::new();
    };
    let corners = [
        Vec3::new(minimum.x, minimum.y, minimum.z),
        Vec3::new(maximum.x, minimum.y, minimum.z),
        Vec3::new(maximum.x, maximum.y, minimum.z),
        Vec3::new(minimum.x, maximum.y, minimum.z),
        Vec3::new(minimum.x, minimum.y, maximum.z),
        Vec3::new(maximum.x, minimum.y, maximum.z),
        Vec3::new(maximum.x, maximum.y, maximum.z),
        Vec3::new(minimum.x, maximum.y, maximum.z),
    ];
    let edges = [
        (0, 1),
        (1, 2),
        (2, 3),
        (3, 0),
        (4, 5),
        (5, 6),
        (6, 7),
        (7, 4),
        (0, 4),
        (1, 5),
        (2, 6),
        (3, 7),
    ];
    edges
        .into_iter()
        .flat_map(|(first, second)| {
            [
                GpuVertex::overlay(corners[first]),
                GpuVertex::overlay(corners[second]),
            ]
        })
        .collect()
}

fn mesh_bounds(positions: &[[f32; 3]]) -> Option<(Vec3, Vec3)> {
    let mut finite = positions
        .iter()
        .copied()
        .map(Vec3::from_array)
        .filter(|position| position.is_finite());
    let first = finite.next()?;
    Some(finite.fold((first, first), |(minimum, maximum), position| {
        (minimum.min(position), maximum.max(position))
    }))
}

fn unique_wire_indices(indices: &[u32]) -> Vec<u32> {
    let mut edge_set = HashSet::new();
    let mut wire_indices = Vec::with_capacity(indices.len().saturating_mul(2));
    for triangle in indices.chunks_exact(3) {
        for (first, second) in [
            (triangle[0], triangle[1]),
            (triangle[1], triangle[2]),
            (triangle[2], triangle[0]),
        ] {
            let edge = if first <= second {
                (first, second)
            } else {
                (second, first)
            };
            if edge_set.insert(edge) {
                wire_indices.extend_from_slice(&[first, second]);
            }
        }
    }
    wire_indices
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

fn upload_dds_texture(
    device: &wgpu::Device,
    queue: &wgpu::Queue,
    bytes: &[u8],
    role: TextureRole,
) -> Result<wgpu::Texture, RenderError> {
    let plan =
        plan_2d_upload(bytes, role).map_err(|error| RenderError::Texture(error.to_string()))?;
    let format = map_dds_format(&plan.metadata.format, plan.metadata.color_space)?;
    if format.is_compressed()
        && !device
            .features()
            .contains(wgpu::Features::TEXTURE_COMPRESSION_BC)
    {
        return Err(RenderError::Texture(
            "selected adapter does not support BC texture upload".to_owned(),
        ));
    }
    let texture = device.create_texture(&wgpu::TextureDescriptor {
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
        queue.write_texture(
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
    Ok(texture)
}

fn map_dds_format(
    format: &DdsFormat,
    color_space: ColorSpace,
) -> Result<wgpu::TextureFormat, RenderError> {
    let supports_srgb = matches!(
        format,
        DdsFormat::Bc1Unorm
            | DdsFormat::Bc1Srgb
            | DdsFormat::Bc2Unorm
            | DdsFormat::Bc2Srgb
            | DdsFormat::Bc3Unorm
            | DdsFormat::Bc3Srgb
            | DdsFormat::Bc7Unorm
            | DdsFormat::Bc7Srgb
            | DdsFormat::Rgba8Unorm
            | DdsFormat::Rgba8Srgb
            | DdsFormat::Bgra8Unorm
            | DdsFormat::Bgra8Srgb
    );
    if color_space == ColorSpace::Srgb && !supports_srgb {
        return Err(RenderError::Texture(format!(
            "DDS format {format:?} has no sRGB wgpu sampling variant"
        )));
    }
    let mapped = match format {
        DdsFormat::Bc1Unorm | DdsFormat::Bc1Srgb => match color_space {
            ColorSpace::Srgb => wgpu::TextureFormat::Bc1RgbaUnormSrgb,
            ColorSpace::Linear => wgpu::TextureFormat::Bc1RgbaUnorm,
        },
        DdsFormat::Bc2Unorm | DdsFormat::Bc2Srgb => match color_space {
            ColorSpace::Srgb => wgpu::TextureFormat::Bc2RgbaUnormSrgb,
            ColorSpace::Linear => wgpu::TextureFormat::Bc2RgbaUnorm,
        },
        DdsFormat::Bc3Unorm | DdsFormat::Bc3Srgb => match color_space {
            ColorSpace::Srgb => wgpu::TextureFormat::Bc3RgbaUnormSrgb,
            ColorSpace::Linear => wgpu::TextureFormat::Bc3RgbaUnorm,
        },
        DdsFormat::Bc4Unorm => wgpu::TextureFormat::Bc4RUnorm,
        DdsFormat::Bc4Snorm => wgpu::TextureFormat::Bc4RSnorm,
        DdsFormat::Bc5Unorm => wgpu::TextureFormat::Bc5RgUnorm,
        DdsFormat::Bc5Snorm => wgpu::TextureFormat::Bc5RgSnorm,
        DdsFormat::Bc6hUnsignedFloat => wgpu::TextureFormat::Bc6hRgbUfloat,
        DdsFormat::Bc6hSignedFloat => wgpu::TextureFormat::Bc6hRgbFloat,
        DdsFormat::Bc7Unorm | DdsFormat::Bc7Srgb => match color_space {
            ColorSpace::Srgb => wgpu::TextureFormat::Bc7RgbaUnormSrgb,
            ColorSpace::Linear => wgpu::TextureFormat::Bc7RgbaUnorm,
        },
        DdsFormat::R8Unorm => wgpu::TextureFormat::R8Unorm,
        DdsFormat::Rg8Unorm => wgpu::TextureFormat::Rg8Unorm,
        DdsFormat::Rgba8Unorm | DdsFormat::Rgba8Srgb => match color_space {
            ColorSpace::Srgb => wgpu::TextureFormat::Rgba8UnormSrgb,
            ColorSpace::Linear => wgpu::TextureFormat::Rgba8Unorm,
        },
        DdsFormat::Bgra8Unorm | DdsFormat::Bgra8Srgb => match color_space {
            ColorSpace::Srgb => wgpu::TextureFormat::Bgra8UnormSrgb,
            ColorSpace::Linear => wgpu::TextureFormat::Bgra8Unorm,
        },
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

#[cfg(test)]
mod tests {
    use super::*;

    fn legacy_dxt1() -> Vec<u8> {
        let mut bytes = vec![0_u8; 128 + 8];
        bytes[..4].copy_from_slice(b"DDS ");
        bytes[4..8].copy_from_slice(&124_u32.to_le_bytes());
        bytes[12..16].copy_from_slice(&4_u32.to_le_bytes());
        bytes[16..20].copy_from_slice(&4_u32.to_le_bytes());
        bytes[28..32].copy_from_slice(&1_u32.to_le_bytes());
        bytes[76..80].copy_from_slice(&32_u32.to_le_bytes());
        bytes[84..88].copy_from_slice(b"DXT1");
        bytes
    }

    #[test]
    fn shared_triangle_edges_are_uploaded_once() {
        let wire = unique_wire_indices(&[0, 1, 2, 2, 1, 3]);
        assert_eq!(wire.len(), 10);
        let edges = wire
            .chunks_exact(2)
            .map(|edge| {
                if edge[0] <= edge[1] {
                    (edge[0], edge[1])
                } else {
                    (edge[1], edge[0])
                }
            })
            .collect::<HashSet<_>>();
        assert_eq!(edges.len(), 5);
    }

    #[test]
    fn camera_uniform_matches_the_wgsl_scalar_padding_contract() {
        assert_eq!(std::mem::size_of::<CameraUniform>(), 80);
    }

    #[test]
    fn every_view_mode_has_a_distinct_user_label() {
        let labels = [
            ViewMode::TexturedSolid,
            ViewMode::Solid,
            ViewMode::SolidWire,
            ViewMode::Wireframe,
            ViewMode::Vertices,
            ViewMode::WireVertices,
            ViewMode::XRay,
        ]
        .map(ViewMode::label)
        .into_iter()
        .collect::<HashSet<_>>();
        assert_eq!(labels.len(), 7);
    }

    #[test]
    fn legacy_dxt1_base_color_uses_the_srgb_gpu_format() {
        let plan = plan_2d_upload(&legacy_dxt1(), TextureRole::BaseColor)
            .expect("legacy DXT1 upload plan");
        assert_eq!(plan.metadata.color_space, ColorSpace::Srgb);
        assert_eq!(
            map_dds_format(&plan.metadata.format, plan.metadata.color_space)
                .expect("sRGB BC1 mapping"),
            wgpu::TextureFormat::Bc1RgbaUnormSrgb
        );
    }

    #[test]
    fn an_srgb_normal_map_is_sampled_as_linear() {
        assert_eq!(
            map_dds_format(&DdsFormat::Bc7Srgb, ColorSpace::Linear).expect("linear BC7 mapping"),
            wgpu::TextureFormat::Bc7RgbaUnorm
        );
    }

    #[test]
    fn formats_without_an_srgb_variant_are_rejected_for_srgb_sampling() {
        assert!(map_dds_format(&DdsFormat::Bc5Unorm, ColorSpace::Srgb).is_err());
    }

    #[test]
    fn normal_and_bounds_overlays_build_persistent_line_vertices() {
        let snapshot = DrawSnapshot {
            mesh_identity: 1,
            draw_revision: 1,
            topology_generation: 1,
            positions: vec![[0.0, 0.0, 0.0], [2.0, 4.0, 6.0]],
            normals: vec![[0.0, 1.0, 0.0], [1.0, 0.0, 0.0]],
            uvs: vec![[0.0, 0.0]; 2],
            indices: Vec::new(),
            selected_vertices: Vec::new(),
            fingerprint: String::new(),
        };
        let normals = normal_line_vertices(&snapshot);
        assert_eq!(normals.len(), 4);
        assert_eq!(normals[0].position, snapshot.positions[0]);
        assert!(normals[1].position[1] > normals[0].position[1]);
        assert!(normals[3].position[0] > normals[2].position[0]);

        let bounds = bounds_line_vertices(&snapshot.positions);
        assert_eq!(bounds.len(), 24);
        assert!(
            bounds
                .iter()
                .any(|vertex| vertex.position == [0.0, 0.0, 0.0])
        );
        assert!(
            bounds
                .iter()
                .any(|vertex| vertex.position == [2.0, 4.0, 6.0])
        );
    }
}
