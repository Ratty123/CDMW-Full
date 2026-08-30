#![forbid(unsafe_code)]

use bytemuck::{Pod, Zeroable};
use cdmw_mesh::DrawSnapshot;
use cdmw_texture::{ColorSpace, DdsFormat, TextureRole, plan_2d_upload};
use glam::{Mat4, Vec2, Vec3};
use std::collections::{BTreeMap, HashSet};
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
    @location(2) normal: vec3<f32>,
    @location(3) tangent: vec4<f32>,
};

struct MaterialUniform {
    flags: u32,
    _padding_0: u32,
    _padding_1: u32,
    _padding_2: u32,
    emissive_color_and_intensity: vec4<f32>,
    surface_factors: vec4<f32>,
};

@group(0) @binding(0) var base_texture: texture_2d<f32>;
@group(0) @binding(1) var normal_texture: texture_2d<f32>;
@group(0) @binding(2) var material_texture: texture_2d<f32>;
@group(0) @binding(3) var roughness_texture: texture_2d<f32>;
@group(0) @binding(4) var metalness_texture: texture_2d<f32>;
@group(0) @binding(5) var occlusion_texture: texture_2d<f32>;
@group(0) @binding(6) var emissive_texture: texture_2d<f32>;
@group(0) @binding(7) var material_sampler: sampler;
@group(0) @binding(8) var<uniform> material: MaterialUniform;
@group(0) @binding(9) var specular_texture: texture_2d<f32>;
@group(0) @binding(10) var opacity_texture: texture_2d<f32>;
@group(1) @binding(0) var<uniform> camera: CameraUniform;

const MATERIAL_BASE_COLOR: u32 = 1u;
const MATERIAL_NORMAL: u32 = 2u;
const MATERIAL_SURFACE: u32 = 4u;
const MATERIAL_ROUGHNESS: u32 = 8u;
const MATERIAL_METALNESS: u32 = 16u;
const MATERIAL_OCCLUSION: u32 = 32u;
const MATERIAL_EMISSIVE: u32 = 64u;
const MATERIAL_ROUGHNESS_FACTOR: u32 = 128u;
const MATERIAL_METALNESS_FACTOR: u32 = 256u;
const MATERIAL_SPECULAR_FACTOR: u32 = 512u;
const MATERIAL_SPECULAR: u32 = 1024u;
const MATERIAL_OPACITY: u32 = 2048u;
const MATERIAL_ALPHA_CUTOUT: u32 = 4096u;

@vertex
fn vs_main(
    @location(0) position: vec3<f32>,
    @location(1) normal: vec3<f32>,
    @location(2) uv: vec2<f32>,
    @location(3) tangent: vec4<f32>,
) -> VertexOut {
    var out: VertexOut;
    out.position = camera.view_projection * vec4<f32>(position, 1.0);
    out.color = normal * 0.35 + vec3<f32>(0.55, 0.58, 0.65);
    out.uv = uv;
    out.normal = normal;
    out.tangent = tangent;
    return out;
}

@fragment
fn fs_solid(input: VertexOut) -> @location(0) vec4<f32> {
    if camera.solid_mode == 1u {
        return vec4<f32>(input.color, 1.0);
    }
    if material.flags == 0u {
        return vec4<f32>(input.color, 1.0);
    }

    let texel = textureSample(base_texture, material_sampler, input.uv);
    if (material.flags & MATERIAL_ALPHA_CUTOUT) != 0u {
        var material_alpha = texel.a;
        if (material.flags & MATERIAL_OPACITY) != 0u {
            material_alpha = textureSample(opacity_texture, material_sampler, input.uv).r;
        }
        if material_alpha < material.surface_factors.w {
            discard;
        }
    }
    var surface_normal = normalize(input.normal);
    if (material.flags & MATERIAL_NORMAL) != 0u {
        let tangent_xy = textureSample(normal_texture, material_sampler, input.uv).xy * 2.0 - vec2<f32>(1.0);
        let tangent_z = sqrt(max(1.0 - dot(tangent_xy, tangent_xy), 0.0));
        let tangent = normalize(input.tangent.xyz - surface_normal * dot(surface_normal, input.tangent.xyz));
        let bitangent = normalize(cross(surface_normal, tangent)) * input.tangent.w;
        surface_normal = normalize(
            tangent * tangent_xy.x
            + bitangent * tangent_xy.y
            + surface_normal * tangent_z);
    }

    var roughness = 0.65;
    var metalness = 0.0;
    if (material.flags & MATERIAL_SURFACE) != 0u {
        let packed = textureSample(material_texture, material_sampler, input.uv);
        roughness = clamp(packed.g, 0.04, 1.0);
        metalness = clamp(packed.b, 0.0, 1.0);
    }
    if (material.flags & MATERIAL_ROUGHNESS) != 0u {
        roughness = clamp(textureSample(roughness_texture, material_sampler, input.uv).r, 0.04, 1.0);
    }
    if (material.flags & MATERIAL_METALNESS) != 0u {
        metalness = clamp(textureSample(metalness_texture, material_sampler, input.uv).r, 0.0, 1.0);
    }
    if (material.flags & MATERIAL_ROUGHNESS_FACTOR) != 0u {
        let has_source_roughness =
            (material.flags & (MATERIAL_SURFACE | MATERIAL_ROUGHNESS)) != 0u;
        let factor_weight = select(0.55, 0.15, has_source_roughness);
        roughness = clamp(mix(roughness, material.surface_factors.x, factor_weight), 0.04, 1.0);
    }
    if (material.flags & MATERIAL_METALNESS_FACTOR) != 0u
        && material.surface_factors.y > 0.02 {
        metalness = max(metalness, material.surface_factors.y);
    }
    var occlusion = 1.0;
    if (material.flags & MATERIAL_OCCLUSION) != 0u {
        occlusion = clamp(textureSample(occlusion_texture, material_sampler, input.uv).r, 0.0, 1.0);
    }

    let light_direction = normalize(vec3<f32>(-0.35, 0.80, 0.45));
    let view_direction = normalize(vec3<f32>(0.10, 0.20, 1.0));
    let half_vector = normalize(light_direction + view_direction);
    let ndotl = max(dot(surface_normal, light_direction), 0.0);
    let ndoth = max(dot(surface_normal, half_vector), 0.0);
    let diffuse = texel.rgb * (0.18 * occlusion + 0.82 * ndotl) * (1.0 - metalness);
    let metal_body = texel.rgb * metalness * (0.10 * occlusion + 0.28 * ndotl);
    var f0 = mix(vec3<f32>(0.04), texel.rgb, vec3<f32>(metalness));
    if (material.flags & MATERIAL_SPECULAR) != 0u {
        let mapped_specular = textureSample(specular_texture, material_sampler, input.uv).rgb;
        f0 = mix(f0, max(f0, mapped_specular), vec3<f32>(metalness));
    }
    if (material.flags & MATERIAL_SPECULAR_FACTOR) != 0u
        && material.surface_factors.z > 0.02 {
        let factored_specular = mix(0.04, material.surface_factors.z, metalness);
        f0 = max(f0, vec3<f32>(factored_specular));
    }
    let specular_power = mix(96.0, 8.0, roughness);
    let specular = f0 * pow(ndoth, specular_power) * (0.20 + 0.80 * (1.0 - roughness));
    let environment_specular = f0 * (0.04 + 0.28 * (1.0 - roughness));
    var emissive = vec3<f32>(0.0);
    if (material.flags & MATERIAL_EMISSIVE) != 0u {
        emissive = textureSample(emissive_texture, material_sampler, input.uv).rgb
            * material.emissive_color_and_intensity.rgb
            * material.emissive_color_and_intensity.a;
    }
    return vec4<f32>(diffuse + metal_body + specular + environment_specular + emissive, 1.0);
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

#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
struct MaterialUniform {
    flags: u32,
    _padding: [u32; 3],
    emissive_color_and_intensity: [f32; 4],
    surface_factors: [f32; 4],
}

const MATERIAL_BASE_COLOR: u32 = 1;
const MATERIAL_NORMAL: u32 = 2;
const MATERIAL_SURFACE: u32 = 4;
const MATERIAL_ROUGHNESS: u32 = 8;
const MATERIAL_METALNESS: u32 = 16;
const MATERIAL_OCCLUSION: u32 = 32;
const MATERIAL_EMISSIVE: u32 = 64;
const MATERIAL_ROUGHNESS_FACTOR: u32 = 128;
const MATERIAL_METALNESS_FACTOR: u32 = 256;
const MATERIAL_SPECULAR_FACTOR: u32 = 512;
const MATERIAL_SPECULAR: u32 = 1024;
const MATERIAL_OPACITY: u32 = 2048;
const MATERIAL_ALPHA_CUTOUT: u32 = 4096;

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
    tangent: [f32; 4],
}

impl GpuVertex {
    const ATTRIBUTES: [wgpu::VertexAttribute; 4] = wgpu::vertex_attr_array![
        0 => Float32x3,
        1 => Float32x3,
        2 => Float32x2,
        3 => Float32x4
    ];

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
            tangent: [1.0, 0.0, 0.0, 1.0],
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

#[derive(Debug, Clone, Copy, Default, PartialEq)]
pub struct MaterialPreviewFactors {
    pub emissive_color: Option<[f32; 3]>,
    pub emissive_intensity: Option<f32>,
    pub roughness: Option<f32>,
    pub metalness: Option<f32>,
    pub specular: Option<f32>,
    pub alpha_cutoff: Option<f32>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HeadlessRenderReport {
    pub adapter: AdapterReport,
    pub frames_rendered: u32,
    pub modes_rendered: u32,
    pub viewport_sizes_rendered: u32,
    pub dds_textures_uploaded: u32,
    pub sampled_material_roles: u32,
    pub material_ranges_rendered: u32,
    pub composed_material_pixels_changed: usize,
    pub emissive_factor_pixels_changed: usize,
    pub roughness_factor_pixels_changed: usize,
    pub metalness_factor_pixels_changed: usize,
    pub specular_factor_pixels_changed: usize,
    pub specular_texture_pixels_changed: usize,
    pub dielectric_specular_pixels_changed: usize,
    pub opacity_cutout_pixels_removed: usize,
    pub opaque_opacity_pixels_changed: usize,
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
    #[error("draw snapshot material ownership is invalid: {0}")]
    InvalidSnapshot(String),
    #[error("DDS texture upload failed: {0}")]
    Texture(String),
}

pub struct GpuMeshBuffers {
    vertex: wgpu::Buffer,
    triangle_index: wgpu::Buffer,
    wire_index: wgpu::Buffer,
    normal_lines: wgpu::Buffer,
    bounds_lines: wgpu::Buffer,
    material_ranges: Vec<GpuMaterialRange>,
    triangle_index_count: u32,
    wire_index_count: u32,
    vertex_count: u32,
    normal_line_vertex_count: u32,
    bounds_line_vertex_count: u32,
    mesh_identity: u64,
    pub draw_revision: u64,
    pub topology_generation: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct GpuMaterialRange {
    material: u32,
    first_index: u32,
    index_count: u32,
}

struct GpuMaterialTexture {
    _texture: wgpu::Texture,
    role: TextureRole,
    material_indices_by_lod: Vec<Vec<u32>>,
}

struct MaterialFactorOwnership {
    factors: MaterialPreviewFactors,
    material_indices_by_lod: Vec<Vec<u32>>,
}

struct DefaultMaterialTextures {
    base_color: wgpu::Texture,
    normal: wgpu::Texture,
    surface: wgpu::Texture,
    roughness: wgpu::Texture,
    metalness: wgpu::Texture,
    occlusion: wgpu::Texture,
    emissive: wgpu::Texture,
    specular: wgpu::Texture,
    opacity: wgpu::Texture,
}

struct GpuMaterialBinding {
    bind_group: wgpu::BindGroup,
    _uniform_buffer: wgpu::Buffer,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
struct MaterialTextureIndices {
    base_color: Option<usize>,
    normal: Option<usize>,
    surface: Option<usize>,
    roughness: Option<usize>,
    metalness: Option<usize>,
    occlusion: Option<usize>,
    emissive: Option<usize>,
    specular: Option<usize>,
    opacity: Option<usize>,
}

impl GpuMeshBuffers {
    pub fn upload(device: &wgpu::Device, snapshot: &DrawSnapshot) -> Result<Self, RenderError> {
        let tangents = vertex_tangents(snapshot)?;
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
                let tangent = tangents.get(index).copied().unwrap_or([1.0, 0.0, 0.0, 1.0]);
                GpuVertex {
                    position: *position,
                    normal,
                    uv,
                    tangent,
                }
            })
            .collect::<Vec<_>>();
        let vertex = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("CDMW Rust Mesh Lab vertices"),
            contents: bytemuck::cast_slice(&vertices),
            usage: wgpu::BufferUsages::VERTEX,
        });
        let (material_indices, material_ranges) = material_index_batches(snapshot)?;
        let triangle_index = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("CDMW Rust Mesh Lab triangle indices"),
            contents: bytemuck::cast_slice(&material_indices),
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
            material_ranges,
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
    default_material_binding: GpuMaterialBinding,
    default_material_textures: DefaultMaterialTextures,
    material_sampler: wgpu::Sampler,
    material_textures: Vec<GpuMaterialTexture>,
    material_factors: Vec<MaterialFactorOwnership>,
    active_material_bindings: BTreeMap<u32, GpuMaterialBinding>,
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
        let default_material_textures = create_default_material_textures(&device, &queue);
        let material_sampler = create_material_sampler(&device);
        let default_material_binding = create_material_bind_group(
            &device,
            &texture_bind_group_layout,
            &material_sampler,
            &default_material_textures,
            &[],
            MaterialTextureIndices::default(),
            MaterialPreviewFactors::default(),
        );
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
            default_material_binding,
            default_material_textures,
            material_sampler,
            material_textures: Vec::new(),
            material_factors: Vec::new(),
            active_material_bindings: BTreeMap::new(),
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

    pub fn add_dds_texture(
        &mut self,
        bytes: &[u8],
        role: TextureRole,
        material_indices_by_lod: &[Vec<u32>],
    ) -> Result<(), RenderError> {
        if material_indices_by_lod.iter().all(Vec::is_empty) {
            return Err(RenderError::Texture(
                "DDS texture has no owning material range".to_owned(),
            ));
        }
        if !matches!(
            role,
            TextureRole::BaseColor
                | TextureRole::Normal
                | TextureRole::Material
                | TextureRole::Roughness
                | TextureRole::Metalness
                | TextureRole::Occlusion
                | TextureRole::Emissive
                | TextureRole::Specular
                | TextureRole::Opacity
        ) {
            return Err(RenderError::Texture(format!(
                "the {role:?} role is classified but is not sampled by the current material approximation"
            )));
        }
        let texture = upload_dds_texture(&self.device, &self.queue, bytes, role)?;
        self.material_textures.push(GpuMaterialTexture {
            _texture: texture,
            role,
            material_indices_by_lod: material_indices_by_lod.to_vec(),
        });
        Ok(())
    }

    pub fn add_material_factors(
        &mut self,
        factors: MaterialPreviewFactors,
        material_indices_by_lod: &[Vec<u32>],
    ) -> Result<(), RenderError> {
        if material_indices_by_lod.iter().all(Vec::is_empty) {
            return Err(RenderError::Texture(
                "material factors have no owning material range".to_owned(),
            ));
        }
        if factors.emissive_color.is_none()
            && factors.emissive_intensity.is_none()
            && factors.roughness.is_none()
            && factors.metalness.is_none()
            && factors.specular.is_none()
            && factors.alpha_cutoff.is_none()
        {
            return Err(RenderError::Texture(
                "material factor set contains no sampled value".to_owned(),
            ));
        }
        if factors.emissive_color.is_some_and(|color| {
            color
                .into_iter()
                .any(|value| !value.is_finite() || !(0.0..=1.0).contains(&value))
        }) || factors
            .emissive_intensity
            .is_some_and(|value| !value.is_finite() || !(0.0..=32.0).contains(&value))
            || [
                factors.roughness,
                factors.metalness,
                factors.specular,
                factors.alpha_cutoff,
            ]
            .into_iter()
            .flatten()
            .any(|value| !value.is_finite() || !(0.0..=1.0).contains(&value))
        {
            return Err(RenderError::Texture(
                "material factors contain a non-finite or out-of-range value".to_owned(),
            ));
        }
        self.material_factors.push(MaterialFactorOwnership {
            factors,
            material_indices_by_lod: material_indices_by_lod.to_vec(),
        });
        Ok(())
    }

    pub fn set_material_lod(&mut self, lod_index: usize) -> Result<usize, RenderError> {
        let mut active = match resolve_material_bindings(
            self.material_textures
                .iter()
                .map(|texture| (texture.role, texture.material_indices_by_lod.as_slice())),
            lod_index,
        ) {
            Ok(active) => active,
            Err(error) => {
                self.active_material_bindings.clear();
                return Err(error);
            }
        };
        let factors = match resolve_material_factors(
            self.material_factors
                .iter()
                .map(|owned| (owned.factors, owned.material_indices_by_lod.as_slice())),
            lod_index,
        ) {
            Ok(factors) => factors,
            Err(error) => {
                self.active_material_bindings.clear();
                return Err(error);
            }
        };
        let bound = active.len();
        for material in factors.keys() {
            active.entry(*material).or_default();
        }
        self.active_material_bindings = active
            .into_iter()
            .map(|(material, indices)| {
                let binding = create_material_bind_group(
                    &self.device,
                    &self.texture_bind_group_layout,
                    &self.material_sampler,
                    &self.default_material_textures,
                    &self.material_textures,
                    indices,
                    factors.get(&material).copied().unwrap_or_default(),
                );
                (material, binding)
            })
            .collect();
        Ok(bound)
    }

    pub fn reset_texture(&mut self) {
        self.material_textures.clear();
        self.material_factors.clear();
        self.active_material_bindings.clear();
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
                    &self.default_material_binding.bind_group,
                    &self.active_material_bindings,
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
    let default_material_textures = create_default_material_textures(&device, &queue);
    let material_sampler = create_material_sampler(&device);
    let default_material_binding = create_material_bind_group(
        &device,
        &texture_layout,
        &material_sampler,
        &default_material_textures,
        &[],
        MaterialTextureIndices::default(),
        MaterialPreviewFactors::default(),
    );
    let synthetic_dds = |color: [u8; 4]| {
        let mut bytes = cdmw_texture::synthetic::rgba8_checker_dds();
        if let Some(pixels) = bytes.get_mut(148..164) {
            for pixel in pixels.chunks_exact_mut(4) {
                pixel.copy_from_slice(&color);
            }
        }
        bytes
    };
    let synthetic_opacity_dds = || {
        let mut bytes = cdmw_texture::synthetic::rgba8_checker_dds();
        if let Some(pixels) = bytes.get_mut(148..164) {
            for (index, pixel) in pixels.chunks_exact_mut(4).enumerate() {
                let opacity = if index.is_multiple_of(2) { 0 } else { 255 };
                pixel.copy_from_slice(&[opacity, opacity, opacity, 255]);
            }
        }
        bytes
    };
    let mut material_textures = Vec::new();
    for (material, role, bytes) in [
        (
            0_u32,
            TextureRole::BaseColor,
            synthetic_dds([210, 70, 55, 255]),
        ),
        (
            0_u32,
            TextureRole::Normal,
            synthetic_dds([128, 178, 240, 255]),
        ),
        (
            0_u32,
            TextureRole::Material,
            synthetic_dds([255, 70, 230, 255]),
        ),
        (
            0_u32,
            TextureRole::Roughness,
            synthetic_dds([20, 0, 0, 255]),
        ),
        (
            0_u32,
            TextureRole::Metalness,
            synthetic_dds([235, 0, 0, 255]),
        ),
        (
            0_u32,
            TextureRole::Occlusion,
            synthetic_dds([30, 0, 0, 255]),
        ),
        (
            0_u32,
            TextureRole::Emissive,
            synthetic_dds([90, 30, 10, 255]),
        ),
        (
            0_u32,
            TextureRole::Specular,
            synthetic_dds([250, 180, 60, 255]),
        ),
        (0_u32, TextureRole::Opacity, synthetic_opacity_dds()),
        (
            1_u32,
            TextureRole::BaseColor,
            synthetic_dds([70, 230, 90, 255]),
        ),
    ] {
        let texture = upload_dds_texture(&device, &queue, &bytes, role)?;
        material_textures.push(GpuMaterialTexture {
            _texture: texture,
            role,
            material_indices_by_lod: vec![vec![material]],
        });
    }
    let resolved_bindings = resolve_material_bindings(
        material_textures
            .iter()
            .map(|texture| (texture.role, texture.material_indices_by_lod.as_slice())),
        0,
    )?;
    let bindings_for_roles = |roles: &[TextureRole], factors: MaterialPreviewFactors| {
        resolved_bindings
            .iter()
            .map(|(material, indices)| {
                let selected = MaterialTextureIndices {
                    base_color: if roles.contains(&TextureRole::BaseColor) {
                        indices.base_color
                    } else {
                        None
                    },
                    normal: if roles.contains(&TextureRole::Normal) {
                        indices.normal
                    } else {
                        None
                    },
                    surface: if roles.contains(&TextureRole::Material) {
                        indices.surface
                    } else {
                        None
                    },
                    roughness: if roles.contains(&TextureRole::Roughness) {
                        indices.roughness
                    } else {
                        None
                    },
                    metalness: if roles.contains(&TextureRole::Metalness) {
                        indices.metalness
                    } else {
                        None
                    },
                    occlusion: if roles.contains(&TextureRole::Occlusion) {
                        indices.occlusion
                    } else {
                        None
                    },
                    emissive: if roles.contains(&TextureRole::Emissive) {
                        indices.emissive
                    } else {
                        None
                    },
                    specular: if roles.contains(&TextureRole::Specular) {
                        indices.specular
                    } else {
                        None
                    },
                    opacity: if roles.contains(&TextureRole::Opacity) {
                        indices.opacity
                    } else {
                        None
                    },
                };
                (
                    *material,
                    create_material_bind_group(
                        &device,
                        &texture_layout,
                        &material_sampler,
                        &default_material_textures,
                        &material_textures,
                        selected,
                        factors,
                    ),
                )
            })
            .collect::<BTreeMap<_, _>>()
    };
    let base_only_material_bindings =
        bindings_for_roles(&[TextureRole::BaseColor], MaterialPreviewFactors::default());
    let base_normal_material_bindings = bindings_for_roles(
        &[TextureRole::BaseColor, TextureRole::Normal],
        MaterialPreviewFactors::default(),
    );
    let base_surface_material_bindings = bindings_for_roles(
        &[TextureRole::BaseColor, TextureRole::Material],
        MaterialPreviewFactors::default(),
    );
    let base_roughness_material_bindings = bindings_for_roles(
        &[TextureRole::BaseColor, TextureRole::Roughness],
        MaterialPreviewFactors::default(),
    );
    let base_metalness_material_bindings = bindings_for_roles(
        &[TextureRole::BaseColor, TextureRole::Metalness],
        MaterialPreviewFactors::default(),
    );
    let base_occlusion_material_bindings = bindings_for_roles(
        &[TextureRole::BaseColor, TextureRole::Occlusion],
        MaterialPreviewFactors::default(),
    );
    let base_emissive_material_bindings = bindings_for_roles(
        &[TextureRole::BaseColor, TextureRole::Emissive],
        MaterialPreviewFactors::default(),
    );
    let base_specular_material_bindings = bindings_for_roles(
        &[
            TextureRole::BaseColor,
            TextureRole::Metalness,
            TextureRole::Specular,
        ],
        MaterialPreviewFactors::default(),
    );
    let dielectric_specular_material_bindings = bindings_for_roles(
        &[TextureRole::BaseColor, TextureRole::Specular],
        MaterialPreviewFactors::default(),
    );
    let opaque_opacity_material_bindings = bindings_for_roles(
        &[TextureRole::BaseColor, TextureRole::Opacity],
        MaterialPreviewFactors::default(),
    );
    let opacity_cutout_material_bindings = bindings_for_roles(
        &[TextureRole::BaseColor, TextureRole::Opacity],
        MaterialPreviewFactors {
            alpha_cutoff: Some(0.5),
            ..MaterialPreviewFactors::default()
        },
    );
    let factored_emissive_material_bindings = bindings_for_roles(
        &[TextureRole::BaseColor, TextureRole::Emissive],
        MaterialPreviewFactors {
            emissive_color: Some([0.05, 0.8, 0.2]),
            emissive_intensity: Some(3.0),
            ..MaterialPreviewFactors::default()
        },
    );
    let roughness_factor_material_bindings = bindings_for_roles(
        &[TextureRole::BaseColor],
        MaterialPreviewFactors {
            roughness: Some(0.95),
            ..MaterialPreviewFactors::default()
        },
    );
    let metalness_factor_material_bindings = bindings_for_roles(
        &[TextureRole::BaseColor],
        MaterialPreviewFactors {
            metalness: Some(0.85),
            ..MaterialPreviewFactors::default()
        },
    );
    let metal_specular_factor_material_bindings = bindings_for_roles(
        &[TextureRole::BaseColor],
        MaterialPreviewFactors {
            metalness: Some(0.85),
            specular: Some(1.0),
            ..MaterialPreviewFactors::default()
        },
    );
    let active_material_bindings = bindings_for_roles(
        &[
            TextureRole::BaseColor,
            TextureRole::Normal,
            TextureRole::Material,
            TextureRole::Roughness,
            TextureRole::Metalness,
            TextureRole::Occlusion,
            TextureRole::Emissive,
            TextureRole::Specular,
            TextureRole::Opacity,
        ],
        MaterialPreviewFactors {
            alpha_cutoff: Some(0.5),
            ..MaterialPreviewFactors::default()
        },
    );
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
    let mut render_snapshot = snapshot.clone();
    render_snapshot.triangle_materials.fill(0);
    let first_triangle = render_snapshot.indices.get(..3).ok_or_else(|| {
        RenderError::InvalidSnapshot(
            "headless material proof requires at least one triangle".to_owned(),
        )
    })?;
    let source_indices = [
        usize::try_from(first_triangle[0]).map_err(|_| RenderError::ResourceLimit)?,
        usize::try_from(first_triangle[1]).map_err(|_| RenderError::ResourceLimit)?,
        usize::try_from(first_triangle[2]).map_err(|_| RenderError::ResourceLimit)?,
    ];
    let mut copied_positions = Vec::with_capacity(3);
    let mut copied_normals = Vec::with_capacity(3);
    let mut copied_uvs = Vec::with_capacity(3);
    for index in source_indices {
        let position = render_snapshot
            .positions
            .get(index)
            .copied()
            .ok_or_else(|| {
                RenderError::InvalidSnapshot(format!(
                    "triangle index {index} exceeds the vertex count"
                ))
            })?;
        let normal = render_snapshot.normals.get(index).copied().ok_or_else(|| {
            RenderError::InvalidSnapshot(format!("triangle index {index} exceeds the normal count"))
        })?;
        let uv = render_snapshot.uvs.get(index).copied().ok_or_else(|| {
            RenderError::InvalidSnapshot(format!(
                "triangle index {index} exceeds the texture-coordinate count"
            ))
        })?;
        copied_positions.push([position[0] + 1.25, position[1], position[2]]);
        copied_normals.push(normal);
        copied_uvs.push(uv);
    }
    let first_new_index =
        u32::try_from(render_snapshot.positions.len()).map_err(|_| RenderError::ResourceLimit)?;
    render_snapshot.positions.extend(copied_positions);
    render_snapshot.normals.extend(copied_normals);
    render_snapshot.uvs.extend(copied_uvs);
    render_snapshot.indices.extend_from_slice(&[
        first_new_index,
        first_new_index.saturating_add(1),
        first_new_index.saturating_add(2),
    ]);
    render_snapshot.triangle_materials.push(1);
    let mesh = GpuMeshBuffers::upload(&device, &render_snapshot)?;
    if !mesh.matches_snapshot(&render_snapshot) {
        return Err(RenderError::Device(
            "headless mesh cache rejected its current snapshot".to_owned(),
        ));
    }
    let mut different_mesh = render_snapshot.clone();
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
                headless_view_projection(&render_snapshot, width, height).to_cols_array_2d();
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
                &default_material_binding.bind_group,
                &active_material_bindings,
                &camera_bind_group,
                &pipelines,
                mode,
            );
            queue.submit([encoder.finish()]);
            frames_rendered = frames_rendered.saturating_add(1);
        }
    }
    let probe_bindings = [
        ("unresolved", BTreeMap::new()),
        ("base color", base_only_material_bindings),
        ("normal", base_normal_material_bindings),
        ("packed material", base_surface_material_bindings),
        ("roughness", base_roughness_material_bindings),
        ("metalness", base_metalness_material_bindings),
        ("specular", base_specular_material_bindings),
        ("dielectric specular", dielectric_specular_material_bindings),
        ("opaque opacity", opaque_opacity_material_bindings),
        ("opacity cutout", opacity_cutout_material_bindings),
        ("occlusion", base_occlusion_material_bindings),
        ("emissive", base_emissive_material_bindings),
        ("emissive factors", factored_emissive_material_bindings),
        ("roughness factor", roughness_factor_material_bindings),
        ("metalness factor", metalness_factor_material_bindings),
        (
            "metalness and specular factors",
            metal_specular_factor_material_bindings,
        ),
        ("composed", active_material_bindings),
    ];
    let readbacks = probe_bindings
        .iter()
        .map(|(_, bindings)| {
            render_headless_readback(
                &device,
                &queue,
                format,
                &mesh,
                &default_material_binding.bind_group,
                bindings,
                &camera_bind_group,
                &pipelines,
                &render_snapshot,
                &mut camera_uniform,
                &camera_buffer,
            )
        })
        .collect::<Vec<_>>();
    frames_rendered = frames_rendered
        .saturating_add(u32::try_from(readbacks.len()).map_err(|_| RenderError::ResourceLimit)?);
    device
        .poll(wgpu::PollType::wait_indefinitely())
        .map_err(|error| RenderError::Device(format!("headless GPU wait failed: {error}")))?;
    if let Some(error) = error_scope.pop().await {
        return Err(RenderError::Device(format!(
            "headless GPU validation failed: {error}"
        )));
    }
    let probe_pixels = readbacks
        .iter()
        .map(|(readback, width, height)| read_headless_pixels(&device, readback, *width, *height))
        .collect::<Result<Vec<_>, _>>()?;
    let probe_index = |label: &str| {
        probe_bindings
            .iter()
            .position(|(candidate, _)| *candidate == label)
            .ok_or_else(|| RenderError::Device(format!("headless {label} probe is missing")))
    };
    let base_only_pixels = &probe_pixels[probe_index("base color")?];
    let composed_pixels = &probe_pixels[probe_index("composed")?];
    let background = composed_pixels.get(..4).ok_or_else(|| {
        RenderError::Device("headless GPU frame has no complete pixel".to_owned())
    })?;
    let non_background_pixels = composed_pixels
        .chunks_exact(4)
        .filter(|pixel| *pixel != background)
        .count();
    if non_background_pixels == 0 {
        return Err(RenderError::Device(
            "headless GPU frame contained only the clear color".to_owned(),
        ));
    }
    let mut role_changes = Vec::with_capacity(9);
    for (role, reference) in [
        ("base color", "unresolved"),
        ("normal", "base color"),
        ("packed material", "base color"),
        ("roughness", "base color"),
        ("metalness", "base color"),
        ("specular", "metalness"),
        ("opacity cutout", "opaque opacity"),
        ("occlusion", "base color"),
        ("emissive", "base color"),
    ] {
        let role_index = probe_index(role)?;
        let reference_index = probe_index(reference)?;
        role_changes.push((
            role,
            changed_pixel_count(&probe_pixels[reference_index], &probe_pixels[role_index])?,
        ));
    }
    for (role, changed) in &role_changes {
        if *changed == 0 {
            return Err(RenderError::Device(format!(
                "headless {role} sampling did not change any rendered pixel"
            )));
        }
    }
    let composed_material_pixels_changed = changed_pixel_count(base_only_pixels, composed_pixels)?;
    if composed_material_pixels_changed == 0 {
        return Err(RenderError::Device(
            "headless material roles did not change any rendered pixel from the base-only pass"
                .to_owned(),
        ));
    }
    let emissive_pixels = &probe_pixels[probe_index("emissive")?];
    let factored_emissive_pixels = &probe_pixels[probe_index("emissive factors")?];
    let emissive_factor_pixels_changed =
        changed_pixel_count(emissive_pixels, factored_emissive_pixels)?;
    if emissive_factor_pixels_changed == 0 {
        return Err(RenderError::Device(
            "headless emissive color/intensity factors did not change any rendered pixel"
                .to_owned(),
        ));
    }
    let roughness_factor_pixels_changed = changed_pixel_count(
        base_only_pixels,
        &probe_pixels[probe_index("roughness factor")?],
    )?;
    if roughness_factor_pixels_changed == 0 {
        return Err(RenderError::Device(
            "headless roughness factor did not change any rendered pixel".to_owned(),
        ));
    }
    let metalness_factor_pixels = &probe_pixels[probe_index("metalness factor")?];
    let metalness_factor_pixels_changed =
        changed_pixel_count(base_only_pixels, metalness_factor_pixels)?;
    if metalness_factor_pixels_changed == 0 {
        return Err(RenderError::Device(
            "headless metalness factor did not change any rendered pixel".to_owned(),
        ));
    }
    let specular_factor_pixels_changed = changed_pixel_count(
        metalness_factor_pixels,
        &probe_pixels[probe_index("metalness and specular factors")?],
    )?;
    if specular_factor_pixels_changed == 0 {
        return Err(RenderError::Device(
            "headless specular factor did not change any rendered pixel".to_owned(),
        ));
    }
    let specular_texture_pixels_changed = changed_pixel_count(
        &probe_pixels[probe_index("metalness")?],
        &probe_pixels[probe_index("specular")?],
    )?;
    if specular_texture_pixels_changed == 0 {
        return Err(RenderError::Device(
            "headless specular texture did not change any rendered pixel".to_owned(),
        ));
    }
    let dielectric_specular_pixels_changed = changed_pixel_count(
        base_only_pixels,
        &probe_pixels[probe_index("dielectric specular")?],
    )?;
    if dielectric_specular_pixels_changed != 0 {
        return Err(RenderError::Device(
            "headless specular texture changed a dielectric material".to_owned(),
        ));
    }
    let opaque_opacity_pixels = &probe_pixels[probe_index("opaque opacity")?];
    let opacity_cutout_pixels = &probe_pixels[probe_index("opacity cutout")?];
    let opaque_opacity_pixels_changed =
        changed_pixel_count(base_only_pixels, opaque_opacity_pixels)?;
    if opaque_opacity_pixels_changed != 0 {
        return Err(RenderError::Device(
            "headless opacity texture changed an explicitly opaque material".to_owned(),
        ));
    }
    let opacity_cutout_pixels_changed =
        changed_pixel_count(opaque_opacity_pixels, opacity_cutout_pixels)?;
    let opacity_cutout_pixels_removed = opaque_opacity_pixels
        .chunks_exact(4)
        .zip(opacity_cutout_pixels.chunks_exact(4))
        .filter(|(opaque, cutout)| *opaque != background && *cutout == background)
        .count();
    if opacity_cutout_pixels_removed == 0
        || opacity_cutout_pixels_removed != opacity_cutout_pixels_changed
    {
        return Err(RenderError::Device(format!(
            "headless opacity cutout removed {opacity_cutout_pixels_removed} of {opacity_cutout_pixels_changed} changed pixels"
        )));
    }
    Ok(HeadlessRenderReport {
        adapter: adapter_report(&adapter),
        frames_rendered,
        modes_rendered: u32::try_from(modes.len()).map_err(|_| RenderError::ResourceLimit)?,
        viewport_sizes_rendered: u32::try_from(sizes.len())
            .map_err(|_| RenderError::ResourceLimit)?,
        dds_textures_uploaded: u32::try_from(material_textures.len())
            .map_err(|_| RenderError::ResourceLimit)?,
        sampled_material_roles: u32::try_from(role_changes.len())
            .map_err(|_| RenderError::ResourceLimit)?,
        material_ranges_rendered: u32::try_from(mesh.material_ranges.len())
            .map_err(|_| RenderError::ResourceLimit)?,
        composed_material_pixels_changed,
        emissive_factor_pixels_changed,
        roughness_factor_pixels_changed,
        metalness_factor_pixels_changed,
        specular_factor_pixels_changed,
        specular_texture_pixels_changed,
        dielectric_specular_pixels_changed,
        opacity_cutout_pixels_removed,
        opaque_opacity_pixels_changed,
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
    default_material_bind_group: &wgpu::BindGroup,
    active_material_bindings: &BTreeMap<u32, GpuMaterialBinding>,
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
        default_material_bind_group,
        active_material_bindings,
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
    default_material_bind_group: &wgpu::BindGroup,
    active_material_bindings: &BTreeMap<u32, GpuMaterialBinding>,
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
    camera_uniform.solid_mode = 0;
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
        default_material_bind_group,
        active_material_bindings,
        camera_bind_group,
        pipelines,
        ViewMode::TexturedSolid,
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

fn read_headless_pixels(
    device: &wgpu::Device,
    readback: &wgpu::Buffer,
    width: u32,
    height: u32,
) -> Result<Vec<u8>, RenderError> {
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
    let pixels = mapped.to_vec();
    drop(mapped);
    readback.unmap();
    Ok(pixels)
}

fn changed_pixel_count(reference: &[u8], candidate: &[u8]) -> Result<usize, RenderError> {
    if reference.len() != candidate.len() || !reference.len().is_multiple_of(4) {
        return Err(RenderError::Device(format!(
            "headless pixel comparison size mismatch: {} versus {} bytes",
            reference.len(),
            candidate.len()
        )));
    }
    Ok(reference
        .chunks_exact(4)
        .zip(candidate.chunks_exact(4))
        .filter(|(reference, candidate)| reference != candidate)
        .count())
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

fn draw_textured_solid<'a>(
    pass: &mut wgpu::RenderPass<'a>,
    mesh: &'a GpuMeshBuffers,
    default_material_bind_group: &'a wgpu::BindGroup,
    active_material_bindings: &'a BTreeMap<u32, GpuMaterialBinding>,
    pipeline: &'a wgpu::RenderPipeline,
) {
    pass.set_pipeline(pipeline);
    pass.set_index_buffer(mesh.triangle_index.slice(..), wgpu::IndexFormat::Uint32);
    for range in &mesh.material_ranges {
        let bind_group = active_material_bindings
            .get(&range.material)
            .map_or(default_material_bind_group, |binding| &binding.bind_group);
        pass.set_bind_group(0, bind_group, &[]);
        pass.draw_indexed(
            range.first_index..range.first_index.saturating_add(range.index_count),
            0,
            0..1,
        );
    }
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
    default_material_bind_group: &'a wgpu::BindGroup,
    active_material_bindings: &'a BTreeMap<u32, GpuMaterialBinding>,
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
    pass.set_bind_group(0, default_material_bind_group, &[]);
    pass.set_bind_group(1, camera_bind_group, &[]);
    pass.set_vertex_buffer(0, mesh.vertex.slice(..));
    match view_mode {
        ViewMode::TexturedSolid => draw_textured_solid(
            pass,
            mesh,
            default_material_bind_group,
            active_material_bindings,
            solid_pipeline,
        ),
        ViewMode::Solid => draw_solid(pass, mesh, solid_pipeline),
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

fn resolve_material_bindings<'a>(
    material_indices_by_texture: impl IntoIterator<Item = (TextureRole, &'a [Vec<u32>])>,
    lod_index: usize,
) -> Result<BTreeMap<u32, MaterialTextureIndices>, RenderError> {
    let mut active = BTreeMap::<u32, MaterialTextureIndices>::new();
    for (texture_index, (role, ownership)) in material_indices_by_texture.into_iter().enumerate() {
        let Some(materials) = ownership.get(lod_index) else {
            continue;
        };
        for material in materials {
            let slots = active.entry(*material).or_default();
            let slot = match role {
                TextureRole::BaseColor => &mut slots.base_color,
                TextureRole::Normal => &mut slots.normal,
                TextureRole::Material => &mut slots.surface,
                TextureRole::Roughness => &mut slots.roughness,
                TextureRole::Metalness => &mut slots.metalness,
                TextureRole::Occlusion => &mut slots.occlusion,
                TextureRole::Emissive => &mut slots.emissive,
                TextureRole::Specular => &mut slots.specular,
                TextureRole::Opacity => &mut slots.opacity,
                _ => {
                    return Err(RenderError::Texture(format!(
                        "the {role:?} role is not sampled by the current material approximation"
                    )));
                }
            };
            if slot.replace(texture_index).is_some() {
                return Err(RenderError::Texture(format!(
                    "material {material} has more than one {role:?} texture in LOD {lod_index}"
                )));
            }
        }
    }
    Ok(active)
}

fn resolve_material_factors<'a>(
    factors_by_owner: impl IntoIterator<Item = (MaterialPreviewFactors, &'a [Vec<u32>])>,
    lod_index: usize,
) -> Result<BTreeMap<u32, MaterialPreviewFactors>, RenderError> {
    let mut active = BTreeMap::<u32, MaterialPreviewFactors>::new();
    for (factors, ownership) in factors_by_owner {
        let Some(materials) = ownership.get(lod_index) else {
            continue;
        };
        for material in materials {
            let resolved = active.entry(*material).or_default();
            if let Some(color) = factors.emissive_color {
                if resolved.emissive_color.is_some_and(|existing| {
                    existing
                        .into_iter()
                        .zip(color)
                        .any(|(left, right)| left.to_bits() != right.to_bits())
                }) {
                    return Err(RenderError::Texture(format!(
                        "material {material} has conflicting emissive colors in LOD {lod_index}"
                    )));
                }
                resolved.emissive_color = Some(color);
            }
            if let Some(intensity) = factors.emissive_intensity {
                if resolved
                    .emissive_intensity
                    .is_some_and(|existing| existing.to_bits() != intensity.to_bits())
                {
                    return Err(RenderError::Texture(format!(
                        "material {material} has conflicting emissive intensities in LOD {lod_index}"
                    )));
                }
                resolved.emissive_intensity = Some(intensity);
            }
            if let Some(roughness) = factors.roughness {
                if resolved
                    .roughness
                    .is_some_and(|existing| existing.to_bits() != roughness.to_bits())
                {
                    return Err(RenderError::Texture(format!(
                        "material {material} has conflicting roughness factors in LOD {lod_index}"
                    )));
                }
                resolved.roughness = Some(roughness);
            }
            if let Some(metalness) = factors.metalness {
                if resolved
                    .metalness
                    .is_some_and(|existing| existing.to_bits() != metalness.to_bits())
                {
                    return Err(RenderError::Texture(format!(
                        "material {material} has conflicting metalness factors in LOD {lod_index}"
                    )));
                }
                resolved.metalness = Some(metalness);
            }
            if let Some(specular) = factors.specular {
                if resolved
                    .specular
                    .is_some_and(|existing| existing.to_bits() != specular.to_bits())
                {
                    return Err(RenderError::Texture(format!(
                        "material {material} has conflicting specular factors in LOD {lod_index}"
                    )));
                }
                resolved.specular = Some(specular);
            }
            if let Some(alpha_cutoff) = factors.alpha_cutoff {
                if resolved
                    .alpha_cutoff
                    .is_some_and(|existing| existing.to_bits() != alpha_cutoff.to_bits())
                {
                    return Err(RenderError::Texture(format!(
                        "material {material} has conflicting alpha cutoffs in LOD {lod_index}"
                    )));
                }
                resolved.alpha_cutoff = Some(alpha_cutoff);
            }
        }
    }
    Ok(active)
}

fn vertex_tangents(snapshot: &DrawSnapshot) -> Result<Vec<[f32; 4]>, RenderError> {
    if snapshot.positions.len() != snapshot.normals.len()
        || snapshot.positions.len() != snapshot.uvs.len()
    {
        return Err(RenderError::InvalidSnapshot(format!(
            "{} positions have {} normals and {} texture coordinates",
            snapshot.positions.len(),
            snapshot.normals.len(),
            snapshot.uvs.len()
        )));
    }
    if !snapshot.indices.len().is_multiple_of(3) {
        return Err(RenderError::InvalidSnapshot(
            "triangle index count is not divisible by three".to_owned(),
        ));
    }
    let mut accumulated_tangent = vec![Vec3::ZERO; snapshot.positions.len()];
    let mut accumulated_bitangent = vec![Vec3::ZERO; snapshot.positions.len()];
    for triangle in snapshot.indices.chunks_exact(3) {
        let indices = [
            usize::try_from(triangle[0]).map_err(|_| RenderError::ResourceLimit)?,
            usize::try_from(triangle[1]).map_err(|_| RenderError::ResourceLimit)?,
            usize::try_from(triangle[2]).map_err(|_| RenderError::ResourceLimit)?,
        ];
        let mut positions = [Vec3::ZERO; 3];
        let mut uvs = [Vec2::ZERO; 3];
        for (corner, index) in indices.iter().copied().enumerate() {
            positions[corner] = snapshot
                .positions
                .get(index)
                .copied()
                .map(Vec3::from_array)
                .ok_or_else(|| {
                    RenderError::InvalidSnapshot(format!(
                        "triangle index {index} exceeds the vertex count"
                    ))
                })?;
            uvs[corner] = Vec2::from_array(snapshot.uvs[index]);
        }
        let edge_one = positions[1] - positions[0];
        let edge_two = positions[2] - positions[0];
        let uv_one = uvs[1] - uvs[0];
        let uv_two = uvs[2] - uvs[0];
        let determinant = uv_one.x * uv_two.y - uv_one.y * uv_two.x;
        if !determinant.is_finite() || determinant.abs() <= 1.0e-12 {
            continue;
        }
        let reciprocal = determinant.recip();
        let tangent = (edge_one * uv_two.y - edge_two * uv_one.y) * reciprocal;
        let bitangent = (edge_two * uv_one.x - edge_one * uv_two.x) * reciprocal;
        if !tangent.is_finite() || !bitangent.is_finite() {
            continue;
        }
        for index in indices {
            accumulated_tangent[index] += tangent;
            accumulated_bitangent[index] += bitangent;
        }
    }
    Ok(snapshot
        .normals
        .iter()
        .enumerate()
        .map(|(index, normal)| {
            let normal = Vec3::from_array(*normal).try_normalize().unwrap_or(Vec3::Y);
            let projected =
                accumulated_tangent[index] - normal * normal.dot(accumulated_tangent[index]);
            let fallback_axis = if normal.x.abs() < 0.9 {
                Vec3::X
            } else {
                Vec3::Y
            };
            let fallback = (fallback_axis - normal * normal.dot(fallback_axis))
                .try_normalize()
                .unwrap_or(Vec3::Z);
            let tangent = projected.try_normalize().unwrap_or(fallback);
            let handedness = if normal.cross(tangent).dot(accumulated_bitangent[index]) < 0.0 {
                -1.0
            } else {
                1.0
            };
            [tangent.x, tangent.y, tangent.z, handedness]
        })
        .collect())
}

fn material_index_batches(
    snapshot: &DrawSnapshot,
) -> Result<(Vec<u32>, Vec<GpuMaterialRange>), RenderError> {
    if !snapshot.indices.len().is_multiple_of(3) {
        return Err(RenderError::InvalidSnapshot(
            "triangle index count is not divisible by three".to_owned(),
        ));
    }
    let triangle_count = snapshot.indices.len() / 3;
    if snapshot.triangle_materials.len() != triangle_count {
        return Err(RenderError::InvalidSnapshot(format!(
            "{} triangles have {} material owners",
            triangle_count,
            snapshot.triangle_materials.len()
        )));
    }
    let mut grouped = BTreeMap::<u32, Vec<u32>>::new();
    for (triangle, material) in snapshot
        .indices
        .chunks_exact(3)
        .zip(snapshot.triangle_materials.iter().copied())
    {
        grouped
            .entry(material)
            .or_default()
            .extend_from_slice(triangle);
    }
    let mut indices = Vec::with_capacity(snapshot.indices.len());
    let mut ranges = Vec::with_capacity(grouped.len());
    for (material, material_indices) in grouped {
        let first_index = u32::try_from(indices.len()).map_err(|_| RenderError::ResourceLimit)?;
        let index_count =
            u32::try_from(material_indices.len()).map_err(|_| RenderError::ResourceLimit)?;
        indices.extend(material_indices);
        ranges.push(GpuMaterialRange {
            material,
            first_index,
            index_count,
        });
    }
    Ok((indices, ranges))
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
                ty: wgpu::BindingType::Texture {
                    sample_type: wgpu::TextureSampleType::Float { filterable: true },
                    view_dimension: wgpu::TextureViewDimension::D2,
                    multisampled: false,
                },
                count: None,
            },
            wgpu::BindGroupLayoutEntry {
                binding: 2,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Texture {
                    sample_type: wgpu::TextureSampleType::Float { filterable: true },
                    view_dimension: wgpu::TextureViewDimension::D2,
                    multisampled: false,
                },
                count: None,
            },
            wgpu::BindGroupLayoutEntry {
                binding: 3,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Texture {
                    sample_type: wgpu::TextureSampleType::Float { filterable: true },
                    view_dimension: wgpu::TextureViewDimension::D2,
                    multisampled: false,
                },
                count: None,
            },
            wgpu::BindGroupLayoutEntry {
                binding: 4,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Texture {
                    sample_type: wgpu::TextureSampleType::Float { filterable: true },
                    view_dimension: wgpu::TextureViewDimension::D2,
                    multisampled: false,
                },
                count: None,
            },
            wgpu::BindGroupLayoutEntry {
                binding: 5,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Texture {
                    sample_type: wgpu::TextureSampleType::Float { filterable: true },
                    view_dimension: wgpu::TextureViewDimension::D2,
                    multisampled: false,
                },
                count: None,
            },
            wgpu::BindGroupLayoutEntry {
                binding: 6,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Texture {
                    sample_type: wgpu::TextureSampleType::Float { filterable: true },
                    view_dimension: wgpu::TextureViewDimension::D2,
                    multisampled: false,
                },
                count: None,
            },
            wgpu::BindGroupLayoutEntry {
                binding: 7,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
                count: None,
            },
            wgpu::BindGroupLayoutEntry {
                binding: 8,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Buffer {
                    ty: wgpu::BufferBindingType::Uniform,
                    has_dynamic_offset: false,
                    min_binding_size: None,
                },
                count: None,
            },
            wgpu::BindGroupLayoutEntry {
                binding: 9,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Texture {
                    sample_type: wgpu::TextureSampleType::Float { filterable: true },
                    view_dimension: wgpu::TextureViewDimension::D2,
                    multisampled: false,
                },
                count: None,
            },
            wgpu::BindGroupLayoutEntry {
                binding: 10,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Texture {
                    sample_type: wgpu::TextureSampleType::Float { filterable: true },
                    view_dimension: wgpu::TextureViewDimension::D2,
                    multisampled: false,
                },
                count: None,
            },
        ],
    })
}

fn create_material_sampler(device: &wgpu::Device) -> wgpu::Sampler {
    device.create_sampler(&wgpu::SamplerDescriptor {
        label: Some("CDMW Rust Mesh Lab material sampler"),
        address_mode_u: wgpu::AddressMode::Repeat,
        address_mode_v: wgpu::AddressMode::Repeat,
        address_mode_w: wgpu::AddressMode::Repeat,
        mag_filter: wgpu::FilterMode::Linear,
        min_filter: wgpu::FilterMode::Linear,
        mipmap_filter: wgpu::MipmapFilterMode::Linear,
        ..Default::default()
    })
}

fn create_solid_texture(
    device: &wgpu::Device,
    queue: &wgpu::Queue,
    label: &str,
    format: wgpu::TextureFormat,
    pixel: [u8; 4],
) -> wgpu::Texture {
    let texture = device.create_texture(&wgpu::TextureDescriptor {
        label: Some(label),
        size: wgpu::Extent3d {
            width: 1,
            height: 1,
            depth_or_array_layers: 1,
        },
        mip_level_count: 1,
        sample_count: 1,
        dimension: wgpu::TextureDimension::D2,
        format,
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
        &pixel,
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
    texture
}

fn create_default_material_textures(
    device: &wgpu::Device,
    queue: &wgpu::Queue,
) -> DefaultMaterialTextures {
    DefaultMaterialTextures {
        base_color: create_solid_texture(
            device,
            queue,
            "CDMW Rust Mesh Lab default base color",
            wgpu::TextureFormat::Rgba8UnormSrgb,
            [210, 215, 225, 255],
        ),
        normal: create_solid_texture(
            device,
            queue,
            "CDMW Rust Mesh Lab default tangent normal",
            wgpu::TextureFormat::Rgba8Unorm,
            [128, 128, 255, 255],
        ),
        surface: create_solid_texture(
            device,
            queue,
            "CDMW Rust Mesh Lab default material surface",
            wgpu::TextureFormat::Rgba8Unorm,
            [255, 166, 0, 255],
        ),
        roughness: create_solid_texture(
            device,
            queue,
            "CDMW Rust Mesh Lab default roughness",
            wgpu::TextureFormat::Rgba8Unorm,
            [166, 0, 0, 255],
        ),
        metalness: create_solid_texture(
            device,
            queue,
            "CDMW Rust Mesh Lab default metalness",
            wgpu::TextureFormat::Rgba8Unorm,
            [0, 0, 0, 255],
        ),
        occlusion: create_solid_texture(
            device,
            queue,
            "CDMW Rust Mesh Lab default occlusion",
            wgpu::TextureFormat::Rgba8Unorm,
            [255, 0, 0, 255],
        ),
        emissive: create_solid_texture(
            device,
            queue,
            "CDMW Rust Mesh Lab default emissive",
            wgpu::TextureFormat::Rgba8UnormSrgb,
            [0, 0, 0, 255],
        ),
        specular: create_solid_texture(
            device,
            queue,
            "CDMW Rust Mesh Lab default specular",
            wgpu::TextureFormat::Rgba8Unorm,
            [0, 0, 0, 255],
        ),
        opacity: create_solid_texture(
            device,
            queue,
            "CDMW Rust Mesh Lab default opacity",
            wgpu::TextureFormat::Rgba8Unorm,
            [255, 255, 255, 255],
        ),
    }
}

fn create_material_bind_group(
    device: &wgpu::Device,
    layout: &wgpu::BindGroupLayout,
    sampler: &wgpu::Sampler,
    defaults: &DefaultMaterialTextures,
    textures: &[GpuMaterialTexture],
    indices: MaterialTextureIndices,
    factors: MaterialPreviewFactors,
) -> GpuMaterialBinding {
    let base_texture = indices
        .base_color
        .and_then(|index| textures.get(index))
        .map_or(&defaults.base_color, |texture| &texture._texture);
    let normal_texture = indices
        .normal
        .and_then(|index| textures.get(index))
        .map_or(&defaults.normal, |texture| &texture._texture);
    let surface_texture = indices
        .surface
        .and_then(|index| textures.get(index))
        .map_or(&defaults.surface, |texture| &texture._texture);
    let roughness_texture = indices
        .roughness
        .and_then(|index| textures.get(index))
        .map_or(&defaults.roughness, |texture| &texture._texture);
    let metalness_texture = indices
        .metalness
        .and_then(|index| textures.get(index))
        .map_or(&defaults.metalness, |texture| &texture._texture);
    let occlusion_texture = indices
        .occlusion
        .and_then(|index| textures.get(index))
        .map_or(&defaults.occlusion, |texture| &texture._texture);
    let emissive_texture = indices
        .emissive
        .and_then(|index| textures.get(index))
        .map_or(&defaults.emissive, |texture| &texture._texture);
    let specular_texture = indices
        .specular
        .and_then(|index| textures.get(index))
        .map_or(&defaults.specular, |texture| &texture._texture);
    let opacity_texture = indices
        .opacity
        .and_then(|index| textures.get(index))
        .map_or(&defaults.opacity, |texture| &texture._texture);
    let base_view = base_texture.create_view(&wgpu::TextureViewDescriptor::default());
    let normal_view = normal_texture.create_view(&wgpu::TextureViewDescriptor::default());
    let surface_view = surface_texture.create_view(&wgpu::TextureViewDescriptor::default());
    let roughness_view = roughness_texture.create_view(&wgpu::TextureViewDescriptor::default());
    let metalness_view = metalness_texture.create_view(&wgpu::TextureViewDescriptor::default());
    let occlusion_view = occlusion_texture.create_view(&wgpu::TextureViewDescriptor::default());
    let emissive_view = emissive_texture.create_view(&wgpu::TextureViewDescriptor::default());
    let specular_view = specular_texture.create_view(&wgpu::TextureViewDescriptor::default());
    let opacity_view = opacity_texture.create_view(&wgpu::TextureViewDescriptor::default());
    let mut flags = 0;
    if indices.base_color.is_some() {
        flags |= MATERIAL_BASE_COLOR;
    }
    if indices.normal.is_some() {
        flags |= MATERIAL_NORMAL;
    }
    if indices.surface.is_some() {
        flags |= MATERIAL_SURFACE;
    }
    if indices.roughness.is_some() {
        flags |= MATERIAL_ROUGHNESS;
    }
    if indices.metalness.is_some() {
        flags |= MATERIAL_METALNESS;
    }
    if indices.occlusion.is_some() {
        flags |= MATERIAL_OCCLUSION;
    }
    if indices.emissive.is_some() {
        flags |= MATERIAL_EMISSIVE;
    }
    if indices.specular.is_some() {
        flags |= MATERIAL_SPECULAR;
    }
    if indices.opacity.is_some() {
        flags |= MATERIAL_OPACITY;
    }
    if factors.roughness.is_some() {
        flags |= MATERIAL_ROUGHNESS_FACTOR;
    }
    if factors.metalness.is_some() {
        flags |= MATERIAL_METALNESS_FACTOR;
    }
    if factors.specular.is_some() {
        flags |= MATERIAL_SPECULAR_FACTOR;
    }
    if factors.alpha_cutoff.is_some_and(|cutoff| cutoff > 0.0) {
        flags |= MATERIAL_ALPHA_CUTOUT;
    }
    let uniform = MaterialUniform {
        flags,
        _padding: [0; 3],
        emissive_color_and_intensity: {
            let color = factors.emissive_color.unwrap_or([1.0; 3]);
            [
                color[0],
                color[1],
                color[2],
                factors.emissive_intensity.unwrap_or(1.0),
            ]
        },
        surface_factors: [
            factors.roughness.unwrap_or(0.0),
            factors.metalness.unwrap_or(0.0),
            factors.specular.unwrap_or(0.0),
            factors.alpha_cutoff.unwrap_or(0.0),
        ],
    };
    let uniform_buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
        label: Some("CDMW Rust Mesh Lab material uniform"),
        contents: bytemuck::bytes_of(&uniform),
        usage: wgpu::BufferUsages::UNIFORM,
    });
    let bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
        label: Some("CDMW Rust Mesh Lab texture bind group"),
        layout,
        entries: &[
            wgpu::BindGroupEntry {
                binding: 0,
                resource: wgpu::BindingResource::TextureView(&base_view),
            },
            wgpu::BindGroupEntry {
                binding: 1,
                resource: wgpu::BindingResource::TextureView(&normal_view),
            },
            wgpu::BindGroupEntry {
                binding: 2,
                resource: wgpu::BindingResource::TextureView(&surface_view),
            },
            wgpu::BindGroupEntry {
                binding: 3,
                resource: wgpu::BindingResource::TextureView(&roughness_view),
            },
            wgpu::BindGroupEntry {
                binding: 4,
                resource: wgpu::BindingResource::TextureView(&metalness_view),
            },
            wgpu::BindGroupEntry {
                binding: 5,
                resource: wgpu::BindingResource::TextureView(&occlusion_view),
            },
            wgpu::BindGroupEntry {
                binding: 6,
                resource: wgpu::BindingResource::TextureView(&emissive_view),
            },
            wgpu::BindGroupEntry {
                binding: 7,
                resource: wgpu::BindingResource::Sampler(sampler),
            },
            wgpu::BindGroupEntry {
                binding: 8,
                resource: uniform_buffer.as_entire_binding(),
            },
            wgpu::BindGroupEntry {
                binding: 9,
                resource: wgpu::BindingResource::TextureView(&specular_view),
            },
            wgpu::BindGroupEntry {
                binding: 10,
                resource: wgpu::BindingResource::TextureView(&opacity_view),
            },
        ],
    });
    GpuMaterialBinding {
        bind_group,
        _uniform_buffer: uniform_buffer,
    }
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
    fn material_uniform_and_vertex_match_the_wgsl_layout_contracts() {
        assert_eq!(std::mem::size_of::<MaterialUniform>(), 48);
        assert_eq!(std::mem::size_of::<GpuVertex>(), 48);
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
    fn material_batches_group_noncontiguous_triangles_without_losing_indices() {
        let snapshot = DrawSnapshot {
            mesh_identity: 1,
            draw_revision: 1,
            topology_generation: 1,
            positions: vec![[0.0, 0.0, 0.0]; 4],
            normals: vec![[0.0, 1.0, 0.0]; 4],
            uvs: vec![[0.0, 0.0]; 4],
            indices: vec![0, 1, 2, 1, 3, 2, 2, 3, 0],
            triangle_materials: vec![7, 3, 7],
            selected_vertices: Vec::new(),
            fingerprint: String::new(),
        };
        let (indices, ranges) = material_index_batches(&snapshot).expect("material batches");
        assert_eq!(indices, vec![1, 3, 2, 0, 1, 2, 2, 3, 0]);
        assert_eq!(
            ranges,
            vec![
                GpuMaterialRange {
                    material: 3,
                    first_index: 0,
                    index_count: 3,
                },
                GpuMaterialRange {
                    material: 7,
                    first_index: 3,
                    index_count: 6,
                },
            ]
        );
    }

    #[test]
    fn material_binding_conflicts_fail_instead_of_retaining_a_previous_guess() {
        let distinct = [
            (TextureRole::BaseColor, vec![vec![0_u32]]),
            (TextureRole::Normal, vec![vec![0_u32]]),
            (TextureRole::Material, vec![vec![0_u32]]),
            (TextureRole::Roughness, vec![vec![0_u32]]),
            (TextureRole::Metalness, vec![vec![0_u32]]),
            (TextureRole::Occlusion, vec![vec![0_u32]]),
            (TextureRole::Emissive, vec![vec![0_u32]]),
            (TextureRole::Specular, vec![vec![0_u32]]),
            (TextureRole::Opacity, vec![vec![0_u32]]),
            (TextureRole::BaseColor, vec![vec![1_u32]]),
        ];
        let bindings = resolve_material_bindings(
            distinct
                .iter()
                .map(|(role, ownership)| (*role, ownership.as_slice())),
            0,
        )
        .expect("distinct material-role bindings");
        assert_eq!(
            bindings,
            BTreeMap::from([
                (
                    0,
                    MaterialTextureIndices {
                        base_color: Some(0),
                        normal: Some(1),
                        surface: Some(2),
                        roughness: Some(3),
                        metalness: Some(4),
                        occlusion: Some(5),
                        emissive: Some(6),
                        specular: Some(7),
                        opacity: Some(8),
                    }
                ),
                (
                    1,
                    MaterialTextureIndices {
                        base_color: Some(9),
                        ..MaterialTextureIndices::default()
                    }
                ),
            ])
        );

        let conflicting = [
            (TextureRole::BaseColor, vec![vec![0_u32]]),
            (TextureRole::BaseColor, vec![vec![0_u32]]),
        ];
        assert!(
            resolve_material_bindings(
                conflicting
                    .iter()
                    .map(|(role, ownership)| (*role, ownership.as_slice())),
                0
            )
            .is_err()
        );
        let conflicting_specular = [
            (TextureRole::Specular, vec![vec![0_u32]]),
            (TextureRole::Specular, vec![vec![0_u32]]),
        ];
        assert!(
            resolve_material_bindings(
                conflicting_specular
                    .iter()
                    .map(|(role, ownership)| (*role, ownership.as_slice())),
                0
            )
            .is_err()
        );
        let conflicting_opacity = [
            (TextureRole::Opacity, vec![vec![0_u32]]),
            (TextureRole::Opacity, vec![vec![0_u32]]),
        ];
        assert!(
            resolve_material_bindings(
                conflicting_opacity
                    .iter()
                    .map(|(role, ownership)| (*role, ownership.as_slice())),
                0
            )
            .is_err()
        );
    }

    #[test]
    fn material_factors_merge_distinct_fields_and_reject_conflicts() {
        let ownership = vec![vec![2_u32]];
        let distinct = [
            (
                MaterialPreviewFactors {
                    emissive_color: Some([0.1, 0.2, 0.3]),
                    ..MaterialPreviewFactors::default()
                },
                ownership.clone(),
            ),
            (
                MaterialPreviewFactors {
                    emissive_intensity: Some(4.0),
                    ..MaterialPreviewFactors::default()
                },
                ownership.clone(),
            ),
            (
                MaterialPreviewFactors {
                    roughness: Some(0.7),
                    ..MaterialPreviewFactors::default()
                },
                ownership.clone(),
            ),
            (
                MaterialPreviewFactors {
                    metalness: Some(0.8),
                    ..MaterialPreviewFactors::default()
                },
                ownership.clone(),
            ),
            (
                MaterialPreviewFactors {
                    specular: Some(0.9),
                    ..MaterialPreviewFactors::default()
                },
                ownership.clone(),
            ),
            (
                MaterialPreviewFactors {
                    alpha_cutoff: Some(0.08),
                    ..MaterialPreviewFactors::default()
                },
                ownership.clone(),
            ),
        ];
        let resolved = resolve_material_factors(
            distinct
                .iter()
                .map(|(factors, ownership)| (*factors, ownership.as_slice())),
            0,
        )
        .expect("distinct material factors");
        assert_eq!(
            resolved.get(&2),
            Some(&MaterialPreviewFactors {
                emissive_color: Some([0.1, 0.2, 0.3]),
                emissive_intensity: Some(4.0),
                roughness: Some(0.7),
                metalness: Some(0.8),
                specular: Some(0.9),
                alpha_cutoff: Some(0.08),
            })
        );

        let conflicting = [
            (
                MaterialPreviewFactors {
                    emissive_intensity: Some(1.0),
                    ..MaterialPreviewFactors::default()
                },
                ownership.clone(),
            ),
            (
                MaterialPreviewFactors {
                    emissive_intensity: Some(2.0),
                    ..MaterialPreviewFactors::default()
                },
                ownership.clone(),
            ),
        ];
        assert!(
            resolve_material_factors(
                conflicting
                    .iter()
                    .map(|(factors, ownership)| (*factors, ownership.as_slice())),
                0,
            )
            .is_err()
        );
        let surface_conflicts = [
            (
                MaterialPreviewFactors {
                    roughness: Some(0.1),
                    ..MaterialPreviewFactors::default()
                },
                MaterialPreviewFactors {
                    roughness: Some(0.2),
                    ..MaterialPreviewFactors::default()
                },
            ),
            (
                MaterialPreviewFactors {
                    metalness: Some(0.1),
                    ..MaterialPreviewFactors::default()
                },
                MaterialPreviewFactors {
                    metalness: Some(0.2),
                    ..MaterialPreviewFactors::default()
                },
            ),
            (
                MaterialPreviewFactors {
                    specular: Some(0.1),
                    ..MaterialPreviewFactors::default()
                },
                MaterialPreviewFactors {
                    specular: Some(0.2),
                    ..MaterialPreviewFactors::default()
                },
            ),
            (
                MaterialPreviewFactors {
                    alpha_cutoff: Some(0.1),
                    ..MaterialPreviewFactors::default()
                },
                MaterialPreviewFactors {
                    alpha_cutoff: Some(0.2),
                    ..MaterialPreviewFactors::default()
                },
            ),
        ];
        for (left, right) in surface_conflicts {
            let claims = [(left, ownership.clone()), (right, ownership.clone())];
            assert!(
                resolve_material_factors(
                    claims
                        .iter()
                        .map(|(factors, ownership)| (*factors, ownership.as_slice())),
                    0,
                )
                .is_err()
            );
        }
    }

    #[test]
    fn tangent_basis_is_derived_from_positions_and_texture_coordinates() {
        let snapshot = DrawSnapshot {
            mesh_identity: 1,
            draw_revision: 1,
            topology_generation: 1,
            positions: vec![[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            normals: vec![[0.0, 0.0, 1.0]; 3],
            uvs: vec![[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]],
            indices: vec![0, 1, 2],
            triangle_materials: vec![0],
            selected_vertices: Vec::new(),
            fingerprint: String::new(),
        };
        let tangents = vertex_tangents(&snapshot).expect("tangent basis");
        assert_eq!(tangents, vec![[1.0, 0.0, 0.0, 1.0]; 3]);
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
            triangle_materials: Vec::new(),
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
