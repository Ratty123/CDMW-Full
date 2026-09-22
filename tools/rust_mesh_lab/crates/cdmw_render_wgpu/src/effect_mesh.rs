//! Indexed, GPU-deformed lightning meshes. Geometry and curves are uploaded once;
//! a frame contains one small record per particle, never one record per triangle.
use super::*;

pub const MAX_EFFECT_MESH_TRIANGLES: usize = 4_194_304;
const MAX_PARTICLES: usize = 32_768;

#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
pub struct EffectMeshVertex {
    pub position: [f32; 3],
    pub normal: [f32; 3],
    pub uv: [f32; 2],
    pub controls: [f32; 4],
}

impl EffectMeshVertex {
    const ATTRIBUTES: [wgpu::VertexAttribute; 4] = wgpu::vertex_attr_array![
        0 => Float32x3, 1 => Float32x3, 2 => Float32x2, 3 => Float32x4
    ];
    fn layout() -> wgpu::VertexBufferLayout<'static> {
        wgpu::VertexBufferLayout {
            array_stride: std::mem::size_of::<Self>() as u64,
            step_mode: wgpu::VertexStepMode::Vertex,
            attributes: &Self::ATTRIBUTES,
        }
    }
}

/// Parameters and ten 128-sample curves for the decoded lightning variant.
/// This is an internal renderer ABI, not a saved project or package schema.
#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
pub struct EffectLightningMaterial {
    pub parameters: [[f32; 4]; 8],
    pub curves: [[f32; 128]; 10],
}

#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
pub struct EffectMeshParticle {
    pub transform: [[f32; 4]; 4],
    pub colour: [f32; 4],
    pub scale_age: [f32; 4],
    pub seed: [u32; 4],
    pub parent_scale: [f32; 4],
    pub parent_origin: [f32; 4],
}

#[derive(Debug, Clone, Copy)]
pub struct EffectMeshInstance {
    pub mesh_index: usize,
    pub particle: EffectMeshParticle,
    pub depth: f32,
}

#[derive(Debug, Clone)]
pub struct EffectMeshAsset {
    pub vertices: Vec<EffectMeshVertex>,
    pub indices: Vec<u32>,
    pub lightning: EffectLightningMaterial,
}

#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
pub struct EffectMeshView {
    pub eye_height: [f32; 4],
    pub fov_padding: [f32; 4],
}

struct Mesh {
    vertices: wgpu::Buffer,
    indices: wgpu::Buffer,
    index_count: u32,
    material: wgpu::Buffer,
    binding: Option<wgpu::BindGroup>,
}

#[derive(Default)]
pub(super) struct Resources {
    meshes: Vec<Mesh>,
    particles: Option<(wgpu::Buffer, usize)>,
    order: Vec<(usize, f32)>,
}

pub(super) struct MeshParticles {
    pub resources: Resources,
    layout: wgpu::BindGroupLayout,
    view: wgpu::Buffer,
    pipeline: wgpu::RenderPipeline,
}

impl MeshParticles {
    pub fn new(
        device: &wgpu::Device,
        format: wgpu::TextureFormat,
        camera: &wgpu::BindGroupLayout,
        texture: &wgpu::BindGroupLayout,
        depth: &wgpu::BindGroupLayout,
        samples: u32,
    ) -> Self {
        let layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("lightning mesh data"),
            entries: &[0, 1, 2].map(|binding| wgpu::BindGroupLayoutEntry {
                binding,
                visibility: wgpu::ShaderStages::VERTEX,
                ty: wgpu::BindingType::Buffer {
                    ty: if binding == 2 {
                        wgpu::BufferBindingType::Uniform
                    } else {
                        wgpu::BufferBindingType::Storage { read_only: true }
                    },
                    has_dynamic_offset: false,
                    min_binding_size: None,
                },
                count: None,
            }),
        });
        let view = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("lightning camera"),
            size: std::mem::size_of::<EffectMeshView>() as u64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let source = format!(
            "{}\n{}",
            effect_particle_shader::SHADER,
            super::effect_mesh_shader::SHADER
        );
        let source = if samples > 1 {
            source
                .replace("texture_depth_2d", "texture_depth_multisampled_2d")
                .replace(
                    "textureLoad(effect_scene_depth, pixel, 0)",
                    "textureLoad(effect_scene_depth, pixel, i32(sample_index))",
                )
        } else {
            source
        };
        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("decoded lightning mesh shader"),
            source: wgpu::ShaderSource::Wgsl(source.into()),
        });
        let pipeline_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("lightning mesh pipeline layout"),
            bind_group_layouts: &[Some(camera), Some(texture), Some(depth), Some(&layout)],
            immediate_size: 0,
        });
        let pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("indexed lightning particles"),
            layout: Some(&pipeline_layout),
            vertex: wgpu::VertexState {
                module: &shader,
                entry_point: Some("vs_effect_mesh"),
                compilation_options: Default::default(),
                buffers: &[Some(EffectMeshVertex::layout())],
            },
            fragment: Some(wgpu::FragmentState {
                module: &shader,
                entry_point: Some("fs_effect_particle"),
                compilation_options: Default::default(),
                targets: &[Some(wgpu::ColorTargetState {
                    format,
                    blend: Some(wgpu::BlendState {
                        color: wgpu::BlendComponent {
                            src_factor: wgpu::BlendFactor::SrcAlpha,
                            dst_factor: wgpu::BlendFactor::One,
                            operation: wgpu::BlendOperation::Add,
                        },
                        alpha: wgpu::BlendComponent {
                            src_factor: wgpu::BlendFactor::One,
                            dst_factor: wgpu::BlendFactor::One,
                            operation: wgpu::BlendOperation::Add,
                        },
                    }),
                    write_mask: wgpu::ColorWrites::ALL,
                })],
            }),
            primitive: wgpu::PrimitiveState {
                cull_mode: None,
                ..Default::default()
            },
            depth_stencil: Some(wgpu::DepthStencilState {
                format: DEPTH_FORMAT,
                depth_write_enabled: Some(false),
                depth_compare: Some(wgpu::CompareFunction::LessEqual),
                stencil: Default::default(),
                bias: Default::default(),
            }),
            multisample: wgpu::MultisampleState {
                count: samples,
                ..Default::default()
            },
            multiview_mask: None,
            cache: None,
        });
        Self {
            resources: Resources::default(),
            layout,
            view,
            pipeline,
        }
    }

    pub fn is_empty(&self) -> bool {
        self.resources.order.is_empty()
    }

    pub(super) fn draw<'a>(
        &'a self,
        pass: &mut wgpu::RenderPass<'a>,
        mesh_index: usize,
        first: u32,
        end: u32,
        camera: &'a wgpu::BindGroup,
        texture: &'a wgpu::BindGroup,
        depth: &'a wgpu::BindGroup,
    ) {
        let mesh = &self.resources.meshes[mesh_index];
        pass.set_pipeline(&self.pipeline);
        pass.set_bind_group(0, camera, &[]);
        pass.set_bind_group(1, texture, &[]);
        pass.set_bind_group(2, depth, &[]);
        pass.set_bind_group(3, mesh.binding.as_ref().expect("uploaded mesh"), &[]);
        pass.set_vertex_buffer(0, mesh.vertices.slice(..));
        pass.set_index_buffer(mesh.indices.slice(..), wgpu::IndexFormat::Uint32);
        pass.draw_indexed(0..mesh.index_count, 0, first..end);
    }

    pub fn add(
        &mut self,
        device: &wgpu::Device,
        asset: &EffectMeshAsset,
    ) -> Result<usize, RenderError> {
        if asset.vertices.is_empty()
            || asset.vertices.len() > 8192
            || asset.indices.is_empty()
            || asset.indices.len() > 8192 * 3
            || asset.indices.len() % 3 != 0
            || self.resources.meshes.len() >= 2048
            || self
                .resources
                .meshes
                .iter()
                .map(|m| m.vertices.size())
                .sum::<u64>()
                + (asset.vertices.len() * std::mem::size_of::<EffectMeshVertex>()) as u64
                > 32 * 1024 * 1024
            || self
                .resources
                .meshes
                .iter()
                .map(|m| m.indices.size())
                .sum::<u64>()
                + (asset.indices.len() * 4) as u64
                > 16 * 1024 * 1024
        {
            return Err(RenderError::ResourceLimit);
        }
        if bytemuck::cast_slice::<_, f32>(&asset.vertices)
            .iter()
            .any(|v| !v.is_finite())
            || bytemuck::cast_slice::<_, f32>(std::slice::from_ref(&asset.lightning))
                .iter()
                .any(|v| !v.is_finite())
            || asset
                .indices
                .iter()
                .any(|i| *i as usize >= asset.vertices.len())
        {
            return Err(RenderError::InvalidOverlay(
                "invalid lightning mesh or material".into(),
            ));
        }
        let buffer = |label, bytes, usage| {
            device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
                label: Some(label),
                contents: bytes,
                usage,
            })
        };
        let index = self.resources.meshes.len();
        self.resources.meshes.push(Mesh {
            vertices: buffer(
                "shared lightning vertices",
                bytemuck::cast_slice(&asset.vertices),
                wgpu::BufferUsages::VERTEX,
            ),
            indices: buffer(
                "shared lightning indices",
                bytemuck::cast_slice(&asset.indices),
                wgpu::BufferUsages::INDEX,
            ),
            material: buffer(
                "lightning curves",
                bytemuck::bytes_of(&asset.lightning),
                wgpu::BufferUsages::STORAGE,
            ),
            index_count: asset.indices.len() as u32,
            binding: None,
        });
        Ok(index)
    }

    pub fn set(
        &mut self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        instances: &[EffectMeshInstance],
        view: EffectMeshView,
    ) -> Result<(), RenderError> {
        if instances.len() > MAX_PARTICLES {
            return Err(RenderError::ResourceLimit);
        }
        if bytemuck::cast_slice::<_, f32>(std::slice::from_ref(&view))
            .iter()
            .any(|v| !v.is_finite())
            || view.eye_height[3] <= 0.
            || view.fov_padding[0] <= 0.
        {
            return Err(RenderError::InvalidOverlay(
                "invalid lightning camera".into(),
            ));
        }
        let mut triangles = 0usize;
        for instance in instances {
            let Some(mesh) = self.resources.meshes.get(instance.mesh_index) else {
                return Err(RenderError::InvalidOverlay("unknown lightning mesh".into()));
            };
            triangles += mesh.index_count as usize / 3;
            let p = &instance.particle;
            if !instance.depth.is_finite()
                || p.transform
                    .iter()
                    .flatten()
                    .chain(p.colour.iter())
                    .chain(p.scale_age.iter())
                    .chain(p.parent_scale.iter())
                    .chain(p.parent_origin.iter())
                    .any(|v| !v.is_finite())
                || p.scale_age[..3].iter().any(|v| *v <= 0.)
            {
                return Err(RenderError::InvalidOverlay(
                    "invalid lightning particle".into(),
                ));
            }
        }
        if triangles > MAX_EFFECT_MESH_TRIANGLES {
            return Err(RenderError::ResourceLimit);
        }
        self.resources.order.clear();
        if instances.is_empty() {
            return Ok(());
        }
        let mut ordered = instances.to_vec();
        ordered.sort_by(|a, b| b.depth.total_cmp(&a.depth));
        if self
            .resources
            .particles
            .as_ref()
            .is_none_or(|(_, capacity)| *capacity < ordered.len())
        {
            let capacity = ordered.len().next_power_of_two().min(MAX_PARTICLES);
            self.resources.particles = Some((
                device.create_buffer(&wgpu::BufferDescriptor {
                    label: Some("reusable lightning particles"),
                    size: (capacity * std::mem::size_of::<EffectMeshParticle>()) as u64,
                    usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_DST,
                    mapped_at_creation: false,
                }),
                capacity,
            ));
            for mesh in &mut self.resources.meshes {
                mesh.binding = None;
            }
        }
        let buffer = &self
            .resources
            .particles
            .as_ref()
            .expect("allocated particles")
            .0;
        for mesh in &mut self.resources.meshes {
            if mesh.binding.is_none() {
                mesh.binding = Some(device.create_bind_group(&wgpu::BindGroupDescriptor {
                    label: Some("lightning geometry binding"),
                    layout: &self.layout,
                    entries: &[
                        wgpu::BindGroupEntry {
                            binding: 0,
                            resource: mesh.material.as_entire_binding(),
                        },
                        wgpu::BindGroupEntry {
                            binding: 1,
                            resource: buffer.as_entire_binding(),
                        },
                        wgpu::BindGroupEntry {
                            binding: 2,
                            resource: self.view.as_entire_binding(),
                        },
                    ],
                }));
            }
        }
        let gpu = ordered.iter().map(|v| v.particle).collect::<Vec<_>>();
        queue.write_buffer(buffer, 0, bytemuck::cast_slice(&gpu));
        queue.write_buffer(&self.view, 0, bytemuck::bytes_of(&view));
        self.resources.order = ordered.iter().map(|v| (v.mesh_index, v.depth)).collect();
        Ok(())
    }
}

/// Merge the existing sorted sprite stream with mesh particles. A large mesh
/// counts as one particle in this order, and complete runs share an indexed draw.
pub(super) fn draw_combined<'a>(
    renderer: &'a WindowRenderer,
    pass: &mut wgpu::RenderPass<'a>,
    depth: &'a wgpu::BindGroup,
) {
    #[derive(Clone, Copy, PartialEq)]
    enum Kind {
        Sprite(usize),
        Mesh(usize),
    }
    let mut sprite_batch = 0usize;
    let mut sprite_at = 0usize;
    let mut mesh_at = 0usize;
    let mut run: Option<(Kind, u32, u32)> = None;
    let meshes = &renderer.effect_mesh;
    let flush = |pass: &mut wgpu::RenderPass<'a>, kind, first, end| {
        pass.set_bind_group(0, &renderer.camera_bind_group, &[]);
        pass.set_bind_group(2, depth, &[]);
        match kind {
            Kind::Sprite(i) => {
                let batch = &renderer.effect_batches[i];
                pass.set_pipeline(match batch.blend {
                    EffectBlendMode::Alpha => &renderer.effect_particle_alpha_pipeline,
                    EffectBlendMode::Additive => &renderer.effect_particle_additive_pipeline,
                });
                pass.set_bind_group(
                    1,
                    &renderer.effect_textures[batch.texture_index].bind_group,
                    &[],
                );
                pass.set_vertex_buffer(0, renderer.effect_quad.slice(..));
                pass.set_vertex_buffer(1, batch.instances.slice(..));
                pass.draw(0..6, first..end);
            }
            Kind::Mesh(i) => {
                meshes.draw(
                    pass,
                    i,
                    first,
                    end,
                    &renderer.camera_bind_group,
                    &renderer.effect_textures[0].bind_group,
                    depth,
                );
            }
        }
    };
    loop {
        let sprite = renderer.effect_batches.get(sprite_batch);
        let mesh = meshes.resources.order.get(mesh_at);
        let take_sprite = sprite.is_some_and(|s| mesh.is_none_or(|m| s.depths[sprite_at] >= m.1));
        let (kind, at) = if take_sprite {
            let s = sprite.expect("available sprite");
            let result = (
                Kind::Sprite(sprite_batch),
                s.first_instance + sprite_at as u32,
            );
            sprite_at += 1;
            if sprite_at == s.instance_count as usize {
                sprite_batch += 1;
                sprite_at = 0;
            }
            result
        } else if let Some(&(index, _)) = mesh {
            let result = (Kind::Mesh(index), mesh_at as u32);
            mesh_at += 1;
            result
        } else {
            break;
        };
        if let Some((old, first, end)) = run {
            if old == kind && end == at {
                run = Some((old, first, end + 1));
                continue;
            }
            flush(pass, old, first, end);
        }
        run = Some((kind, at, at + 1));
    }
    if let Some((kind, first, end)) = run {
        flush(pass, kind, first, end);
    }
}
