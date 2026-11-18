//! Texture edits CDMW shows on the model while the user paints (step 8, B item 6).
//!
//! CDMW names an edited texture by the source hash it was loaded with. Two kinds
//! of texture answer to that name: the material textures the renderer loaded
//! itself, and the layer textures (mask, detail colour, normal and response maps)
//! the shader combines from a material graph (`preview_gpu_layers`). An edited
//! layer is put into every layered material that samples it, keeps answering to
//! its source's name after a second edit, a part reorder or a material reload,
//! and has its mean luminance taken again so dyed layers follow the edit.
//!
//! Materials composed on the CPU when the model opened sample a colour made from
//! their layers, not the layers, so an edit of one of those layers is not shown;
//! nor is a colour edit of a base map whose material takes its colour from three
//! layers. `live_texture_sources` tells CDMW which textures are shown, per part.

use crate::loader::LoadedTexture;
use cdmw_render_wgpu::{
    BLEND_NORMAL_SLOT, DETAIL_MASK_SLOT, GRIME_SLOT, MaterialLayerSet, OVERLAY_SLOT, WindowRenderer,
};
use cdmw_texture::{TextureRole, dds_mean_luminance_of_any_size};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;
use std::sync::Arc;

pub const NO_SUCH_TEXTURE: &str = "the session has no texture with that source";

#[derive(Debug, Clone)]
struct LayerEdit {
    bytes: Arc<[u8]>,
    /// The renderer caches uploads by this key, so each edit has its own: a digest
    /// of the source's name and the edited bytes (upper case, as layer keys are).
    key: String,
    mean: Option<f32>,
}

/// The layer textures edited in this editor session, by the source hash CDMW names.
#[derive(Debug, Default)]
pub struct LayerTextureEdits {
    edits: BTreeMap<String, LayerEdit>,
    /// An edit's key back to the source it replaced.
    sources: BTreeMap<String, String>,
}

impl LayerTextureEdits {
    #[cfg(test)]
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.edits.is_empty()
    }

    /// The source hash (lower case) CDMW knows a layer texture by.
    #[must_use]
    pub fn source_of(&self, key: &str) -> String {
        self.sources
            .get(&key.to_ascii_uppercase())
            .cloned()
            .unwrap_or_else(|| key.to_ascii_lowercase())
    }

    /// Whether a layered material samples the texture loaded from `source`.
    #[must_use]
    pub fn uses(&self, layers: &[MaterialLayerSet], source: &str) -> bool {
        let source = source.to_ascii_lowercase();
        layers.iter().any(|set| {
            set.textures
                .iter()
                .flatten()
                .any(|texture| self.source_of(&texture.source_sha256) == source)
        })
    }

    /// Keep `bytes` as the edited texture of `source` and put it into every layered
    /// material that samples it; the indices of the materials changed.
    pub fn record(
        &mut self,
        layers: &mut [MaterialLayerSet],
        source: &str,
        bytes: Vec<u8>,
    ) -> Vec<usize> {
        let source = source.to_ascii_lowercase();
        let mut digest = Sha256::new();
        digest.update(source.as_bytes());
        digest.update(b":");
        digest.update(&bytes);
        let key = digest
            .finalize()
            .iter()
            .map(|byte| format!("{byte:02X}"))
            .collect::<String>();
        let mean = dds_mean_luminance_of_any_size(&bytes).ok();
        let edit = LayerEdit {
            bytes: Arc::from(bytes),
            key: key.clone(),
            mean,
        };
        self.sources.insert(key, source.clone());
        self.edits.insert(source.clone(), edit);
        let edit = &self.edits[&source];
        (0..layers.len())
            .filter(|&index| put_edit(&mut layers[index], &self.sources, &source, edit))
            .collect()
    }

    /// Put every edit into `layers` (materials read again or remapped).
    pub fn reapply(&self, layers: &mut [MaterialLayerSet]) {
        for (source, edit) in &self.edits {
            for set in layers.iter_mut() {
                put_edit(set, &self.sources, source, edit);
            }
        }
    }
}

fn put_edit(
    set: &mut MaterialLayerSet,
    sources: &BTreeMap<String, String>,
    source: &str,
    edit: &LayerEdit,
) -> bool {
    let eye = set.uniform.control[0] == 3;
    let mut changed = false;
    for (slot, texture) in set.textures.iter_mut().enumerate() {
        let Some(texture) = texture else {
            continue;
        };
        let known_as = sources
            .get(&texture.source_sha256.to_ascii_uppercase())
            .cloned()
            .unwrap_or_else(|| texture.source_sha256.to_ascii_lowercase());
        if known_as != source || texture.source_sha256 == edit.key {
            continue;
        }
        texture.bytes = Arc::clone(&edit.bytes);
        texture.source_sha256.clone_from(&edit.key);
        changed = true;
        if slot == BLEND_NORMAL_SLOT && set.uniform.blend_switches[3] == 2.0 {
            // As grime below: an edit is unsigned RGBA8, so the symbol's signed
            // BC5 normal now reads as unsigned RG.
            set.uniform.blend_switches[3] = 1.0;
        }
        if slot == 0 || slot == DETAIL_MASK_SLOT || slot >= OVERLAY_SLOT {
            // Masks and the overlay map have no per-layer uniform to follow them.
            continue;
        }
        if slot >= GRIME_SLOT {
            // Grime colour, normal and response per channel, after the detail mask.
            let entry = &mut set.uniform.layers[(slot - GRIME_SLOT) / 3];
            // An edit is unsigned RGBA8: a signed BC5 normal reads as unsigned RG now.
            if (slot - GRIME_SLOT) % 3 == 1 && entry.grime[2] == 2.0 {
                entry.grime[2] = 1.0;
            }
            continue;
        }
        // Slots after the mask are colour, normal and response per channel.
        let entry = &mut set.uniform.layers[(slot - 1) / 3];
        match (slot - 1) % 3 {
            0 if !eye => {
                if let Some(mean) = edit.mean {
                    entry.properties[1] = mean;
                }
            }
            // An edit is unsigned RGBA8: a signed BC5 normal reads as unsigned RG now.
            1 if entry.properties[3] == 2.0 => entry.properties[3] = 1.0,
            _ => {}
        }
    }
    changed
}

/// Show one edited texture in place of every material texture loaded from its
/// source and every layer texture the shader combines from it.
pub fn apply_texture_update(
    renderer: &mut WindowRenderer,
    sources: &[String],
    layers: &mut [MaterialLayerSet],
    edits: &mut LayerTextureEdits,
    source_sha256: &str,
    path: &Path,
) -> Result<(), String> {
    let source = source_sha256.to_ascii_lowercase();
    let direct = sources
        .iter()
        .enumerate()
        .filter(|(_, known)| **known == source)
        .map(|(index, _)| index)
        .collect::<Vec<_>>();
    let layered = edits.uses(layers, &source);
    if direct.is_empty() && !layered {
        return Err(NO_SUCH_TEXTURE.to_owned());
    }
    let bytes = std::fs::read(path)
        .map_err(|error| format!("could not read {}: {error}", path.display()))?;
    if !direct.is_empty() {
        renderer
            .replace_material_textures(&direct, &bytes)
            .map_err(|error| error.to_string())?;
    }
    if layered {
        let changed = edits.record(layers, &source, bytes);
        renderer
            .refresh_material_layers(changed.iter().map(|&index| &layers[index]))
            .map_err(|error| error.to_string())?;
    }
    Ok(())
}

/// Whether CDMW's texture update can be applied now, rather than wait for the textures.
#[must_use]
pub fn known_texture(
    sources: &[String],
    layers: &[MaterialLayerSet],
    edits: &LayerTextureEdits,
    source_sha256: &str,
) -> bool {
    let source = source_sha256.to_ascii_lowercase();
    sources.contains(&source) || edits.uses(layers, &source)
}

/// The textures an edit shows on, by source hash: the LOD 0 parts that sample each.
///
/// A base colour map bound to a material whose layers cover all three channels is
/// left out: the shader takes that material's colour from the layers alone
/// (`MaterialLayerSet::hides_base_colour`), so a colour edit of the map changes
/// nothing on the model.
#[must_use]
pub fn live_texture_sources(
    resources: &[LoadedTexture],
    sources: &[String],
    layers: &[MaterialLayerSet],
    edits: &LayerTextureEdits,
    bound: impl Fn(usize, u32) -> bool,
) -> BTreeMap<String, BTreeSet<u32>> {
    let hidden_base = layers
        .iter()
        .filter(|set| {
            set.lod_index == 0
                && bound(set.lod_index, set.material_index)
                && set.hides_base_colour()
        })
        .map(|set| set.material_index)
        .collect::<BTreeSet<_>>();
    let mut shown = BTreeMap::<String, BTreeSet<u32>>::new();
    for resource in resources {
        let source = resource.metadata.source_sha256.to_ascii_lowercase();
        if sources.contains(&source) {
            let hidden = resource.role == TextureRole::BaseColor;
            shown.entry(source).or_default().extend(
                resource
                    .material_indices_by_lod
                    .first()
                    .into_iter()
                    .flatten()
                    .filter(|material| !(hidden && hidden_base.contains(material))),
            );
        }
    }
    for set in layers
        .iter()
        .filter(|set| set.lod_index == 0 && bound(set.lod_index, set.material_index))
    {
        for texture in set.textures.iter().flatten() {
            shown
                .entry(edits.source_of(&texture.source_sha256))
                .or_default()
                .insert(set.material_index);
        }
    }
    shown.retain(|_, parts| !parts.is_empty());
    shown
}

#[cfg(test)]
mod tests {
    use super::*;
    use cdmw_render_wgpu::{LayerTexture, LayerUniform};
    use cdmw_texture::{TextureRole, encode_rgba8_dds, encode_rgba8_mipmapped_dds, inspect_dds};

    fn texture(pixel: [u8; 4], role: TextureRole) -> LayerTexture {
        let bytes = encode_rgba8_mipmapped_dds(4, 4, &pixel.repeat(16), role).expect("dds");
        let sha = inspect_dds(&bytes, role).expect("inspect").source_sha256;
        LayerTexture {
            bytes: Arc::from(bytes),
            role,
            source_sha256: sha.to_ascii_uppercase(),
        }
    }

    fn set(material_index: u32, mask: &LayerTexture, colour: &LayerTexture) -> MaterialLayerSet {
        let mut set = MaterialLayerSet {
            lod_index: 0,
            material_index,
            uniform: LayerUniform {
                control: [2, 0, 0, 0],
                ..Default::default()
            },
            textures: std::array::from_fn(|_| None),
        };
        set.textures[0] = Some(mask.clone());
        set.textures[1] = Some(colour.clone());
        set.textures[4] = Some(colour.clone());
        // Channel G's normal slot, from the same file: its BC5 snorm encoding (2).
        set.textures[5] = Some(colour.clone());
        set.uniform.layers[0].properties = [1.0, 0.5, 1.0, 0.0];
        set.uniform.layers[1].properties = [1.0, 0.5, 1.0, 2.0];
        set
    }

    fn edit_bytes(pixel: [u8; 4]) -> Vec<u8> {
        // As CDMW writes a live edit: one uncompressed mip larger than 64px.
        encode_rgba8_dds(128, 128, &pixel.repeat(128 * 128), TextureRole::BaseColor).expect("dds")
    }

    #[test]
    fn an_edited_detail_mask_or_grime_map_reaches_its_slot() {
        let mask = texture([255, 0, 0, 255], TextureRole::LayerMask);
        let colour = texture([128, 128, 128, 255], TextureRole::BaseColor);
        let detail = texture([0, 200, 0, 255], TextureRole::LayerMask);
        let grime = texture([90, 60, 30, 255], TextureRole::BaseColor);
        let mut one = set(4, &mask, &colour);
        one.textures[DETAIL_MASK_SLOT] = Some(detail.clone());
        // Channel B's grime colour and normal, the normal as signed BC5 (2).
        one.textures[GRIME_SLOT + 6] = Some(grime.clone());
        one.textures[GRIME_SLOT + 7] = Some(grime.clone());
        one.uniform.layers[2].grime = [1.0, 1.0, 2.0, 0.0];
        let mut layers = vec![one];
        let mut edits = LayerTextureEdits::default();
        for source in [&detail, &grime] {
            let name = source.source_sha256.to_ascii_lowercase();
            assert!(edits.uses(&layers, &name));
            let changed = edits.record(&mut layers, &name, edit_bytes([255, 255, 255, 255]));
            assert_eq!(changed, vec![0]);
        }
        let set = &layers[0];
        assert_ne!(
            set.textures[DETAIL_MASK_SLOT]
                .as_ref()
                .unwrap()
                .source_sha256,
            detail.source_sha256
        );
        assert_ne!(
            set.textures[GRIME_SLOT + 6].as_ref().unwrap().source_sha256,
            grime.source_sha256
        );
        assert_eq!(
            set.uniform.layers[2].grime[2], 1.0,
            "an edited grime normal reads as unsigned"
        );
        assert_eq!(
            set.uniform.layers[0].properties,
            [1.0, 0.5, 1.0, 0.0],
            "the colour layers are untouched"
        );
    }

    #[test]
    fn an_edited_layer_reaches_every_material_and_slot_that_samples_it() {
        let mask = texture([255, 0, 0, 255], TextureRole::LayerMask);
        let colour = texture([128, 128, 128, 255], TextureRole::BaseColor);
        let other = texture([10, 20, 30, 255], TextureRole::BaseColor);
        let mut layers = vec![set(4, &mask, &colour), set(8, &mask, &other)];
        let mut edits = LayerTextureEdits::default();
        let source = colour.source_sha256.to_ascii_lowercase();
        assert!(
            edits.uses(&layers, &source),
            "CDMW names the source in lower case"
        );
        assert!(known_texture(&[], &layers, &edits, &source));

        let changed = edits.record(&mut layers, &source, edit_bytes([255, 255, 255, 255]));
        assert_eq!(changed, vec![0], "only the material that samples the layer");
        let slot = layers[0].textures[1].as_ref().expect("colour");
        assert_ne!(
            slot.source_sha256, colour.source_sha256,
            "the renderer caches by key"
        );
        assert_eq!(slot.bytes.len(), edit_bytes([0; 4]).len());
        assert!(Arc::ptr_eq(
            &slot.bytes,
            &layers[0].textures[4]
                .as_ref()
                .expect("second channel")
                .bytes
        ));
        assert!(
            (layers[0].uniform.layers[0].properties[1] - 1.0).abs() < 1e-4,
            "white mean"
        );
        assert!(
            (layers[0].uniform.layers[1].properties[1] - 1.0).abs() < 1e-4,
            "both channels"
        );
        assert_eq!(
            layers[0].uniform.layers[1].properties[3], 1.0,
            "unsigned RG normal"
        );
        assert_eq!(
            layers[0].uniform.layers[0].properties[3], 0.0,
            "no normal there"
        );
        assert_eq!(
            layers[1].textures[1].as_ref().unwrap().source_sha256,
            other.source_sha256
        );

        // A second edit (an undo or the next stroke) still finds the layer by its source.
        assert!(edits.uses(&layers, &source));
        let first_key = slot.source_sha256.clone();
        assert_eq!(
            edits.record(&mut layers, &source, edit_bytes([0, 0, 0, 255])),
            vec![0]
        );
        assert_ne!(
            layers[0].textures[1].as_ref().unwrap().source_sha256,
            first_key
        );
        assert!(
            layers[0].uniform.layers[0].properties[1] < 1e-4,
            "black mean"
        );

        // Materials read again from the package get the edit too.
        let mut reloaded = vec![set(4, &mask, &colour)];
        edits.reapply(&mut reloaded);
        assert_eq!(
            reloaded[0].textures[1].as_ref().unwrap().source_sha256,
            layers[0].textures[1].as_ref().unwrap().source_sha256
        );
    }

    #[test]
    fn two_layers_edited_alike_stay_two_sources() {
        let mask = texture([255, 0, 0, 255], TextureRole::LayerMask);
        let first = texture([1, 2, 3, 255], TextureRole::BaseColor);
        let second = texture([4, 5, 6, 255], TextureRole::BaseColor);
        let mut layers = vec![set(0, &mask, &first), set(1, &mask, &second)];
        let mut edits = LayerTextureEdits::default();
        let (first, second) = (
            first.source_sha256.to_ascii_lowercase(),
            second.source_sha256.to_ascii_lowercase(),
        );
        edits.record(&mut layers, &first, edit_bytes([9, 9, 9, 255]));
        edits.record(&mut layers, &second, edit_bytes([9, 9, 9, 255]));
        assert_eq!(
            edits.record(&mut layers, &first, edit_bytes([7, 7, 7, 255])),
            vec![0]
        );
    }

    #[test]
    fn cdmw_is_told_each_shown_texture_with_its_parts() {
        let root = tempfile::tempdir().expect("temporary directory");
        let bridge =
            crate::cdmw_session::CdmwBridge::for_test(root.path().to_path_buf(), "live", 3, 0);
        let shown = BTreeMap::from([("ab".repeat(32), BTreeSet::from([4, 8]))]);
        let message = crate::cdmw_session::live_textures_message(bridge.manifest(), &shown);
        assert_eq!(message["event"], "live_textures");
        assert_eq!(message["session_id"], "live");
        assert_eq!(message["process_generation"], 3);
        assert_eq!(
            message["textures"],
            serde_json::json!([{"source_sha256": "ab".repeat(32), "parts": [4, 8]}])
        );
    }

    #[test]
    fn the_shown_textures_name_each_part_that_samples_them() {
        let mask = texture([255, 0, 0, 255], TextureRole::LayerMask);
        let colour = texture([128, 128, 128, 255], TextureRole::BaseColor);
        let mut composed = set(9, &mask, &colour);
        composed.lod_index = 1;
        let layers = vec![set(4, &mask, &colour), set(5, &mask, &colour), composed];
        let edits = LayerTextureEdits::default();
        let shown = live_texture_sources(&[], &[], &layers, &edits, |_, material| material != 5);
        let colour = colour.source_sha256.to_ascii_lowercase();
        assert_eq!(
            shown[&colour],
            BTreeSet::from([4]),
            "LOD 0 materials the renderer bound"
        );
        assert_eq!(
            shown[&mask.source_sha256.to_ascii_lowercase()],
            BTreeSet::from([4])
        );
    }

    fn loaded(texture: &LayerTexture, materials: Vec<u32>) -> LoadedTexture {
        LoadedTexture {
            label: "base.dds".to_owned(),
            metadata: inspect_dds(&texture.bytes, texture.role).expect("inspect"),
            bytes: Arc::clone(&texture.bytes),
            role: texture.role,
            requested_reference: "base.dds".to_owned(),
            parameter_name: None,
            sidecar_label: None,
            resolution_method: cdmw_asset_graph::ResolutionMethod::ExplicitVirtualPath,
            archive_compression: None,
            material_indices_by_lod: vec![materials],
        }
    }

    #[test]
    fn a_base_colour_under_layers_on_every_channel_is_not_shown() {
        // Armour 0374's belts (B pass 8): their base colour map is bound, but the
        // shader takes their colour from detail layers on R, G and B, so a magenta
        // cross painted on the map changed no pixel of the model.
        let mask = texture([255, 0, 0, 255], TextureRole::LayerMask);
        let layer = texture([128, 128, 128, 255], TextureRole::BaseColor);
        let base = texture([200, 100, 50, 255], TextureRole::BaseColor);
        let normal = texture([128, 128, 255, 255], TextureRole::Normal);
        let response = texture([255, 160, 0, 255], TextureRole::Material);
        let three = |material: u32, mode: u32| {
            let mut three = set(material, &mask, &layer);
            three.textures[7] = Some(layer.clone());
            three.uniform.layers[2].properties = [1.0, 0.5, 1.0, 0.0];
            three.uniform.control[0] = mode;
            three
        };
        // 4: layers on R, G and B. 5: none on B, so the base shows there. 6: masked
        // overlays over the base. 7: not bound, so the base is drawn as it is. 8: no layers.
        let layers = vec![three(4, 1), set(5, &mask, &layer), three(6, 2), three(7, 1)];
        let resources = vec![
            loaded(&base, vec![4, 5, 6, 7, 8]),
            loaded(&normal, vec![4]),
            loaded(&response, vec![4]),
        ];
        let sources = resources
            .iter()
            .map(|resource| resource.metadata.source_sha256.to_ascii_lowercase())
            .collect::<Vec<_>>();
        let shown = live_texture_sources(
            &resources,
            &sources,
            &layers,
            &LayerTextureEdits::default(),
            |_, material| material != 7,
        );
        assert_eq!(
            shown[&sources[0]],
            BTreeSet::from([5, 6, 7, 8]),
            "the base colour is not shown on material 4"
        );
        assert_eq!(
            shown[&sources[1]],
            BTreeSet::from([4]),
            "the base normal map still shows"
        );
        assert_eq!(
            shown[&sources[2]],
            BTreeSet::from([4]),
            "the response map is still read (EyeCover alpha)"
        );
        assert_eq!(
            shown[&layer.source_sha256.to_ascii_lowercase()],
            BTreeSet::from([4, 5, 6]),
            "the layers themselves are shown"
        );
    }

    #[test]
    fn a_new_session_starts_without_the_last_one_s_layer_edits() {
        // The same process can take another session (a helper that showed Browse's model).
        let root = tempfile::tempdir().expect("temporary directory");
        let document = cdmw_formats::decode_mesh(
            &cdmw_formats::synthetic::triangle_pam("body_base.dds"),
            cdmw_formats::MeshFormat::Pam,
        )
        .expect("triangle");
        let bridge = |id: &str| {
            crate::cdmw_session::CdmwBridge::for_test(root.path().to_path_buf(), id, 1, 0)
        };
        let mut application =
            crate::LabApplication::new_cdmw(bridge("first"), document.clone(), None)
                .expect("first session");
        let mask = texture([255, 0, 0, 255], TextureRole::LayerMask);
        let colour = texture([128, 128, 128, 255], TextureRole::BaseColor);
        let mut layers = vec![set(0, &mask, &colour)];
        let source = colour.source_sha256.to_ascii_lowercase();
        application.cdmw_layer_texture_edits.record(
            &mut layers,
            &source,
            edit_bytes([1, 1, 1, 255]),
        );
        application.cdmw_published_live_textures = Some(BTreeMap::new());
        assert!(!application.cdmw_layer_texture_edits.is_empty());

        application
            .install_cdmw(bridge("second"), document)
            .expect("second session");
        assert!(application.cdmw_layer_texture_edits.is_empty());
        assert!(
            application.cdmw_published_live_textures.is_none(),
            "CDMW is told again what shows live"
        );
    }
}
