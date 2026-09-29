#![forbid(unsafe_code)]

use crate::cdmw_session::{
    CdmwTextureResource, FileReference, MAX_TEXTURE_TOTAL_BYTES, PreviewCoreMaterial,
    PreviewCoreMaterialGraph, PreviewCoreMaterialLayer, SessionError, SessionMaterialPresentation,
};
use cdmw_formats::MeshDocument;
use cdmw_texture::{
    DecodedRgba8, TextureRole, decode_dds_rgba8, encode_rgba8_mipmapped_dds, inspect_dds,
};
use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;

mod work {
    //! Bounded CPU preparation; resource ownership is published by the caller in graph order.
    use super::*;
    use cdmw_texture::DdsMetadata;
    use sha2::{Digest, Sha256};
    use std::cell::RefCell;
    use std::collections::VecDeque;
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::mpsc;
    use std::time::Duration;

    const MAX_WORKERS: usize = 4;
    const COMPLETED_CACHE_BYTES: usize = 128 * 1024 * 1024;
    const COMPLETED_CACHE_ENTRIES: usize = 256;

    pub(super) struct ComposedMap {
        pub role: TextureRole,
        pub metadata: DdsMetadata,
        pub bytes: Vec<u8>,
    }

    impl ComposedMap {
        pub(super) fn encode(role: TextureRole, image: DecodedRgba8) -> Result<Self, SessionError> {
            let bytes = encode_rgba8_mipmapped_dds(image.width, image.height, &image.pixels, role)
                .map_err(|error| SessionError::InvalidPayload(error.to_string()))?;
            let metadata = inspect_dds(&bytes, role)
                .map_err(|error| SessionError::InvalidPayload(error.to_string()))?;
            Ok(Self {
                role,
                metadata,
                bytes,
            })
        }
    }

    type Completed = Arc<Vec<ComposedMap>>;

    #[derive(Default)]
    struct CompletedCache {
        entries: VecDeque<([u8; 32], Completed)>,
        bytes: usize,
    }

    impl CompletedCache {
        fn get(&mut self, key: &[u8; 32]) -> Option<Completed> {
            let index = self
                .entries
                .iter()
                .position(|(candidate, _)| candidate == key)?;
            let entry = self.entries.remove(index)?;
            let result = Arc::clone(&entry.1);
            self.entries.push_back(entry);
            Some(result)
        }

        fn insert(&mut self, key: [u8; 32], maps: Completed, protected: &BTreeSet<[u8; 32]>) {
            let bytes: usize = maps.iter().map(|map| map.bytes.len()).sum();
            if bytes > COMPLETED_CACHE_BYTES || self.get(&key).is_some() {
                return;
            }
            while self.bytes + bytes > COMPLETED_CACHE_BYTES
                || self.entries.len() >= COMPLETED_CACHE_ENTRIES
            {
                let Some(index) = self
                    .entries
                    .iter()
                    .position(|(key, _)| !protected.contains(key))
                else {
                    return;
                };
                let Some((_, old)) = self.entries.remove(index) else {
                    return;
                };
                self.bytes -= old.iter().map(|map| map.bytes.len()).sum::<usize>();
            }
            self.bytes += bytes;
            self.entries.push_back((key, maps));
        }
    }

    // The resident loader owns this cache. Workers never borrow it, and a closed
    // loader releases it. No mutable global cache or filesystem lifetime is shared.
    thread_local! {
        static COMPLETED: RefCell<CompletedCache> = RefCell::default();
    }

    struct Job {
        material: PreviewCoreMaterial,
        key: [u8; 32],
    }

    fn cache_key(
        material: &PreviewCoreMaterial,
        presentations: &[SessionMaterialPresentation],
        resources: &[CdmwTextureResource],
    ) -> [u8; 32] {
        let presentation = presentations.iter().find(|row| {
            row.lod_index == material.lod_index && row.material_index == material.material_index
        });
        // Process-local only: Debug covers every graph/presentation field without
        // introducing a persisted schema. Owned inputs include painted channels.
        let mut hash = Sha256::new();
        hash.update(format!("{material:?}|{presentation:?}"));
        for resource in resources {
            if resource
                .material_indices_by_lod
                .get(material.lod_index as usize)
                .is_some_and(|owners| owners.contains(&material.material_index))
            {
                hash.update(format!(
                    "{:?}|{};",
                    resource.role, resource.metadata.source_sha256
                ));
            }
        }
        hash.finalize().into()
    }

    fn maps() -> [(LayerMap, TextureRole); 4] {
        [
            (LayerMap::Diffuse, TextureRole::BaseColor),
            (LayerMap::Material, TextureRole::Material),
            (LayerMap::Normal, TextureRole::Normal),
            (LayerMap::Height, TextureRole::Height),
        ]
    }

    fn references_for_map(material: &PreviewCoreMaterial, map: LayerMap) -> Vec<&FileReference> {
        material
            .layers
            .iter()
            .flat_map(|layer| {
                let reference = map.reference(layer);
                let mask = if reference.is_some()
                    || matches!(map, LayerMap::Diffuse) && layer.layer_role == "color_seed"
                {
                    layer.mask.as_ref()
                } else {
                    None
                };
                [reference, mask].into_iter().flatten()
            })
            .collect()
    }

    fn working_bytes(
        material: &PreviewCoreMaterial,
        resources: &[CdmwTextureResource],
        cache: &ImageCache,
    ) -> Result<u64, SessionError> {
        let mut resized = BTreeMap::new();
        let mut outputs = 0_u64;
        let mut scratch = 0_u64;
        for (map, role) in maps() {
            if !map_needs_composition(material, resources, map) {
                continue;
            }
            let Some((width, height)) = largest_target(material, cache, map)? else {
                continue;
            };
            for reference in references_for_map(material, map) {
                let image = cache.image(reference)?;
                if (image.width, image.height) != (width, height) {
                    resized.insert(
                        (reference.sha256.clone(), width, height),
                        u64::from(width) * u64::from(height) * 4,
                    );
                }
            }
            let mut output_width = width;
            let mut output_height = height;
            let painted = (role == TextureRole::BaseColor && material.authoring_channels & 1 != 0)
                || (role == TextureRole::Material && material.authoring_channels & 2 != 0);
            if painted {
                for resource in resources.iter().filter(|resource| {
                    resource.role == role
                        && resource
                            .material_indices_by_lod
                            .get(material.lod_index as usize)
                            .is_some_and(|owners| owners.contains(&material.material_index))
                }) {
                    output_width = output_width.max(resource.metadata.width);
                    output_height = output_height.max(resource.metadata.height);
                }
            }
            let pixels = u64::from(output_width) * u64::from(output_height) * 4;
            // Exact mip storage, plus the peak encode/paint scratch. Counting thin
            // textures explicitly keeps large square maps eligible for four workers.
            outputs = outputs.saturating_add(148);
            let (mut w, mut h) = (output_width, output_height);
            loop {
                outputs = outputs.saturating_add(u64::from(w) * u64::from(h) * 4);
                if w == 1 && h == 1 {
                    break;
                }
                (w, h) = ((w / 2).max(1), (h / 2).max(1));
            }
            scratch = scratch.max(pixels.saturating_mul(if painted { 4 } else { 2 }));
        }
        Ok(resized
            .values()
            .copied()
            .sum::<u64>()
            .saturating_add(outputs)
            .saturating_add(scratch))
    }

    fn prepare(
        material: &PreviewCoreMaterial,
        presentations: &[SessionMaterialPresentation],
        resources: &[CdmwTextureResource],
        mut cache: ImageCache,
        cancelled: &dyn Fn() -> bool,
    ) -> Result<Completed, SessionError> {
        cache.begin_material();
        let mut result = Vec::new();
        for (_, role) in maps() {
            crate::cdmw_session::check_preview_cancelled(cancelled)?;
            let image = match role {
                TextureRole::BaseColor => compose_base_color(material, resources, &mut cache)?,
                TextureRole::Material => {
                    compose_material_response(material, presentations, &mut cache)?
                }
                TextureRole::Normal => compose_normal(material, resources, &mut cache)?,
                TextureRole::Height => compose_height(material, resources, &mut cache)?,
                _ => unreachable!(),
            };
            if let Some(mut image) = image {
                if role == TextureRole::BaseColor && material.authoring_channels & 1 != 0 {
                    apply_authored_channel(&mut image, resources, material, role, 3)?;
                } else if role == TextureRole::Material && material.authoring_channels & 2 != 0 {
                    apply_authored_channel(&mut image, resources, material, role, 0)?;
                }
                crate::cdmw_session::check_preview_cancelled(cancelled)?;
                result.push(ComposedMap::encode(role, image)?);
            }
        }
        Ok(Arc::new(result))
    }

    pub(super) fn compose<F>(
        graph: &PreviewCoreMaterialGraph,
        presentations: &[SessionMaterialPresentation],
        document: &MeshDocument,
        resources: &mut Vec<CdmwTextureResource>,
        read_reference: &mut F,
        cancelled: &dyn Fn() -> bool,
    ) -> Result<PreviewCoreMaterialCompositionMetrics, SessionError>
    where
        F: FnMut(&FileReference) -> Result<Vec<u8>, SessionError>,
    {
        if graph.quality != "full" {
            return Ok(PreviewCoreMaterialCompositionMetrics::default());
        }
        let jobs: Vec<_> = graph
            .materials
            .iter()
            .map(|material| {
                let mut composition = material.clone();
                // Runtime skin detail must not be baked a second time.
                if let Some(index) = runtime_skin_detail_layer(material, presentations, resources) {
                    composition.layers.remove(index);
                }
                Job {
                    key: cache_key(&composition, presentations, resources),
                    material: composition,
                }
            })
            .collect();
        let mut required = BTreeSet::new();
        for job in &jobs {
            if COMPLETED.with(|cache| cache.borrow_mut().get(&job.key).is_some()) {
                continue;
            }
            for (map, _) in maps() {
                if map_needs_composition(&job.material, resources, map) {
                    required.extend(
                        references_for_map(&job.material, map)
                            .iter()
                            .map(|reference| reference.sha256.trim().to_ascii_uppercase()),
                    );
                }
            }
        }
        // Even cache hits validate every source through the owning reader. A changed
        // or corrupt package must never be hidden by reusable finished pixels.
        let cache = ImageCache::preload(graph, &required, |reference| {
            crate::cdmw_session::check_preview_cancelled(cancelled)?;
            read_reference(reference)
        })?;
        let workers = std::thread::available_parallelism()
            .map_or(1, |count| count.get())
            .min(MAX_WORKERS);
        let mut remaining: BTreeSet<_> = jobs.iter().map(|job| job.key).collect();
        let mut first = 0;
        while first < jobs.len() {
            crate::cdmw_session::check_preview_cancelled(cancelled)?;
            // Pin only this batch's cache hits. Pinning every hit would retain evicted
            // entries and quietly defeat the cache's memory bound on large scenes.
            let mut ready = Vec::new();
            let mut bytes = 0_u64;
            for job in jobs.iter().skip(first).take(workers) {
                let hit = COMPLETED.with(|cache| cache.borrow_mut().get(&job.key));
                let estimate = if hit.is_some() {
                    0
                } else {
                    working_bytes(&job.material, resources, &cache)?
                };
                if !ready.is_empty() && bytes.saturating_add(estimate) > MAX_RESIZED_MATERIAL_BYTES {
                    break;
                }
                bytes = bytes.saturating_add(estimate);
                ready.push(hit);
            }
            let batch = &jobs[first..first + ready.len()];
            let stop = AtomicBool::new(false);
            let results = if batch.len() == 1 {
                vec![match ready.pop().flatten() {
                    Some(hit) => hit,
                    None => prepare(
                        &batch[0].material,
                        presentations,
                        resources,
                        cache.clone(),
                        cancelled,
                    )?,
                }]
            } else {
                std::thread::scope(|scope| -> Result<Vec<Completed>, SessionError> {
                    let (sender, receiver) = mpsc::channel();
                    let mut handles = Vec::new();
                    for (index, (job, hit)) in batch.iter().zip(&ready).enumerate() {
                        if hit.is_some() {
                            continue;
                        }
                        let sender = sender.clone();
                        let cache = cache.clone();
                        let resources = &*resources;
                        let stop = &stop;
                        let handle = std::thread::Builder::new()
                            .name("cdmw-material".into())
                            .spawn_scoped(scope, move || {
                                let result =
                                    prepare(&job.material, presentations, resources, cache, &|| {
                                        stop.load(Ordering::Relaxed)
                                    });
                                if result.is_err() {
                                    stop.store(true, Ordering::Relaxed);
                                }
                                let _ = sender.send((index, result));
                            })
                            .map_err(|error| {
                                stop.store(true, Ordering::Relaxed);
                                SessionError::InvalidPayload(format!(
                                    "Preview Core material worker could not start: {error}"
                                ))
                            })?;
                        handles.push(handle);
                    }
                    drop(sender);
                    let mut failure = None;
                    let mut pending = handles.len();
                    while pending > 0 {
                        if cancelled() {
                            stop.store(true, Ordering::Relaxed);
                        }
                        match receiver.recv_timeout(Duration::from_millis(10)) {
                            Ok((index, result)) => {
                                pending -= 1;
                                match result {
                                    Ok(maps) => ready[index] = Some(maps),
                                    Err(error) => {
                                        if failure.is_none()
                                            || !matches!(&error, SessionError::InvalidPayload(message) if message == "Preview load cancelled")
                                        {
                                            failure = Some(error);
                                        }
                                    }
                                }
                            }
                            Err(mpsc::RecvTimeoutError::Timeout) => {}
                            Err(mpsc::RecvTimeoutError::Disconnected) => break,
                        }
                    }
                    for handle in handles {
                        if handle.join().is_err() {
                            failure = Some(SessionError::InvalidPayload(
                                "Preview Core material worker failed".to_owned(),
                            ));
                        }
                    }
                    crate::cdmw_session::check_preview_cancelled(cancelled)?;
                    if let Some(error) = failure {
                        return Err(error);
                    }
                    ready
                        .into_iter()
                        .map(|entry| {
                            entry.ok_or_else(|| {
                                SessionError::InvalidPayload(
                                    "Preview Core material worker returned no result".to_owned(),
                                )
                            })
                        })
                        .collect()
                })?
            };
            for (job, result) in batch.iter().zip(results) {
                crate::cdmw_session::check_preview_cancelled(cancelled)?;
                for map in result.iter() {
                    publish_prepared_resource(
                        resources,
                        document,
                        &job.material,
                        map,
                        MAX_TEXTURE_TOTAL_BYTES,
                    )?;
                }
                remaining.remove(&job.key);
                // Keep not-yet-consumed hits resident: those sources were validated
                // without decoding. Skip insertion if every eviction is protected.
                COMPLETED.with(|cache| cache.borrow_mut().insert(job.key, result, &remaining));
            }
            first += batch.len();
        }
        resources.retain(|resource| {
            resource
                .material_indices_by_lod
                .iter()
                .any(|owners| !owners.is_empty())
        });
        Ok(cache.metrics)
    }

    #[cfg(test)]
    mod tests {
        use super::super::tests::{document, layer, reference};
        use super::*;
        use cdmw_texture::encode_rgba8_dds;
        use std::cell::Cell;

        fn fixture() -> (PreviewCoreMaterialGraph, BTreeMap<String, Vec<u8>>) {
            let mut files = BTreeMap::new();
            let mut refs = Vec::new();
            for seed in 0..5 {
                let pixels: Vec<_> = (0..32 * 16 * 4)
                    .map(|i| ((i * 37 + seed * 53) % 256) as u8)
                    .collect();
                let bytes = encode_rgba8_dds(32, 16, &pixels, TextureRole::Unknown).unwrap();
                let reference = reference(seed, &bytes);
                files.insert(reference.path.clone(), bytes);
                refs.push(reference);
            }
            let mut base = layer("base", "r");
            base.diffuse = Some(refs[0].clone());
            base.material = Some(refs[1].clone());
            base.normal = Some(refs[2].clone());
            base.height = Some(refs[3].clone());
            let mut detail = base.clone();
            detail.layer_role = "detail".into();
            detail.mask = Some(refs[4].clone());
            let materials = (0..8)
                .map(|index| {
                    let mut detail = detail.clone();
                    detail.weight = 0.1 + index as f32 * 0.1;
                    PreviewCoreMaterial {
                        lod_index: 0,
                        material_index: index,
                        material_slot_index: index,
                        material_name: format!("material-{index}"),
                        authoring_channels: 0,
                        base_color: [0.5; 3],
                        layers: vec![base.clone(), detail],
                    }
                })
                .collect();
            (
                PreviewCoreMaterialGraph {
                    schema_version: 1,
                    graph_version: 4,
                    semantics_version: 10,
                    quality: "full".into(),
                    resources_included: true,
                    source_edge_count: 72,
                    unique_resource_count: 5,
                    copied_resource_count: 5,
                    unique_resource_bytes: files.values().map(|bytes| bytes.len() as u64).sum(),
                    materials,
                },
                files,
            )
        }

        fn output(resources: &[CdmwTextureResource]) -> Vec<(u32, String, Vec<u8>)> {
            let mut result = Vec::new();
            for resource in resources {
                assert!(resource.metadata.mip_count > 1);
                for owner in &resource.material_indices_by_lod[0] {
                    result.push((
                        *owner,
                        role_label(resource.role).into(),
                        resource.bytes.clone(),
                    ));
                }
            }
            result.sort();
            result
        }

        #[test]
        fn parallel_and_cached_maps_match_serial_pixels_mips_and_owners() {
            COMPLETED.with(|cache| *cache.borrow_mut() = CompletedCache::default());
            let (graph, files) = fixture();
            let required = graph
                .materials
                .iter()
                .flat_map(|material| {
                    maps()
                        .into_iter()
                        .flat_map(move |(map, _)| references_for_map(material, map))
                })
                .map(|reference| reference.sha256.clone())
                .collect();
            let cache = ImageCache::preload(&graph, &required, |reference| {
                Ok(files[&reference.path].clone())
            })
            .unwrap();
            let mut serial = Vec::new();
            for material in &graph.materials {
                let result = prepare(material, &[], &[], cache.clone(), &|| false).unwrap();
                for map in result.iter() {
                    publish_prepared_resource(
                        &mut serial,
                        &document(),
                        material,
                        map,
                        MAX_TEXTURE_TOTAL_BYTES,
                    )
                    .unwrap();
                }
            }
            let expected = output(&serial);
            for expected_decodes in [5, 0] {
                let mut resources = Vec::new();
                let reads = Cell::new(0);
                let metrics = compose(
                    &graph,
                    &[],
                    &document(),
                    &mut resources,
                    &mut |reference| {
                        reads.set(reads.get() + 1);
                        Ok(files[&reference.path].clone())
                    },
                    &|| false,
                )
                .unwrap();
                assert_eq!(reads.get(), 5, "cached results still validate every binary");
                assert_eq!(metrics.source_dds_decode_count, expected_decodes);
                assert_eq!(output(&resources), expected);
            }
            let mut changed = graph.clone();
            changed.materials[0].layers[1].tint[0] = 0.2;
            let mut resources = Vec::new();
            let metrics = compose(
                &changed,
                &[],
                &document(),
                &mut resources,
                &mut |reference| Ok(files[&reference.path].clone()),
                &|| false,
            )
            .unwrap();
            assert_eq!(metrics.source_dds_decode_count, 5);
            assert_ne!(output(&resources), expected);
            assert_eq!(
                output(&resources)
                    .into_iter()
                    .filter(|row| row.0 != 0)
                    .collect::<Vec<_>>(),
                expected
                    .into_iter()
                    .filter(|row| row.0 != 0)
                    .collect::<Vec<_>>()
            );
            let error = compose(
                &graph,
                &[],
                &document(),
                &mut Vec::new(),
                &mut |_| Err(SessionError::InvalidPayload("source hash mismatch".into())),
                &|| false,
            )
            .unwrap_err();
            assert!(error.to_string().contains("source hash mismatch"));
        }

        #[test]
        fn direct_maps_validate_without_decoding_and_same_size_pixels_are_shared() {
            COMPLETED.with(|cache| *cache.borrow_mut() = CompletedCache::default());
            let (mut graph, files) = fixture();
            graph.materials.truncate(1);
            graph.materials[0].layers.truncate(1);
            graph.materials[0].layers[0].material = None;
            let mut resources = Vec::new();
            for (map, role) in maps() {
                if let Some(reference) = map.reference(&graph.materials[0].layers[0]) {
                    let bytes = files[&reference.path].clone();
                    resources.push(CdmwTextureResource {
                        label: reference.path.clone(),
                        role,
                        metadata: inspect_dds(&bytes, role).unwrap(),
                        bytes,
                        material_indices_by_lod: vec![vec![0]],
                    });
                }
            }
            let original: Vec<_> = resources
                .iter()
                .map(|resource| resource.bytes.clone())
                .collect();
            let metrics = compose(
                &graph,
                &[],
                &document(),
                &mut resources,
                &mut |reference| Ok(files[&reference.path].clone()),
                &|| false,
            )
            .unwrap();
            assert_eq!(metrics.source_dds_decode_count, 0);
            assert_eq!(metrics.unique_source_dds_count, 3);
            assert_eq!(
                original,
                resources
                    .iter()
                    .map(|resource| resource.bytes.clone())
                    .collect::<Vec<_>>()
            );
            let reference = graph.materials[0].layers[0].diffuse.as_ref().unwrap();
            let mut cache = ImageCache::preload(
                &graph,
                &BTreeSet::from([reference.sha256.clone()]),
                |reference| Ok(files[&reference.path].clone()),
            )
            .unwrap();
            let pixels = cache.resized(reference, 32, 16).unwrap();
            assert!(Arc::ptr_eq(&pixels.0, &cache.decoded[&reference.sha256]));
            assert_eq!(cache.resized_bytes, 0);
        }

        #[test]
        fn cached_material_invalidates_when_painted_input_changes() {
            COMPLETED.with(|cache| *cache.borrow_mut() = CompletedCache::default());
            let (mut graph, files) = fixture();
            graph.materials.truncate(1);
            graph.materials[0].authoring_channels = 1;
            for (alpha, expected_decodes) in [(24, 5), (201, 5), (201, 0)] {
                let bytes =
                    encode_rgba8_dds(1, 1, &[51, 92, 133, alpha], TextureRole::BaseColor).unwrap();
                let mut resources = vec![CdmwTextureResource {
                    label: "painted.dds".into(),
                    role: TextureRole::BaseColor,
                    metadata: inspect_dds(&bytes, TextureRole::BaseColor).unwrap(),
                    bytes,
                    material_indices_by_lod: vec![vec![0]],
                }];
                let metrics = compose(
                    &graph,
                    &[],
                    &document(),
                    &mut resources,
                    &mut |reference| Ok(files[&reference.path].clone()),
                    &|| false,
                )
                .unwrap();
                assert_eq!(metrics.source_dds_decode_count, expected_decodes);
                let base = resources
                    .iter()
                    .find(|resource| resource.role == TextureRole::BaseColor)
                    .unwrap();
                let image = decode_dds_rgba8(&base.bytes, base.role).unwrap();
                assert!(image.pixels.chunks_exact(4).all(|pixel| pixel[3] == alpha));
            }
        }

        #[test]
        fn cancellation_joins_workers_before_returning_without_publishing_a_batch() {
            COMPLETED.with(|cache| *cache.borrow_mut() = CompletedCache::default());
            let (graph, files) = fixture();
            let polls = Cell::new(0);
            let mut resources = Vec::new();
            let error = compose(
                &graph,
                &[],
                &document(),
                &mut resources,
                &mut |reference| Ok(files[&reference.path].clone()),
                &|| {
                    polls.set(polls.get() + 1);
                    polls.get() > 6
                },
            )
            .unwrap_err();
            assert!(error.to_string().contains("cancelled"));
            assert!(resources.is_empty());
            COMPLETED.with(|cache| assert!(cache.borrow().entries.is_empty()));
        }

        #[test]
        fn failed_material_joins_workers_and_does_not_publish_partial_maps() {
            COMPLETED.with(|cache| *cache.borrow_mut() = CompletedCache::default());
            let (mut graph, files) = fixture();
            graph.materials[0].authoring_channels = 1;
            let mut resources = Vec::new();
            let error = compose(
                &graph,
                &[],
                &document(),
                &mut resources,
                &mut |reference| Ok(files[&reference.path].clone()),
                &|| false,
            )
            .unwrap_err();
            assert!(
                error
                    .to_string()
                    .contains("requires one owned source texture")
            );
            assert!(resources.is_empty());
            COMPLETED.with(|cache| assert!(cache.borrow().entries.is_empty()));
        }

        #[test]
        fn completed_cache_bounds_entries_bytes_and_preserves_pending_hits() {
            let mut cache = CompletedCache::default();
            let empty = Arc::new(Vec::new());
            let mut protected = BTreeSet::new();
            for index in 0..COMPLETED_CACHE_ENTRIES {
                let mut key = [0; 32];
                key[..8].copy_from_slice(&(index as u64).to_le_bytes());
                cache.insert(key, Arc::clone(&empty), &protected);
                protected.insert(key);
            }
            cache.insert([255; 32], Arc::clone(&empty), &protected);
            assert_eq!(cache.entries.len(), COMPLETED_CACHE_ENTRIES);
            assert!(cache.get(&[255; 32]).is_none());
            cache.insert([255; 32], empty, &BTreeSet::new());
            assert!(cache.get(&[0; 32]).is_none());
            let mut large = ComposedMap::encode(
                TextureRole::BaseColor,
                DecodedRgba8 {
                    width: 1,
                    height: 1,
                    pixels: vec![128; 4],
                },
            )
            .unwrap();
            large.bytes.resize(COMPLETED_CACHE_BYTES + 1, 0);
            cache.insert([254; 32], Arc::new(vec![large]), &BTreeSet::new());
            assert!(cache.get(&[254; 32]).is_none());
            assert!(cache.bytes <= COMPLETED_CACHE_BYTES);
        }
    }
}


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

#[derive(Clone)]
struct ImagePixels(Arc<DecodedRgba8>);

impl std::ops::Deref for ImagePixels {
    type Target = [u8];

    fn deref(&self) -> &[u8] {
        &self.0.pixels
    }
}

#[derive(Default, Clone)]
struct ImageCache {
    decoded: Arc<BTreeMap<String, Arc<DecodedRgba8>>>,
    resized: BTreeMap<(String, u32, u32), ImagePixels>,
    resized_bytes: u64,
    metrics: PreviewCoreMaterialCompositionMetrics,
}

impl ImageCache {
    fn preload<F>(
        graph: &PreviewCoreMaterialGraph,
        required: &BTreeSet<String>,
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
            let metadata = inspect_dds(&bytes, TextureRole::Unknown)
                .map_err(|error| SessionError::InvalidPayload(error.to_string()))?;
            if !required.contains(&sha256) {
                continue;
            }
            // Check before allocating, including sources shared by several workers.
            let image_bytes = u64::from(metadata.width) * u64::from(metadata.height) * 4;
            if decoded_bytes.saturating_add(image_bytes) > MAX_DECODED_SOURCE_BYTES {
                return Err(SessionError::InvalidPayload(
                    "Preview Core decoded material sources exceed the 512 MiB limit".to_owned(),
                ));
            }
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
            decoded.insert(sha256, Arc::new(image));
        }
        Ok(Self {
            decoded: Arc::new(decoded),
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
            .map(AsRef::as_ref)
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
    ) -> Result<ImagePixels, SessionError> {
        let key = (reference.sha256.trim().to_ascii_uppercase(), width, height);
        if let Some(pixels) = self.resized.get(&key) {
            return Ok(pixels.clone());
        }
        let image = self.image(reference)?;
        if image.width == width && image.height == height {
            return Ok(ImagePixels(Arc::clone(&self.decoded[&key.0])));
        }
        let resized_bytes = u64::from(width) * u64::from(height) * 4;
        if self.resized_bytes.saturating_add(resized_bytes) > MAX_RESIZED_MATERIAL_BYTES {
            return Err(SessionError::InvalidPayload(
                "Preview Core resized material sources exceed the 512 MiB limit".to_owned(),
            ));
        }
        let resized = ImagePixels(Arc::new(DecodedRgba8 {
            width,
            height,
            pixels: resize_rgba8(image, width, height)?,
        }));
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
        self.resized.insert(key, resized.clone());
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
    work::compose(
        graph, presentations, document, resources, &mut read_reference, cancelled,
    )
}

fn apply_authored_channel(
    composed: &mut DecodedRgba8,
    resources: &[CdmwTextureResource],
    material: &PreviewCoreMaterial,
    role: TextureRole,
    channel: usize,
) -> Result<(), SessionError> {
    let sources: Vec<_> = resources.iter().filter(|resource| {
        resource.role == role && resource.material_indices_by_lod
            .get(material.lod_index as usize)
            .is_some_and(|owners| owners.contains(&material.material_index))
    }).collect();
    if sources.len() != 1 {
        return Err(SessionError::InvalidPayload("Painted material channel requires one owned source texture".to_owned()));
    }
    let authored = decode_dds_rgba8(&sources[0].bytes, role)
        .map_err(|error| SessionError::InvalidPayload(error.to_string()))?;
    let (width, height) = (composed.width.max(authored.width), composed.height.max(authored.height));
    checked_pixel_count(width, height)?;
    let mut pixels = resize_rgba8(composed, width, height)?;
    let authored = resize_rgba8(&authored, width, height)?;
    for (pixel, source) in pixels.chunks_exact_mut(4).zip(authored.chunks_exact(4)) {
        pixel[channel] = source[channel];
    }
    composed.width = width;
    composed.height = height;
    composed.pixels = pixels;
    Ok(())
}

fn map_needs_composition(
    material: &PreviewCoreMaterial,
    resources: &[CdmwTextureResource],
    map: LayerMap,
) -> bool {
    if !material.layers.iter().any(|layer| map.reference(layer).is_some()) {
        return false;
    }
    match map {
        LayerMap::Diffuse => {
            material.layers.iter().skip(1)
                .any(|layer| layer.layer_role == "color_seed" || layer.diffuse.is_some())
                || !material.layers.first().and_then(|layer| layer.diffuse.as_ref())
                    .is_some_and(|reference| {
                        resource_matches(resources, TextureRole::BaseColor, material, reference)
                    })
        }
        LayerMap::Material => true,
        LayerMap::Normal | LayerMap::Height => {
            let role = match map {
                LayerMap::Normal => TextureRole::Normal,
                _ => TextureRole::Height,
            };
            material.layers.iter().skip(1).any(|layer| map.reference(layer).is_some())
                || !resource_owns(resources, role, material.lod_index, material.material_index)
        }
    }
}

fn compose_base_color(
    material: &PreviewCoreMaterial,
    resources: &[CdmwTextureResource],
    cache: &mut ImageCache,
) -> Result<Option<DecodedRgba8>, SessionError> {
    if !map_needs_composition(material, resources, LayerMap::Diffuse) {
        // Preserve authored compression, full resolution and mip filtering.
        return Ok(None);
    }
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
    let mut masks: [Option<ImagePixels>; 3] = [None, None, None];
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
    if !map_needs_composition(material, resources, LayerMap::Normal) {
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
    if !map_needs_composition(material, resources, LayerMap::Height) {
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

fn resource_matches(
    resources: &[CdmwTextureResource],
    role: TextureRole,
    material: &PreviewCoreMaterial,
    reference: &FileReference,
) -> bool {
    usize::try_from(material.lod_index).ok().is_some_and(|lod| {
        resources.iter().any(|resource| {
            resource.role == role
                && resource
                    .metadata
                    .source_sha256
                    .eq_ignore_ascii_case(&reference.sha256)
                && resource
                    .material_indices_by_lod
                    .get(lod)
                    .is_some_and(|owners| owners.contains(&material.material_index))
        })
    })
}

fn runtime_skin_detail_layer(
    material: &PreviewCoreMaterial,
    presentations: &[SessionMaterialPresentation],
    resources: &[CdmwTextureResource],
) -> Option<usize> {
    let presentation = presentations.iter().find(|row| {
        row.lod_index == material.lod_index && row.material_index == material.material_index
    })?;
    let scale = presentation.skin_detail_scale?;
    let opacity = presentation.skin_detail_opacity?;
    let mut layers = material
        .layers
        .iter()
        .enumerate()
        .filter(|(_, layer)| layer.layer_role == "skin_detail");
    let (index, layer) = layers.next()?;
    if layers.next().is_some()
        || index == 0
        || scale <= 0.0
        || (scale - layer.detail_scale).abs() > 0.000_001
        || (opacity - layer.weight).abs() > 0.000_001
        || layer.mask_channel != "r"
        || layer.diffuse.is_some()
        || layer.diffuse_declared
        || layer.height.is_some()
        || layer.height_declared
        || ![&layer.source_parameter, &layer.mask_parameter]
            .iter()
            .any(|name| TextureRole::from_parameter_name(name) == TextureRole::SkinDetailMask)
    {
        return None;
    }
    [
        (TextureRole::SkinDetailMask, layer.mask.as_ref()),
        (TextureRole::SkinDetailNormal, layer.normal.as_ref()),
        (TextureRole::SkinDetailMaterial, layer.material.as_ref()),
    ]
    .into_iter()
    .all(|(role, reference)| {
        reference.is_some_and(|reference| resource_matches(resources, role, material, reference))
    })
    .then_some(index)
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

#[cfg(test)]
fn publish_composed_resource(
    resources: &mut Vec<CdmwTextureResource>,
    document: &MeshDocument,
    material: &PreviewCoreMaterial,
    role: TextureRole,
    image: DecodedRgba8,
    max_bytes: u64,
) -> Result<(), SessionError> {
    let prepared = work::ComposedMap::encode(role, image)?;
    publish_prepared_resource(resources, document, material, &prepared, max_bytes)
}

fn publish_prepared_resource(
    resources: &mut Vec<CdmwTextureResource>,
    document: &MeshDocument,
    material: &PreviewCoreMaterial,
    prepared: &work::ComposedMap,
    max_bytes: u64,
) -> Result<(), SessionError> {
    let role = prepared.role;
    let bytes = &prepared.bytes;
    let metadata = &prepared.metadata;
    let lod_index = usize::try_from(material.lod_index).map_err(|_| {
        SessionError::InvalidManifest("Preview Core material LOD exceeds this platform".to_owned())
    })?;
    if lod_index >= document.lods.len() {
        return Err(SessionError::InvalidManifest(
            "Preview Core composed texture ownership LOD is invalid".to_owned(),
        ));
    }
    let existing_index = resources.iter().position(|resource| {
        resource.role == role
            && resource.metadata.source_sha256 == metadata.source_sha256
            && resource.bytes == *bytes
    });
    if let Some(index) = existing_index
        && resources[index]
            .material_indices_by_lod
            .get(lod_index)
            .is_none()
    {
        return Err(SessionError::InvalidManifest(
            "Preview Core composed texture ownership LOD is invalid".to_owned(),
        ));
    }
    // Include input and generated DDS bytes, counting a deduplicated output
    // once and reclaiming only sources whose final owner this output replaces.
    // Encoding is individually bounded; reject before changing existing owners.
    let mut retained_bytes = if existing_index.is_none() {
        bytes.len() as u64
    } else {
        0
    };
    for (index, resource) in resources.iter().enumerate() {
        let retained = Some(index) == existing_index
            || resource
                .material_indices_by_lod
                .iter()
                .enumerate()
                .any(|(lod, owners)| {
                    owners.iter().any(|owner| {
                        resource.role != role
                            || lod != lod_index
                            || *owner != material.material_index
                    })
                });
        if retained {
            retained_bytes = retained_bytes.saturating_add(resource.bytes.len() as u64);
        }
    }
    if retained_bytes > max_bytes {
        return Err(SessionError::InvalidPayload(
            "Preview Core composed resources exceed the total texture byte safety limit".to_owned(),
        ));
    }
    for resource in resources
        .iter_mut()
        .filter(|resource| resource.role == role)
    {
        if let Some(owners) = resource.material_indices_by_lod.get_mut(lod_index) {
            owners.retain(|owner| *owner != material.material_index);
        }
    }
    if let Some(index) = existing_index {
        let owners = resources[index]
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
    } else {
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
            metadata: metadata.clone(),
            bytes: bytes.clone(),
            material_indices_by_lod,
        });
    }
    resources.retain(|resource| {
        resource
            .material_indices_by_lod
            .iter()
            .any(|owners| !owners.is_empty())
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
    use cdmw_texture::encode_rgba8_dds;
    use sha2::{Digest, Sha256};
    use std::cell::Cell;

    pub(super) fn reference(name_index: u32, bytes: &[u8]) -> FileReference {
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

    pub(super) fn layer(role: &str, channel: &str) -> PreviewCoreMaterialLayer {
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

    pub(super) fn document() -> MeshDocument {
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
                    shader_masks: Vec::new(),
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
    fn composed_resource_budget_counts_inputs_deduplication_and_replacements() {
        let mut document = document();
        let submesh = document.lods[0].submeshes[0].clone();
        document.lods[0].submeshes.resize(3, submesh);
        let mut material = PreviewCoreMaterial {
            authoring_channels: 0,
            lod_index: 0,
            material_index: 0,
            material_slot_index: 0,
            material_name: "test".to_owned(),
            base_color: [1.0; 3],
            layers: vec![layer("base", "r")],
        };
        let image = |red| DecodedRgba8 {
            width: 2,
            height: 2,
            pixels: [red, 0, 0, 255].repeat(4),
        };
        let encoded =
            encode_rgba8_mipmapped_dds(2, 2, &image(0).pixels, TextureRole::BaseColor).unwrap();
        let texture_bytes = encoded.len() as u64;
        let limit = texture_bytes * 2;
        // An existing authored texture consumes the same budget as baked output.
        let mut resources = vec![CdmwTextureResource {
            label: "authored.dds".to_owned(),
            role: TextureRole::Normal,
            metadata: inspect_dds(&encoded, TextureRole::Normal).unwrap(),
            bytes: encoded,
            material_indices_by_lod: vec![vec![0]],
        }];
        publish_composed_resource(
            &mut resources,
            &document,
            &material,
            TextureRole::BaseColor,
            image(16),
            limit,
        )
        .unwrap();
        assert_eq!(
            resources.iter().map(|r| r.bytes.len() as u64).sum::<u64>(),
            limit
        );
        material.material_index = 1;
        let before = resources.clone();
        let error = publish_composed_resource(
            &mut resources,
            &document,
            &material,
            TextureRole::BaseColor,
            image(32),
            limit,
        )
        .unwrap_err();
        assert!(
            error
                .to_string()
                .contains("total texture byte safety limit")
        );
        assert_eq!(resources.len(), before.len());
        for (actual, original) in resources.iter().zip(&before) {
            assert_eq!(actual.bytes, original.bytes);
            assert_eq!(
                actual.material_indices_by_lod,
                original.material_indices_by_lod
            );
        }
        // Sharing the existing composed payload costs no additional bytes.
        publish_composed_resource(
            &mut resources,
            &document,
            &material,
            TextureRole::BaseColor,
            image(16),
            limit,
        )
        .unwrap();
        assert_eq!(resources.len(), 2);
        assert_eq!(resources[1].material_indices_by_lod, vec![vec![0, 1]]);
        // Replacing one owner cannot reclaim the other owner's texture.
        material.material_index = 0;
        assert!(
            publish_composed_resource(
                &mut resources,
                &document,
                &material,
                TextureRole::BaseColor,
                image(32),
                limit
            )
            .is_err()
        );
        assert_eq!(resources[1].material_indices_by_lod, vec![vec![0, 1]]);
        // A sole owner's previous payload is reclaimed immediately.
        resources[1].material_indices_by_lod[0] = vec![0];
        publish_composed_resource(
            &mut resources,
            &document,
            &material,
            TextureRole::BaseColor,
            image(32),
            limit,
        )
        .unwrap();
        assert_eq!(resources.len(), 2);
        assert_eq!(
            resources.iter().map(|r| r.bytes.len() as u64).sum::<u64>(),
            limit
        );
        assert_eq!(
            decode_dds_rgba8(&resources[1].bytes, TextureRole::BaseColor)
                .unwrap()
                .pixels,
            image(32).pixels
        );
    }

    #[test]
    fn composed_resource_failure_does_not_remove_existing_owners() {
        let document = document();
        let material = PreviewCoreMaterial {
            authoring_channels: 0,
            lod_index: 0,
            material_index: 0,
            material_slot_index: 0,
            material_name: "test".to_owned(),
            base_color: [1.0; 3],
            layers: vec![],
        };
        let mut resources = Vec::new();
        publish_composed_resource(
            &mut resources,
            &document,
            &material,
            TextureRole::BaseColor,
            DecodedRgba8 {
                width: 1,
                height: 1,
                pixels: vec![255; 4],
            },
            MAX_TEXTURE_TOTAL_BYTES,
        )
        .unwrap();
        let original = resources.clone();
        assert!(
            publish_composed_resource(
                &mut resources,
                &document,
                &material,
                TextureRole::BaseColor,
                DecodedRgba8 {
                    width: 2,
                    height: 2,
                    pixels: vec![]
                },
                MAX_TEXTURE_TOTAL_BYTES
            )
            .is_err()
        );
        assert_eq!(resources.len(), original.len());
        assert_eq!(resources[0].bytes, original[0].bytes);
        assert_eq!(
            resources[0].material_indices_by_lod,
            original[0].material_indices_by_lod
        );
    }

    #[test]
    fn authored_channels_survive_full_graph_composition_without_changing_other_owners() {
        let source = encode_rgba8_mipmapped_dds(2, 2, &[32, 90, 170, 220].repeat(4), TextureRole::Material).unwrap();
        let original = reference(0, &source);
        let mut base = layer("base", "r");
        base.diffuse = Some(original.clone());
        base.material = Some(original);
        let mut graph = PreviewCoreMaterialGraph {
            schema_version: 1, graph_version: 4, semantics_version: 10,
            quality: "full".to_owned(), resources_included: true, source_edge_count: 2,
            unique_resource_count: 1, copied_resource_count: 0, unique_resource_bytes: source.len() as u64,
            materials: vec![PreviewCoreMaterial {
                lod_index: 0, material_index: 0, material_slot_index: 0,
                material_name: "test".to_owned(), base_color: [1.0; 3], layers: vec![base], authoring_channels: 0,
            }],
        };
        let painted_pixels = [201, 1, 2, 17, 3, 1, 2, 239].repeat(4);
        let mut inputs = Vec::new();
        for role in [TextureRole::BaseColor, TextureRole::Material] {
            let bytes = encode_rgba8_mipmapped_dds(4, 2, &painted_pixels, role).unwrap();
            inputs.push(CdmwTextureResource {
                label: "owned paint".to_owned(), role, metadata: inspect_dds(&bytes, role).unwrap(),
                bytes, material_indices_by_lod: vec![vec![0, 1]],
            });
        }
        let mut baseline = inputs.clone();
        compose_preview_core_material_resources(&graph, &[], &document(), &mut baseline, |_| Ok(source.clone())).unwrap();
        graph.materials[0].authoring_channels = 3;
        let mut painted = inputs.clone();
        compose_preview_core_material_resources(&graph, &[], &document(), &mut painted, |_| Ok(source.clone())).unwrap();
        for (role, channel) in [(TextureRole::BaseColor, 3), (TextureRole::Material, 0)] {
            let owned = |resources: &[CdmwTextureResource]| {
                let resource = resources.iter().find(|row| row.role == role && row.material_indices_by_lod[0].contains(&0)).unwrap();
                decode_dds_rgba8(&resource.bytes, role).unwrap()
            };
            let actual = owned(&painted);
            assert_eq!((actual.width, actual.height), (4, 2));
            let expected = resize_rgba8(&owned(&baseline), 4, 2).unwrap();
            for ((pixel, composed), authored) in actual.pixels.chunks_exact(4).zip(expected.chunks_exact(4)).zip(painted_pixels.chunks_exact(4)) {
                for lane in 0..4 { assert_eq!(pixel[lane], if lane == channel { authored[lane] } else { composed[lane] }); }
            }
            let untouched = painted.iter().find(|row| row.role == role && row.material_indices_by_lod[0] == vec![1]).unwrap();
            assert_eq!(untouched.bytes, inputs.iter().find(|row| row.role == role).unwrap().bytes);
        }
        let mut image = DecodedRgba8 { width: 1, height: 1, pixels: vec![255; 4] };
        assert!(apply_authored_channel(&mut image, &[], &graph.materials[0], TextureRole::Material, 0).is_err());
    }

    #[test]
    fn runtime_skin_detail_preserves_original_dds_mips_and_owner_bindings() {
        let roles = [
            TextureRole::BaseColor,
            TextureRole::Normal,
            TextureRole::SkinDetailMask,
            TextureRole::SkinDetailNormal,
            TextureRole::SkinDetailMaterial,
        ];
        let mut resources = Vec::new();
        let mut references = Vec::new();
        let mut files = BTreeMap::new();
        for (index, role) in roles.into_iter().enumerate() {
            let pixels = [128, 128, 255, 255].repeat(8 * 4);
            let bytes = encode_rgba8_mipmapped_dds(8, 4, &pixels, role).expect("DDS");
            let file = reference(index as u32, &bytes);
            resources.push(CdmwTextureResource {
                label: file.path.clone(),
                role,
                metadata: inspect_dds(&bytes, role).expect("DDS metadata"),
                bytes: bytes.clone(),
                material_indices_by_lod: vec![vec![0]],
            });
            files.insert(file.path.clone(), bytes);
            references.push(file);
        }
        let mut base = layer("base", "r");
        base.diffuse = Some(references[0].clone());
        base.normal = Some(references[1].clone());
        let mut skin = layer("skin_detail", "r");
        skin.source_parameter = "_skinDetailMaskTexture".to_owned();
        skin.mask_parameter = skin.source_parameter.clone();
        skin.detail_scale = 0.015;
        skin.weight = 0.74;
        skin.mask = Some(references[2].clone());
        skin.normal = Some(references[3].clone());
        skin.material = Some(references[4].clone());
        let graph = PreviewCoreMaterialGraph {
            schema_version: 1,
            graph_version: 4,
            semantics_version: 10,
            quality: "full".to_owned(),
            resources_included: true,
            source_edge_count: 5,
            unique_resource_count: 2,
            copied_resource_count: 0,
            unique_resource_bytes: 0,
            materials: vec![PreviewCoreMaterial {
                lod_index: 0,
                material_index: 0,
                material_slot_index: 7,
                authoring_channels: 0,
                material_name: "skin".to_owned(),
                base_color: [1.0; 3],
                layers: vec![base, skin],
            }],
        };
        let presentation: SessionMaterialPresentation = serde_json::from_value(serde_json::json!({
            "lod_index": 0, "material_index": 0, "material_slot_index": 7,
            "material_category": "skin", "category_code": 5, "category_confidence": 1.0,
            "shader_family": "SkinnedMeshSkin", "normal_y_policy": "preserve",
            "normal_y_inverted": false, "alpha_mode": "opaque", "double_sided": false,
            "hair_anisotropy": false, "skin_detail_scale": 0.015, "skin_detail_opacity": 0.74,
        }))
        .expect("presentation");
        let material = &graph.materials[0];
        assert_eq!(
            runtime_skin_detail_layer(material, std::slice::from_ref(&presentation), &resources),
            Some(1)
        );
        let original = resources.clone();
        compose_preview_core_material_resources(
            &graph,
            std::slice::from_ref(&presentation),
            &document(),
            &mut resources,
            |reference| Ok(files.get(&reference.path).expect("source").clone()),
        )
        .expect("compose");
        assert_eq!(resources.len(), original.len());
        for (actual, expected) in resources.iter().zip(&original) {
            assert_eq!(actual.bytes, expected.bytes);
            assert_eq!(
                actual.material_indices_by_lod,
                expected.material_indices_by_lod
            );
            assert_eq!(actual.metadata.mip_count, 4);
        }
        // A different owner or payload cannot authorize skipping a graph layer.
        resources[4].material_indices_by_lod = vec![vec![1]];
        assert_eq!(
            runtime_skin_detail_layer(material, std::slice::from_ref(&presentation), &resources),
            None
        );
        resources[4] = original[4].clone();
        resources[4].metadata.source_sha256 = "0".repeat(64);
        assert_eq!(
            runtime_skin_detail_layer(material, std::slice::from_ref(&presentation), &resources),
            None
        );
        let mut missing_factors = presentation.clone();
        missing_factors.skin_detail_scale = None;
        assert_eq!(
            runtime_skin_detail_layer(material, &[missing_factors], &original),
            None
        );
        let mut extra_layer = material.clone();
        extra_layer.layers.push(extra_layer.layers[1].clone());
        assert_eq!(
            runtime_skin_detail_layer(&extra_layer, &[presentation], &original),
            None
        );
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
                authoring_channels: 0,
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
        assert_eq!(color.metadata.mip_count, 2);
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
        assert_eq!(surface.metadata.mip_count, 2);
        let surface = decode_dds_rgba8(&surface.bytes, TextureRole::Material)
            .expect("decode composed response");
        assert!(
            surface.pixels[2] > 190 && surface.pixels[6] > 190,
            "packed response was {:?}",
            surface.pixels
        );
    }
}
