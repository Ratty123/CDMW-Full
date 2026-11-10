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
use cdmw_render_wgpu::{LayerEntryUniform, LayerTexture, LayerUniform, MaterialLayerSet};
use cdmw_texture::{DdsFormat, TextureRole, dds_mean_luminance, inspect_dds};
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
    let mut channels = BTreeSet::new();
    let mut mask = None;
    let mut mask_parameter = None;
    for layer in material.layers.iter().skip(1) {
        if !matches!(layer.layer_role.as_str(), "detail" | "color_seed") {
            return false;
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
    let value = dds_mean_luminance(&texture.bytes)
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
        let metadata = inspect_dds(
            &sources[&reference.sha256.to_ascii_uppercase()],
            TextureRole::BaseColor,
        )
        .map_err(|error| SessionError::InvalidPayload(error.to_string()))?;
        if metadata.width.max(metadata.height) >> (metadata.mip_count - 1) > 64 {
            return Ok(false);
        }
    }
    Ok(true)
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
    }
    for layer in material.layers.iter().skip(1) {
        let k = channel(layer).expect("eligible channel");
        result.textures[0] = Some(layer_texture(
            layer.mask.as_ref().expect("eligible mask"),
            TextureRole::LayerMask,
            sources,
        ));
        if layer.layer_role == "color_seed" {
            let mut seed = dye(layer.tint);
            seed[3] *= layer.weight;
            result.uniform.seeds[k] = seed;
            continue;
        }
        let affine = layer.sampling_transform();
        let color = layer_texture(
            layer.diffuse.as_ref().expect("eligible diffuse"),
            TextureRole::BaseColor,
            sources,
        );
        result.uniform.layers[k] = LayerEntryUniform {
            dye: dye(layer.tint),
            affine: [affine[0], affine[1], affine[2], affine[3]],
            offset: [
                affine[4],
                affine[5],
                layer.blend_flags.unwrap_or(15) as f32,
                0.0,
            ],
            properties: [
                if result.uniform.control[0] == 2 {
                    layer.blend_opacity.unwrap_or(layer.weight)
                } else {
                    layer.weight
                },
                mean(&color)?,
                1.0,
                0.0,
            ],
        };
        result.textures[1 + k * 3] = Some(color);
        if let Some(reference) = &layer.normal {
            let texture = layer_texture(reference, TextureRole::Normal, sources);
            let metadata = inspect_dds(&texture.bytes, texture.role)
                .map_err(|error| SessionError::InvalidPayload(error.to_string()))?;
            result.uniform.layers[k].properties[3] = match metadata.format {
                DdsFormat::Bc5Unorm | DdsFormat::Rg8Unorm => 1.0,
                DdsFormat::Bc5Snorm => 2.0,
                _ => 0.0,
            };
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
            material.layers.retain(|layer| layer.layer_role != "grime");
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
                    let metadata = inspect_dds(&bytes, role)
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
    fn eligibility_requires_distinct_channels_and_one_shared_mask() {
        let bytes =
            cdmw_texture::encode_rgba8_dds(1, 1, &[255; 4], TextureRole::BaseColor).unwrap();
        let reference = reference(&bytes, "test.dds");
        let base = layer("base", "r", &reference);
        let detail = layer("detail", "r", &reference);
        let mut value = material(vec![base, detail]);
        assert!(eligible(&value));
        value.layers.push(layer("color_seed", "b", &reference));
        assert!(eligible(&value), "common colour seeds stay on the GPU");
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
