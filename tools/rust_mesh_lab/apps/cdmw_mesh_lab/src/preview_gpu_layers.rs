//! Select source-backed RGB layers without changing package or authoring authority.
use crate::cdmw_session::{
    CdmwTextureResource, FileReference, MAX_TEXTURE_TOTAL_BYTES, PreviewCoreMaterial,
    PreviewCoreMaterialGraph, PreviewCoreMaterialLayer, SessionError, SessionMaterialPresentation,
    check_preview_cancelled,
};
use crate::preview_core_material::{
    PreviewCoreMaterialCompositionMetrics, compose_preview_core_material_resources_cancellable,
};
use cdmw_formats::MeshDocument;
use cdmw_render_wgpu::{
    BLEND_MATERIAL_SLOT, BLEND_NORMAL_SLOT, BLEND_SLOT, DETAIL_MASK_SLOT, GRIME_SLOT,
    LAYER_CONTROL_COLOUR_ONLY, LAYER_CONTROL_NO_BASE, LAYER_CONTROL_OVERLAY,
    LAYER_CONTROL_OVERLAY_LUMA, LAYER_MODE_LEGACY, LayerEntryUniform, BLEND_HEIGHT_BASE,
    LAYER_MODE_BLEND_HEIGHT,
    LayerTexture, LayerUniform, MaterialLayerSet, OVERLAY_SLOT,
};
use cdmw_texture::{
    DdsFormat, TextureRole, dds_mean_luminance_with_verified_sha256,
    inspect_dds_with_verified_sha256,
};
use std::cell::RefCell;
use std::collections::{BTreeMap, BTreeSet};
use std::sync::{Arc, OnceLock};

thread_local! { static MEANS: RefCell<BTreeMap<String, f32>> = RefCell::default(); }

pub fn supported() -> bool {
    static SUPPORT: OnceLock<bool> = OnceLock::new();
    *SUPPORT.get_or_init(|| pollster::block_on(cdmw_render_wgpu::material_layers_supported()))
}

fn channel(layer: &PreviewCoreMaterialLayer) -> Option<usize> {
    match layer.mask_channel.as_str() {
        "r" => Some(0),
        "g" => Some(1),
        "b" => Some(2),
        _ => None,
    }
}

pub(super) fn eligible(material: &PreviewCoreMaterial) -> bool {
    if material.authoring_channels != 0 {
        return false;
    }
    if material
        .layers
        .first()
        .is_some_and(|base| base.shader_family.eq_ignore_ascii_case("SkinnedMeshEye"))
    {
        let mut channels = BTreeSet::new();
        return material.layers.len() > 1
            && material.layers.iter().skip(1).all(|layer| {
                eye_channel(layer).is_some_and(|channel| channels.insert(channel))
                    && layer.mask_channel == "a"
                    && layer
                        .diffuse
                        .as_ref()
                        .zip(layer.mask.as_ref())
                        .is_some_and(|(color, mask)| color.sha256 == mask.sha256)
            });
    }
    let mut channels = BTreeSet::new();
    let mut grime_channels = BTreeSet::new();
    let mut detail_mask = None;
    let mut mask = None;
    let mut mask_parameter = None;
    for layer in material.layers.iter().skip(1) {
        if layer.is_legacy_dye() || layer.is_ver2_overlay() || layer.is_ver2_blend() {
            // The legacy dye recolours the base beneath the layers; the Ver2
            // overlay and blend layer the colour above them. None is one of the
            // three layers, and none decides whether the layer path draws them.
            continue;
        }
        if layer.is_ver2_grime() {
            // Grime the game's rule can draw rides on its channel's layer slot.
            let Some(channel) = channel(layer) else {
                return false;
            };
            let reference = layer.detail_mask.as_ref().expect("ver2 grime detail mask");
            if !grime_channels.insert(channel)
                || detail_mask.is_some_and(|sha| sha != &reference.sha256)
            {
                return false;
            }
            detail_mask = Some(&reference.sha256);
        } else if !matches!(layer.layer_role.as_str(), "detail" | "color_seed") {
            return false;
        } else if layer.is_ver2_scratch() {
            // Scratches and grime read one detail mask.
            let reference = layer
                .detail_mask
                .as_ref()
                .expect("ver2 scratch detail mask");
            if detail_mask.is_some_and(|sha| sha != &reference.sha256) {
                return false;
            }
            detail_mask = Some(&reference.sha256);
        }
        if mask_parameter.is_some_and(|name| name != &layer.mask_parameter) {
            return false;
        }
        mask_parameter = Some(&layer.mask_parameter);
        if layer.mask_parameter != "_colorBlendingMaskTexture"
            && (!matches!(
                layer.mask_parameter.as_str(),
                "_maskTexture" | "_detailMaskTexture"
            ) || layer.layer_role != "detail"
                || layer.blend_flags.is_none()
                || layer.blend_opacity.is_none())
        {
            return false;
        }
        let Some(channel) = channel(layer) else {
            return false;
        };
        let Some(reference) = &layer.mask else {
            return false;
        };
        if mask.is_some_and(|sha| sha != &reference.sha256) {
            return false;
        }
        mask = Some(&reference.sha256);
        if layer.layer_role == "detail"
            && (layer.diffuse.is_none()
                || !channels.insert(channel)
                || layer.source_parameter
                    != [
                        "_detailDiffuseMaskR",
                        "_detailDiffuseMaskG",
                        "_detailDiffuseMaskB",
                    ][channel])
        {
            return false;
        }
    }
    !channels.is_empty() && channels.len() <= 3
}

/// The dye colours the layer path draws for a layer-shaped legacy material: its
/// legacy dye, when `_maskTexture` is also the mask its colour layers read (the
/// layer binding has one mask slot).
pub(super) fn layered_legacy_dye(material: &PreviewCoreMaterial) -> Option<[[f32; 4]; 3]> {
    let (seeds, dye_mask) = material.legacy_dye()?;
    let layer_mask = material
        .layers
        .iter()
        .skip(1)
        .filter(|layer| !layer.is_legacy_dye())
        .find_map(|layer| layer.mask.as_ref())?;
    layer_mask
        .sha256
        .eq_ignore_ascii_case(&dye_mask.sha256)
        .then_some(seeds)
}

/// Whether the material is a legacy part whose only colour rule beyond its base
/// map is the dye: `_dyeingColorMaskR/G/B` through `_maskTexture`, with no colour
/// layer. The GPU then recolours the base and leaves every other map alone.
pub(super) fn dye_only(material: &PreviewCoreMaterial) -> bool {
    material.authoring_channels == 0
        && material.legacy_dye().is_some()
        && material
            .layers
            .first()
            .is_some_and(|base| base.diffuse.is_some())
        && !material.layers.iter().skip(1).any(|layer| {
            !layer.is_legacy_dye() && (layer.diffuse.is_some() || layer.layer_role == "color_seed")
        })
}

fn build_dye_only(
    material: &PreviewCoreMaterial,
    sources: &BTreeMap<String, Arc<[u8]>>,
) -> MaterialLayerSet {
    let (seeds, mask) = material.legacy_dye().expect("dye-only material");
    let mut textures: [Option<LayerTexture>; cdmw_render_wgpu::LAYER_TEXTURE_SLOTS] =
        std::array::from_fn(|_| None);
    textures[0] = Some(layer_texture(mask, TextureRole::LayerMask, sources));
    MaterialLayerSet {
        lod_index: material.lod_index as usize,
        material_index: material.material_index,
        uniform: LayerUniform {
            seeds,
            base_color: [1.0; 4],
            control: [LAYER_MODE_LEGACY, 0, 0, LAYER_CONTROL_COLOUR_ONLY],
            ..Default::default()
        },
        textures,
    }
}

fn eye_channel(layer: &PreviewCoreMaterialLayer) -> Option<usize> {
    if layer.layer_role != "overlay" || !layer.shader_family.eq_ignore_ascii_case("SkinnedMeshEye")
    {
        return None;
    }
    match layer.source_parameter.as_str() {
        "_irisDiffuseTexture" => Some(0),
        "_pupilTexture" => Some(1),
        _ => None,
    }
}

fn linear(value: f32) -> f32 {
    if value <= 0.04045 {
        value / 12.92
    } else {
        ((value + 0.055) / 1.055).powf(2.4)
    }
}

fn dye(tint: [f32; 4]) -> [f32; 4] {
    [linear(tint[0]), linear(tint[1]), linear(tint[2]), tint[3]]
}

fn mean(texture: &LayerTexture) -> Result<f32, SessionError> {
    if let Some(value) = MEANS.with(|cache| cache.borrow().get(&texture.source_sha256).copied()) {
        return Ok(value);
    }
    let value = dds_mean_luminance_with_verified_sha256(&texture.bytes, &texture.source_sha256)
        .map_err(|error| SessionError::InvalidPayload(error.to_string()))?;
    MEANS.with(|cache| {
        let mut cache = cache.borrow_mut();
        if cache.len() >= 512 {
            cache.clear();
        }
        cache.insert(texture.source_sha256.clone(), value);
    });
    Ok(value)
}

fn layer_texture(
    reference: &FileReference,
    role: TextureRole,
    sources: &BTreeMap<String, Arc<[u8]>>,
) -> LayerTexture {
    LayerTexture {
        bytes: Arc::clone(&sources[&reference.sha256.to_ascii_uppercase()]),
        role,
        source_sha256: reference.sha256.to_ascii_uppercase(),
    }
}

fn small_colour_mips(
    material: &PreviewCoreMaterial,
    sources: &BTreeMap<String, Arc<[u8]>>,
) -> Result<bool, SessionError> {
    for reference in material
        .layers
        .iter()
        .filter_map(|layer| layer.diffuse.as_ref())
    {
        let metadata = inspect_dds_with_verified_sha256(
            &sources[&reference.sha256.to_ascii_uppercase()],
            TextureRole::BaseColor,
            &reference.sha256,
        )
        .map_err(|error| SessionError::InvalidPayload(error.to_string()))?;
        if metadata.width.max(metadata.height) >> (metadata.mip_count - 1) > 64 {
            return Ok(false);
        }
    }
    Ok(true)
}

/// How a layer normal map stores its vector: 0 RGB, 1 RG, 2 signed RG.
fn normal_encoding(texture: &LayerTexture) -> Result<f32, SessionError> {
    let metadata =
        inspect_dds_with_verified_sha256(&texture.bytes, texture.role, &texture.source_sha256)
            .map_err(|error| SessionError::InvalidPayload(error.to_string()))?;
    Ok(match metadata.format {
        DdsFormat::Bc5Unorm | DdsFormat::Rg8Unorm => 1.0,
        DdsFormat::Bc5Snorm => 2.0,
        _ => 0.0,
    })
}

/// Keep only the grime the game's Ver2 rule can draw, and only on a material the
/// layer path takes with it. Every other grime layer stays hidden: drawn at a
/// constant weight it tints the whole surface.
pub(crate) fn keep_drawable_grime(material: &mut PreviewCoreMaterial) {
    let mut kept = material.clone();
    kept.layers
        .retain(|layer| layer.layer_role != "grime" || layer.is_ver2_grime());
    if kept.layers.iter().any(|layer| layer.layer_role == "grime") && eligible(&kept) {
        *material = kept;
    } else {
        material.layers.retain(|layer| layer.layer_role != "grime");
    }
}

fn build(
    material: &PreviewCoreMaterial,
    sources: &BTreeMap<String, Arc<[u8]>>,
) -> Result<MaterialLayerSet, SessionError> {
    let mut result = MaterialLayerSet {
        lod_index: material.lod_index as usize,
        material_index: material.material_index,
        uniform: LayerUniform {
            base_color: [
                material.base_color[0],
                material.base_color[1],
                material.base_color[2],
                1.0,
            ],
            control: [1, 0, 0, 0],
            ..Default::default()
        },
        textures: std::array::from_fn(|_| None),
    };
    let family = material.layers[0].shader_family.to_ascii_lowercase();
    if family == "skinnedmesheye" {
        result.uniform.control = [3, 0, 1, 0];
        // The package's neutral geometry placeholder is not an eye tint.
        // Authored eye colour comes from these source maps and their coverage.
        result.uniform.base_color = [1.0; 4];
        // Layer slot B is free on an eye: it carries the wrapper's eye words.
        // dye = `_eyeProperty0` bytes, affine = `_eyeProperty1` bytes,
        // properties = (`_irisBrightness`, iris normal bound, iris material
        // bound, iris normal encoding).
        let base = &material.layers[0];
        let words = base.eye_properties.unwrap_or([0x80401A00, 0xFF00FFFF, 0x0000FF00]);
        result.uniform.layers[2].dye = crate::cdmw_session::byte4(words[0]);
        result.uniform.layers[2].affine = crate::cdmw_session::byte4(words[1]);
        result.uniform.layers[2].properties[0] = base.iris_brightness.unwrap_or(0.5);
        for layer in material.layers.iter().skip(1) {
            let k = eye_channel(layer).expect("eligible eye layer");
            result.uniform.layers[k] = LayerEntryUniform {
                properties: [1.0, 0.0, 1.0, 0.0],
                ..Default::default()
            };
            result.textures[1 + k * 3] = Some(layer_texture(
                layer.diffuse.as_ref().expect("eligible eye diffuse"),
                TextureRole::BaseColor,
                sources,
            ));
            if k == 0 {
                if let Some(reference) = &layer.normal {
                    let texture = layer_texture(reference, TextureRole::Normal, sources);
                    result.uniform.layers[2].properties[1] = 1.0;
                    result.uniform.layers[2].properties[3] = normal_encoding(&texture)?;
                    result.textures[2] = Some(texture);
                }
                if let Some(reference) = &layer.material {
                    result.uniform.layers[2].properties[2] = 1.0;
                    result.textures[3] =
                        Some(layer_texture(reference, TextureRole::Material, sources));
                }
            }
        }
        return Ok(result);
    }
    let legacy = material.is_legacy_dye_family();
    let blend_height = material.is_blend_height();
    if material.layers.iter().skip(1).any(|layer| {
        !layer.is_legacy_dye()
            && !layer.is_ver2_overlay()
            && !layer.is_ver2_blend()
            && layer.mask_parameter != "_colorBlendingMaskTexture"
    }) {
        // The legacy and BlendHeight families follow the game's traced rules;
        // the other families that read `_maskTexture` keep the weighted mix.
        result.uniform.control[0] = if blend_height {
            LAYER_MODE_BLEND_HEIGHT
        } else if legacy {
            LAYER_MODE_LEGACY
        } else {
            2
        };
    }
    let legacy = legacy && result.uniform.control[0] == LAYER_MODE_LEGACY;
    let blend_height = blend_height && result.uniform.control[0] == LAYER_MODE_BLEND_HEIGHT;
    let mut height_presence = 0_u32;
    if blend_height {
        // No dye and no whole-part tint: the base map, the layers and their heights.
        result.uniform.base_color = [1.0; 4];
        if let Some(reference) = &material.layers[0].height {
            result.textures[DETAIL_MASK_SLOT] =
                Some(layer_texture(reference, TextureRole::Height, sources));
            height_presence |= BLEND_HEIGHT_BASE;
        }
        let [width, base_scale] = material
            .layers
            .iter()
            .skip(1)
            .find_map(|layer| layer.blend_height)
            .unwrap_or([0.01, 0.0]);
        result.uniform.blend_height = [width.max(0.01), base_scale.max(0.0), 0.0, 0.0];
    }
    if legacy {
        // The game's legacy rule has no whole-part tint: `_dyeingColorMask*`
        // colours the base through the mask instead.
        result.uniform.base_color = [1.0; 4];
        result.uniform.seeds = layered_legacy_dye(material).unwrap_or_default();
    }
    result.uniform.control[1] = u32::from(family.contains("skin") && !family.contains("skinned"));
    // Native names include SkinnedMeshSkin and SkinWrinkle.
    if family.contains("meshskin") || family.contains("skinwrinkle") {
        result.uniform.control[1] = 1;
    }
    result.uniform.control[2] = u32::from(family.contains("eye"));
    if let Some(base) = material.layers[0].diffuse.as_ref() {
        result.uniform.base_color[3] = mean(&layer_texture(base, TextureRole::BaseColor, sources))?;
    } else {
        // A layered material without a base colour map samples white beneath
        // its layers (as CDMW Next does), not the grey untextured placeholder.
        result.uniform.control[3] = LAYER_CONTROL_NO_BASE;
    }
    for layer in material.layers.iter().skip(1) {
        if layer.is_legacy_dye() {
            continue;
        }
        if layer.is_ver2_overlay() {
            // The game runs the overlay step in its Ver2 shaders only.
            if result.uniform.control[0] == 1 {
                result.uniform.control[3] |= LAYER_CONTROL_OVERLAY
                    | ((layer.blend_flags.unwrap_or(0) & 7) * LAYER_CONTROL_OVERLAY_LUMA);
                result.textures[OVERLAY_SLOT] = Some(layer_texture(
                    layer.diffuse.as_ref().expect("overlay colour map"),
                    TextureRole::LayerMask,
                    sources,
                ));
            }
            continue;
        }
        if layer.is_ver2_blend() {
            // As the overlay step: the game's Ver2 shaders only.
            if result.uniform.control[0] == 1 {
                let affine = layer.sampling_transform();
                result.uniform.blend_dye = layer.tint;
                result.uniform.blend_affine = [affine[0], affine[1], affine[2], affine[3]];
                result.uniform.blend_offset = [
                    affine[4],
                    affine[5],
                    layer.blend_opacity.unwrap_or(0.0),
                    1.0,
                ];
                result.textures[BLEND_SLOT] = Some(layer_texture(
                    layer.diffuse.as_ref().expect("blend layer colour"),
                    TextureRole::BaseColor,
                    sources,
                ));
                // The symbol's normal and material (fix 16a): flag bits 12 to 14
                // and option bit 6 in `blend_flags` bits 0 to 3.
                let flags = layer.blend_flags.unwrap_or(0);
                let [rough, metal, angle] = layer.blend_surface.unwrap_or([0.0, 0.0, 0.0]);
                result.uniform.blend_surface = [angle.cos(), angle.sin(), rough, metal];
                let mut switches = [f32::from(flags & 1 != 0), 0.0, 0.0, 0.0];
                if flags & 2 != 0
                    && let Some(reference) = &layer.normal
                {
                    let texture = layer_texture(reference, TextureRole::Normal, sources);
                    switches[3] = normal_encoding(&texture)?;
                    switches[1] = if flags & 8 != 0 { 2.0 } else { 1.0 };
                    result.textures[BLEND_NORMAL_SLOT] = Some(texture);
                }
                if flags & 4 != 0
                    && let Some(reference) = &layer.material
                {
                    switches[2] = 1.0;
                    result.textures[BLEND_MATERIAL_SLOT] =
                        Some(layer_texture(reference, TextureRole::Material, sources));
                }
                result.uniform.blend_switches = switches;
            }
            continue;
        }
        let k = channel(layer).expect("eligible channel");
        result.textures[0] = Some(layer_texture(
            layer.mask.as_ref().expect("eligible mask"),
            TextureRole::LayerMask,
            sources,
        ));
        if layer.layer_role == "color_seed" {
            // `_dyeingColorMask*` is read by no Ver2 shader of the game: a channel
            // without a colour layer shows the surface beneath, undyed. The
            // BlendHeight shaders do not read it either.
            continue;
        }
        if blend_height && layer.layer_role == "detail" {
            if let Some(reference) = &layer.height {
                result.textures[GRIME_SLOT + k * 3] =
                    Some(layer_texture(reference, TextureRole::Height, sources));
                height_presence |= BLEND_HEIGHT_BASE << (k + 1);
            }
        }
        if layer.is_ver2_grime() {
            let [low, high, intensity] = layer.grime_blend.expect("ver2 grime ramp");
            let affine = layer.sampling_transform();
            let slot = GRIME_SLOT + k * 3;
            let mut encoding = 0.0;
            result.textures[DETAIL_MASK_SLOT] = Some(layer_texture(
                layer.detail_mask.as_ref().expect("ver2 grime detail mask"),
                TextureRole::LayerMask,
                sources,
            ));
            result.textures[slot] = Some(layer_texture(
                layer.diffuse.as_ref().expect("ver2 grime diffuse"),
                TextureRole::BaseColor,
                sources,
            ));
            if let Some(reference) = &layer.normal {
                let texture = layer_texture(reference, TextureRole::Normal, sources);
                encoding = normal_encoding(&texture)?;
                result.textures[slot + 1] = Some(texture);
            }
            if let Some(reference) = &layer.material {
                result.textures[slot + 2] =
                    Some(layer_texture(reference, TextureRole::Material, sources));
            }
            let entry = &mut result.uniform.layers[k];
            entry.grime_affine = [affine[0], affine[1], affine[2], affine[3]];
            entry.grime_offset = [
                affine[4],
                affine[5],
                low as f32 / 255.0,
                high as f32 / 255.0,
            ];
            // The game overlays the tint on display-space values: no decode.
            entry.grime_tint = layer.tint;
            entry.grime = [intensity as f32 * 2.0 / 255.0, 1.0, encoding, 0.0];
            continue;
        }
        let affine = layer.sampling_transform();
        let color = layer_texture(
            layer.diffuse.as_ref().expect("eligible diffuse"),
            TextureRole::BaseColor,
            sources,
        );
        // Grime of this channel may already sit in the entry: keep it.
        result.uniform.layers[k] = LayerEntryUniform {
            // Colour-blend and legacy layers are dyed by the game's overlay, on
            // display values.
            dye: if result.uniform.control[0] == 1 || legacy {
                layer.tint
            } else {
                dye(layer.tint)
            },
            affine: [affine[0], affine[1], affine[2], affine[3]],
            offset: [
                affine[4],
                affine[5],
                layer.blend_flags.unwrap_or(15) as f32,
                // The legacy rule draws no colour from a map the wrapper does
                // not declare.
                f32::from(u8::from(legacy && layer.colour_authored == Some(false))),
            ],
            properties: [
                // Next and the source use the per-channel _dyeingGlobalOpacity
                // byte in both blend modes; `weight` is only its fallback.
                layer.blend_opacity.unwrap_or(layer.weight),
                mean(&color)?,
                1.0,
                0.0,
            ],
            ..result.uniform.layers[k]
        };
        result.textures[1 + k * 3] = Some(color);
        if layer.is_ver2_scratch() {
            let [roughness, metal] = layer.scratch_steps();
            result.uniform.layers[k].scratch = [roughness, metal, 1.0, 0.0];
            // The game overlays the tint on display-space values: no decode.
            result.uniform.layers[k].scratch_tint = layer.scratch_tint.unwrap_or([0.0; 4]);
            result.textures[DETAIL_MASK_SLOT] = Some(layer_texture(
                layer
                    .detail_mask
                    .as_ref()
                    .expect("ver2 scratch detail mask"),
                TextureRole::LayerMask,
                sources,
            ));
        }
        if let Some(reference) = &layer.normal {
            let texture = layer_texture(reference, TextureRole::Normal, sources);
            result.uniform.layers[k].properties[3] = normal_encoding(&texture)?;
            result.textures[2 + k * 3] = Some(texture);
        }
        if let Some(reference) = &layer.material {
            result.textures[3 + k * 3] =
                Some(layer_texture(reference, TextureRole::Material, sources));
        }
    }
    if blend_height {
        result.uniform.blend_height[2] = height_presence as f32;
    }
    Ok(result)
}

// Owned-bytes form of `prepare_arc`, kept for the tests; the app passes shared bytes.
#[cfg(test)]
#[allow(clippy::too_many_arguments)]
pub fn prepare<F>(
    graph: &PreviewCoreMaterialGraph,
    presentations: &[SessionMaterialPresentation],
    document: &MeshDocument,
    resources: &mut Vec<CdmwTextureResource>,
    gpu_supported: bool,
    draw_grime: bool,
    mut read: F,
    cancelled: &dyn Fn() -> bool,
) -> Result<(PreviewCoreMaterialCompositionMetrics, Vec<MaterialLayerSet>), SessionError>
where
    F: FnMut(&FileReference) -> Result<Vec<u8>, SessionError>,
{
    prepare_arc(
        graph,
        presentations,
        document,
        resources,
        gpu_supported,
        draw_grime,
        |reference| read(reference).map(Arc::from),
        cancelled,
    )
}

#[allow(clippy::too_many_arguments)]
pub fn prepare_arc<F>(
    graph: &PreviewCoreMaterialGraph,
    presentations: &[SessionMaterialPresentation],
    document: &MeshDocument,
    resources: &mut Vec<CdmwTextureResource>,
    gpu_supported: bool,
    draw_grime: bool,
    mut read: F,
    cancelled: &dyn Fn() -> bool,
) -> Result<(PreviewCoreMaterialCompositionMetrics, Vec<MaterialLayerSet>), SessionError>
where
    F: FnMut(&FileReference) -> Result<Arc<[u8]>, SessionError>,
{
    if graph.quality != "full" {
        return Ok((PreviewCoreMaterialCompositionMetrics::default(), Vec::new()));
    }
    // Validate every declared graph resource, including disabled grime, exactly once.
    let mut sources = BTreeMap::<String, Arc<[u8]>>::new();
    let mut bytes = 0_u64;
    let mut reference_count = 0_u64;
    for layer in graph.materials.iter().flat_map(|m| &m.layers) {
        for reference in [
            &layer.diffuse,
            &layer.normal,
            &layer.material,
            &layer.height,
            &layer.mask,
            &layer.detail_mask,
        ]
        .into_iter()
        .flatten()
        {
            reference_count += 1;
            let sha = reference.sha256.to_ascii_uppercase();
            if let std::collections::btree_map::Entry::Vacant(entry) = sources.entry(sha) {
                check_preview_cancelled(cancelled)?;
                bytes = bytes.checked_add(reference.byte_length).ok_or_else(|| {
                    SessionError::InvalidPayload("layer byte budget overflow".into())
                })?;
                if bytes > MAX_TEXTURE_TOTAL_BYTES {
                    return Err(SessionError::InvalidPayload(
                        "material sources exceed the 512 MiB limit".into(),
                    ));
                }
                entry.insert(read(reference)?);
            }
        }
    }
    let mut cpu = graph.clone();
    let validated: BTreeSet<_> = sources
        .keys()
        .cloned()
        .chain(
            resources
                .iter()
                .map(|r| r.metadata.source_sha256.to_ascii_uppercase()),
        )
        .collect();
    let mut layers = Vec::new();
    cpu.materials.clear();
    for original in &graph.materials {
        check_preview_cancelled(cancelled)?;
        let mut material = original.clone();
        if !draw_grime {
            keep_drawable_grime(&mut material);
        }
        if gpu_supported && eligible(&material) && small_colour_mips(&material, &sources)? {
            let gpu = build(&material, &sources)?;
            // Bind the exact base maps, not a native fast-preview layer substitute.
            for role in [
                TextureRole::BaseColor,
                TextureRole::Normal,
                TextureRole::Material,
            ] {
                for resource in resources.iter_mut().filter(|r| r.role == role) {
                    if let Some(owners) = resource
                        .material_indices_by_lod
                        .get_mut(material.lod_index as usize)
                    {
                        owners.retain(|owner| *owner != material.material_index);
                    }
                }
                let base = &material.layers[0];
                let reference = match role {
                    TextureRole::BaseColor => &base.diffuse,
                    TextureRole::Normal => &base.normal,
                    _ => &base.material,
                };
                if let Some(reference) = reference {
                    let bytes = Arc::clone(&sources[&reference.sha256.to_ascii_uppercase()]);
                    let metadata =
                        inspect_dds_with_verified_sha256(&bytes, role, &reference.sha256)
                            .map_err(|error| SessionError::InvalidPayload(error.to_string()))?;
                    let mut owners = vec![Vec::new(); document.lods.len()];
                    owners[material.lod_index as usize].push(material.material_index);
                    resources.push(CdmwTextureResource {
                        label: reference.path.clone(),
                        role,
                        metadata,
                        bytes,
                        material_indices_by_lod: owners,
                    });
                }
            }
            layers.push(gpu);
        } else if gpu_supported && dye_only(&material) {
            // The GPU dyes the authored base map; everything else about the
            // material is composed as it is without the dye.
            layers.push(build_dye_only(&material, &sources));
            material.layers.retain(|layer| !layer.is_legacy_dye());
            cpu.materials.push(material);
        } else {
            cpu.materials.push(material);
        }
    }
    resources.retain(|r| {
        r.material_indices_by_lod
            .iter()
            .any(|owners| !owners.is_empty())
    });
    let mut metrics = compose_preview_core_material_resources_cancellable(
        &cpu,
        presentations,
        document,
        resources,
        |reference| Ok(sources[&reference.sha256.to_ascii_uppercase()].to_vec()),
        cancelled,
    )?;
    metrics.unique_source_dds_count = sources.len() as u64;
    metrics.source_reference_count = reference_count;
    metrics.validated_source_sha256 = validated.into_iter().collect();
    metrics.gpu_layer_material_count = layers.len() as u64;
    Ok((metrics, layers))
}

#[cfg(test)]
mod tests {
    use super::*;
    use cdmw_texture::inspect_dds;

    fn layer(role: &str, channel: &str, reference: &FileReference) -> PreviewCoreMaterialLayer {
        serde_json::from_value(serde_json::json!({
            "owner_wrapper_item_id":"owner", "material_wrapper_index":0,
            "layer_role":role,"mask_channel":channel,"shader_family":"SkinnedMeshStandard_Ver2",
            "shader_rule":"standard","evidence_grade":"exact","source_parameter":"_detailDiffuseMaskR",
            "mask_parameter":"_colorBlendingMaskTexture","weight":1.0,"detail_scale":0.0,
            "roughness_hint":0.0,"metalness_hint":0.0,"specular_hint":0.0,"height_scale_hint":0.0,
            "tint":[1.0,1.0,1.0,0.0],"diffuse_declared":true,"diffuse_archive_path":"source.dds","diffuse":reference,
            "normal_declared":false,"normal_archive_path":"","normal":null,
            "material_declared":false,"material_archive_path":"","material":null,
            "height_declared":false,"height_archive_path":"","height":null,
            "mask_declared":true,"mask_archive_path":"mask.dds","mask":reference
        })).unwrap()
    }

    fn material(layers: Vec<PreviewCoreMaterialLayer>) -> PreviewCoreMaterial {
        PreviewCoreMaterial {
            lod_index: 0,
            material_index: 0,
            material_slot_index: 0,
            material_name: "test".into(),
            base_color: [1.0; 3],
            layers,
            authoring_channels: 0,
        }
    }

    fn reference(bytes: &[u8], name: &str) -> FileReference {
        FileReference {
            path: name.into(),
            data_type: "dds".into(),
            count: bytes.len() as u64,
            byte_length: bytes.len() as u64,
            sha256: inspect_dds(bytes, TextureRole::BaseColor)
                .unwrap()
                .source_sha256
                .to_ascii_uppercase(),
            content_type: "image/vnd-ms.dds".into(),
        }
    }

    #[test]
    fn eye_layers_preserve_order_alpha_and_cpu_fallback() {
        let pixels = [[0, 255, 0, 255], [255, 0, 0, 128], [0, 0, 255, 64]];
        let bytes: Vec<_> = pixels
            .iter()
            .map(|p| cdmw_texture::encode_rgba8_dds(1, 1, p, TextureRole::BaseColor).unwrap())
            .collect();
        let refs: Vec<_> = bytes
            .iter()
            .enumerate()
            .map(|(k, b)| reference(b, &format!("eye-{k}.dds")))
            .collect();
        let mut entries: Vec<_> = refs
            .iter()
            .enumerate()
            .map(|(k, r)| {
                let mut entry = layer(if k == 0 { "base" } else { "overlay" }, "a", r);
                entry.shader_family = "SkinnedMeshEye".into();
                entry.source_parameter =
                    ["_baseColorTexture", "_irisDiffuseTexture", "_pupilTexture"][k].into();
                entry
            })
            .collect();
        let mut eye = material(entries.clone());
        assert!(eligible(&eye));
        eye.layers.push(eye.layers[1].clone());
        assert!(!eligible(&eye), "duplicate iris is ambiguous");
        entries[0].mask = None;
        let graph = PreviewCoreMaterialGraph {
            schema_version: 1,
            graph_version: 5,
            semantics_version: 10,
            quality: "full".into(),
            resources_included: true,
            source_edge_count: 5,
            unique_resource_count: 3,
            copied_resource_count: 3,
            unique_resource_bytes: bytes.iter().map(|b| b.len() as u64).sum(),
            materials: vec![material(entries)],
        };
        let document = cdmw_formats::decode_mesh(
            &cdmw_formats::synthetic::triangle_pam("test.dds"),
            cdmw_formats::MeshFormat::Pam,
        )
        .unwrap();
        for gpu in [false, true] {
            let mut resources = Vec::new();
            let (_, layers) = prepare(
                &graph,
                &[],
                &document,
                &mut resources,
                gpu,
                false,
                |r| Ok(bytes[refs.iter().position(|p| p.path == r.path).unwrap()].clone()),
                &|| false,
            )
            .unwrap();
            if gpu {
                assert_eq!(layers.len(), 1);
                assert_eq!(layers[0].uniform.control[0], 3);
                assert_eq!(
                    layers[0].textures[1].as_ref().unwrap().source_sha256,
                    refs[1].sha256
                );
                assert_eq!(
                    layers[0].textures[4].as_ref().unwrap().source_sha256,
                    refs[2].sha256
                );
            } else {
                let base = resources
                    .iter()
                    .find(|r| r.role == TextureRole::BaseColor)
                    .unwrap();
                let decoded = cdmw_texture::decode_dds_rgba8(&base.bytes, base.role).unwrap();
                let expected = [
                    128.0 / 255.0 * 191.0 / 255.0,
                    127.0 / 255.0 * 191.0 / 255.0,
                    64.0 / 255.0,
                ];
                for (k, expected) in expected.iter().enumerate() {
                    assert!((linear(f32::from(decoded.pixels[k]) / 255.0) - expected).abs() < 0.01);
                }
                assert_eq!(decoded.pixels[3], 255, "eye coverage stays opaque");
            }
        }
    }

    #[test]
    fn eye_layers_carry_the_iris_surface_maps_and_the_eye_words() {
        // SkinnedMeshEye lerps the normal and (with UseMaterialTextureRoughness)
        // the roughness toward `_irisNormalTexture` / `_irisMaterialTexture` by
        // the iris alpha, at UVs set by `_eyeProperty0/1`.
        let make = |pixel: [u8; 4]| {
            cdmw_texture::encode_rgba8_dds(1, 1, &pixel, TextureRole::BaseColor).unwrap()
        };
        let bytes = [
            make([200, 200, 200, 255]),
            make([40, 80, 160, 255]),
            make([128, 128, 255, 255]),
            make([255, 90, 30, 255]),
        ];
        let refs: Vec<_> = bytes
            .iter()
            .enumerate()
            .map(|(k, b)| reference(b, &format!("eye-{k}.dds")))
            .collect();
        let mut base = layer("base", "r", &refs[0]);
        base.shader_family = "SkinnedMeshEye".into();
        base.source_parameter = "_baseColorTexture".into();
        base.mask = None;
        base.eye_properties = Some([0xB6FF2600, 0xFF01FF61, 0x0000FF00]);
        base.iris_brightness = Some(0.25);
        let mut iris = layer("overlay", "a", &refs[1]);
        iris.shader_family = "SkinnedMeshEye".into();
        iris.source_parameter = "_irisDiffuseTexture".into();
        iris.normal = Some(refs[2].clone());
        iris.material = Some(refs[3].clone());
        let eye = material(vec![base, iris]);
        assert!(eligible(&eye));
        let sources = refs
            .iter()
            .zip(&bytes)
            .map(|(r, b)| (r.sha256.clone(), Arc::from(b.clone())))
            .collect();
        let built = build(&eye, &sources).unwrap();
        assert_eq!(built.uniform.control[0], 3);
        assert_eq!(built.textures[2].as_ref().unwrap().source_sha256, refs[2].sha256);
        assert_eq!(built.textures[3].as_ref().unwrap().source_sha256, refs[3].sha256);
        assert_eq!(built.uniform.layers[2].dye, [0.0, 38.0, 255.0, 182.0]);
        assert_eq!(built.uniform.layers[2].affine, [97.0, 255.0, 1.0, 255.0]);
        assert_eq!(built.uniform.layers[2].properties[..3], [0.25, 1.0, 1.0]);
        // The CPU fallback: the iris (opaque) times twice `_irisBrightness`.
        let graph = PreviewCoreMaterialGraph {
            schema_version: 1,
            graph_version: 5,
            semantics_version: 10,
            quality: "full".into(),
            resources_included: true,
            source_edge_count: 4,
            unique_resource_count: 4,
            copied_resource_count: 4,
            unique_resource_bytes: bytes.iter().map(|b| b.len() as u64).sum(),
            materials: vec![eye],
        };
        let document = cdmw_formats::decode_mesh(
            &cdmw_formats::synthetic::triangle_pam("test.dds"),
            cdmw_formats::MeshFormat::Pam,
        )
        .unwrap();
        let mut resources = Vec::new();
        prepare(
            &graph,
            &[],
            &document,
            &mut resources,
            false,
            false,
            |r| Ok(bytes[refs.iter().position(|p| p.path == r.path).unwrap()].clone()),
            &|| false,
        )
        .unwrap();
        let base = resources
            .iter()
            .find(|r| r.role == TextureRole::BaseColor)
            .unwrap();
        let decoded = cdmw_texture::decode_dds_rgba8(&base.bytes, base.role).unwrap();
        for (k, iris) in [40.0_f32, 80.0, 160.0].iter().enumerate() {
            let expected = linear(iris / 255.0) * 0.5;
            assert!((linear(f32::from(decoded.pixels[k]) / 255.0) - expected).abs() < 0.01);
        }
    }

    #[test]
    fn eye_uvs_follow_the_games_iris_size_and_pupil_stretch() {
        use crate::cdmw_session::{byte4, eye_uvs};
        // Defaults: IrisSize 128 and EyeImageScale 255 leave the mesh UV (to 0.4%).
        let (uvp, uvi, uvpu, r) = eye_uvs([0.8, 0.5], byte4(0x80401A00), byte4(0xFF00FFFF));
        assert_eq!(uvp, [0.8, 0.5]);
        assert!((r - 0.6).abs() < 1e-5);
        assert!((uvi[0] - (0.6 * (1.0 - 128.0 / 255.0) + 0.5)).abs() < 1e-5);
        assert!((uvpu[0] - uvi[0]).abs() < 1e-5, "outside r 0.5 the pupil is not warped");
        // The commonest animal eye: IrisSize 182 magnifies the iris 1.75 times;
        // UVScale (97, 255) squeezes the pupil's U and stretches its V.
        let (_, uvi, uvpu, _) = eye_uvs([0.8, 0.8], byte4(0xB6FF2600), byte4(0xFF01FF61));
        let iris = 1.0 - 182.0 / 255.0;
        assert!((uvi[0] - (0.6 * iris + 0.5)).abs() < 1e-5);
        let a: [f32; 2] = [97.0 * 2.0 / 255.0, 2.0];
        let s = [a[0].min(a[0] + (1.0 - a[0]) * 97.0 / 255.0), a[1].min(a[1] + (1.0 - a[1]) * 97.0 / 255.0)];
        assert!((uvpu[0] - (0.6 * iris * s[0] + 0.5)).abs() < 1e-5);
        assert!((uvpu[1] - (0.6 * iris * s[1] + 0.5)).abs() < 1e-5);
        // Inside r 0.5 the pupil is warped by pow(2r, 1 - 2 stretch).
        let (_, uvi, uvpu, r) = eye_uvs([0.6, 0.5], byte4(0x80401A00), byte4(0xFF00FFFF));
        let stretch = (2.0_f32 * (26.0 / 255.0 + 0.05 + 38.0 / 255.0 * 0.0)).clamp(0.0, 1.0);
        let pw = (2.0 * r).powf(1.0 - 2.0 * stretch);
        assert!((uvpu[0] - ((uvi[0] - 0.5) / pw + 0.5)).abs() < 1e-5);
    }

    #[test]
    fn layered_material_without_base_matches_on_gpu_uniform_and_cpu_fallback() {
        // cd_phm_02_sword_0015 shape: channelled detail layers, one blend
        // mask, no base colour map. Both routes use white beneath the layers,
        // draw the layer of the largest mask channel as the game does, and
        // carry the authored _dyeingGlobalOpacity byte.
        let make = |pixel: [u8; 4]| {
            cdmw_texture::encode_rgba8_dds(1, 1, &pixel, TextureRole::BaseColor).unwrap()
        };
        let bytes = [
            make([255, 0, 0, 255]),
            make([0, 255, 0, 255]),
            make([100, 150, 0, 255]),
        ];
        let refs = [
            reference(&bytes[0], "red.dds"),
            reference(&bytes[1], "green.dds"),
            reference(&bytes[2], "mask.dds"),
        ];
        let mut base = layer("base", "r", &refs[0]);
        base.diffuse = None;
        base.mask = None;
        let mut red = layer("detail", "r", &refs[0]);
        red.mask = Some(refs[2].clone());
        red.blend_opacity = Some(0.5);
        red.blend_flags = Some(15);
        let mut green = layer("detail", "g", &refs[1]);
        green.mask = Some(refs[2].clone());
        green.source_parameter = "_detailDiffuseMaskG".into();
        // A colour seed on the empty blue channel: the game's shader ignores it.
        let mut seed = layer("color_seed", "b", &refs[2]);
        seed.diffuse = None;
        seed.diffuse_declared = false;
        seed.diffuse_archive_path = String::new();
        seed.tint = [0.0, 0.0, 1.0, 1.0];
        let value = material(vec![base, seed, red, green]);
        assert!(eligible(&value));
        let graph = PreviewCoreMaterialGraph {
            schema_version: 1,
            graph_version: 5,
            semantics_version: 10,
            quality: "full".into(),
            resources_included: true,
            source_edge_count: 5,
            unique_resource_count: 3,
            copied_resource_count: 3,
            unique_resource_bytes: bytes.iter().map(|b| b.len() as u64).sum(),
            materials: vec![value],
        };
        let document = cdmw_formats::decode_mesh(
            &cdmw_formats::synthetic::triangle_pam("test.dds"),
            cdmw_formats::MeshFormat::Pam,
        )
        .unwrap();
        for gpu in [true, false] {
            let mut resources = Vec::new();
            let (_, layers) = prepare(
                &graph,
                &[],
                &document,
                &mut resources,
                gpu,
                false,
                |r| {
                    Ok(bytes[refs
                        .iter()
                        .position(|p| p.sha256 == r.sha256.to_ascii_uppercase())
                        .unwrap()]
                    .clone())
                },
                &|| false,
            )
            .unwrap();
            if gpu {
                assert_eq!(layers.len(), 1);
                let uniform = &layers[0].uniform;
                assert_eq!(uniform.control[0], 1, "one blend mask selects layers");
                assert_eq!(uniform.seeds, [[0.0; 4]; 3], "colour seeds are not drawn");
                assert_eq!(uniform.control[3], 1, "missing base samples white");
                assert_eq!(
                    uniform.layers[0].properties[0], 0.5,
                    "authored opacity byte"
                );
                assert_eq!(
                    uniform.layers[1].properties[0], 1.0,
                    "weight is the fallback"
                );
            } else {
                assert!(layers.is_empty());
                let base = resources
                    .iter()
                    .find(|r| r.role == TextureRole::BaseColor)
                    .expect("composed base colour");
                let decoded = cdmw_texture::decode_dds_rgba8(&base.bytes, base.role).unwrap();
                // Green has the largest mask channel (150 over 100): its layer
                // alone, no mix with red, no grey and no first-layer base.
                assert!(decoded.pixels[0] <= 3, "{:?}", &decoded.pixels[..4]);
                assert!(decoded.pixels[1] >= 252, "{:?}", &decoded.pixels[..4]);
                assert!(decoded.pixels[2] <= 3, "{:?}", &decoded.pixels[..4]);
            }
        }
    }

    /// The plate of `cd_phm_00_vest_0047_04`: grime R ramps from 0.576 to 1.0 over
    /// the detail mask's green at intensity byte 0x8E. The GPU uniform states that
    /// ramp, and the CPU fallback composes the same colour.
    #[test]
    fn ver2_grime_follows_the_detail_mask_ramp_on_gpu_uniform_and_cpu_fallback() {
        let make = |pixel: [u8; 4]| {
            cdmw_texture::encode_rgba8_dds(1, 1, &pixel, TextureRole::BaseColor).unwrap()
        };
        let document = cdmw_formats::decode_mesh(
            &cdmw_formats::synthetic::triangle_pam("test.dds"),
            cdmw_formats::MeshFormat::Pam,
        )
        .unwrap();
        // Detail mask green 201: half way up the ramp, weight 0.5 * 142 * 2 / 255.
        for (green, weight) in [
            (100_u8, 0.0_f32),
            (201, 0.5 * 142.0 * 2.0 / 255.0),
            (255, 1.0),
        ] {
            let bytes = [
                make([128, 128, 128, 255]),
                make([200, 100, 50, 255]),
                make([255, 0, 0, 255]),
                make([0, green, 0, 255]),
            ];
            let refs = [
                reference(&bytes[0], "steel.dds"),
                reference(&bytes[1], "rust.dds"),
                reference(&bytes[2], "mask.dds"),
                reference(&bytes[3], "detail-mask.dds"),
            ];
            let mut base = layer("base", "r", &refs[0]);
            base.diffuse = None;
            base.mask = None;
            let mut steel = layer("detail", "r", &refs[0]);
            steel.mask = Some(refs[2].clone());
            let mut grime = layer("grime", "r", &refs[1]);
            grime.source_parameter = "_grimeDiffuseTextureR".into();
            grime.mask = Some(refs[2].clone());
            grime.tint = [1.0, 1.0, 1.0, 0.0];
            let mut hidden = material(vec![base.clone(), steel.clone(), grime.clone()]);
            keep_drawable_grime(&mut hidden);
            assert_eq!(hidden.layers.len(), 2, "grime without a ramp stays hidden");
            grime.grime_blend = Some([147, 255, 142]);
            grime.detail_mask_declared = true;
            grime.detail_mask_archive_path = "detail-mask.dds".into();
            grime.detail_mask = Some(refs[3].clone());
            let value = material(vec![base, steel, grime]);
            assert!(eligible(&value));
            let graph = PreviewCoreMaterialGraph {
                schema_version: 1,
                graph_version: 5,
                semantics_version: 10,
                quality: "full".into(),
                resources_included: true,
                source_edge_count: 5,
                unique_resource_count: 4,
                copied_resource_count: 4,
                unique_resource_bytes: bytes.iter().map(|b| b.len() as u64).sum(),
                materials: vec![value],
            };
            for gpu in [true, false] {
                let mut resources = Vec::new();
                let (_, layers) = prepare(
                    &graph,
                    &[],
                    &document,
                    &mut resources,
                    gpu,
                    false,
                    |r| {
                        Ok(bytes[refs
                            .iter()
                            .position(|p| p.sha256 == r.sha256.to_ascii_uppercase())
                            .unwrap()]
                        .clone())
                    },
                    &|| false,
                )
                .unwrap();
                if gpu {
                    assert_eq!(layers.len(), 1, "drawn grime keeps the material on the GPU");
                    let entry = &layers[0].uniform.layers[0];
                    assert!((entry.grime_offset[2] - 147.0 / 255.0).abs() < 1e-6);
                    assert_eq!(entry.grime_offset[3], 1.0);
                    assert!((entry.grime[0] - 142.0 * 2.0 / 255.0).abs() < 1e-6);
                    assert_eq!(entry.grime[1], 1.0);
                    assert_eq!(entry.properties[2], 1.0, "the colour layer keeps its slot");
                    assert_eq!(
                        layers[0].textures[DETAIL_MASK_SLOT]
                            .as_ref()
                            .unwrap()
                            .source_sha256,
                        refs[3].sha256
                    );
                    assert_eq!(
                        layers[0].textures[GRIME_SLOT]
                            .as_ref()
                            .unwrap()
                            .source_sha256,
                        refs[1].sha256
                    );
                } else {
                    assert!(layers.is_empty());
                    let composed = resources
                        .iter()
                        .find(|r| r.role == TextureRole::BaseColor)
                        .expect("composed base colour");
                    let decoded =
                        cdmw_texture::decode_dds_rgba8(&composed.bytes, composed.role).unwrap();
                    for (channel, (clean, soiled)) in [(128_u8, 200_u8), (128, 100), (128, 50)]
                        .into_iter()
                        .enumerate()
                    {
                        let clean = linear(f32::from(clean) / 255.0);
                        let soiled = linear(f32::from(soiled) / 255.0);
                        let expected = clean + (soiled - clean) * weight;
                        let drawn = linear(f32::from(decoded.pixels[channel]) / 255.0);
                        assert!(
                            (drawn - expected).abs() <= 0.01,
                            "green {green}, channel {channel}: {drawn} != {expected}"
                        );
                    }
                }
            }
        }
    }

    /// The plate's layer R: scratch bytes 0x9B and 0xFF move roughness by +0.216 of
    /// its remaining range and metal by +1.0 where the detail mask's red is set,
    /// and `_scratchTintColorR` (#c8b9b4, alpha 0x2d) is overlaid on the colour.
    #[test]
    fn ver2_scratch_moves_response_and_colour_on_gpu_uniform_and_cpu_fallback() {
        let make = |pixel: [u8; 4]| {
            cdmw_texture::encode_rgba8_dds(1, 1, &pixel, TextureRole::BaseColor).unwrap()
        };
        let document = cdmw_formats::decode_mesh(
            &cdmw_formats::synthetic::triangle_pam("test.dds"),
            cdmw_formats::MeshFormat::Pam,
        )
        .unwrap();
        let tint = [200.0 / 255.0, 185.0 / 255.0, 180.0 / 255.0, 45.0 / 255.0];
        for red in [0_u8, 128, 255] {
            let wear = f32::from(red) / 255.0;
            let bytes = [
                make([128, 128, 128, 255]),
                make([255, 128, 100, 255]),
                make([255, 0, 0, 255]),
                make([red, 0, 0, 255]),
            ];
            let refs = [
                reference(&bytes[0], "steel.dds"),
                reference(&bytes[1], "steel_sp.dds"),
                reference(&bytes[2], "mask.dds"),
                reference(&bytes[3], "detail-mask.dds"),
            ];
            let mut base = layer("base", "r", &refs[0]);
            base.diffuse = None;
            base.mask = None;
            let mut steel = layer("detail", "r", &refs[0]);
            steel.mask = Some(refs[2].clone());
            steel.material_declared = true;
            steel.material_archive_path = "steel_sp.dds".into();
            steel.material = Some(refs[1].clone());
            steel.scratch = Some([0x9B, 0xFF]);
            steel.scratch_tint = Some(tint);
            steel.detail_mask_declared = true;
            steel.detail_mask_archive_path = "detail-mask.dds".into();
            steel.detail_mask = Some(refs[3].clone());
            let value = material(vec![base, steel]);
            assert!(eligible(&value));
            let graph = PreviewCoreMaterialGraph {
                schema_version: 1,
                graph_version: 5,
                semantics_version: 10,
                quality: "full".into(),
                resources_included: true,
                source_edge_count: 4,
                unique_resource_count: 4,
                copied_resource_count: 4,
                unique_resource_bytes: bytes.iter().map(|b| b.len() as u64).sum(),
                materials: vec![value],
            };
            for gpu in [true, false] {
                let mut resources = Vec::new();
                let (_, layers) = prepare(
                    &graph,
                    &[],
                    &document,
                    &mut resources,
                    gpu,
                    false,
                    |r| {
                        Ok(bytes[refs
                            .iter()
                            .position(|p| p.sha256 == r.sha256.to_ascii_uppercase())
                            .unwrap()]
                        .clone())
                    },
                    &|| false,
                )
                .unwrap();
                if gpu {
                    assert_eq!(layers.len(), 1);
                    let entry = &layers[0].uniform.layers[0];
                    assert!((entry.scratch[0] - (155.0 * 2.0 / 255.0 - 1.0)).abs() < 1e-6);
                    assert_eq!(entry.scratch[1], 1.0);
                    assert_eq!(entry.scratch[2], 1.0);
                    assert_eq!(entry.scratch_tint, tint);
                    assert_eq!(
                        layers[0].textures[DETAIL_MASK_SLOT]
                            .as_ref()
                            .unwrap()
                            .source_sha256,
                        refs[3].sha256
                    );
                    continue;
                }
                assert!(layers.is_empty());
                let composed = |role| {
                    let resource = resources
                        .iter()
                        .find(|r| r.role == role)
                        .expect("composed map");
                    cdmw_texture::decode_dds_rgba8(&resource.bytes, resource.role)
                        .unwrap()
                        .pixels
                };
                let colour = composed(TextureRole::BaseColor);
                let clean = linear(128.0 / 255.0);
                for channel in 0..3 {
                    // Overlay of the mask value with the tint, mixed in by alpha * mask.
                    let overlaid = if wear < 0.5 {
                        2.0 * wear * tint[channel]
                    } else {
                        1.0 - 2.0 * (1.0 - wear) * (1.0 - tint[channel])
                    };
                    let expected = clean + (linear(overlaid) - clean) * tint[3] * wear;
                    let drawn = linear(f32::from(colour[channel]) / 255.0);
                    assert!(
                        (drawn - expected).abs() <= 0.01,
                        "red {red}, channel {channel}: {drawn} != {expected}"
                    );
                }
                let response = composed(TextureRole::Material);
                let rough = 128.0 / 255.0;
                let expected = rough + (1.0 - rough) * (155.0 * 2.0 / 255.0 - 1.0) * wear;
                assert!(
                    (f32::from(response[1]) / 255.0 - expected).abs() <= 0.012,
                    "red {red}: roughness {} != {expected}",
                    response[1]
                );
                let metal = ((100.0_f32 / 255.0 - 0.18) * 1.22 + wear).min(1.0);
                assert!(
                    (f32::from(response[2]) / 255.0 - metal).abs() <= 0.012,
                    "red {red}: metal {} != {metal}",
                    response[2]
                );
            }
        }
    }

    /// The game dyes a colour layer by desaturating its texel 80%, overlaying the
    /// dye in sRGB and mixing by the dye's alpha (the plate's leather layer G:
    /// `_dyeingDetailLayerColorMaskG` #826c5bff). The layer opacity byte does not
    /// scale it. The GPU uniform carries the sRGB dye; the CPU fallback composes
    /// the same colour.
    #[test]
    fn ver2_dye_overlays_in_srgb_on_gpu_uniform_and_cpu_fallback() {
        let make = |pixel: [u8; 4]| {
            cdmw_texture::encode_rgba8_dds(1, 1, &pixel, TextureRole::BaseColor).unwrap()
        };
        let document = cdmw_formats::decode_mesh(
            &cdmw_formats::synthetic::triangle_pam("test.dds"),
            cdmw_formats::MeshFormat::Pam,
        )
        .unwrap();
        let srgb = |value: f32| {
            if value <= 0.003_130_8 {
                value * 12.92
            } else {
                1.055 * value.powf(1.0 / 2.4) - 0.055
            }
        };
        let texel = [90_u8, 70, 50];
        for dye in [
            [130.0 / 255.0, 108.0 / 255.0, 91.0 / 255.0, 1.0],
            [1.0, 229.0 / 255.0, 99.0 / 255.0, 217.0 / 255.0],
            [0.5, 0.5, 0.5, 0.0],
        ] {
            let bytes = [
                make([texel[0], texel[1], texel[2], 255]),
                make([255, 0, 0, 255]),
            ];
            let refs = [
                reference(&bytes[0], "leather.dds"),
                reference(&bytes[1], "mask.dds"),
            ];
            let mut base = layer("base", "r", &refs[0]);
            base.diffuse = None;
            base.mask = None;
            let mut leather = layer("detail", "r", &refs[0]);
            leather.mask = Some(refs[1].clone());
            leather.tint = dye;
            leather.blend_opacity = Some(0.25);
            leather.blend_flags = Some(15);
            let graph = PreviewCoreMaterialGraph {
                schema_version: 1,
                graph_version: 5,
                semantics_version: 10,
                quality: "full".into(),
                resources_included: true,
                source_edge_count: 2,
                unique_resource_count: 2,
                copied_resource_count: 2,
                unique_resource_bytes: bytes.iter().map(|b| b.len() as u64).sum(),
                materials: vec![material(vec![base, leather])],
            };
            for gpu in [true, false] {
                let mut resources = Vec::new();
                let (_, layers) = prepare(
                    &graph,
                    &[],
                    &document,
                    &mut resources,
                    gpu,
                    false,
                    |r| {
                        Ok(bytes[refs
                            .iter()
                            .position(|p| p.sha256 == r.sha256.to_ascii_uppercase())
                            .unwrap()]
                        .clone())
                    },
                    &|| false,
                )
                .unwrap();
                if gpu {
                    assert_eq!(layers[0].uniform.control[0], 1);
                    assert_eq!(
                        layers[0].uniform.layers[0].dye, dye,
                        "the dye stays in display space for the overlay"
                    );
                    continue;
                }
                let composed = resources
                    .iter()
                    .find(|r| r.role == TextureRole::BaseColor)
                    .expect("composed base colour");
                let decoded =
                    cdmw_texture::decode_dds_rgba8(&composed.bytes, composed.role).unwrap();
                let colour: [f32; 3] = std::array::from_fn(|k| linear(f32::from(texel[k]) / 255.0));
                let luma = 0.299 * colour[0] + 0.587 * colour[1] + 0.114 * colour[2];
                for channel in 0..3 {
                    let grey = srgb(colour[channel] + (luma - colour[channel]) * 0.8);
                    let overlaid = if grey < 0.5 {
                        2.0 * grey * dye[channel]
                    } else {
                        1.0 - 2.0 * (1.0 - grey) * (1.0 - dye[channel])
                    };
                    let expected = colour[channel] + (linear(overlaid) - colour[channel]) * dye[3];
                    let drawn = linear(f32::from(decoded.pixels[channel]) / 255.0);
                    assert!(
                        (drawn - expected).abs() <= 0.006,
                        "dye {dye:?}, channel {channel}: {drawn} != {expected}"
                    );
                }
            }
        }
    }

    /// The game's legacy dye (Standard, Cloth, Fur and kin): `_dyeingColorMaskR/G/B`
    /// through `_maskTexture`, whose alpha shades the dye. The tunic of
    /// `cd_m0001_00_no_phm_ub_43007` (cream base, R `#4a4639ff`, G `#a35835d4`)
    /// drew undyed. The GPU gets a colour-only binding and leaves the base map
    /// alone; the CPU fallback composes the same colour; a Ver2 family ignores
    /// the colours, as the game does.
    #[test]
    #[allow(clippy::needless_range_loop)]
    fn legacy_dye_follows_the_games_formula_on_gpu_binding_and_cpu_fallback() {
        let make = |pixel: [u8; 4]| {
            cdmw_texture::encode_rgba8_dds(1, 1, &pixel, TextureRole::BaseColor).unwrap()
        };
        let document = cdmw_formats::decode_mesh(
            &cdmw_formats::synthetic::triangle_pam("test.dds"),
            cdmw_formats::MeshFormat::Pam,
        )
        .unwrap();
        let cream = [179_u8, 163, 141];
        let dyes = [
            [74.0 / 255.0, 70.0 / 255.0, 57.0 / 255.0, 1.0],
            [163.0 / 255.0, 88.0 / 255.0, 53.0 / 255.0, 212.0 / 255.0],
            [0.0, 0.0, 0.0, 0.0],
        ];
        let overlay = |base: f32, blend: f32| {
            if base < 0.5 {
                2.0 * base * blend
            } else {
                1.0 - 2.0 * (1.0 - base) * (1.0 - blend)
            }
        };
        // (name, mask texel, expected sRGB bytes when the result is exact)
        for (name, mask, exact) in [
            (
                "dye R at neutral shade",
                [255_u8, 0, 0, 128],
                Some([74_u8, 70, 57]),
            ),
            ("dye G by its alpha", [0, 255, 0, 128], None),
            (
                "no dye where the mask is empty",
                [0, 0, 0, 128],
                Some(cream),
            ),
            ("the mask's alpha darkens the dye", [255, 0, 0, 64], None),
            // A bright dye under a dark mask: the alpha, not the dye, picks the
            // overlay's branch (2ab here, not 1 - 2(1-a)(1-b)).
            ("the alpha is the overlay's base", [0, 255, 0, 64], None),
            ("a light mask whitens the dye", [255, 0, 0, 230], None),
            ("R then G", [255, 128, 0, 200], None),
        ] {
            let bytes = [make([cream[0], cream[1], cream[2], 255]), make(mask)];
            let refs = [
                reference(&bytes[0], "tunic.dds"),
                reference(&bytes[1], "tunic_m.dds"),
            ];
            let m: [f32; 4] = std::array::from_fn(|k| f32::from(mask[k]) / 255.0);
            let mut c: [f32; 4] = std::array::from_fn(|k| dyes[0][k] * m[0]);
            c = std::array::from_fn(|k| c[k] + (dyes[1][k] - c[k]) * m[1]);
            c = std::array::from_fn(|k| c[k] + (dyes[2][k] - c[k]) * m[2]);
            let expected: [f32; 3] = std::array::from_fn(|k| {
                let base = linear(f32::from(cream[k]) / 255.0);
                base + (linear(overlay(m[3], c[k])) - base) * c[3]
            });
            for family in ["SkinnedMeshStandard", "SkinnedMeshStandard_Ver2"] {
                let mut base = layer("base", "r", &refs[0]);
                base.mask = None;
                base.shader_family = family.into();
                base.source_parameter = "_baseColorTexture".into();
                base.mask_parameter = String::new();
                let mut layers = vec![base];
                for (k, channel) in ["r", "g", "b"].into_iter().enumerate() {
                    let mut seed = layer("color_seed", channel, &refs[1]);
                    seed.diffuse = None;
                    seed.shader_family = family.into();
                    seed.source_parameter = [
                        "_dyeingColorMaskR",
                        "_dyeingColorMaskG",
                        "_dyeingColorMaskB",
                    ][k]
                        .into();
                    seed.mask_parameter = "_maskTexture".into();
                    seed.tint = dyes[k];
                    layers.push(seed);
                }
                let legacy = family == "SkinnedMeshStandard";
                let value = material(layers);
                assert_eq!(value.legacy_dye().is_some(), legacy, "{family}");
                assert!(!eligible(&value), "a dye alone is not a layer stack");
                assert_eq!(dye_only(&value), legacy, "{family}");
                let graph = PreviewCoreMaterialGraph {
                    schema_version: 1,
                    graph_version: 5,
                    semantics_version: 10,
                    quality: "full".into(),
                    resources_included: true,
                    source_edge_count: 4,
                    unique_resource_count: 2,
                    copied_resource_count: 2,
                    unique_resource_bytes: bytes.iter().map(|b| b.len() as u64).sum(),
                    materials: vec![value],
                };
                for gpu in [true, false] {
                    let mut resources = Vec::new();
                    let (_, sets) = prepare(
                        &graph,
                        &[],
                        &document,
                        &mut resources,
                        gpu,
                        false,
                        |r| {
                            Ok(bytes[refs
                                .iter()
                                .position(|p| p.sha256 == r.sha256.to_ascii_uppercase())
                                .unwrap()]
                            .clone())
                        },
                        &|| false,
                    )
                    .unwrap();
                    let composed = resources
                        .iter()
                        .find(|r| r.role == TextureRole::BaseColor)
                        .expect("base colour");
                    let decoded =
                        cdmw_texture::decode_dds_rgba8(&composed.bytes, composed.role).unwrap();
                    if gpu && legacy {
                        assert_eq!(sets.len(), 1, "{name}");
                        assert_eq!(
                            sets[0].uniform.control,
                            [LAYER_MODE_LEGACY, 0, 0, LAYER_CONTROL_COLOUR_ONLY]
                        );
                        assert_eq!(sets[0].uniform.seeds, dyes, "sRGB colours, undecoded");
                        assert_eq!(sets[0].uniform.base_color, [1.0; 4]);
                        assert_eq!(
                            sets[0].textures[0].as_ref().unwrap().source_sha256,
                            refs[1].sha256
                        );
                        assert!(sets[0].textures[1..].iter().all(Option::is_none));
                        assert_eq!(
                            decoded.pixels[..3],
                            cream,
                            "{name}: the GPU dyes; the base map must not be dyed as well"
                        );
                        continue;
                    }
                    assert!(sets.is_empty(), "{family} {name}");
                    for channel in 0..3 {
                        let wanted = if legacy {
                            expected[channel]
                        } else {
                            linear(f32::from(cream[channel]) / 255.0)
                        };
                        let drawn = linear(f32::from(decoded.pixels[channel]) / 255.0);
                        assert!(
                            (drawn - wanted).abs() <= 0.004,
                            "{family} {name}, channel {channel}: {drawn} != {wanted}"
                        );
                        if let (true, Some(exact)) = (legacy, exact) {
                            assert!(
                                decoded.pixels[channel].abs_diff(exact[channel]) <= 1,
                                "{name}, channel {channel}: {} != {}",
                                decoded.pixels[channel],
                                exact[channel]
                            );
                        }
                    }
                }
            }
        }
    }

    /// A legacy part with colour layers: the dye colours the base, then the
    /// detail layer of the largest mask channel is laid over it by its own alpha
    /// times the opacity byte, dyed by the game's overlay. No whole-part tint.
    #[test]
    #[allow(clippy::needless_range_loop)]
    fn legacy_layers_draw_one_layer_per_pixel_over_the_dyed_base() {
        let make = |pixel: [u8; 4]| {
            cdmw_texture::encode_rgba8_dds(1, 1, &pixel, TextureRole::BaseColor).unwrap()
        };
        let document = cdmw_formats::decode_mesh(
            &cdmw_formats::synthetic::triangle_pam("test.dds"),
            cdmw_formats::MeshFormat::Pam,
        )
        .unwrap();
        let cream = [179_u8, 163, 141];
        let weave = [120_u8, 90, 60, 153];
        let mask = [64_u8, 255, 0, 128];
        let dye_g = [163.0 / 255.0, 88.0 / 255.0, 53.0 / 255.0, 212.0 / 255.0];
        let layer_dye = [0.2, 0.4, 0.8, 0.5];
        let bytes = [
            make([cream[0], cream[1], cream[2], 255]),
            make(mask),
            make(weave),
        ];
        let refs = [
            reference(&bytes[0], "tunic.dds"),
            reference(&bytes[1], "tunic_m.dds"),
            reference(&bytes[2], "weave.dds"),
        ];
        let mut base = layer("base", "r", &refs[0]);
        base.mask = None;
        base.shader_family = "SkinnedMeshCloth".into();
        let mut seed = layer("color_seed", "g", &refs[1]);
        seed.diffuse = None;
        seed.shader_family = "SkinnedMeshCloth".into();
        seed.source_parameter = "_dyeingColorMaskG".into();
        seed.mask_parameter = "_maskTexture".into();
        seed.tint = dye_g;
        // Layer R is not the largest channel here: it must not show.
        let mut red = layer("detail", "r", &refs[0]);
        red.shader_family = "SkinnedMeshCloth".into();
        red.mask = Some(refs[1].clone());
        red.mask_parameter = "_maskTexture".into();
        red.blend_flags = Some(15);
        red.blend_opacity = Some(1.0);
        let mut green = layer("detail", "g", &refs[2]);
        green.shader_family = "SkinnedMeshCloth".into();
        green.source_parameter = "_detailDiffuseMaskG".into();
        green.mask = Some(refs[1].clone());
        green.mask_parameter = "_maskTexture".into();
        green.tint = layer_dye;
        green.blend_flags = Some(15);
        green.blend_opacity = Some(0.5);
        let mut value = material(vec![base, seed, red, green]);
        // The whole-part tint the old rule multiplied in.
        value.base_color = [0.29, 0.27, 0.22];
        assert!(eligible(&value));
        assert!(!dye_only(&value));
        // The same part when the wrapper declares no colour map for layer G (the
        // file is one Preview Core found beside the layer's normal map).
        let mut unauthored = value.clone();
        unauthored.layers[3].colour_authored = Some(false);
        let graphs = [value, unauthored].map(|value| PreviewCoreMaterialGraph {
            schema_version: 1,
            graph_version: 5,
            semantics_version: 10,
            quality: "full".into(),
            resources_included: true,
            source_edge_count: 6,
            unique_resource_count: 3,
            copied_resource_count: 3,
            unique_resource_bytes: bytes.iter().map(|b| b.len() as u64).sum(),
            materials: vec![value],
        });
        let srgb = |value: f32| {
            if value <= 0.003_130_8 {
                value * 12.92
            } else {
                1.055 * value.powf(1.0 / 2.4) - 0.055
            }
        };
        let overlay = |base: f32, blend: f32| {
            if base < 0.5 {
                2.0 * base * blend
            } else {
                1.0 - 2.0 * (1.0 - base) * (1.0 - blend)
            }
        };
        let m: [f32; 4] = std::array::from_fn(|k| f32::from(mask[k]) / 255.0);
        // No R or B colour: c = lerp(0, dyeG, m.g).
        let c: [f32; 4] = std::array::from_fn(|k| dye_g[k] * m[1]);
        let texel: [f32; 3] = std::array::from_fn(|k| linear(f32::from(weave[k]) / 255.0));
        let luma = 0.299 * texel[0] + 0.587 * texel[1] + 0.114 * texel[2];
        let amount = f32::from(weave[3]) / 255.0 * 0.5;
        let dyed_base: [f32; 3] = std::array::from_fn(|k| {
            let base = linear(f32::from(cream[k]) / 255.0);
            base + (linear(overlay(m[3], c[k])) - base) * c[3]
        });
        let layered: [f32; 3] = std::array::from_fn(|k| {
            let grey = srgb(texel[k] + (luma - texel[k]) * 0.8);
            let tinted = texel[k] + (linear(overlay(grey, layer_dye[k])) - texel[k]) * layer_dye[3];
            dyed_base[k] + (tinted - dyed_base[k]) * amount
        });
        for (graph, expected, authored) in
            [(&graphs[0], layered, true), (&graphs[1], dyed_base, false)]
        {
            for gpu in [true, false] {
                let mut resources = Vec::new();
                let (_, sets) = prepare(
                    graph,
                    &[],
                    &document,
                    &mut resources,
                    gpu,
                    false,
                    |r| {
                        Ok(bytes[refs
                            .iter()
                            .position(|p| p.sha256 == r.sha256.to_ascii_uppercase())
                            .unwrap()]
                        .clone())
                    },
                    &|| false,
                )
                .unwrap();
                if gpu {
                    let uniform = &sets[0].uniform;
                    assert_eq!(uniform.control[0], LAYER_MODE_LEGACY);
                    assert_eq!(uniform.control[3] & LAYER_CONTROL_COLOUR_ONLY, 0);
                    assert_eq!(uniform.base_color[..3], [1.0; 3], "no whole-part tint");
                    assert_eq!(uniform.seeds, [[0.0; 4], dye_g, [0.0; 4]]);
                    assert_eq!(uniform.layers[1].dye, layer_dye, "sRGB for the overlay");
                    assert_eq!(uniform.layers[1].properties[0], 0.5);
                    assert_eq!(
                        uniform.layers[1].offset[3],
                        if authored { 0.0 } else { 1.0 },
                        "a map the wrapper does not declare draws no colour"
                    );
                    continue;
                }
                let composed = resources
                    .iter()
                    .find(|r| r.role == TextureRole::BaseColor)
                    .expect("composed base colour");
                let decoded =
                    cdmw_texture::decode_dds_rgba8(&composed.bytes, composed.role).unwrap();
                for channel in 0..3 {
                    let drawn = linear(f32::from(decoded.pixels[channel]) / 255.0);
                    assert!(
                        (drawn - expected[channel]).abs() <= 0.004,
                        "authored {authored}, channel {channel}: {drawn} != {}",
                        expected[channel]
                    );
                }
            }
        }
    }

    /// The game's BlendHeight rule at one pixel (permutation 31455db8225afaa7):
    /// the higher of R and G meets B, the winner's partner is the other of the
    /// two or R, and the layer meets the base by the same height cut.
    #[test]
    fn blend_height_weights_follow_the_games_quirks() {
        use crate::preview_core_material::blend_height_weights;
        // G on top partners R even when B is higher than R.
        let w = blend_height_weights([0.05, 0.3, 0.1], 0.0, 0.392);
        assert_eq!((w.top, w.second), (1, 0));
        assert!((w.partner - 2.0 * 0.05 / 0.35).abs() < 1e-6);
        // With no base height the layer shows at full strength.
        assert_eq!(w.layer, 1.0);
        // B on top partners the higher of R and G; equal heights give the partner alone.
        let w = blend_height_weights([0.0, 0.2, 0.2001], 0.0, 0.392);
        assert_eq!((w.top, w.second), (2, 1));
        assert!(w.partner > 0.999);
        // R wins a tie with G, and its partner is R itself.
        let w = blend_height_weights([0.2, 0.2, 0.0], 0.0, 0.392);
        assert_eq!((w.top, w.second), (0, 0));
        // A partner of height 0 does not mix.
        let w = blend_height_weights([0.0, 0.3, 0.1], 0.0, 0.392);
        assert_eq!((w.top, w.second, w.partner), (1, 0, 0.0));
        // No layer height: the base alone.
        assert_eq!(blend_height_weights([0.0; 3], 0.4, 0.392).layer, 0.0);
        // A narrow width is a hard cut: the higher surface wins outright.
        assert_eq!(blend_height_weights([0.5, 0.0, 0.0], 0.2, 0.01).layer, 1.0);
        assert_eq!(blend_height_weights([0.1, 0.0, 0.0], 0.3, 0.01).layer, 0.0);
        // Within the width, a weighted mean of the two heights.
        let w = blend_height_weights([0.3, 0.0, 0.0], 0.1, 0.392);
        assert!((w.layer - 0.75).abs() < 1e-6);
    }

    /// The BlendHeight families choose their layer by height, not by the
    /// largest mask channel, and draw no dye: the crystal of
    /// `cd_phm_02_spear_0117` showed its pale base where the icon shows the
    /// dark layers that its weak base height gives way to.
    #[test]
    fn blend_height_layers_meet_the_base_by_height_on_gpu_binding_and_cpu_fallback() {
        let make = |pixel: [u8; 4]| {
            cdmw_texture::encode_rgba8_dds(1, 1, &pixel, TextureRole::BaseColor).unwrap()
        };
        let document = cdmw_formats::decode_mesh(
            &cdmw_formats::synthetic::triangle_pam("test.dds"),
            cdmw_formats::MeshFormat::Pam,
        )
        .unwrap();
        let base_rgb = [200_u8, 180, 160];
        let colours = [[180_u8, 40, 40], [40_u8, 160, 60], [30_u8, 30, 200]];
        let bytes = [
            make([base_rgb[0], base_rgb[1], base_rgb[2], 255]),
            make([128, 128, 128, 255]),
            make([255, 255, 255, 255]),
            make([colours[0][0], colours[0][1], colours[0][2], 255]),
            make([colours[1][0], colours[1][1], colours[1][2], 255]),
            make([colours[2][0], colours[2][1], colours[2][2], 255]),
            make([51, 51, 51, 255]),
            make([255, 254, 254, 255]),
        ];
        let refs: Vec<_> = bytes
            .iter()
            .enumerate()
            .map(|(index, bytes)| reference(bytes, &format!("{index}.dds")))
            .collect();
        let mut base = layer("base", "r", &refs[0]);
        base.mask = None;
        base.shader_family = "SkinnedMeshBlendHeight".into();
        base.height = Some(refs[1].clone());
        let mut layers = vec![base];
        // Heights R 0.2 x 0.25, G 1.0 x 0.3, B 1.0 x 0.1; the mask is white.
        for (k, (channel, height, opacity)) in
            [("r", 6, 0.25), ("g", 7, 0.3), ("b", 7, 0.1)].into_iter().enumerate()
        {
            let mut row = layer("detail", channel, &refs[3 + k]);
            row.shader_family = "SkinnedMeshBlendHeight".into();
            row.source_parameter = ["_detailDiffuseMaskR", "_detailDiffuseMaskG", "_detailDiffuseMaskB"][k].into();
            row.mask = Some(refs[2].clone());
            row.mask_parameter = "_maskTexture".into();
            row.height = Some(refs[height].clone());
            row.blend_flags = Some(15);
            row.blend_opacity = Some(opacity);
            // A layer dye the BlendHeight shader does not read.
            row.tint = [1.0, 0.0, 0.0, 1.0];
            row.blend_height = Some([0.392, 0.2]);
            layers.push(row);
        }
        let mut value = material(layers);
        value.base_color = [0.3, 0.3, 0.3];
        assert!(value.is_blend_height());
        assert!(eligible(&value));
        let graph = PreviewCoreMaterialGraph {
            schema_version: 1,
            graph_version: 5,
            semantics_version: 10,
            quality: "full".into(),
            resources_included: true,
            source_edge_count: 8,
            unique_resource_count: 8,
            copied_resource_count: 8,
            unique_resource_bytes: bytes.iter().map(|b| b.len() as u64).sum(),
            materials: vec![value],
        };
        // G (0.3) is on top and partners R (0.05) although B (0.1) is higher;
        // the base height is 128/255 x 0.2.
        let (hr, hg, hb) = (51.0 / 255.0 * 0.25, 0.3, 128.0 / 255.0 * 0.2);
        let t = 2.0 * hr / (hg + hr);
        let share = hg / (hg + hb);
        let expected: [f32; 3] = std::array::from_fn(|c| {
            let base = linear(f32::from(base_rgb[c]) / 255.0);
            let layer = linear(f32::from(colours[1][c]) / 255.0)
                + (linear(f32::from(colours[0][c]) / 255.0) - linear(f32::from(colours[1][c]) / 255.0)) * t;
            base + (layer - base) * share
        });
        for gpu in [true, false] {
            let mut resources = Vec::new();
            let (_, sets) = prepare(
                &graph,
                &[],
                &document,
                &mut resources,
                gpu,
                false,
                |r| {
                    Ok(bytes[refs
                        .iter()
                        .position(|p| p.sha256 == r.sha256.to_ascii_uppercase())
                        .unwrap()]
                    .clone())
                },
                &|| false,
            )
            .unwrap();
            if gpu {
                let set = &sets[0];
                let uniform = &set.uniform;
                assert_eq!(uniform.control[0], LAYER_MODE_BLEND_HEIGHT);
                assert_eq!(uniform.base_color[..3], [1.0; 3], "no whole-part tint");
                assert_eq!(uniform.seeds, [[0.0; 4]; 3], "no dye");
                assert_eq!(uniform.blend_height, [0.392, 0.2, 15.0, 0.0]);
                assert!(!set.hides_base_colour());
                let sha = |slot: usize| set.textures[slot].as_ref().map(|t| t.source_sha256.clone());
                assert_eq!(sha(DETAIL_MASK_SLOT), Some(refs[1].sha256.clone()), "base height");
                for (k, height) in [6, 7, 7].into_iter().enumerate() {
                    assert_eq!(sha(GRIME_SLOT + 3 * k), Some(refs[height].sha256.clone()));
                    assert_eq!(uniform.layers[k].properties[0], [0.25, 0.3, 0.1][k]);
                }
                continue;
            }
            let composed = resources
                .iter()
                .find(|r| r.role == TextureRole::BaseColor)
                .expect("composed base colour");
            let decoded = cdmw_texture::decode_dds_rgba8(&composed.bytes, composed.role).unwrap();
            for channel in 0..3 {
                let drawn = linear(f32::from(decoded.pixels[channel]) / 255.0);
                assert!(
                    (drawn - expected[channel]).abs() <= 0.004,
                    "channel {channel}: {drawn} != {}",
                    expected[channel]
                );
            }
        }
    }

    /// The game's Ver2 overlay step: after grime and scratch every pixel becomes
    /// overlay(base = `_overlayColorTexture`, blend = albedo) on display values
    /// (0.5 neutral), with the map's luma for a layer that asks. CDMW dropped
    /// the map, so the pattern it carries was missing (the weave of the robe
    /// `cd_phm_00_ub_00_0376`). A wrapper without the map reads the engine's
    /// neutral grey in the game, which changes nothing: no step.
    #[test]
    #[allow(clippy::needless_range_loop)]
    fn ver2_overlay_colour_map_is_applied_on_gpu_binding_and_cpu_fallback() {
        let make = |pixel: [u8; 4]| {
            cdmw_texture::encode_rgba8_dds(1, 1, &pixel, TextureRole::BaseColor).unwrap()
        };
        let document = cdmw_formats::decode_mesh(
            &cdmw_formats::synthetic::triangle_pam("test.dds"),
            cdmw_formats::MeshFormat::Pam,
        )
        .unwrap();
        let cloth = [40_u8, 110, 60];
        let lace = [230_u8, 190, 90];
        // (name, the wrapper's map, luma bits, the layer drawn)
        for (name, map, luma, channel) in [
            ("the map's colour", Some(lace), 0_u32, "r"),
            (
                "neutral grey leaves the layer",
                Some([128, 128, 128]),
                0,
                "r",
            ),
            ("no map, no step", None, 0, "r"),
            ("luma for the layer that asks", Some(lace), 0b010, "g"),
            ("not for another layer", Some(lace), 0b010, "r"),
        ] {
            let slot = usize::from(channel == "g");
            let mut mask = [0_u8, 0, 0, 255];
            mask[slot] = 255;
            let bytes = [
                make([cloth[0], cloth[1], cloth[2], 255]),
                make(mask),
                make(map.map_or([1, 2, 3, 255], |m| [m[0], m[1], m[2], 255])),
            ];
            let refs = [
                reference(&bytes[0], "cloth.dds"),
                reference(&bytes[1], "cloth_ma.dds"),
                reference(&bytes[2], "cloth_o.dds"),
            ];
            let mut base = layer("base", "r", &refs[0]);
            base.diffuse = None;
            base.mask = None;
            let mut detail = layer("detail", channel, &refs[0]);
            detail.source_parameter = ["_detailDiffuseMaskR", "_detailDiffuseMaskG"][slot].into();
            detail.mask = Some(refs[1].clone());
            detail.tint = [1.0, 1.0, 1.0, 0.0];
            let mut layers = vec![base, detail];
            if map.is_some() {
                let mut overlay = layer("overlay", "", &refs[2]);
                overlay.source_parameter = "_overlayColorTexture".into();
                overlay.mask_parameter = String::new();
                overlay.mask = None;
                overlay.blend_flags = Some(luma);
                assert!(overlay.is_ver2_overlay());
                layers.push(overlay);
            }
            let value = material(layers);
            assert!(eligible(&value), "{name}: the overlay keeps the layer path");
            let used = 2 + usize::from(map.is_some());
            let graph = PreviewCoreMaterialGraph {
                schema_version: 1,
                graph_version: 5,
                semantics_version: 10,
                quality: "full".into(),
                resources_included: true,
                source_edge_count: used as u64,
                unique_resource_count: used as u64,
                copied_resource_count: used as u64,
                unique_resource_bytes: bytes[..used].iter().map(|b| b.len() as u64).sum(),
                materials: vec![value],
            };
            let over: Option<[f32; 3]> = map.map(|m| {
                let over: [f32; 3] = std::array::from_fn(|k| f32::from(m[k]) / 255.0);
                if luma & (1 << slot) != 0 {
                    [0.299 * over[0] + 0.587 * over[1] + 0.114 * over[2]; 3]
                } else {
                    over
                }
            });
            let expected: [f32; 3] = std::array::from_fn(|k| {
                let albedo = f32::from(cloth[k]) / 255.0;
                linear(match over {
                    None => albedo,
                    Some(over) if over[k] < 0.5 => 2.0 * over[k] * albedo,
                    Some(over) => 1.0 - 2.0 * (1.0 - over[k]) * (1.0 - albedo),
                })
            });
            for gpu in [true, false] {
                let mut resources = Vec::new();
                let (_, sets) = prepare(
                    &graph,
                    &[],
                    &document,
                    &mut resources,
                    gpu,
                    false,
                    |r| {
                        Ok(bytes[refs
                            .iter()
                            .position(|p| p.sha256 == r.sha256.to_ascii_uppercase())
                            .unwrap()]
                        .clone())
                    },
                    &|| false,
                )
                .unwrap();
                if gpu {
                    let control = sets[0].uniform.control;
                    assert_eq!(control[0], 1, "{name}");
                    assert_eq!(
                        control[3] & LAYER_CONTROL_OVERLAY != 0,
                        map.is_some(),
                        "{name}"
                    );
                    assert_eq!(
                        (control[3] / LAYER_CONTROL_OVERLAY_LUMA) & 7,
                        luma,
                        "{name}"
                    );
                    assert_eq!(
                        sets[0].textures[OVERLAY_SLOT]
                            .as_ref()
                            .map(|texture| texture.source_sha256.clone()),
                        map.map(|_| refs[2].sha256.clone()),
                        "{name}"
                    );
                    continue;
                }
                let composed = resources
                    .iter()
                    .find(|r| r.role == TextureRole::BaseColor)
                    .expect("composed base colour");
                let decoded =
                    cdmw_texture::decode_dds_rgba8(&composed.bytes, composed.role).unwrap();
                for k in 0..3 {
                    let drawn = linear(f32::from(decoded.pixels[k]) / 255.0);
                    assert!(
                        (drawn - expected[k]).abs() <= 0.006,
                        "{name}, channel {k}: {drawn} != {}",
                        expected[k]
                    );
                }
            }
        }
    }

    /// The game's Ver2 blend layer (its "symbol", the griffin on a great helm):
    /// `_detailDiffuseBlend`, dyed as a colour layer, laid over the finished
    /// colour by its own alpha times byte 3 of `_dyeingGlobalOpacity`, at one
    /// place of the mesh UV. CDMW dropped it.
    #[test]
    #[allow(clippy::needless_range_loop)]
    fn ver2_blend_layer_is_placed_once_on_gpu_binding_and_cpu_fallback() {
        let make = |pixel: [u8; 4]| {
            cdmw_texture::encode_rgba8_dds(1, 1, &pixel, TextureRole::BaseColor).unwrap()
        };
        let document = cdmw_formats::decode_mesh(
            &cdmw_formats::synthetic::triangle_pam("test.dds"),
            cdmw_formats::MeshFormat::Pam,
        )
        .unwrap();
        let srgb = |value: f32| {
            if value <= 0.003_130_8 {
                value * 12.92
            } else {
                1.055 * value.powf(1.0 / 2.4) - 0.055
            }
        };
        let canvas = [200_u8, 190, 170];
        let emblem = [150_u8, 40, 30, 204];
        let identity = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0];
        // (name, placement, dye, opacity byte as a fraction, whether it draws)
        for (name, placement, dye, opacity, draws) in [
            ("its own colour", identity, [1.0, 1.0, 1.0, 0.0], 1.0, true),
            (
                "half the opacity byte",
                identity,
                [1.0, 1.0, 1.0, 0.0],
                0.5,
                true,
            ),
            ("dyed", identity, [0.302, 0.102, 0.102, 1.0], 1.0, true),
            // The mesh UV 0.5 lands at 2.5: outside the one placement.
            (
                "not tiled",
                [1.0, 0.0, 0.0, 1.0, 2.0, 0.0],
                [1.0, 1.0, 1.0, 0.0],
                1.0,
                false,
            ),
        ] {
            let bytes = [
                make([canvas[0], canvas[1], canvas[2], 255]),
                make([255, 0, 0, 255]),
                make(emblem),
            ];
            let refs = [
                reference(&bytes[0], "canvas.dds"),
                reference(&bytes[1], "sail_ma.dds"),
                reference(&bytes[2], "symbol_dec.dds"),
            ];
            let mut base = layer("base", "r", &refs[0]);
            base.diffuse = None;
            base.mask = None;
            let mut detail = layer("detail", "r", &refs[0]);
            detail.mask = Some(refs[1].clone());
            detail.tint = [1.0, 1.0, 1.0, 0.0];
            let mut blend = layer("overlay", "", &refs[2]);
            blend.source_parameter = "_detailDiffuseBlend".into();
            blend.mask_parameter = String::new();
            blend.mask = None;
            blend.tint = dye;
            blend.uv_transform = Some(placement);
            blend.blend_opacity = Some(opacity);
            assert!(blend.is_ver2_blend());
            let value = material(vec![base, detail, blend]);
            assert!(
                eligible(&value),
                "{name}: the blend layer keeps the layer path"
            );
            let graph = PreviewCoreMaterialGraph {
                schema_version: 1,
                graph_version: 5,
                semantics_version: 10,
                quality: "full".into(),
                resources_included: true,
                source_edge_count: 3,
                unique_resource_count: 3,
                copied_resource_count: 3,
                unique_resource_bytes: bytes.iter().map(|b| b.len() as u64).sum(),
                materials: vec![value],
            };
            let texel: [f32; 3] = std::array::from_fn(|k| linear(f32::from(emblem[k]) / 255.0));
            let luma = 0.299 * texel[0] + 0.587 * texel[1] + 0.114 * texel[2];
            let amount = if draws {
                f32::from(emblem[3]) / 255.0 * opacity
            } else {
                0.0
            };
            let expected: [f32; 3] = std::array::from_fn(|k| {
                let under = linear(f32::from(canvas[k]) / 255.0);
                let grey = srgb(texel[k] + (luma - texel[k]) * 0.8);
                let overlaid = if grey < 0.5 {
                    2.0 * grey * dye[k]
                } else {
                    1.0 - 2.0 * (1.0 - grey) * (1.0 - dye[k])
                };
                let dyed = texel[k] + (linear(overlaid) - texel[k]) * dye[3];
                under + (dyed - under) * amount
            });
            for gpu in [true, false] {
                let mut resources = Vec::new();
                let (_, sets) = prepare(
                    &graph,
                    &[],
                    &document,
                    &mut resources,
                    gpu,
                    false,
                    |r| {
                        Ok(bytes[refs
                            .iter()
                            .position(|p| p.sha256 == r.sha256.to_ascii_uppercase())
                            .unwrap()]
                        .clone())
                    },
                    &|| false,
                )
                .unwrap();
                if gpu {
                    let uniform = &sets[0].uniform;
                    assert_eq!(uniform.control[0], 1, "{name}");
                    assert_eq!(uniform.blend_dye, dye, "{name}: sRGB for the overlay");
                    assert_eq!(
                        uniform.blend_affine,
                        [placement[0], placement[1], placement[2], placement[3]]
                    );
                    assert_eq!(
                        uniform.blend_offset,
                        [placement[4], placement[5], opacity, 1.0]
                    );
                    assert_eq!(
                        sets[0].textures[BLEND_SLOT].as_ref().unwrap().source_sha256,
                        refs[2].sha256
                    );
                    continue;
                }
                let composed = resources
                    .iter()
                    .find(|r| r.role == TextureRole::BaseColor)
                    .expect("composed base colour");
                let decoded =
                    cdmw_texture::decode_dds_rgba8(&composed.bytes, composed.role).unwrap();
                for k in 0..3 {
                    let drawn = linear(f32::from(decoded.pixels[k]) / 255.0);
                    assert!(
                        (drawn - expected[k]).abs() <= 0.006,
                        "{name}, channel {k}: {drawn} != {}",
                        expected[k]
                    );
                }
            }
        }
    }

    /// The symbol's normal and material (fix 16a; permutation d4ae32939fa23e46,
    /// %1782-%1908): weight wn = (flag bit 12 ? colour alpha : 1) times the
    /// opacity byte; roughness and metal move by wn times the bytes 2 and 3 of
    /// `_dyeingTransformProperty4` and, with flag bit 14, to
    /// `_detailMaterialBlend` .g and .b by wn; the normal (bit 13) is turned by
    /// the symbol's angle and laid over, or replaces with option bit 6. CDMW drew
    /// the symbol's colour only.
    #[test]
    fn ver2_symbol_moves_normal_and_response_on_gpu_binding_and_cpu_fallback() {
        let make = |pixel: [u8; 4]| {
            cdmw_texture::encode_rgba8_dds(1, 1, &pixel, TextureRole::BaseColor).unwrap()
        };
        let document = cdmw_formats::decode_mesh(
            &cdmw_formats::synthetic::triangle_pam("test.dds"),
            cdmw_formats::MeshFormat::Pam,
        )
        .unwrap();
        let emblem = [150_u8, 40, 30, 204];
        let symbol_normal = [200_u8, 128, 255, 255];
        let symbol_material = [0_u8, 30, 220, 255];
        let surface = [100_u8, 0];
        // (name, blend_flags, steps and angle, opacity)
        for (name, flags, steps, opacity) in [
            ("steps only", 0_u32, [0.25_f32, -0.5, 0.0], 1.0_f32),
            ("alpha weighs, material map", 5, [0.0, 0.0, 0.0], 0.5),
            ("normal laid over, turned", 3, [0.0, 0.0, 0.8255], 1.0),
            ("normal replaces", 11, [0.0, 0.0, 0.8255], 1.0),
        ] {
            let bytes = [
                make([200, 190, 170, 255]),
                make([255, 0, 0, 255]),
                make(emblem),
                make(symbol_normal),
                make(symbol_material),
                make([0, surface[0], surface[1], 255]),
            ];
            let refs = [
                reference(&bytes[0], "canvas.dds"),
                reference(&bytes[1], "shield_ma.dds"),
                reference(&bytes[2], "symbol_dec.dds"),
                reference(&bytes[3], "symbol_dec_n.dds"),
                reference(&bytes[4], "symbol_dec_sp.dds"),
                reference(&bytes[5], "layer_sp.dds"),
            ];
            let mut base = layer("base", "r", &refs[0]);
            base.diffuse = None;
            base.mask = None;
            let mut detail = layer("detail", "r", &refs[0]);
            detail.mask = Some(refs[1].clone());
            detail.material = Some(refs[5].clone());
            detail.material_declared = true;
            detail.material_archive_path = "layer_sp.dds".into();
            let mut blend = layer("overlay", "", &refs[2]);
            blend.source_parameter = "_detailDiffuseBlend".into();
            blend.mask_parameter = String::new();
            blend.mask = None;
            blend.mask_declared = false;
            blend.mask_archive_path = String::new();
            blend.normal = Some(refs[3].clone());
            blend.normal_declared = true;
            blend.normal_archive_path = "symbol_dec_n.dds".into();
            blend.material = Some(refs[4].clone());
            blend.material_declared = true;
            blend.material_archive_path = "symbol_dec_sp.dds".into();
            blend.blend_opacity = Some(opacity);
            blend.blend_flags = Some(flags);
            blend.blend_surface = Some(steps);
            assert!(blend.is_ver2_blend());
            let value = material(vec![base, detail, blend]);
            assert!(eligible(&value), "{name}: the symbol keeps the layer path");
            let graph = PreviewCoreMaterialGraph {
                schema_version: 1,
                graph_version: 5,
                semantics_version: 10,
                quality: "full".into(),
                resources_included: true,
                source_edge_count: 6,
                unique_resource_count: 6,
                copied_resource_count: 6,
                unique_resource_bytes: bytes.iter().map(|b| b.len() as u64).sum(),
                materials: vec![value],
            };
            let weight = if flags & 1 != 0 {
                f32::from(emblem[3]) / 255.0 * opacity
            } else {
                opacity
            };
            for gpu in [true, false] {
                let mut resources = Vec::new();
                let (_, sets) = prepare(
                    &graph,
                    &[],
                    &document,
                    &mut resources,
                    gpu,
                    false,
                    |r| {
                        Ok(bytes[refs
                            .iter()
                            .position(|p| p.sha256 == r.sha256.to_ascii_uppercase())
                            .unwrap()]
                        .clone())
                    },
                    &|| false,
                )
                .unwrap();
                if gpu {
                    let uniform = &sets[0].uniform;
                    let expected = [steps[2].cos(), steps[2].sin(), steps[0], steps[1]];
                    for k in 0..4 {
                        assert!(
                            (uniform.blend_surface[k] - expected[k]).abs() < 1e-6,
                            "{name}: blend_surface {:?}",
                            uniform.blend_surface
                        );
                    }
                    let mode = match flags & 10 {
                        2 => 1.0,
                        10 => 2.0,
                        _ => 0.0,
                    };
                    assert_eq!(
                        &uniform.blend_switches[..3],
                        &[f32::from(flags & 1 != 0), mode, f32::from(flags & 4 != 0)],
                        "{name}"
                    );
                    assert_eq!(
                        sets[0].textures[BLEND_NORMAL_SLOT]
                            .as_ref()
                            .map(|t| t.source_sha256.clone()),
                        (flags & 2 != 0).then(|| refs[3].sha256.clone()),
                        "{name}: the normal is bound when bit 13 asks for it"
                    );
                    assert_eq!(
                        sets[0].textures[BLEND_MATERIAL_SLOT]
                            .as_ref()
                            .map(|t| t.source_sha256.clone()),
                        (flags & 4 != 0).then(|| refs[4].sha256.clone()),
                        "{name}: the material map is bound when bit 14 asks for it"
                    );
                    continue;
                }
                let response = resources
                    .iter()
                    .find(|r| r.role == TextureRole::Material)
                    .expect("composed response");
                let decoded =
                    cdmw_texture::decode_dds_rgba8(&response.bytes, response.role).unwrap();
                let rough = f32::from(surface[0]) / 255.0;
                let take = if flags & 4 != 0 { weight } else { 0.0 };
                let expected_rough = rough
                    + weight * steps[0]
                    + take * (f32::from(symbol_material[1]) / 255.0 - rough);
                let expected_metal =
                    weight * steps[1] + take * f32::from(symbol_material[2]) / 255.0;
                for (k, expected) in [(1, expected_rough), (2, expected_metal)] {
                    let drawn = f32::from(decoded.pixels[k]) / 255.0;
                    assert!(
                        (drawn - expected.clamp(0.0, 1.0)).abs() <= 0.006,
                        "{name}, response channel {k}: {drawn} != {expected}"
                    );
                }
                let normal = resources
                    .iter()
                    .find(|r| r.role == TextureRole::Normal)
                    .map(|r| cdmw_texture::decode_dds_rgba8(&r.bytes, r.role).unwrap());
                if flags & 2 == 0 {
                    continue;
                }
                let normal = normal.expect("composed normal");
                let x = f32::from(symbol_normal[0]) / 255.0 * 2.0 - 1.0;
                let y = f32::from(symbol_normal[1]) / 255.0 * 2.0 - 1.0;
                let (sine, cosine) = steps[2].sin_cos();
                let d = [
                    x * cosine + y * sine,
                    -x * sine + y * cosine,
                    (1.0 - x * x - y * y).max(0.0).sqrt(),
                ];
                // Over a flat surface the game's layering returns d itself, so
                // laid over it is normalize(lerp((0, 0, 1), d, wn)).
                let w = if flags & 8 != 0 { 1.0 } else { weight };
                let v = [w * d[0], w * d[1], 1.0 - w + w * d[2]];
                let length = (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]).sqrt();
                for k in 0..2 {
                    let drawn = f32::from(normal.pixels[k]) / 255.0 * 2.0 - 1.0;
                    assert!(
                        (drawn - v[k] / length).abs() <= 0.02,
                        "{name}, normal {k}: {drawn} != {}",
                        v[k] / length
                    );
                }
            }
        }
    }

    #[test]
    fn eligibility_requires_distinct_channels_and_one_shared_mask() {
        let bytes =
            cdmw_texture::encode_rgba8_dds(1, 1, &[255; 4], TextureRole::BaseColor).unwrap();
        let reference = reference(&bytes, "test.dds");
        let base = layer("base", "r", &reference);
        let detail = layer("detail", "r", &reference);
        let mut value = material(vec![base, detail]);
        assert!(eligible(&value));
        value.layers.push(layer("color_seed", "b", &reference));
        assert!(
            eligible(&value),
            "colour seeds do not push a material off the GPU"
        );
        for role in ["grime", "skin_detail", "cloth_detail", "damage", "layer"] {
            let mut other = value.clone();
            other.layers.push(layer(role, "g", &reference));
            assert!(!eligible(&other), "{role}");
        }
        let mut duplicate = value.clone();
        duplicate.layers.push(duplicate.layers[1].clone());
        assert!(!eligible(&duplicate));
        value.layers[2].mask.as_mut().unwrap().sha256 = "a".repeat(64);
        assert!(!eligible(&value));
        value.layers.pop();
        value.layers[1].mask_parameter = "_maskTexture".into();
        assert!(
            !eligible(&value),
            "sequential overlays must not replace base colour"
        );
        value.layers[1].blend_flags = Some(2);
        value.layers[1].blend_opacity = Some(1.0);
        assert!(
            eligible(&value),
            "authored sequential overlays use their own GPU rules"
        );
        value.layers[1].mask_parameter = "_colorBlendingMaskTexture".into();
        value.authoring_channels = 1;
        assert!(!eligible(&value));
    }

    #[test]
    fn grime_decision_matches_gpu_and_cpu_and_validates_disabled_sources() {
        let make = |pixel: [u8; 4]| {
            cdmw_texture::encode_rgba8_dds(1, 1, &pixel, TextureRole::BaseColor).unwrap()
        };
        let black = make([0, 0, 0, 255]);
        let red = make([255, 0, 0, 255]);
        let green = make([0, 255, 0, 255]);
        let refs = [
            reference(&black, "base.dds"),
            reference(&red, "detail.dds"),
            reference(&green, "grime.dds"),
        ];
        let base = layer("base", "r", &refs[0]);
        let detail = layer("detail", "r", &refs[1]);
        let mut grime = layer("grime", "r", &refs[2]);
        grime.mask = Some(refs[1].clone());
        let graph = PreviewCoreMaterialGraph {
            schema_version: 1,
            graph_version: 5,
            semantics_version: 10,
            quality: "full".into(),
            resources_included: true,
            source_edge_count: 6,
            unique_resource_count: 3,
            copied_resource_count: 3,
            unique_resource_bytes: (black.len() + red.len() + green.len()) as u64,
            materials: vec![material(vec![base, detail, grime])],
        };
        let document = cdmw_formats::decode_mesh(
            &cdmw_formats::synthetic::triangle_pam("test.dds"),
            cdmw_formats::MeshFormat::Pam,
        )
        .unwrap();
        let sources: BTreeMap<_, _> = refs
            .iter()
            .map(|r| r.path.clone())
            .zip([black, red, green])
            .collect();
        for (gpu, grime, expected) in [
            (true, false, [255, 0, 0]),
            (false, false, [255, 0, 0]),
            (true, true, [0, 255, 0]),
        ] {
            let mut resources = Vec::new();
            let mut reads = Vec::new();
            let (metrics, layers) = prepare(
                &graph,
                &[],
                &document,
                &mut resources,
                gpu,
                grime,
                |r| {
                    reads.push(r.path.clone());
                    Ok(sources[&r.path].clone())
                },
                &|| false,
            )
            .unwrap();
            assert_eq!(reads.len(), 3);
            assert_eq!(metrics.validated_source_sha256.len(), 3);
            assert_eq!(layers.len(), usize::from(gpu && !grime));
            if layers.is_empty() {
                let base = resources
                    .iter()
                    .find(|r| r.role == TextureRole::BaseColor)
                    .unwrap();
                assert_eq!(
                    &cdmw_texture::decode_dds_rgba8(&base.bytes, base.role)
                        .unwrap()
                        .pixels[..3],
                    expected
                );
            } else {
                assert_eq!(metrics.source_dds_decode_count, 0);
            }
        }
        assert!(
            prepare(
                &graph,
                &[],
                &document,
                &mut Vec::new(),
                true,
                false,
                |r| if r.path == "grime.dds" {
                    Err(SessionError::InvalidPayload(
                        "corrupt disabled source".into(),
                    ))
                } else {
                    Ok(sources[&r.path].clone())
                },
                &|| false
            )
            .is_err()
        );
    }
}
