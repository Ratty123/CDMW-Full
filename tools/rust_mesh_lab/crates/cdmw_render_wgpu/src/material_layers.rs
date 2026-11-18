//! Source-resolution layered materials; group zero remains ABI-compatible.
use super::*;

pub(super) const FLAG: u32 = 1 << 27;
/// `LayerUniform::control[3]` bit: the surface beneath the layers has no base colour map.
pub const LAYER_CONTROL_NO_BASE: u32 = 1;
/// `LayerUniform::control[3]` bit: the binding only recolours the base (the
/// legacy dye of a part without colour layers); normal and response stay with
/// the surface shader's own maps.
pub const LAYER_CONTROL_COLOUR_ONLY: u32 = 2;
/// `LayerUniform::control[3]` bit: the Ver2 overlay step runs with the wrapper's
/// map in `OVERLAY_SLOT`. The game runs the step on every Ver2 pixel; without a
/// map of the wrapper's own it reads the engine's neutral grey, which changes
/// nothing, so the step is then left out.
pub const LAYER_CONTROL_OVERLAY: u32 = 4;
/// `LayerUniform::control[3]`, shifted left by the layer's channel (0 R, 1 G, 2
/// B): that layer overlays the map's luma (`_dyeingCustomPropertyMask* & 0x10000`).
pub const LAYER_CONTROL_OVERLAY_LUMA: u32 = 16;
/// `LayerUniform::control[0]` of the legacy families' rule.
pub const LAYER_MODE_LEGACY: u32 = 4;
/// Layer textures: the blend mask; colour, normal and response for R, G, B; the
/// detail mask; grime colour, normal and response for R, G, B; the overlay
/// colour map; then the blend layer's colour map.
pub const LAYER_TEXTURE_SLOTS: usize = 22;
/// Slot of `_detailMaskTexture` (red marks scratches, green grime).
pub const DETAIL_MASK_SLOT: usize = 10;
/// First grime slot; grime of channel k starts at `GRIME_SLOT + 3 * k`.
pub const GRIME_SLOT: usize = 11;
/// Slot of `_overlayColorTexture` (Ver2), sampled at the mesh UV as linear data.
pub const OVERLAY_SLOT: usize = 20;
/// Slot of `_detailDiffuseBlend` (Ver2): the blend layer the game calls the
/// symbol, placed once on the mesh UV, not tiled.
pub const BLEND_SLOT: usize = 21;
/// Sampled textures of one fragment stage with layers bound: 16 material maps,
/// the layer slots and the shadow map (39 of them; the limit leaves one spare).
const REQUIRED_SAMPLED_TEXTURES: u32 = 40;

#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable, Default)]
pub struct LayerEntryUniform {
    /// The layer's dye. Colour-blend layers (mode 1) carry the authored sRGB
    /// colour, which the game overlays in display space; the sequential
    /// overlays (mode 2) carry it linear.
    pub dye: [f32; 4],
    pub affine: [f32; 4],
    /// UV offset, the layer's blend flags, and 1 when the wrapper declares no
    /// colour map for the layer (the legacy rule then draws none).
    pub offset: [f32; 4],
    /// Opacity, mean linear luminance, presence, normal encoding (0 RGB, 1 RG, 2 signed RG).
    pub properties: [f32; 4],
    /// The grime layer's own tiling, as `affine`.
    pub grime_affine: [f32; 4],
    /// Grime UV offset, then the ramp's low and high edge over the detail mask's green.
    pub grime_offset: [f32; 4],
    /// `_tintColor` of the grime: sRGB colour and strength.
    pub grime_tint: [f32; 4],
    /// Grime intensity (0 to 2), presence, normal encoding, reserved.
    pub grime: [f32; 4],
    /// Scratch steps of roughness and metal (each -1 to 1), presence, reserved.
    pub scratch: [f32; 4],
    /// `_scratchTintColor`: sRGB colour and strength.
    pub scratch_tint: [f32; 4],
}

#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable, Default)]
pub struct LayerUniform {
    pub layers: [LayerEntryUniform; 3],
    /// `_dyeingColorMaskR/G/B` of a legacy family (mode 4): authored sRGB
    /// colour and alpha, zero where the wrapper has none. No Ver2 shader of the
    /// game reads them, so the other modes leave them zero.
    pub seeds: [[f32; 4]; 3],
    pub base_color: [f32; 4],
    /// Mode (1 normalized mask, 2 masked overlays, 3 eye alpha overlays, 4 the
    /// legacy families' dye and one detail layer per pixel), skin flag, eye
    /// flag, bits (`LAYER_CONTROL_*`: no base colour map, colour only, the Ver2
    /// overlay step and its options).
    pub control: [u32; 4],
    /// `_dyeingDetailLayerColorBlend`: the blend layer's sRGB dye and strength.
    pub blend_dye: [f32; 4],
    /// The blend layer's placement on the mesh UV, as a layer's `affine`.
    pub blend_affine: [f32; 4],
    /// Its UV offset, its opacity (`_dyeingGlobalOpacity` byte 3), presence.
    pub blend_offset: [f32; 4],
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
    /// Mask followed by colour, normal, packed response for R, G, B; then the
    /// detail mask and grime colour, normal, packed response for R, G, B.
    pub textures: [Option<LayerTexture>; LAYER_TEXTURE_SLOTS],
}

impl MaterialLayerSet {
    /// Whether `evaluate_material_layers` leaves the base colour map's colour off the
    /// surface. Outside the masked-overlay (2), eye (3) and legacy (4) modes a pixel's colour is the
    /// layer of its largest mask channel, and the base only where that channel has none;
    /// with a layer on R, G and B the base colour never shows. Its alpha and the base
    /// normal map still do.
    #[must_use]
    pub fn hides_base_colour(&self) -> bool {
        !matches!(self.uniform.control[0], 2 | 3 | LAYER_MODE_LEGACY)
            && self
                .uniform
                .layers
                .iter()
                .all(|layer| layer.properties[2] > 0.5)
    }
}

pub(super) struct GpuLayers {
    pub bind_group: wgpu::BindGroup,
    _uniform: wgpu::Buffer,
    _textures: Vec<Arc<wgpu::Texture>>,
}

pub(super) fn supported(device: &wgpu::Device) -> bool {
    device.limits().max_sampled_textures_per_shader_stage >= REQUIRED_SAMPLED_TEXTURES
}

pub(super) fn limits(adapter: &wgpu::Adapter) -> wgpu::Limits {
    let mut limits = wgpu::Limits::default();
    if adapter.limits().max_sampled_textures_per_shader_stage >= REQUIRED_SAMPLED_TEXTURES {
        limits.max_sampled_textures_per_shader_stage = REQUIRED_SAMPLED_TEXTURES;
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
        .is_ok_and(|adapter| {
            adapter.limits().max_sampled_textures_per_shader_stage >= REQUIRED_SAMPLED_TEXTURES
        })
}

pub(super) fn layout(device: &wgpu::Device) -> Option<wgpu::BindGroupLayout> {
    if !supported(device) {
        return None;
    }
    // Binding 10 is the uniform; texture slots from 10 up sit one binding higher.
    let mut entries: Vec<_> = (0..LAYER_TEXTURE_SLOTS as u32)
        .map(|slot| wgpu::BindGroupLayoutEntry {
            binding: texture_binding(slot as usize),
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

/// The bind group binding of a texture slot.
fn texture_binding(slot: usize) -> u32 {
    if slot < 10 {
        slot as u32
    } else {
        slot as u32 + 1
    }
}

pub(super) fn binding(
    device: &wgpu::Device,
    defaults: &DefaultMaterialTextures,
    uniform: &LayerUniform,
    uploaded: &[Option<UploadedDdsTexture>; LAYER_TEXTURE_SLOTS],
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
                let texture = if index == 0 || index == DETAIL_MASK_SLOT || index >= OVERLAY_SLOT {
                    &defaults.layer_mask
                } else {
                    let set = if index < DETAIL_MASK_SLOT {
                        index - 1
                    } else {
                        index - GRIME_SLOT
                    };
                    match set % 3 {
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
            binding: texture_binding(index),
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
        "fn material_layers_colour_only() -> bool { return false; }
fn evaluate_material_layers(uv: vec2<f32>, base: vec4<f32>) -> LayerSurface { return LayerSurface(base.rgb, vec3<f32>(0.0,0.0,1.0), vec3<f32>(1.0,0.66,0.0), vec3<f32>(0.0)); }"
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
        "{main}\n{shadows}\n{ambient}\n{}\n{}\n{}",
        include_str!("studio_lighting.wgsl"),
        icon_studio::wgsl(),
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
        assert_eq!(std::mem::size_of::<LayerEntryUniform>(), 160);
        assert_eq!(std::mem::size_of::<LayerUniform>(), 608);
        assert_eq!(std::mem::size_of::<MaterialUniform>(), 288);
        let shader = include_str!("material_layers.wgsl");
        for binding in 0..=LAYER_TEXTURE_SLOTS {
            assert!(shader.contains(&format!("@group(2) @binding({binding})")));
        }
        assert!(shader.contains("textureSampleBias"));
    }

    #[test]
    fn the_base_colour_is_hidden_only_under_three_summed_layers() {
        let mut set = MaterialLayerSet {
            lod_index: 0,
            material_index: 0,
            uniform: LayerUniform {
                control: [1, 0, 0, 0],
                ..Default::default()
            },
            textures: std::array::from_fn(|_| None),
        };
        for layer in &mut set.uniform.layers {
            layer.properties[2] = 1.0;
        }
        assert!(set.hides_base_colour(), "layers on R, G and B");
        set.uniform.control[0] = 2;
        assert!(
            !set.hides_base_colour(),
            "masked overlays start from the base"
        );
        set.uniform.control[0] = 3;
        assert!(!set.hides_base_colour(), "the eye starts from the base");
        set.uniform.control[0] = 1;
        set.uniform.layers[2].properties[2] = 0.0;
        assert!(!set.hides_base_colour(), "channel B shows the base");
    }
}
