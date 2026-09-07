#![forbid(unsafe_code)]

use crate::cdmw_session::{
    CdmwTextureResource, FileReference, PreviewCoreMaterial, PreviewCoreMaterialGraph,
    PreviewCoreMaterialLayer, SessionError, SessionMaterialPresentation,
};
use cdmw_formats::MeshDocument;
use cdmw_texture::{DecodedRgba8, TextureRole, decode_dds_rgba8, encode_rgba8_dds, inspect_dds};
use std::collections::BTreeMap;
use std::sync::Arc;

const MAX_DECODED_SOURCE_BYTES: u64 = 512 * 1024 * 1024;
const MAX_RESIZED_MATERIAL_BYTES: u64 = 512 * 1024 * 1024;

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub(crate) struct PreviewCoreMaterialCompositionMetrics {
    pub source_reference_count: u64,
    pub unique_source_dds_count: u64,
    pub source_dds_decode_count: u64,
    pub decoded_source_bytes: u64,
    pub decoded_rgba8_bytes: u64,
    pub decoded_source_sha256: Vec<String>,
}

impl PreviewCoreMaterialCompositionMetrics {
    fn from_references(
        references: &BTreeMap<String, &FileReference>,
    ) -> Result<Self, SessionError> {
        Ok(Self {
            unique_source_dds_count: u64::try_from(references.len()).map_err(|_| {
                SessionError::InvalidPayload(
                    "Preview Core source DDS count exceeds this platform".to_owned(),
                )
            })?,
            ..Self::default()
        })
    }
}

#[derive(Debug, Clone, Copy)]
enum LayerMap {
    Diffuse,
    Normal,
    Material,
    Height,
}

impl LayerMap {
    fn reference(self, layer: &PreviewCoreMaterialLayer) -> Option<&FileReference> {
        match self {
            Self::Diffuse => layer.diffuse.as_ref(),
            Self::Normal => layer.normal.as_ref(),
            Self::Material => layer.material.as_ref(),
            Self::Height => layer.height.as_ref(),
        }
    }
}

#[derive(Default)]
struct ImageCache {
    decoded: BTreeMap<String, DecodedRgba8>,
    resized: BTreeMap<(String, u32, u32), Arc<[u8]>>,
    resized_bytes: u64,
    metrics: PreviewCoreMaterialCompositionMetrics,
}

impl ImageCache {
    fn preload<F>(
        graph: &PreviewCoreMaterialGraph,
        mut read_reference: F,
    ) -> Result<Self, SessionError>
    where
        F: FnMut(&FileReference) -> Result<Vec<u8>, SessionError>,
    {
        let mut references = BTreeMap::<String, &FileReference>::new();
        let mut source_reference_count = 0_u64;
        for material in &graph.materials {
            for layer in &material.layers {
                for reference in [
                    layer.diffuse.as_ref(),
                    layer.normal.as_ref(),
                    layer.material.as_ref(),
                    layer.height.as_ref(),
                    layer.mask.as_ref(),
                ]
                .into_iter()
                .flatten()
                {
                    source_reference_count =
                        source_reference_count.checked_add(1).ok_or_else(|| {
                            SessionError::InvalidPayload(
                                "Preview Core source DDS reference count overflowed".to_owned(),
                            )
                        })?;
                    references
                        .entry(reference.sha256.trim().to_ascii_uppercase())
                        .or_insert(reference);
                }
            }
        }

        let mut metrics = PreviewCoreMaterialCompositionMetrics::from_references(&references)?;
        metrics.source_reference_count = source_reference_count;
        let mut decoded = BTreeMap::new();
        let mut decoded_bytes = 0_u64;
        for (sha256, reference) in references {
            let bytes = read_reference(reference)?;
            let image = decode_dds_rgba8(&bytes, TextureRole::Unknown).map_err(|error| {
                SessionError::InvalidPayload(format!(
                    "Preview Core material DDS {} could not be decoded: {error}",
                    reference.path
                ))
            })?;
            decoded_bytes = decoded_bytes
                .checked_add(u64::try_from(image.pixels.len()).map_err(|_| {
                    SessionError::InvalidPayload(
                        "Preview Core decoded material size exceeds this platform".to_owned(),
                    )
                })?)
                .ok_or_else(|| {
                    SessionError::InvalidPayload(
                        "Preview Core decoded material size overflowed".to_owned(),
                    )
                })?;
            if decoded_bytes > MAX_DECODED_SOURCE_BYTES {
                return Err(SessionError::InvalidPayload(
                    "Preview Core decoded material sources exceed the 512 MiB limit".to_owned(),
                ));
            }
            metrics.source_dds_decode_count = metrics
                .source_dds_decode_count
                .checked_add(1)
                .ok_or_else(|| {
                    SessionError::InvalidPayload(
                        "Preview Core source DDS decode count overflowed".to_owned(),
                    )
                })?;
            metrics.decoded_source_bytes = metrics
                .decoded_source_bytes
                .checked_add(u64::try_from(bytes.len()).map_err(|_| {
                    SessionError::InvalidPayload(
                        "Preview Core source DDS byte count exceeds this platform".to_owned(),
                    )
                })?)
                .ok_or_else(|| {
                    SessionError::InvalidPayload(
                        "Preview Core source DDS byte count overflowed".to_owned(),
                    )
                })?;
            metrics.decoded_rgba8_bytes = decoded_bytes;
            metrics.decoded_source_sha256.push(sha256.clone());
            decoded.insert(sha256, image);
        }
        Ok(Self {
            decoded,
            resized: BTreeMap::new(),
            resized_bytes: 0,
            metrics,
        })
    }

    fn begin_material(&mut self) {
        self.resized.clear();
        self.resized_bytes = 0;
    }

    fn image(&self, reference: &FileReference) -> Result<&DecodedRgba8, SessionError> {
        self.decoded
            .get(&reference.sha256.trim().to_ascii_uppercase())
            .ok_or_else(|| {
                SessionError::InvalidPayload(format!(
                    "Preview Core material DDS {} was not decoded",
                    reference.path
                ))
            })
    }

    fn resized(
        &mut self,
        reference: &FileReference,
        width: u32,
        height: u32,
    ) -> Result<Arc<[u8]>, SessionError> {
        let key = (reference.sha256.trim().to_ascii_uppercase(), width, height);
        if let Some(pixels) = self.resized.get(&key) {
            return Ok(Arc::clone(pixels));
        }
        let image = self.image(reference)?;
        let resized = Arc::<[u8]>::from(resize_rgba8(image, width, height)?);
        self.resized_bytes = self
            .resized_bytes
            .checked_add(u64::try_from(resized.len()).map_err(|_| {
                SessionError::InvalidPayload(
                    "Preview Core resized material size exceeds this platform".to_owned(),
                )
            })?)
            .ok_or_else(|| {
                SessionError::InvalidPayload(
                    "Preview Core resized material size overflowed".to_owned(),
                )
            })?;
        if self.resized_bytes > MAX_RESIZED_MATERIAL_BYTES {
            return Err(SessionError::InvalidPayload(
                "Preview Core resized material sources exceed the 512 MiB limit".to_owned(),
            ));
        }
        self.resized.insert(key.clone(), Arc::clone(&resized));
        Ok(resized)
    }
}

#[cfg(test)]
pub(crate) fn compose_preview_core_material_resources<F>(
    graph: &PreviewCoreMaterialGraph,
    presentations: &[SessionMaterialPresentation],
    document: &MeshDocument,
    resources: &mut Vec<CdmwTextureResource>,
    read_reference: F,
) -> Result<PreviewCoreMaterialCompositionMetrics, SessionError>
where
    F: FnMut(&FileReference) -> Result<Vec<u8>, SessionError>,
{
    compose_preview_core_material_resources_cancellable(
        graph,
        presentations,
        document,
        resources,
        read_reference,
        &|| false,
    )
}

pub(crate) fn compose_preview_core_material_resources_cancellable<F>(
    graph: &PreviewCoreMaterialGraph,
    presentations: &[SessionMaterialPresentation],
    document: &MeshDocument,
    resources: &mut Vec<CdmwTextureResource>,
    mut read_reference: F,
    cancelled: &dyn Fn() -> bool,
) -> Result<PreviewCoreMaterialCompositionMetrics, SessionError>
where
    F: FnMut(&FileReference) -> Result<Vec<u8>, SessionError>,
{
    if graph.quality != "full" {
        return Ok(PreviewCoreMaterialCompositionMetrics::default());
    }
    let mut cache = ImageCache::preload(graph, |reference| {
        crate::cdmw_session::check_preview_cancelled(cancelled)?;
        read_reference(reference)
    })?;
    for material in &graph.materials {
        crate::cdmw_session::check_preview_cancelled(cancelled)?;
        cache.begin_material();
        if let Some(pixels) = compose_base_color(material, &mut cache)? {
            publish_composed_resource(
                resources,
                document,
                material,
                TextureRole::BaseColor,
                pixels,
            )?;
        }
        if let Some(pixels) = compose_material_response(material, presentations, &mut cache)? {
            publish_composed_resource(
                resources,
                document,
                material,
                TextureRole::Material,
                pixels,
            )?;
        }
        if let Some(pixels) = compose_normal(material, resources, &mut cache)? {
            publish_composed_resource(resources, document, material, TextureRole::Normal, pixels)?;
        }
        if let Some(pixels) = compose_height(material, resources, &mut cache)? {
            publish_composed_resource(resources, document, material, TextureRole::Height, pixels)?;
        }
    }
    resources.retain(|resource| {
        resource
            .material_indices_by_lod
            .iter()
            .any(|owners| !owners.is_empty())
    });
    Ok(cache.metrics)
}

fn compose_base_color(
    material: &PreviewCoreMaterial,
    cache: &mut ImageCache,
) -> Result<Option<DecodedRgba8>, SessionError> {
    let Some((width, height)) = largest_target(material, cache, LayerMap::Diffuse)? else {
        return Ok(None);
    };
    let pixel_count = checked_pixel_count(width, height)?;
    let base_layer = material.layers.first().ok_or_else(|| {
        SessionError::InvalidManifest(
            "Preview Core material graph is missing its base layer".to_owned(),
        )
    })?;
    let mut target = if let Some(reference) = base_layer.diffuse.as_ref() {
        cache.resized(reference, width, height)?.to_vec()
    } else {
        let color = [
            unit_byte(material.base_color[0]),
            unit_byte(material.base_color[1]),
            unit_byte(material.base_color[2]),
            255,
        ];
        let mut pixels = Vec::with_capacity(pixel_count.saturating_mul(4));
        for _ in 0..pixel_count {
            pixels.extend_from_slice(&color);
        }
        pixels
    };

    let color_seed_applied =
        apply_color_seed_layers(&mut target, width, height, &material.layers, cache)?;
    for layer in material
        .layers
        .iter()
        .skip(1)
        .filter(|layer| layer.layer_role != "color_seed")
    {
        let Some(reference) = layer.diffuse.as_ref() else {
            continue;
        };
        let overlay = cache.resized(reference, width, height)?;
        let mask = layer
            .mask
            .as_ref()
            .map(|reference| cache.resized(reference, width, height))
            .transpose()?;
        let channel = channel_index(&layer.mask_channel);
        let tint_active = layer
            .tint
            .iter()
            .take(3)
            .any(|component| (component - 1.0).abs() > (1.0 / 255.0));
        for pixel in 0..pixel_count {
            let offset = pixel * 4;
            let coverage = layer_coverage(layer, mask.as_deref(), offset, channel);
            if coverage <= 0.0 {
                continue;
            }
            let base = [
                unit(target[offset]),
                unit(target[offset + 1]),
                unit(target[offset + 2]),
            ];
            let source = [
                unit(overlay[offset]),
                unit(overlay[offset + 1]),
                unit(overlay[offset + 2]),
            ];
            let output = if layer.layer_role == "detail" && tint_active {
                let luma =
                    (0.299 * source[0] + 0.587 * source[1] + 0.114 * source[2]).clamp(0.0, 1.0);
                let modulation = 0.82 + 0.36 * luma;
                let alpha = coverage * layer.tint[3].clamp(0.0, 1.0);
                [
                    mix(base[0], (layer.tint[0] * modulation).clamp(0.0, 1.0), alpha),
                    mix(base[1], (layer.tint[1] * modulation).clamp(0.0, 1.0), alpha),
                    mix(base[2], (layer.tint[2] * modulation).clamp(0.0, 1.0), alpha),
                ]
            } else if color_seed_applied
                && matches!(layer.layer_role.as_str(), "grime" | "layer" | "damage")
            {
                let luma =
                    (0.299 * source[0] + 0.587 * source[1] + 0.114 * source[2]).clamp(0.0, 1.0);
                let modulation = 0.82 + 0.36 * luma;
                let factor = (1.0 - coverage) + modulation * coverage;
                [
                    (base[0] * factor).clamp(0.0, 1.0),
                    (base[1] * factor).clamp(0.0, 1.0),
                    (base[2] * factor).clamp(0.0, 1.0),
                ]
            } else {
                let tinted = if tint_active {
                    [
                        source[0] * layer.tint[0],
                        source[1] * layer.tint[1],
                        source[2] * layer.tint[2],
                    ]
                } else {
                    source
                };
                [
                    mix(base[0], tinted[0].clamp(0.0, 1.0), coverage),
                    mix(base[1], tinted[1].clamp(0.0, 1.0), coverage),
                    mix(base[2], tinted[2].clamp(0.0, 1.0), coverage),
                ]
            };
            target[offset] = unit_byte(output[0]);
            target[offset + 1] = unit_byte(output[1]);
            target[offset + 2] = unit_byte(output[2]);
        }
    }
    Ok(Some(DecodedRgba8 {
        width,
        height,
        pixels: target,
    }))
}

fn apply_color_seed_layers(
    target: &mut [u8],
    width: u32,
    height: u32,
    layers: &[PreviewCoreMaterialLayer],
    cache: &mut ImageCache,
) -> Result<bool, SessionError> {
    let seeds = ["r", "g", "b"].map(|channel| {
        layers
            .iter()
            .find(|layer| layer.layer_role == "color_seed" && layer.mask_channel == channel)
    });
    if seeds.iter().all(Option::is_none) {
        return Ok(false);
    }
    let mut masks: [Option<Arc<[u8]>>; 3] = [None, None, None];
    let mut palette = [[0.0_f32; 3]; 3];
    let mut strengths = [0.0_f32; 3];
    for channel in 0..3 {
        let Some(layer) = seeds[channel] else {
            continue;
        };
        palette[channel] = [layer.tint[0], layer.tint[1], layer.tint[2]];
        strengths[channel] = layer.tint[3].clamp(0.0, 1.0);
        if let Some(reference) = layer.mask.as_ref() {
            masks[channel] = Some(cache.resized(reference, width, height)?);
        }
    }
    if strengths.iter().all(|strength| *strength <= 1.0 / 255.0) {
        return Ok(false);
    }

    let pixel_count = checked_pixel_count(width, height)?;
    let mut weighted_lumas = [0.0_f64; 3];
    let mut weight_totals = [0.0_f64; 3];
    let mut visible_luma = 0.0_f64;
    let mut visible_count = 0_u64;
    for pixel in 0..pixel_count {
        let offset = pixel * 4;
        let luma = f64::from(
            0.2126 * unit(target[offset])
                + 0.7152 * unit(target[offset + 1])
                + 0.0722 * unit(target[offset + 2]),
        );
        if luma <= 1.0 / 255.0 {
            continue;
        }
        visible_luma += luma;
        visible_count += 1;
        for channel in 0..3 {
            let weight = f64::from(selector_weight(
                masks[channel].as_deref(),
                offset,
                channel,
                strengths[channel],
            ));
            weighted_lumas[channel] += luma * weight;
            weight_totals[channel] += weight;
        }
    }
    let fallback = if visible_count == 0 {
        0.5
    } else {
        visible_luma / visible_count as f64
    };
    let mut reference_lumas = [0.5_f32; 3];
    for channel in 0..3 {
        let value = if weight_totals[channel] > 0.001 {
            weighted_lumas[channel] / weight_totals[channel]
        } else {
            fallback
        };
        reference_lumas[channel] =
            ((value.clamp(1.0 / 255.0, 1.0) * 4096.0).round() / 4096.0) as f32;
    }

    for pixel in 0..pixel_count {
        let offset = pixel * 4;
        let weights = [0, 1, 2].map(|channel| {
            selector_weight(
                masks[channel].as_deref(),
                offset,
                channel,
                strengths[channel],
            )
        });
        let total = weights[0] + weights[1] + weights[2];
        if total <= 0.001 {
            continue;
        }
        let normalized = weights.map(|weight| weight / total);
        let mut seeded = [0.0_f32; 3];
        for component in 0..3 {
            seeded[component] = palette[0][component] * normalized[0]
                + palette[1][component] * normalized[1]
                + palette[2][component] * normalized[2];
        }
        let base = [
            unit(target[offset]),
            unit(target[offset + 1]),
            unit(target[offset + 2]),
        ];
        let source_luma = 0.2126 * base[0] + 0.7152 * base[1] + 0.0722 * base[2];
        let reference_luma = reference_lumas[0] * normalized[0]
            + reference_lumas[1] * normalized[1]
            + reference_lumas[2] * normalized[2];
        let detail_scale = (source_luma / reference_luma.max(1.0 / 255.0)).clamp(0.55, 1.25);
        let coverage = total.clamp(0.0, 1.0);
        for component in 0..3 {
            target[offset + component] = unit_byte(mix(
                base[component],
                seeded[component] * detail_scale,
                coverage,
            ));
        }
    }
    Ok(true)
}

fn compose_material_response(
    material: &PreviewCoreMaterial,
    presentations: &[SessionMaterialPresentation],
    cache: &mut ImageCache,
) -> Result<Option<DecodedRgba8>, SessionError> {
    let Some((width, height)) = largest_target(material, cache, LayerMap::Material)? else {
        return Ok(None);
    };
    let pixel_count = checked_pixel_count(width, height)?;
    let presentation = presentations.iter().find(|presentation| {
        presentation.lod_index == material.lod_index
            && presentation.material_index == material.material_index
    });
    let roughness = presentation
        .and_then(|value| value.roughness)
        .or_else(|| {
            presentation
                .and_then(|value| value.surface_profile.as_ref())
                .map(|profile| profile.fallbacks.roughness)
        })
        .unwrap_or(0.58)
        .clamp(0.04, 1.0);
    let metalness = presentation
        .and_then(|value| value.metalness)
        .or_else(|| {
            presentation
                .and_then(|value| value.surface_profile.as_ref())
                .map(|profile| profile.fallbacks.metalness)
        })
        .unwrap_or(0.0)
        .clamp(0.0, 1.0);
    let specular = presentation
        .and_then(|value| value.specular)
        .or_else(|| {
            presentation
                .and_then(|value| value.surface_profile.as_ref())
                .map(|profile| profile.fallbacks.specular)
        })
        .unwrap_or(0.04)
        .clamp(0.0, 1.0);
    let mut target = vec![0_u8; pixel_count.saturating_mul(4)];
    for pixel in target.chunks_exact_mut(4) {
        pixel.copy_from_slice(&[
            255,
            unit_byte(roughness),
            unit_byte(metalness),
            unit_byte(specular),
        ]);
    }
    for layer in &material.layers {
        let Some(reference) = layer.material.as_ref() else {
            continue;
        };
        let source = cache.resized(reference, width, height)?;
        let mask = layer
            .mask
            .as_ref()
            .map(|reference| cache.resized(reference, width, height))
            .transpose()?;
        let channel = channel_index(&layer.mask_channel);
        let response_decoder = MaterialResponseDecoder::new(layer);
        for pixel in 0..pixel_count {
            let offset = pixel * 4;
            let coverage = layer_coverage(layer, mask.as_deref(), offset, channel);
            if coverage <= 0.0 {
                continue;
            }
            let decoded = response_decoder.decode(&source[offset..offset + 4]);
            target[offset] = 255;
            target[offset + 1] = unit_byte(mix(unit(target[offset + 1]), decoded[0], coverage));
            target[offset + 2] = unit_byte(mix(unit(target[offset + 2]), decoded[1], coverage));
            target[offset + 3] = unit_byte(mix(unit(target[offset + 3]), decoded[2], coverage));
        }
    }
    Ok(Some(DecodedRgba8 {
        width,
        height,
        pixels: target,
    }))
}

#[derive(Clone, Copy)]
enum MaterialResponseKind {
    Standard,
    Skin,
    Hair,
}

impl MaterialResponseKind {
    // Shader identity is constant across a layer. Normalize it once instead of
    // allocating and scanning the same strings for every output texel.
    fn from_layer(layer: &PreviewCoreMaterialLayer) -> Self {
        let rule = layer.shader_rule.to_ascii_lowercase();
        let family = layer
            .shader_family
            .chars()
            .filter(char::is_ascii_alphanumeric)
            .flat_map(char::to_lowercase)
            .collect::<String>();
        if rule == "skin" || family.contains("skinnedmeshskin") || family.contains("skinwrinkle") {
            Self::Skin
        } else if rule == "hair" || family.contains("hair") || family.contains("fur") {
            Self::Hair
        } else {
            Self::Standard
        }
    }
}

fn decode_material_pixel(
    layer: &PreviewCoreMaterialLayer,
    pixel: &[u8],
    response_kind: MaterialResponseKind,
) -> [f32; 3] {
    let green = unit(pixel[1]);
    let blue = unit(pixel[2]);
    let mut roughness = green.clamp(0.04, 1.0);
    let (mut metalness, mut specular) = match response_kind {
        MaterialResponseKind::Skin => (0.0, (0.06 + 0.24 * blue).clamp(0.04, 0.34)),
        MaterialResponseKind::Hair => (0.0, 0.19),
        MaterialResponseKind::Standard => (
            ((blue - 0.18).max(0.0) * 1.22).clamp(0.0, 0.92),
            (0.04 + 0.84 * blue).clamp(0.04, 0.88),
        ),
    };
    if layer.roughness_hint > 0.02 {
        roughness = (roughness * 0.72 + layer.roughness_hint * 0.28).clamp(0.04, 0.98);
    }
    if layer.metalness_hint > 0.02 {
        metalness = metalness.max(layer.metalness_hint * 0.42).clamp(0.0, 1.0);
        specular = specular.max(0.14 + layer.metalness_hint * 0.32);
    }
    if layer.specular_hint > 0.02 {
        specular = specular.max(layer.specular_hint * 0.58);
    }
    [roughness, metalness, specular.clamp(0.0, 1.0)]
}

struct MaterialResponseDecoder {
    channels: [[f32; 3]; 256],
}

impl MaterialResponseDecoder {
    fn new(layer: &PreviewCoreMaterialLayer) -> Self {
        let kind = MaterialResponseKind::from_layer(layer);
        // Roughness depends only on G; metalness and specular only on B.
        // Retain the exact float results until the existing blend/quantization.
        let channels = std::array::from_fn(|value| {
            decode_material_pixel(layer, &[0, value as u8, value as u8, 255], kind)
        });
        Self { channels }
    }

    fn decode(&self, pixel: &[u8]) -> [f32; 3] {
        let green = self.channels[usize::from(pixel[1])];
        let blue = self.channels[usize::from(pixel[2])];
        [green[0], blue[1], blue[2]]
    }
}

fn compose_normal(
    material: &PreviewCoreMaterial,
    resources: &[CdmwTextureResource],
    cache: &mut ImageCache,
) -> Result<Option<DecodedRgba8>, SessionError> {
    let has_layer_normal = material
        .layers
        .iter()
        .skip(1)
        .any(|layer| layer.normal.is_some());
    if !has_layer_normal
        && resource_owns(
            resources,
            TextureRole::Normal,
            material.lod_index,
            material.material_index,
        )
    {
        return Ok(None);
    }
    let Some((width, height)) = largest_target(material, cache, LayerMap::Normal)? else {
        return Ok(None);
    };
    let pixel_count = checked_pixel_count(width, height)?;
    let base = material
        .layers
        .first()
        .and_then(|layer| layer.normal.as_ref());
    let mut target = if let Some(reference) = base {
        cache.resized(reference, width, height)?.to_vec()
    } else {
        let mut pixels = Vec::with_capacity(pixel_count.saturating_mul(4));
        for _ in 0..pixel_count {
            pixels.extend_from_slice(&[128, 128, 255, 255]);
        }
        pixels
    };
    for pixel in target.chunks_exact_mut(4) {
        let normal = unpack_normal(pixel);
        pack_normal(pixel, normal);
    }
    for layer in material.layers.iter().skip(1) {
        let Some(reference) = layer.normal.as_ref() else {
            continue;
        };
        let source = cache.resized(reference, width, height)?;
        let mask = layer
            .mask
            .as_ref()
            .map(|reference| cache.resized(reference, width, height))
            .transpose()?;
        let channel = channel_index(&layer.mask_channel);
        for pixel in 0..pixel_count {
            let offset = pixel * 4;
            let coverage = layer_coverage(layer, mask.as_deref(), offset, channel);
            if coverage <= 0.0 {
                continue;
            }
            let base_normal = unpack_normal(&target[offset..offset + 4]);
            let layer_normal = unpack_normal(&source[offset..offset + 4]);
            let whiteout = normalize3([
                base_normal[0] + layer_normal[0],
                base_normal[1] + layer_normal[1],
                base_normal[2] * layer_normal[2],
            ]);
            let blended = normalize3([
                mix(base_normal[0], whiteout[0], coverage),
                mix(base_normal[1], whiteout[1], coverage),
                mix(base_normal[2], whiteout[2], coverage),
            ]);
            pack_normal(&mut target[offset..offset + 4], blended);
        }
    }
    Ok(Some(DecodedRgba8 {
        width,
        height,
        pixels: target,
    }))
}

fn compose_height(
    material: &PreviewCoreMaterial,
    resources: &[CdmwTextureResource],
    cache: &mut ImageCache,
) -> Result<Option<DecodedRgba8>, SessionError> {
    let has_layer_height = material
        .layers
        .iter()
        .skip(1)
        .any(|layer| layer.height.is_some());
    if !has_layer_height
        && resource_owns(
            resources,
            TextureRole::Height,
            material.lod_index,
            material.material_index,
        )
    {
        return Ok(None);
    }
    let Some((width, height)) = largest_target(material, cache, LayerMap::Height)? else {
        return Ok(None);
    };
    let pixel_count = checked_pixel_count(width, height)?;
    let base = material
        .layers
        .first()
        .and_then(|layer| layer.height.as_ref());
    let mut target = if let Some(reference) = base {
        cache.resized(reference, width, height)?.to_vec()
    } else {
        vec![128_u8; pixel_count.saturating_mul(4)]
    };
    for pixel in target.chunks_exact_mut(4) {
        pixel[1] = pixel[0];
        pixel[2] = pixel[0];
        pixel[3] = 255;
    }
    for layer in material.layers.iter().skip(1) {
        let Some(reference) = layer.height.as_ref() else {
            continue;
        };
        let source = cache.resized(reference, width, height)?;
        let mask = layer
            .mask
            .as_ref()
            .map(|reference| cache.resized(reference, width, height))
            .transpose()?;
        let channel = channel_index(&layer.mask_channel);
        for pixel in 0..pixel_count {
            let offset = pixel * 4;
            let coverage = layer_coverage(layer, mask.as_deref(), offset, channel);
            if coverage <= 0.0 {
                continue;
            }
            let value = unit_byte(mix(unit(target[offset]), unit(source[offset]), coverage));
            target[offset..offset + 4].copy_from_slice(&[value, value, value, 255]);
        }
    }
    Ok(Some(DecodedRgba8 {
        width,
        height,
        pixels: target,
    }))
}

fn largest_target(
    material: &PreviewCoreMaterial,
    cache: &ImageCache,
    map: LayerMap,
) -> Result<Option<(u32, u32)>, SessionError> {
    let mut result = None;
    let mut best = (0_u64, 0_u32);
    for layer in &material.layers {
        let Some(reference) = map.reference(layer) else {
            continue;
        };
        for candidate in [Some(reference), layer.mask.as_ref()].into_iter().flatten() {
            let image = cache.image(candidate)?;
            let score = (
                u64::from(image.width) * u64::from(image.height),
                image.width.max(image.height),
            );
            if score > best {
                best = score;
                result = Some((image.width, image.height));
            }
        }
    }
    Ok(result)
}

fn resize_rgba8(image: &DecodedRgba8, width: u32, height: u32) -> Result<Vec<u8>, SessionError> {
    if image.width == width && image.height == height {
        return Ok(image.pixels.clone());
    }
    let pixel_count = checked_pixel_count(width, height)?;
    let mut output = vec![0_u8; pixel_count.saturating_mul(4)];
    let scale_x = image.width as f32 / width as f32;
    let scale_y = image.height as f32 / height as f32;
    // Every row uses the same horizontal interpolation. Compute its offsets
    // once, and address whole rows instead of rechecking four corners/channel.
    let horizontal = (0..width)
        .map(|x| {
            let source_x =
                ((x as f32 + 0.5) * scale_x - 0.5).clamp(0.0, image.width.saturating_sub(1) as f32);
            let x0 = source_x.floor() as u32;
            let x1 = (x0 + 1).min(image.width - 1);
            Ok((
                source_offset(image.width, x0, 0, 0)?,
                source_offset(image.width, x1, 0, 0)?,
                source_x - x0 as f32,
            ))
        })
        .collect::<Result<Vec<_>, SessionError>>()?;
    let source_row_bytes = source_offset(image.width, image.width, 0, 0)?;
    let target_row_bytes = source_offset(width, width, 0, 0)?;
    for y in 0..height {
        let source_y =
            ((y as f32 + 0.5) * scale_y - 0.5).clamp(0.0, image.height.saturating_sub(1) as f32);
        let y0 = source_y.floor() as u32;
        let y1 = (y0 + 1).min(image.height - 1);
        let fy = source_y - y0 as f32;
        let row0 = source_offset(image.width, 0, y0, 0)?;
        let row1 = source_offset(image.width, 0, y1, 0)?;
        let top_row = &image.pixels[row0..row0 + source_row_bytes];
        let bottom_row = &image.pixels[row1..row1 + source_row_bytes];
        let destination = source_offset(width, 0, y, 0)?;
        for (pixel, &(x0, x1, fx)) in output[destination..destination + target_row_bytes]
            .chunks_exact_mut(4)
            .zip(&horizontal)
        {
            for component in 0..4 {
                let p00 = unit(top_row[x0 + component]);
                let p10 = unit(top_row[x1 + component]);
                let p01 = unit(bottom_row[x0 + component]);
                let p11 = unit(bottom_row[x1 + component]);
                let top = mix(p00, p10, fx);
                let bottom = mix(p01, p11, fx);
                pixel[component] = unit_byte(mix(top, bottom, fy));
            }
        }
    }
    Ok(output)
}

fn source_offset(width: u32, x: u32, y: u32, component: usize) -> Result<usize, SessionError> {
    usize::try_from((u64::from(y) * u64::from(width) + u64::from(x)) * 4)
        .ok()
        .and_then(|offset| offset.checked_add(component))
        .ok_or_else(|| {
            SessionError::InvalidPayload(
                "Preview Core material source offset overflowed".to_owned(),
            )
        })
}

fn checked_pixel_count(width: u32, height: u32) -> Result<usize, SessionError> {
    usize::try_from(u64::from(width) * u64::from(height)).map_err(|_| {
        SessionError::InvalidPayload(
            "Preview Core material dimensions exceed this platform".to_owned(),
        )
    })
}

fn channel_index(channel: &str) -> usize {
    match channel {
        "g" => 1,
        "b" => 2,
        "a" => 3,
        _ => 0,
    }
}

fn layer_coverage(
    layer: &PreviewCoreMaterialLayer,
    mask: Option<&[u8]>,
    offset: usize,
    channel: usize,
) -> f32 {
    let selector = mask.map_or(1.0, |pixels| unit(pixels[offset + channel]));
    (selector * layer.weight).clamp(0.0, 1.0)
}

fn selector_weight(mask: Option<&[u8]>, offset: usize, channel: usize, strength: f32) -> f32 {
    mask.map_or(0.0, |pixels| unit(pixels[offset + channel])) * strength
}

fn unpack_normal(pixel: &[u8]) -> [f32; 3] {
    let x = unit(pixel[0]) * 2.0 - 1.0;
    let y = unit(pixel[1]) * 2.0 - 1.0;
    normalize3([x, y, (1.0 - x * x - y * y).max(0.0).sqrt()])
}

fn pack_normal(pixel: &mut [u8], normal: [f32; 3]) {
    pixel[0] = unit_byte(normal[0] * 0.5 + 0.5);
    pixel[1] = unit_byte(normal[1] * 0.5 + 0.5);
    pixel[2] = unit_byte(normal[2] * 0.5 + 0.5);
    pixel[3] = 255;
}

fn normalize3(value: [f32; 3]) -> [f32; 3] {
    let length = (value[0] * value[0] + value[1] * value[1] + value[2] * value[2]).sqrt();
    if length <= f32::EPSILON {
        [0.0, 0.0, 1.0]
    } else {
        [value[0] / length, value[1] / length, value[2] / length]
    }
}

fn unit(value: u8) -> f32 {
    f32::from(value) / 255.0
}

fn unit_byte(value: f32) -> u8 {
    (value.clamp(0.0, 1.0) * 255.0).round() as u8
}

fn mix(left: f32, right: f32, amount: f32) -> f32 {
    left * (1.0 - amount) + right * amount
}

fn resource_owns(
    resources: &[CdmwTextureResource],
    role: TextureRole,
    lod_index: u32,
    material_index: u32,
) -> bool {
    usize::try_from(lod_index).ok().is_some_and(|lod| {
        resources.iter().any(|resource| {
            resource.role == role
                && resource
                    .material_indices_by_lod
                    .get(lod)
                    .is_some_and(|owners| owners.contains(&material_index))
        })
    })
}

fn publish_composed_resource(
    resources: &mut Vec<CdmwTextureResource>,
    document: &MeshDocument,
    material: &PreviewCoreMaterial,
    role: TextureRole,
    image: DecodedRgba8,
) -> Result<(), SessionError> {
    let lod_index = usize::try_from(material.lod_index).map_err(|_| {
        SessionError::InvalidManifest("Preview Core material LOD exceeds this platform".to_owned())
    })?;
    for resource in resources
        .iter_mut()
        .filter(|resource| resource.role == role)
    {
        if let Some(owners) = resource.material_indices_by_lod.get_mut(lod_index) {
            owners.retain(|owner| *owner != material.material_index);
        }
    }
    let bytes = encode_rgba8_dds(image.width, image.height, &image.pixels, role)
        .map_err(|error| SessionError::InvalidPayload(error.to_string()))?;
    let metadata = inspect_dds(&bytes, role)
        .map_err(|error| SessionError::InvalidPayload(error.to_string()))?;
    if let Some(existing) = resources.iter_mut().find(|resource| {
        resource.role == role
            && resource.metadata.source_sha256 == metadata.source_sha256
            && resource.bytes == bytes
    }) {
        let owners = existing
            .material_indices_by_lod
            .get_mut(lod_index)
            .ok_or_else(|| {
                SessionError::InvalidManifest(
                    "Preview Core composed texture ownership LOD is invalid".to_owned(),
                )
            })?;
        if !owners.contains(&material.material_index) {
            owners.push(material.material_index);
            owners.sort_unstable();
        }
        return Ok(());
    }
    let mut material_indices_by_lod = vec![Vec::new(); document.lods.len()];
    material_indices_by_lod
        .get_mut(lod_index)
        .ok_or_else(|| {
            SessionError::InvalidManifest(
                "Preview Core composed texture ownership LOD is invalid".to_owned(),
            )
        })?
        .push(material.material_index);
    resources.push(CdmwTextureResource {
        label: format!(
            "preview-core-composed-{:04}-{}.dds",
            material.material_index,
            role_label(role)
        ),
        role,
        metadata,
        bytes,
        material_indices_by_lod,
    });
    Ok(())
}

fn role_label(role: TextureRole) -> &'static str {
    match role {
        TextureRole::BaseColor => "base-color",
        TextureRole::Normal => "normal",
        TextureRole::Material => "material",
        TextureRole::Height => "height",
        _ => "texture",
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use cdmw_formats::{MeshFormat, MeshLod, SourceRange, Submesh};
    use sha2::{Digest, Sha256};
    use std::cell::Cell;

    fn reference(name_index: u32, bytes: &[u8]) -> FileReference {
        let sha256 = format!("{:X}", Sha256::digest(bytes));
        FileReference {
            path: format!(
                "texture-{name_index:04}-{}.dds",
                &sha256[..12].to_ascii_lowercase()
            ),
            data_type: "dds_texture".to_owned(),
            count: 1,
            byte_length: u64::try_from(bytes.len()).expect("byte length"),
            sha256,
            content_type: "image/vnd-ms.dds".to_owned(),
        }
    }

    fn layer(role: &str, channel: &str) -> PreviewCoreMaterialLayer {
        PreviewCoreMaterialLayer {
            owner_wrapper_item_id: "owner".to_owned(),
            material_wrapper_index: 0,
            layer_role: role.to_owned(),
            mask_channel: channel.to_owned(),
            shader_family: "SkinnedMeshStandard_Ver2".to_owned(),
            shader_rule: "standard_v2".to_owned(),
            evidence_grade: "exact".to_owned(),
            source_parameter: "_detailDiffuseMaskR".to_owned(),
            mask_parameter: "_colorBlendingMaskTexture".to_owned(),
            weight: 1.0,
            detail_scale: 0.0,
            roughness_hint: 0.0,
            metalness_hint: 0.0,
            specular_hint: 0.0,
            height_scale_hint: 0.0,
            tint: [1.0; 4],
            diffuse_declared: false,
            diffuse_archive_path: String::new(),
            diffuse: None,
            normal_declared: false,
            normal_archive_path: String::new(),
            normal: None,
            material_declared: false,
            material_archive_path: String::new(),
            material: None,
            height_declared: false,
            height_archive_path: String::new(),
            height: None,
            mask_declared: false,
            mask_archive_path: String::new(),
            mask: None,
        }
    }

    fn document() -> MeshDocument {
        MeshDocument {
            format: MeshFormat::Pac,
            source_sha256: String::new(),
            parser: "test".to_owned(),
            lod_count_reported: 1,
            lods: vec![MeshLod {
                level: 0,
                submeshes: vec![Submesh {
                    name: "handle".to_owned(),
                    material: "handle".to_owned(),
                    positions: vec![[0.0, 0.0, 0.0]; 3],
                    normals: vec![[0.0, 0.0, 1.0]; 3],
                    uvs: vec![[0.0, 0.0]; 3],
                    indices: vec![0, 1, 2],
                    source_vertex_indices: vec![0, 1, 2],
                    source_range: SourceRange {
                        offset: 0,
                        length: 0,
                    },
                    vertex_stride: 0,
                    layout: "test".to_owned(),
                }],
            }],
            warnings: Vec::new(),
            structural_fingerprint: String::new(),
        }
    }

    #[test]
    fn material_response_matches_original_channel_bytes() {
        // Recorded from the original per-pixel decoder for every green/blue
        // byte pair, including disabled, threshold and active material hints.
        let standard = "BE2F49FD68C1EF76E3F9070235C0C3967CCF176F2952BC84E5B1FF1298486EB7";
        let skin = "A9F7DD3A42AE7E405608F6D98FC9DD1A3A9862B8D1A32760FCDF98C4D582922E";
        let hair = "30E6F6B1C320A1AA051D8F8C238555425E2868D07E76E107ACC7F1B0D02C4AC5";
        for (rule, family, expected) in [
            ("standard_v2", "SkinnedMeshStandard_Ver2", standard),
            ("SkIn", "", skin),
            ("HAIR", "", hair),
            ("", "Skinned_Mesh-Skin", skin),
            ("", "Skin_Wrinkle_Fur", skin),
            ("", "CUSTOM_FUR", hair),
        ] {
            let mut source = layer("base", "r");
            source.shader_rule = rule.to_owned();
            source.shader_family = family.to_owned();
            let mut hash = Sha256::new();
            for hints in [[0.0, 0.0, 0.0], [0.02, 0.02, 0.02], [0.6, 0.4, 0.3]] {
                [
                    source.roughness_hint,
                    source.metalness_hint,
                    source.specular_hint,
                ] = hints;
                let kind = MaterialResponseKind::from_layer(&source);
                let decoder = MaterialResponseDecoder::new(&source);
                for green in 0..=255_u8 {
                    for blue in 0..=255_u8 {
                        let pixel = [0, green, blue, 255];
                        let decoded = decoder.decode(&pixel);
                        assert_eq!(
                            decoded.map(f32::to_bits),
                            decode_material_pixel(&source, &pixel, kind).map(f32::to_bits),
                        );
                        hash.update(decoded.map(unit_byte));
                    }
                }
            }
            assert_eq!(
                format!("{:X}", hash.finalize()),
                expected,
                "{rule}/{family}"
            );
        }
    }

    #[test]
    fn bilinear_resize_matches_original_pixels() {
        for (dimensions, expected) in [
            (
                [64, 64, 1024, 1024],
                "582a0cf6162f6e4ee39e657a587d77f01d903b83da431ace5b25b0f17803425e",
            ),
            (
                [512, 512, 1024, 1024],
                "c48479157ab85ff526f1188d524271a6a5f2e8787dba5c32ad193abdc4c8c9c4",
            ),
            (
                [1024, 512, 512, 256],
                "7763a50cd3e4f01c8b7e53b105921d68d9493324875758c1d29c558a2b59b598",
            ),
            (
                [31, 57, 127, 253],
                "747ef93943212f90f0e5466e474d598b20c59a7aad6732150a34e05ad4e6d2be",
            ),
            (
                [1, 1, 41, 19],
                "fe3b351decfea90a2e0c7f96dec19c1bb3da645bdd4630e9741608774bbafe0f",
            ),
            (
                [127, 67, 127, 67],
                "9c8ba97c484703b61117613496ba3efebc194414ff1404a9a802b1448ee42987",
            ),
        ] {
            let [source_width, source_height, width, height] = dimensions;
            let source = DecodedRgba8 {
                width: source_width,
                height: source_height,
                pixels: (0..source_width * source_height * 4)
                    .map(|index| ((index * 37 + index / 7) % 256) as u8)
                    .collect(),
            };
            let pixels = resize_rgba8(&source, width, height).expect("resized image");
            assert_eq!(
                format!("{:x}", Sha256::digest(&pixels)),
                expected,
                "{dimensions:?}"
            );
        }
    }

    #[test]
    fn masked_blue_and_copper_layers_compose_in_rust_and_sources_decode_once() {
        let mask_bytes = encode_rgba8_dds(
            2,
            1,
            &[255, 0, 0, 255, 0, 255, 0, 255],
            TextureRole::LayerMask,
        )
        .expect("mask DDS");
        let diffuse_bytes = encode_rgba8_dds(
            2,
            1,
            &[128, 128, 128, 255, 128, 128, 128, 255],
            TextureRole::BaseColor,
        )
        .expect("diffuse DDS");
        let material_bytes = encode_rgba8_dds(
            2,
            1,
            &[255, 52, 242, 255, 255, 52, 242, 255],
            TextureRole::Material,
        )
        .expect("material DDS");
        let mask_ref = reference(0, &mask_bytes);
        let diffuse_ref = reference(1, &diffuse_bytes);
        let material_ref = reference(2, &material_bytes);

        let mut base = layer("base", "r");
        base.source_parameter.clear();
        base.mask_parameter.clear();
        let mut blue = layer("detail", "r");
        blue.tint = [0.086_274_5, 0.184_314, 1.0, 1.0];
        blue.diffuse_declared = true;
        blue.diffuse_archive_path = "blue.dds".to_owned();
        blue.diffuse = Some(diffuse_ref.clone());
        blue.material_declared = true;
        blue.material_archive_path = "blue_sp.dds".to_owned();
        blue.material = Some(material_ref.clone());
        blue.mask_declared = true;
        blue.mask_archive_path = "selector.dds".to_owned();
        blue.mask = Some(mask_ref.clone());
        let mut copper = layer("detail", "g");
        copper.tint = [0.76, 0.31, 0.08, 1.0];
        copper.diffuse_declared = true;
        copper.diffuse_archive_path = "copper.dds".to_owned();
        copper.diffuse = Some(diffuse_ref.clone());
        copper.material_declared = true;
        copper.material_archive_path = "copper_sp.dds".to_owned();
        copper.material = Some(material_ref.clone());
        copper.mask_declared = true;
        copper.mask_archive_path = "selector.dds".to_owned();
        copper.mask = Some(mask_ref.clone());
        let graph = PreviewCoreMaterialGraph {
            schema_version: 1,
            graph_version: 4,
            semantics_version: 10,
            quality: "full".to_owned(),
            resources_included: true,
            source_edge_count: 6,
            unique_resource_count: 3,
            copied_resource_count: 3,
            unique_resource_bytes: u64::try_from(
                mask_bytes.len() + diffuse_bytes.len() + material_bytes.len(),
            )
            .expect("unique bytes"),
            materials: vec![PreviewCoreMaterial {
                lod_index: 0,
                material_index: 0,
                material_slot_index: 0,
                material_name: "handle".to_owned(),
                base_color: [0.62; 3],
                layers: vec![base, blue, copper],
            }],
        };
        let source_byte_count =
            u64::try_from(mask_bytes.len() + diffuse_bytes.len() + material_bytes.len())
                .expect("source bytes");
        let files = BTreeMap::from([
            (mask_ref.path.clone(), mask_bytes),
            (diffuse_ref.path.clone(), diffuse_bytes),
            (material_ref.path.clone(), material_bytes),
        ]);
        let reads = Cell::new(0_usize);
        let mut resources = Vec::new();
        let metrics = compose_preview_core_material_resources(
            &graph,
            &[],
            &document(),
            &mut resources,
            |reference| {
                reads.set(reads.get() + 1);
                Ok(files.get(&reference.path).expect("source bytes").clone())
            },
        )
        .expect("compose material graph");

        assert_eq!(reads.get(), 3, "each content-unique DDS decodes once");
        assert_eq!(metrics.source_reference_count, 6);
        assert_eq!(metrics.unique_source_dds_count, 3);
        assert_eq!(metrics.source_dds_decode_count, 3);
        assert_eq!(metrics.decoded_source_sha256.len(), 3);
        assert_eq!(metrics.decoded_source_bytes, source_byte_count);
        assert_eq!(resources.len(), 2);
        let color = resources
            .iter()
            .find(|resource| resource.role == TextureRole::BaseColor)
            .expect("composed color");
        let decoded =
            decode_dds_rgba8(&color.bytes, TextureRole::BaseColor).expect("decode composed color");
        assert!(
            decoded.pixels[2] > decoded.pixels[0] * 4,
            "R mask is royal blue"
        );
        assert!(
            decoded.pixels[4] > decoded.pixels[5] * 2 && decoded.pixels[5] > decoded.pixels[6] * 2,
            "G mask is copper"
        );
        let surface = resources
            .iter()
            .find(|resource| resource.role == TextureRole::Material)
            .expect("composed material response");
        let surface = decode_dds_rgba8(&surface.bytes, TextureRole::Material)
            .expect("decode composed response");
        assert!(
            surface.pixels[2] > 190 && surface.pixels[6] > 190,
            "packed response was {:?}",
            surface.pixels
        );
    }
}
