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
    DETAIL_MASK_SLOT, GRIME_SLOT, LayerEntryUniform, LayerTexture, LayerUniform, MaterialLayerSet,
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
        for layer in material.layers.iter().skip(1) {
            let k = eye_channel(layer).expect("eligible eye layer");
            let affine = layer.sampling_transform();
            result.uniform.layers[k] = LayerEntryUniform {
                affine: [affine[0], affine[1], affine[2], affine[3]],
                offset: [affine[4], affine[5], 0.0, 0.0],
                properties: [layer.weight, 0.0, 1.0, 0.0],
                ..Default::default()
            };
            result.textures[1 + k * 3] = Some(layer_texture(
                layer.diffuse.as_ref().expect("eligible eye diffuse"),
                TextureRole::BaseColor,
                sources,
            ));
        }
        return Ok(result);
    }
    if material
        .layers
        .iter()
        .skip(1)
        .any(|layer| layer.mask_parameter != "_colorBlendingMaskTexture")
    {
        result.uniform.control[0] = 2;
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
        result.uniform.control[3] = 1;
    }
    for layer in material.layers.iter().skip(1) {
        let k = channel(layer).expect("eligible channel");
        result.textures[0] = Some(layer_texture(
            layer.mask.as_ref().expect("eligible mask"),
            TextureRole::LayerMask,
            sources,
        ));
        if layer.layer_role == "color_seed" {
            // `_dyeingColorMask*` is read by no Ver2 shader of the game: a channel
            // without a colour layer shows the surface beneath, undyed.
            continue;
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
            // Colour-blend layers are dyed by the game's overlay, on display values.
            dye: if result.uniform.control[0] == 1 {
                layer.tint
            } else {
                dye(layer.tint)
            },
            affine: [affine[0], affine[1], affine[2], affine[3]],
            offset: [
                affine[4],
                affine[5],
                layer.blend_flags.unwrap_or(15) as f32,
                0.0,
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
    Ok(result)
}

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
                entry.insert(Arc::from(read(reference)?));
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
                    let bytes = sources[&reference.sha256.to_ascii_uppercase()].to_vec();
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
