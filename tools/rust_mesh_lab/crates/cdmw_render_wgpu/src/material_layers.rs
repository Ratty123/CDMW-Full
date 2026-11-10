//! Source-resolution layered materials; group zero remains ABI-compatible.
use super::*;

pub(super) const FLAG: u32 = 1 << 27;

#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable, Default)]
pub struct LayerEntryUniform {
    pub dye: [f32; 4],
    pub affine: [f32; 4],
    pub offset: [f32; 4],
    /// Opacity, mean linear luminance, presence, normal encoding (0 RGB, 1 RG, 2 signed RG).
    pub properties: [f32; 4],
}

#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable, Default)]
pub struct LayerUniform {
    pub layers: [LayerEntryUniform; 3],
    pub seeds: [[f32; 4]; 3],
    pub base_color: [f32; 4],
    /// Mode (1 shared normalized mask, 2 sequential overlays), skin flag, eye flag, reserved.
    pub control: [u32; 4],
}

#[derive(Debug, Clone)]
pub struct LayerTexture {
    pub bytes: Arc<[u8]>,
    pub role: TextureRole,
    pub source_sha256: String,
}

#[derive(Debug, Clone)]
pub struct MaterialLayerSet {
    pub lod_index: usize,
    pub material_index: u32,
    pub uniform: LayerUniform,
    /// Mask followed by colour, normal, packed response for R, G, B.
    pub textures: [Option<LayerTexture>; 10],
}

pub(super) struct GpuLayers {
    pub bind_group: wgpu::BindGroup,
    _uniform: wgpu::Buffer,
    _textures: Vec<Arc<wgpu::Texture>>,
}

pub(super) fn supported(device: &wgpu::Device) -> bool {
    device.limits().max_sampled_textures_per_shader_stage >= 32
}

pub(super) fn limits(adapter: &wgpu::Adapter) -> wgpu::Limits {
    let mut limits = wgpu::Limits::default();
    if adapter.limits().max_sampled_textures_per_shader_stage >= 32 {
        limits.max_sampled_textures_per_shader_stage = 32;
    } else if adapter.limits().max_sampled_textures_per_shader_stage >= 17 {
        limits.max_sampled_textures_per_shader_stage = 17;
    }
    limits
}

/// Read-only capability query for the package loader, before it selects CPU work.
pub async fn material_layers_supported() -> bool {
    let mut descriptor = wgpu::InstanceDescriptor::new_without_display_handle();
    descriptor.backends = wgpu::Backends::DX12;
    let instance = wgpu::Instance::new(descriptor);
    instance
        .request_adapter(&wgpu::RequestAdapterOptions {
            power_preference: wgpu::PowerPreference::HighPerformance,
            force_fallback_adapter: false,
            compatible_surface: None,
            apply_limit_buckets: false,
        })
        .await
        .is_ok_and(|adapter| adapter.limits().max_sampled_textures_per_shader_stage >= 32)
}

pub(super) fn layout(device: &wgpu::Device) -> Option<wgpu::BindGroupLayout> {
    if !supported(device) {
        return None;
    }
    let mut entries: Vec<_> = (0..10)
        .map(|binding| wgpu::BindGroupLayoutEntry {
            binding,
            visibility: wgpu::ShaderStages::FRAGMENT,
            ty: wgpu::BindingType::Texture {
                sample_type: wgpu::TextureSampleType::Float { filterable: true },
                view_dimension: wgpu::TextureViewDimension::D2,
                multisampled: false,
            },
            count: None,
        })
        .collect();
    entries.push(wgpu::BindGroupLayoutEntry {
        binding: 10,
        visibility: wgpu::ShaderStages::FRAGMENT,
        ty: wgpu::BindingType::Buffer {
            ty: wgpu::BufferBindingType::Uniform,
            has_dynamic_offset: false,
            min_binding_size: wgpu::BufferSize::new(std::mem::size_of::<LayerUniform>() as u64),
        },
        count: None,
    });
    Some(
        device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("material layers"),
            entries: &entries,
        }),
    )
}

pub(super) fn binding(
    device: &wgpu::Device,
    defaults: &DefaultMaterialTextures,
    uniform: &LayerUniform,
    uploaded: &[Option<UploadedDdsTexture>; 10],
) -> Option<Arc<GpuLayers>> {
    let layout = layout(device)?;
    let views: Vec<_> = uploaded
        .iter()
        .enumerate()
        .map(|(index, uploaded)| {
            if let Some(uploaded) = uploaded {
                uploaded.texture.create_view(&wgpu::TextureViewDescriptor {
                    format: Some(uploaded.view_format),
                    ..Default::default()
                })
            } else {
                let texture = if index == 0 {
                    &defaults.layer_mask
                } else {
                    match (index - 1) % 3 {
                        0 => &defaults.base_color,
                        1 => &defaults.normal,
                        _ => &defaults.surface,
                    }
                };
                texture.create_view(&Default::default())
            }
        })
        .collect();
    let buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
        label: Some("material layer uniform"),
        contents: bytemuck::bytes_of(uniform),
        usage: wgpu::BufferUsages::UNIFORM,
    });
    let mut entries: Vec<_> = views
        .iter()
        .enumerate()
        .map(|(index, view)| wgpu::BindGroupEntry {
            binding: index as u32,
            resource: wgpu::BindingResource::TextureView(view),
        })
        .collect();
    entries.push(wgpu::BindGroupEntry {
        binding: 10,
        resource: buffer.as_entire_binding(),
    });
    Some(Arc::new(GpuLayers {
        bind_group: device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("material layer binding"),
            layout: &layout,
            entries: &entries,
        }),
        _uniform: buffer,
        _textures: uploaded
            .iter()
            .flatten()
            .map(|texture| Arc::clone(&texture.texture))
            .collect(),
    }))
}

pub(super) fn shader(device: &wgpu::Device, include_depth: bool) -> String {
    let source = if supported(device) {
        include_str!("material_layers.wgsl")
    } else {
        "fn evaluate_material_layers(uv: vec2<f32>, base: vec4<f32>) -> LayerSurface { return LayerSurface(base.rgb, vec3<f32>(0.0,0.0,1.0), vec3<f32>(1.0,0.66,0.0), vec3<f32>(0.0)); }"
    };
    let main = SHADER.replace("// MATERIAL_LAYER_FUNCTIONS", source);
    let shadows = if include_depth && lighting_depth::shadow_supported(device) {
        include_str!("shadows.wgsl")
    } else {
        "fn shadow_visibility(world:vec3<f32>, normal:vec3<f32>) -> f32 { return 1.0; }"
    };
    let ambient = if include_depth && lighting_depth::shadow_supported(device) {
        include_str!("ambient_occlusion.wgsl")
            .replace(
                "// AMBIENT_BINDINGS",
                "@group(3) @binding(4) var<uniform> ambient: AmbientParameters;",
            )
            .replace("LOAD_DEPTH", "textureLoad(shadow_depth,p,1,0)")
    } else {
        "fn studio_ambient_visibility(pixel:vec2<f32>) -> f32 { return 1.0; }\nfn studio_view_direction(world:vec3<f32>) -> vec3<f32> { return safe_normalize(camera.view_direction.xyz,vec3(0.0,0.0,-1.0)); }".to_owned()
    };
    format!(
        "{main}\n{shadows}\n{ambient}\n{}\n{}",
        include_str!("studio_lighting.wgsl"),
        lighting_depth::SHADOW_FRAGMENT
    )
}

pub(super) fn apply(
    queue: &wgpu::Queue,
    material: &mut GpuMaterialBinding,
    layers: &Arc<GpuLayers>,
) {
    material.layers = Some(Arc::clone(layers));
    material.flags |= FLAG;
    queue.write_buffer(
        &material._uniform_buffer,
        0,
        bytemuck::bytes_of(&material.flags),
    );
}

pub(super) fn bind<'a>(pass: &mut wgpu::RenderPass<'a>, material: &'a GpuMaterialBinding) {
    pass.set_bind_group(0, &material.bind_group, &[]);
    if let Some(layers) = &material.layers {
        pass.set_bind_group(2, &layers.bind_group, &[]);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn layer_uniform_preserves_group_zero_abi() {
        assert_eq!(std::mem::size_of::<LayerEntryUniform>(), 64);
        assert_eq!(std::mem::size_of::<LayerUniform>(), 272);
        assert_eq!(std::mem::size_of::<MaterialUniform>(), 288);
        let shader = include_str!("material_layers.wgsl");
        for binding in 0..=10 {
            assert!(shader.contains(&format!("@group(2) @binding({binding})")));
        }
        assert!(shader.contains("textureSampleBias"));
    }
}
