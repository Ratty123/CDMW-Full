use cdmw_archive::{
    ArchiveCatalog, ArchiveLimits, CancellationToken, CatalogProgress, CompressionOutcome,
    DecodedEntry, open_archive_root, read_entry_unverified,
};
use cdmw_asset_graph::{AssetIndex, AssetRelation, RelationKind, ResolutionMethod};
use cdmw_formats::{MeshDocument, MeshFormat, decode_mesh};
use cdmw_mesh::WorkingMesh;
use cdmw_oracle::export_working_obj_cancellable;
use cdmw_texture::{
    DDS_MAX_PAYLOAD_BYTES, DdsMetadata, MATERIAL_SIDECAR_MAX_BYTES, MaterialParameter,
    MaterialParameterKind, MaterialSidecar, MaterialTextureReference, TextureRole, inspect_dds,
    parse_material_sidecar,
};
use crossbeam_channel::{Receiver, Sender, TrySendError, bounded};
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Component, Path, PathBuf};
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};
use std::thread;
use thiserror::Error;

#[derive(Debug)]
pub struct LoadedMesh {
    pub path: PathBuf,
    pub document: MeshDocument,
    pub mesh: WorkingMesh,
    pub other_lod_meshes: Vec<WorkingMesh>,
    pub textures: Vec<LoadedTexture>,
    pub material_parameters: Vec<LoadedMaterialParameter>,
    pub material_factors: Vec<LoadedMaterialFactors>,
}

#[derive(Debug)]
pub struct LoadedTexture {
    pub label: String,
    pub metadata: DdsMetadata,
    pub bytes: Vec<u8>,
    pub role: TextureRole,
    pub requested_reference: String,
    pub parameter_name: Option<String>,
    pub sidecar_label: Option<String>,
    pub resolution_method: ResolutionMethod,
    pub archive_compression: Option<CompressionOutcome>,
    pub material_indices_by_lod: Vec<Vec<u32>>,
}

#[derive(Debug, Clone)]
pub struct LoadedMaterialParameter {
    pub sidecar_label: String,
    pub parameter: MaterialParameter,
    pub material_indices_by_lod: Vec<Vec<u32>>,
    pub preview_semantic: Option<&'static str>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct LoadedMaterialFactors {
    pub sidecar_label: String,
    pub emissive_color: Option<[f32; 3]>,
    pub emissive_intensity: Option<f32>,
    pub roughness: Option<f32>,
    pub metalness: Option<f32>,
    pub specular: Option<f32>,
    pub material_indices_by_lod: Vec<Vec<u32>>,
}

#[derive(Debug, Default)]
struct TextureLoadResult {
    textures: Vec<LoadedTexture>,
    material_parameters: Vec<LoadedMaterialParameter>,
    material_factors: Vec<LoadedMaterialFactors>,
    warnings: Vec<String>,
}

#[derive(Debug)]
pub enum LoadEvent {
    Progress {
        generation: u64,
        progress: CatalogProgress,
    },
    Mesh {
        generation: u64,
        result: Box<Result<LoadedMesh, String>>,
    },
    Archive {
        generation: u64,
        result: Result<Arc<ArchiveCatalog>, String>,
    },
    Query {
        generation: u64,
        indices: Vec<usize>,
        total_matches: usize,
    },
    Export {
        generation: u64,
        result: Result<PathBuf, String>,
    },
}

#[derive(Debug, Error)]
pub enum LoaderError {
    #[error("the bounded loader queue is busy")]
    Busy,
    #[error("the loader worker is no longer available")]
    Disconnected,
}

enum LoadRequest {
    Mesh {
        generation: u64,
        path: PathBuf,
        cancellation: Arc<CancellationToken>,
    },
    Archive {
        generation: u64,
        root: PathBuf,
        cancellation: Arc<CancellationToken>,
    },
    ArchiveMesh {
        generation: u64,
        catalog: Arc<ArchiveCatalog>,
        entry_index: usize,
        cancellation: Arc<CancellationToken>,
    },
    Query {
        generation: u64,
        catalog: Arc<ArchiveCatalog>,
        query: String,
        cancellation: Arc<CancellationToken>,
    },
    Export {
        generation: u64,
        mesh: Box<WorkingMesh>,
        destination: PathBuf,
        cancellation: Arc<CancellationToken>,
    },
    Shutdown,
}

pub struct Loader {
    requests: Sender<LoadRequest>,
    events: Receiver<LoadEvent>,
    current_generation: Arc<AtomicU64>,
    active_cancellation: Option<Arc<CancellationToken>>,
}

impl Loader {
    pub fn start() -> Self {
        let (requests, request_receiver) = bounded(2);
        let (event_sender, events) = bounded(8);
        let current_generation = Arc::new(AtomicU64::new(0));
        let worker_generation = current_generation.clone();
        thread::Builder::new()
            .name("cdmw-rust-mesh-loader".to_owned())
            .spawn(move || worker_loop(request_receiver, event_sender, worker_generation))
            .ok();
        Self {
            requests,
            events,
            current_generation,
            active_cancellation: None,
        }
    }

    pub fn load_mesh(&mut self, path: PathBuf) -> Result<u64, LoaderError> {
        self.submit(|generation, cancellation| LoadRequest::Mesh {
            generation,
            path,
            cancellation,
        })
    }

    pub fn open_archive(&mut self, root: PathBuf) -> Result<u64, LoaderError> {
        self.submit(|generation, cancellation| LoadRequest::Archive {
            generation,
            root,
            cancellation,
        })
    }

    pub fn load_archive_mesh(
        &mut self,
        catalog: Arc<ArchiveCatalog>,
        entry_index: usize,
    ) -> Result<u64, LoaderError> {
        self.submit(|generation, cancellation| LoadRequest::ArchiveMesh {
            generation,
            catalog,
            entry_index,
            cancellation,
        })
    }

    pub fn query_archive(
        &mut self,
        catalog: Arc<ArchiveCatalog>,
        query: String,
    ) -> Result<u64, LoaderError> {
        self.submit(|generation, cancellation| LoadRequest::Query {
            generation,
            catalog,
            query,
            cancellation,
        })
    }

    pub fn export_obj(
        &mut self,
        mesh: WorkingMesh,
        destination: PathBuf,
    ) -> Result<u64, LoaderError> {
        self.submit(|generation, cancellation| LoadRequest::Export {
            generation,
            mesh: Box::new(mesh),
            destination,
            cancellation,
        })
    }

    pub fn try_events(&self) -> impl Iterator<Item = LoadEvent> + '_ {
        self.events.try_iter()
    }

    fn submit(
        &mut self,
        request: impl FnOnce(u64, Arc<CancellationToken>) -> LoadRequest,
    ) -> Result<u64, LoaderError> {
        if let Some(token) = self.active_cancellation.take() {
            token.cancel();
        }
        let generation = self
            .current_generation
            .fetch_add(1, Ordering::AcqRel)
            .saturating_add(1);
        let cancellation = Arc::new(CancellationToken::default());
        match self
            .requests
            .try_send(request(generation, cancellation.clone()))
        {
            Ok(()) => {
                self.active_cancellation = Some(cancellation);
                Ok(generation)
            }
            Err(TrySendError::Full(_)) => Err(LoaderError::Busy),
            Err(TrySendError::Disconnected(_)) => Err(LoaderError::Disconnected),
        }
    }
}

impl Drop for Loader {
    fn drop(&mut self) {
        if let Some(token) = self.active_cancellation.take() {
            token.cancel();
        }
        let _ = self.requests.try_send(LoadRequest::Shutdown);
    }
}

fn worker_loop(
    requests: Receiver<LoadRequest>,
    events: Sender<LoadEvent>,
    current_generation: Arc<AtomicU64>,
) {
    while let Ok(request) = requests.recv() {
        match request {
            LoadRequest::Shutdown => break,
            LoadRequest::Mesh {
                generation,
                path,
                cancellation,
            } => {
                let result = load_mesh(path, &cancellation);
                if current_generation.load(Ordering::Acquire) == generation {
                    let _ = events.send(LoadEvent::Mesh {
                        generation,
                        result: Box::new(result),
                    });
                }
            }
            LoadRequest::Archive {
                generation,
                root,
                cancellation,
            } => {
                let progress_events = events.clone();
                let current = current_generation.clone();
                let result =
                    open_archive_root(&root, ArchiveLimits::default(), &cancellation, |progress| {
                        if current.load(Ordering::Acquire) == generation {
                            let _ = progress_events.try_send(LoadEvent::Progress {
                                generation,
                                progress,
                            });
                        }
                    })
                    .map(Arc::new)
                    .map_err(|error| error.to_string());
                if current_generation.load(Ordering::Acquire) == generation {
                    let _ = events.send(LoadEvent::Archive { generation, result });
                }
            }
            LoadRequest::ArchiveMesh {
                generation,
                catalog,
                entry_index,
                cancellation,
            } => {
                let result = load_archive_mesh(&catalog, entry_index, &cancellation);
                if current_generation.load(Ordering::Acquire) == generation {
                    let _ = events.send(LoadEvent::Mesh {
                        generation,
                        result: Box::new(result),
                    });
                }
            }
            LoadRequest::Query {
                generation,
                catalog,
                query,
                cancellation,
            } => {
                let normalized = query.replace('\\', "/").to_ascii_lowercase();
                let mut indices = Vec::new();
                let mut total_matches = 0_usize;
                for (index, entry) in catalog.entries.iter().enumerate() {
                    if index.is_multiple_of(4_096) && cancellation.check().is_err() {
                        break;
                    }
                    if normalized.is_empty()
                        || entry
                            .entry
                            .virtual_path
                            .to_ascii_lowercase()
                            .contains(&normalized)
                    {
                        total_matches = total_matches.saturating_add(1);
                        if indices.len() < 20_000 {
                            indices.push(index);
                        }
                    }
                }
                if current_generation.load(Ordering::Acquire) == generation {
                    let _ = events.send(LoadEvent::Query {
                        generation,
                        indices,
                        total_matches,
                    });
                }
            }
            LoadRequest::Export {
                generation,
                mesh,
                destination,
                cancellation,
            } => {
                let result = cancellation
                    .check()
                    .map_err(|error| error.to_string())
                    .and_then(|()| {
                        export_working_obj_cancellable(&destination, &mesh, || {
                            cancellation.check().is_err()
                        })
                        .map(|_| destination)
                        .map_err(|error| error.to_string())
                    });
                if current_generation.load(Ordering::Acquire) == generation {
                    let _ = events.send(LoadEvent::Export { generation, result });
                }
            }
        }
    }
}

fn load_archive_mesh(
    catalog: &ArchiveCatalog,
    entry_index: usize,
    cancellation: &CancellationToken,
) -> Result<LoadedMesh, String> {
    let catalog_entry = catalog
        .entries
        .get(entry_index)
        .ok_or_else(|| "archive selection is stale".to_owned())?;
    let payload_root = catalog
        .indexes
        .get(catalog_entry.index_id)
        .ok_or_else(|| "archive selection references a missing index".to_owned())?
        .parent()
        .ok_or_else(|| "archive index has no payload directory".to_owned())?;
    let decoded = read_entry_unverified(
        payload_root,
        &catalog_entry.entry,
        ArchiveLimits::default(),
        cancellation,
    )
    .map_err(|error| error.to_string())?;
    let path = PathBuf::from(&catalog_entry.entry.virtual_path);
    let format = MeshFormat::from_path(&path).map_err(|error| error.to_string())?;
    let mut document = decode_mesh(&decoded.bytes, format).map_err(|error| error.to_string())?;
    let mut lod_meshes = build_lod_meshes(&document, cancellation)?.into_iter();
    let mesh = lod_meshes
        .next()
        .ok_or_else(|| "decoded document has no editable LOD".to_owned())?;
    let other_lod_meshes = lod_meshes.collect();
    let texture_result = resolve_archive_texture(catalog, catalog_entry, &document, cancellation)?;
    document.warnings.extend(texture_result.warnings);
    Ok(LoadedMesh {
        path,
        document,
        mesh,
        other_lod_meshes,
        textures: texture_result.textures,
        material_parameters: texture_result.material_parameters,
        material_factors: texture_result.material_factors,
    })
}

fn load_mesh(path: PathBuf, cancellation: &CancellationToken) -> Result<LoadedMesh, String> {
    cancellation.check().map_err(|error| error.to_string())?;
    let format = MeshFormat::from_path(&path).map_err(|error| error.to_string())?;
    let bytes =
        fs::read(&path).map_err(|error| format!("failed to read {}: {error}", path.display()))?;
    cancellation.check().map_err(|error| error.to_string())?;
    let mut document = decode_mesh(&bytes, format).map_err(|error| error.to_string())?;
    cancellation.check().map_err(|error| error.to_string())?;
    let mut lod_meshes = build_lod_meshes(&document, cancellation)?.into_iter();
    let mesh = lod_meshes
        .next()
        .ok_or_else(|| "decoded document has no editable LOD".to_owned())?;
    let other_lod_meshes = lod_meshes.collect();
    let texture_result = resolve_direct_texture(&path, &document)?;
    document.warnings.extend(texture_result.warnings);
    Ok(LoadedMesh {
        path,
        document,
        mesh,
        other_lod_meshes,
        textures: texture_result.textures,
        material_parameters: texture_result.material_parameters,
        material_factors: texture_result.material_factors,
    })
}

pub(super) fn build_lod_meshes(
    document: &MeshDocument,
    cancellation: &CancellationToken,
) -> Result<Vec<WorkingMesh>, String> {
    let mut meshes = Vec::with_capacity(document.lods.len());
    for lod_index in 0..document.lods.len() {
        cancellation.check().map_err(|error| error.to_string())?;
        meshes.push(
            WorkingMesh::from_document_lod(document, lod_index).map_err(|error| {
                format!(
                    "LOD {} is not editable: {error}",
                    document.lods[lod_index].level
                )
            })?,
        );
    }
    cancellation.check().map_err(|error| error.to_string())?;
    Ok(meshes)
}

fn resolve_direct_texture(
    mesh_path: &Path,
    document: &MeshDocument,
) -> Result<TextureLoadResult, String> {
    let mut result = TextureLoadResult::default();
    let sidecars = direct_material_sidecars(mesh_path);
    if sidecars.len() > 1 {
        result.warnings.push(format!(
            "More than one same-stem material sidecar exists for {}; no texture was selected",
            mesh_path.display()
        ));
        return Ok(result);
    }
    if let Some(sidecar_path) = sidecars.first() {
        let sidecar_bytes = match read_bounded_file(
            sidecar_path,
            MATERIAL_SIDECAR_MAX_BYTES,
            "material sidecar",
        ) {
            Ok(bytes) => bytes,
            Err(error) => {
                result.warnings.push(format!(
                    "Material sidecar {} could not be read: {error}; viewport keeps the material approximation",
                    sidecar_path.display()
                ));
                return Ok(result);
            }
        };
        let sidecar = match parse_material_sidecar(&sidecar_bytes) {
            Ok(sidecar) => sidecar,
            Err(error) => {
                result.warnings.push(format!(
                    "Material sidecar {} could not be parsed: {error}; viewport keeps the material approximation",
                    sidecar_path.display()
                ));
                return Ok(result);
            }
        };
        result.warnings.extend(
            sidecar
                .warnings
                .iter()
                .map(|warning| format!("Material sidecar {}: {warning}", sidecar_path.display())),
        );
        let sidecar_label = sidecar_path.to_string_lossy().replace('\\', "/");
        let (material_parameters, material_factors) =
            resolve_material_parameters(&sidecar, document, &sidecar_label, &mut result.warnings);
        result.material_parameters = material_parameters;
        result.material_factors = material_factors;
        let references = owned_preview_texture_references(&sidecar, document, &mut result.warnings);
        if references.is_empty() {
            result.warnings.push(format!(
                "Material sidecar {} has no unambiguous sampled-texture ownership; viewport keeps the material approximation for unresolved material ranges",
                sidecar_path.display()
            ));
            return Ok(result);
        }
        for owned in references {
            let reference = &owned.reference;
            match resolve_direct_reference(sidecar_path, &reference.path) {
                DirectReferenceResolution::Resolved(path, method) => {
                    if let Some(texture) = load_direct_dds(
                        &path,
                        reference,
                        Some(sidecar_path),
                        method,
                        owned.material_indices_by_lod,
                        &mut result.warnings,
                    ) {
                        result.textures.push(texture);
                    }
                }
                DirectReferenceResolution::Missing => result.warnings.push(format!(
                    "Material sidecar {} requests {}, but no matching DDS exists; its material ranges keep the approximation",
                    sidecar_path.display(),
                    reference.path
                )),
                DirectReferenceResolution::Ambiguous(count) => result.warnings.push(format!(
                    "Material sidecar {} requests {}, but {count} local files match; its material ranges keep the approximation",
                    sidecar_path.display(),
                    reference.path
                )),
                DirectReferenceResolution::Rejected(reason) => result.warnings.push(format!(
                    "Material sidecar {} contains a rejected texture reference {}: {reason}",
                    sidecar_path.display(),
                    reference.path
                )),
            }
        }
        return Ok(result);
    }

    result.warnings.push(format!(
        "No same-stem material sidecar was found for {}; checking decoded mesh references only",
        mesh_path.display()
    ));
    resolve_direct_fallback(mesh_path, document, &mut result);
    Ok(result)
}

fn resolve_archive_texture(
    catalog: &ArchiveCatalog,
    source: &cdmw_archive::CatalogEntry,
    document: &MeshDocument,
    cancellation: &CancellationToken,
) -> Result<TextureLoadResult, String> {
    cancellation.check().map_err(|error| error.to_string())?;
    let mut result = TextureLoadResult::default();
    let Some(sidecar_reference) = material_sidecar_virtual_reference(&source.entry.virtual_path)
    else {
        resolve_archive_fallback(catalog, source, document, cancellation, &mut result)?;
        return Ok(result);
    };
    let sidecar_relation = resolve_archive_relation(
        catalog,
        &source.entry.virtual_path,
        &sidecar_reference,
        RelationKind::MaterialSidecar,
        &[
            "pac_xml",
            "pam_xml",
            "pamlod_xml",
            "pami",
            "app_xml",
            "prefabdata_xml",
        ],
    );
    let Some(sidecar_target) = sidecar_relation.target_virtual_path.as_deref() else {
        if sidecar_relation.ambiguity_count > 1 {
            result.warnings.push(format!(
                "Material sidecar lookup for {} is ambiguous across {} archive entries; no texture was selected",
                source.entry.virtual_path, sidecar_relation.ambiguity_count
            ));
            return Ok(result);
        }
        result.warnings.push(format!(
            "No material sidecar resolved for {}; checking decoded mesh references only",
            source.entry.virtual_path
        ));
        resolve_archive_fallback(catalog, source, document, cancellation, &mut result)?;
        return Ok(result);
    };
    let Some(sidecar_entry) = unique_catalog_entry(catalog, sidecar_target) else {
        result.warnings.push(format!(
            "Material sidecar target {sidecar_target} is duplicated in the archive catalog; no texture was selected"
        ));
        return Ok(result);
    };
    let sidecar_bytes = match read_catalog_entry(
        catalog,
        sidecar_entry,
        MATERIAL_SIDECAR_MAX_BYTES,
        cancellation,
    ) {
        Ok(decoded) => decoded.bytes,
        Err(error) => {
            cancellation
                .check()
                .map_err(|cancelled| cancelled.to_string())?;
            result.warnings.push(format!(
                "Material sidecar {sidecar_target} could not be read: {error}; viewport keeps the material approximation"
            ));
            return Ok(result);
        }
    };
    let sidecar = match parse_material_sidecar(&sidecar_bytes) {
        Ok(sidecar) => sidecar,
        Err(error) => {
            result.warnings.push(format!(
                "Material sidecar {sidecar_target} could not be parsed: {error}; viewport keeps the material approximation"
            ));
            return Ok(result);
        }
    };
    result.warnings.extend(
        sidecar
            .warnings
            .iter()
            .map(|warning| format!("Material sidecar {sidecar_target}: {warning}")),
    );
    let (material_parameters, material_factors) =
        resolve_material_parameters(&sidecar, document, sidecar_target, &mut result.warnings);
    result.material_parameters = material_parameters;
    result.material_factors = material_factors;
    let references = owned_preview_texture_references(&sidecar, document, &mut result.warnings);
    if references.is_empty() {
        result.warnings.push(format!(
            "Material sidecar {sidecar_target} has no unambiguous sampled-texture ownership; unresolved material ranges keep the approximation"
        ));
        return Ok(result);
    }
    for owned in references {
        let reference = &owned.reference;
        if !is_safe_virtual_reference(&reference.path) {
            result.warnings.push(format!(
                "Material sidecar {sidecar_target} contains a rejected texture reference {}; its material ranges keep the approximation",
                reference.path
            ));
            continue;
        }
        let relation = resolve_archive_relation(
            catalog,
            sidecar_target,
            &reference.path,
            relation_kind(reference.role),
            &["dds"],
        );
        let Some(target) = relation.target_virtual_path.as_deref() else {
            result.warnings.push(unresolved_relation_warning(
                sidecar_target,
                &reference.path,
                &relation,
            ));
            continue;
        };
        if !relation.target_format_supported {
            result.warnings.push(format!(
                "Material sidecar {sidecar_target} resolves {} to {target}, but it is not a DDS texture",
                reference.path
            ));
            continue;
        }
        let Some(texture_entry) = unique_catalog_entry(catalog, target) else {
            result.warnings.push(format!(
                "Texture target {target} is duplicated in the archive catalog; its material ranges keep the approximation"
            ));
            continue;
        };
        let decoded = match read_catalog_entry(
            catalog,
            texture_entry,
            DDS_MAX_PAYLOAD_BYTES,
            cancellation,
        ) {
            Ok(decoded) => decoded,
            Err(error) => {
                cancellation
                    .check()
                    .map_err(|cancelled| cancelled.to_string())?;
                result.warnings.push(format!(
                    "Resolved DDS {target} could not be read: {error}; its material ranges keep the approximation"
                ));
                continue;
            }
        };
        let metadata = match inspect_dds(&decoded.bytes, reference.role) {
            Ok(metadata) => metadata,
            Err(error) => {
                result.warnings.push(format!(
                    "Resolved DDS {target} is not directly uploadable: {error}; its material ranges keep the approximation"
                ));
                continue;
            }
        };
        append_dds_warnings(target, &metadata, &mut result.warnings);
        result.warnings.push(format!(
            "Viewport texture resolved {sidecar_target} parameter {} to {target} through {:?} for {} material range(s) in LOD0",
            reference.parameter_name,
            relation.method,
            owned.material_indices_by_lod.first().map_or(0, Vec::len)
        ));
        result.textures.push(LoadedTexture {
            label: target.to_owned(),
            metadata,
            bytes: decoded.bytes,
            role: reference.role,
            requested_reference: reference.path.clone(),
            parameter_name: Some(reference.parameter_name.clone()),
            sidecar_label: Some(sidecar_target.to_owned()),
            resolution_method: relation.method,
            archive_compression: Some(decoded.compression),
            material_indices_by_lod: owned.material_indices_by_lod,
        });
    }
    Ok(result)
}

fn resolve_direct_fallback(
    mesh_path: &Path,
    document: &MeshDocument,
    result: &mut TextureLoadResult,
) {
    let references = texture_references(document);
    if references.is_empty() {
        result.warnings.push(
            "No decoded DDS reference is available; Textured Solid uses the normal-based material approximation"
                .to_owned(),
        );
        return;
    }
    if references.len() > 1 {
        result.warnings.push(format!(
            "Decoded mesh metadata contains {} distinct DDS references without material ownership; no texture was selected",
            references.len()
        ));
        return;
    }
    let reference = &references[0];
    match resolve_direct_reference(mesh_path, reference) {
        DirectReferenceResolution::Resolved(path, method) => {
            let inferred = MaterialTextureReference {
                wrapper_type: String::new(),
                submesh_name: String::new(),
                material_name: String::new(),
                parameter_name: "(decoded mesh reference)".to_owned(),
                path: reference.clone(),
                role: TextureRole::BaseColor,
            };
            if let Some(texture) = load_direct_dds(
                &path,
                &inferred,
                None,
                method,
                all_material_indices(document),
                &mut result.warnings,
            ) {
                result.textures.push(texture);
            }
        }
        DirectReferenceResolution::Missing => result.warnings.push(format!(
            "Decoded DDS reference {reference} was not found; viewport keeps the material approximation"
        )),
        DirectReferenceResolution::Ambiguous(count) => result.warnings.push(format!(
            "Decoded DDS reference {reference} matches {count} local files; no texture was selected"
        )),
        DirectReferenceResolution::Rejected(reason) => result
            .warnings
            .push(format!("Decoded DDS reference {reference} was rejected: {reason}")),
    }
}

fn resolve_archive_fallback(
    catalog: &ArchiveCatalog,
    source: &cdmw_archive::CatalogEntry,
    document: &MeshDocument,
    cancellation: &CancellationToken,
    result: &mut TextureLoadResult,
) -> Result<(), String> {
    let references = texture_references(document);
    if references.is_empty() {
        result.warnings.push(
            "No decoded DDS reference is available; Textured Solid uses the normal-based material approximation"
                .to_owned(),
        );
        return Ok(());
    }
    if references.len() > 1 {
        result.warnings.push(format!(
            "Decoded mesh metadata contains {} distinct DDS references without material ownership; no texture was selected",
            references.len()
        ));
        return Ok(());
    }
    let reference = &references[0];
    if !is_safe_virtual_reference(reference) {
        result
            .warnings
            .push(format!("Decoded DDS reference {reference} was rejected"));
        return Ok(());
    }
    let relation = resolve_archive_relation(
        catalog,
        &source.entry.virtual_path,
        reference,
        RelationKind::BaseColorTexture,
        &["dds"],
    );
    let Some(target) = relation.target_virtual_path.as_deref() else {
        result.warnings.push(unresolved_relation_warning(
            &source.entry.virtual_path,
            reference,
            &relation,
        ));
        return Ok(());
    };
    let Some(entry) = unique_catalog_entry(catalog, target) else {
        result.warnings.push(format!(
            "Decoded DDS target {target} is duplicated in the archive catalog; no texture was selected"
        ));
        return Ok(());
    };
    let decoded = match read_catalog_entry(catalog, entry, DDS_MAX_PAYLOAD_BYTES, cancellation) {
        Ok(decoded) => decoded,
        Err(error) => {
            cancellation
                .check()
                .map_err(|cancelled| cancelled.to_string())?;
            result.warnings.push(format!(
                "Resolved DDS {target} could not be read: {error}; viewport keeps the material approximation"
            ));
            return Ok(());
        }
    };
    let metadata = match inspect_dds(&decoded.bytes, TextureRole::BaseColor) {
        Ok(metadata) => metadata,
        Err(error) => {
            result.warnings.push(format!(
                "Resolved DDS {target} is not directly uploadable: {error}; viewport keeps the material approximation"
            ));
            return Ok(());
        }
    };
    append_dds_warnings(target, &metadata, &mut result.warnings);
    result.warnings.push(format!(
        "Viewport texture uses decoded mesh reference {reference} resolved to {target} through {:?}; no material sidecar ownership was available",
        relation.method
    ));
    result.textures.push(LoadedTexture {
        label: target.to_owned(),
        metadata,
        bytes: decoded.bytes,
        role: TextureRole::BaseColor,
        requested_reference: reference.clone(),
        parameter_name: None,
        sidecar_label: None,
        resolution_method: relation.method,
        archive_compression: Some(decoded.compression),
        material_indices_by_lod: all_material_indices(document),
    });
    Ok(())
}

fn load_direct_dds(
    path: &Path,
    reference: &MaterialTextureReference,
    sidecar_path: Option<&Path>,
    method: ResolutionMethod,
    material_indices_by_lod: Vec<Vec<u32>>,
    warnings: &mut Vec<String>,
) -> Option<LoadedTexture> {
    let bytes = match read_bounded_file(path, DDS_MAX_PAYLOAD_BYTES, "DDS") {
        Ok(bytes) => bytes,
        Err(error) => {
            warnings.push(format!(
                "Resolved DDS {} could not be read: {error}; viewport keeps the material approximation",
                path.display()
            ));
            return None;
        }
    };
    let metadata = match inspect_dds(&bytes, reference.role) {
        Ok(metadata) => metadata,
        Err(error) => {
            warnings.push(format!(
                "Resolved DDS {} is not directly uploadable: {error}; viewport keeps the material approximation",
                path.display()
            ));
            return None;
        }
    };
    let label = path.to_string_lossy().replace('\\', "/");
    append_dds_warnings(&label, &metadata, warnings);
    let lod0_range_count = material_indices_by_lod.first().map_or(0, Vec::len);
    warnings.push(format!(
        "Viewport texture resolved {} to {} through {method:?} for {lod0_range_count} material range(s) in LOD0",
        reference.path, label,
    ));
    Some(LoadedTexture {
        label,
        metadata,
        bytes,
        role: reference.role,
        requested_reference: reference.path.clone(),
        parameter_name: (reference.parameter_name != "(decoded mesh reference)")
            .then(|| reference.parameter_name.clone()),
        sidecar_label: sidecar_path.map(|path| path.to_string_lossy().replace('\\', "/")),
        resolution_method: method,
        archive_compression: None,
        material_indices_by_lod,
    })
}

fn append_dds_warnings(label: &str, metadata: &DdsMetadata, warnings: &mut Vec<String>) {
    warnings.extend(
        metadata
            .warnings
            .iter()
            .map(|warning| format!("DDS {label}: {warning}")),
    );
}

#[derive(Debug, Clone, Copy)]
enum MaterialFactorClaim {
    EmissiveColor([u8; 3]),
    EmissiveIntensity(u32),
    Roughness(u32),
    Metalness(u32),
    Specular(u32),
}

fn resolve_material_parameters(
    sidecar: &MaterialSidecar,
    document: &MeshDocument,
    sidecar_label: &str,
    warnings: &mut Vec<String>,
) -> (Vec<LoadedMaterialParameter>, Vec<LoadedMaterialFactors>) {
    let mut loaded = Vec::with_capacity(sidecar.parameters.len());
    let mut color_claims = BTreeMap::<(usize, u32), BTreeSet<[u8; 3]>>::new();
    let mut intensity_claims = BTreeMap::<(usize, u32), BTreeSet<u32>>::new();
    let mut roughness_claims = BTreeMap::<(usize, u32), BTreeSet<u32>>::new();
    let mut metalness_claims = BTreeMap::<(usize, u32), BTreeSet<u32>>::new();
    let mut specular_claims = BTreeMap::<(usize, u32), BTreeSet<u32>>::new();

    for parameter in &sidecar.parameters {
        let ownership =
            material_indices_for_owner(&parameter.submesh_name, &parameter.material_name, document);
        if ownership.iter().all(Vec::is_empty) {
            warnings.push(format!(
                "Material parameter {} in {sidecar_label} does not match a decoded material range; it is preserved but remains unbound",
                parameter.parameter_name
            ));
        }
        let preview_semantic = material_parameter_preview_semantic(parameter);
        let factor = material_parameter_factor_claim(parameter);
        if preview_semantic.is_some() && factor.is_none() {
            warnings.push(format!(
                "Material parameter {} in {sidecar_label} has an invalid explicit value; it is preserved but remains unbound",
                parameter.parameter_name
            ));
        }
        if let Some(factor) = factor {
            for (lod_index, materials) in ownership.iter().enumerate() {
                for material in materials {
                    match factor {
                        MaterialFactorClaim::EmissiveColor(value) => {
                            color_claims
                                .entry((lod_index, *material))
                                .or_default()
                                .insert(value);
                        }
                        MaterialFactorClaim::EmissiveIntensity(value) => {
                            intensity_claims
                                .entry((lod_index, *material))
                                .or_default()
                                .insert(value);
                        }
                        MaterialFactorClaim::Roughness(value) => {
                            roughness_claims
                                .entry((lod_index, *material))
                                .or_default()
                                .insert(value);
                        }
                        MaterialFactorClaim::Metalness(value) => {
                            metalness_claims
                                .entry((lod_index, *material))
                                .or_default()
                                .insert(value);
                        }
                        MaterialFactorClaim::Specular(value) => {
                            specular_claims
                                .entry((lod_index, *material))
                                .or_default()
                                .insert(value);
                        }
                    }
                }
            }
        }
        loaded.push(LoadedMaterialParameter {
            sidecar_label: sidecar_label.to_owned(),
            parameter: parameter.clone(),
            material_indices_by_lod: ownership,
            preview_semantic,
        });
    }

    let color_conflicts = color_claims
        .values()
        .filter(|values| values.len() > 1)
        .count();
    if color_conflicts > 0 {
        warnings.push(format!(
            "{color_conflicts} material range(s) claim conflicting emissive colors; only those color factors remain unbound"
        ));
    }
    let intensity_conflicts = intensity_claims
        .values()
        .filter(|values| values.len() > 1)
        .count();
    if intensity_conflicts > 0 {
        warnings.push(format!(
            "{intensity_conflicts} material range(s) claim conflicting emissive intensities; only those intensity factors remain unbound"
        ));
    }
    append_material_factor_conflict_warning(&roughness_claims, "roughness", warnings);
    append_material_factor_conflict_warning(&metalness_claims, "metalness", warnings);
    append_material_factor_conflict_warning(&specular_claims, "specular", warnings);

    let mut grouped = BTreeMap::<
        (
            Option<[u8; 3]>,
            Option<u32>,
            Option<u32>,
            Option<u32>,
            Option<u32>,
        ),
        Vec<Vec<u32>>,
    >::new();
    for (lod_index, lod) in document.lods.iter().enumerate() {
        for material_index in 0..lod.submeshes.len() {
            let Ok(material) = u32::try_from(material_index) else {
                continue;
            };
            let key = (lod_index, material);
            let color = color_claims
                .get(&key)
                .filter(|values| values.len() == 1)
                .and_then(|values| values.first().copied());
            let intensity = intensity_claims
                .get(&key)
                .filter(|values| values.len() == 1)
                .and_then(|values| values.first().copied());
            let roughness = unique_material_factor_claim(&roughness_claims, key);
            let metalness = unique_material_factor_claim(&metalness_claims, key);
            let specular = unique_material_factor_claim(&specular_claims, key);
            if color.is_none()
                && intensity.is_none()
                && roughness.is_none()
                && metalness.is_none()
                && specular.is_none()
            {
                continue;
            }
            grouped
                .entry((color, intensity, roughness, metalness, specular))
                .or_insert_with(|| vec![Vec::new(); document.lods.len()])[lod_index]
                .push(material);
        }
    }
    let factors = grouped
        .into_iter()
        .map(
            |((color, intensity, roughness, metalness, specular), mut ownership)| {
                for materials in &mut ownership {
                    materials.sort_unstable();
                    materials.dedup();
                }
                LoadedMaterialFactors {
                    sidecar_label: sidecar_label.to_owned(),
                    emissive_color: color.map(|value| {
                        [
                            f32::from(value[0]) / 255.0,
                            f32::from(value[1]) / 255.0,
                            f32::from(value[2]) / 255.0,
                        ]
                    }),
                    emissive_intensity: intensity.map(f32::from_bits),
                    roughness: roughness.map(f32::from_bits),
                    metalness: metalness.map(f32::from_bits),
                    specular: specular.map(f32::from_bits),
                    material_indices_by_lod: ownership,
                }
            },
        )
        .collect();
    (loaded, factors)
}

fn append_material_factor_conflict_warning(
    claims: &BTreeMap<(usize, u32), BTreeSet<u32>>,
    label: &str,
    warnings: &mut Vec<String>,
) {
    let conflicts = claims.values().filter(|values| values.len() > 1).count();
    if conflicts > 0 {
        warnings.push(format!(
            "{conflicts} material range(s) claim conflicting {label} factors; only those {label} factors remain unbound"
        ));
    }
}

fn unique_material_factor_claim(
    claims: &BTreeMap<(usize, u32), BTreeSet<u32>>,
    key: (usize, u32),
) -> Option<u32> {
    claims
        .get(&key)
        .filter(|values| values.len() == 1)
        .and_then(|values| values.first().copied())
}

fn material_parameter_preview_semantic(parameter: &MaterialParameter) -> Option<&'static str> {
    let key = normalized_parameter_key(&parameter.parameter_name);
    if parameter.kind == MaterialParameterKind::Color
        && [
            "emissivecolor",
            "emissivetintcolor",
            "glowcolor",
            "emissivelightcolor",
        ]
        .iter()
        .any(|name| key.contains(name))
    {
        Some("Emissive color")
    } else if parameter.kind == MaterialParameterKind::Float
        && [
            "emissiveintensity",
            "emissiveamount",
            "emissivepower",
            "glowintensity",
        ]
        .iter()
        .any(|name| key.contains(name))
    {
        Some("Emissive intensity")
    } else if matches!(
        parameter.kind,
        MaterialParameterKind::Float | MaterialParameterKind::Byte4
    ) && ["roughness", "scratchroughness"]
        .iter()
        .any(|name| key.contains(name))
    {
        Some("Roughness factor")
    } else if matches!(
        parameter.kind,
        MaterialParameterKind::Float | MaterialParameterKind::Byte4
    ) && ["metallic", "metalness", "scratchmetallic"]
        .iter()
        .any(|name| key.contains(name))
    {
        Some("Metalness factor")
    } else if matches!(
        parameter.kind,
        MaterialParameterKind::Float | MaterialParameterKind::Byte4
    ) && ["specular", "specularamount"]
        .iter()
        .any(|name| key.contains(name))
    {
        Some("Specular factor")
    } else {
        None
    }
}

fn material_parameter_factor_claim(parameter: &MaterialParameter) -> Option<MaterialFactorClaim> {
    match material_parameter_preview_semantic(parameter)? {
        "Emissive color" => {
            parse_hex_color(parameter.raw_value.as_deref()?).map(MaterialFactorClaim::EmissiveColor)
        }
        "Emissive intensity" => {
            let value = parameter.raw_value.as_deref()?.trim().parse::<f32>().ok()?;
            value
                .is_finite()
                .then(|| MaterialFactorClaim::EmissiveIntensity(value.clamp(0.0, 32.0).to_bits()))
        }
        "Roughness factor" => scalar_material_parameter_value(parameter)
            .map(|value| MaterialFactorClaim::Roughness(value.clamp(0.0, 1.0).to_bits())),
        "Metalness factor" => scalar_material_parameter_value(parameter)
            .map(|value| MaterialFactorClaim::Metalness(value.clamp(0.0, 1.0).to_bits())),
        "Specular factor" => scalar_material_parameter_value(parameter)
            .map(|value| MaterialFactorClaim::Specular(value.clamp(0.0, 1.0).to_bits())),
        _ => None,
    }
}

fn scalar_material_parameter_value(parameter: &MaterialParameter) -> Option<f32> {
    match parameter.kind {
        MaterialParameterKind::Float => {
            let value = parameter.raw_value.as_deref()?.trim().parse::<f32>().ok()?;
            value.is_finite().then_some(value)
        }
        MaterialParameterKind::Byte4 => {
            let packed = parameter.raw_value.as_deref()?.trim().parse::<u32>().ok()?;
            packed
                .to_le_bytes()
                .into_iter()
                .max()
                .map(|value| f32::from(value) / 255.0)
        }
        _ => None,
    }
}

fn normalized_parameter_key(value: &str) -> String {
    value
        .chars()
        .filter(char::is_ascii_alphanumeric)
        .flat_map(char::to_lowercase)
        .collect()
}

fn parse_hex_color(value: &str) -> Option<[u8; 3]> {
    let value = value.trim().strip_prefix('#').unwrap_or(value.trim());
    if value.len() != 6 && value.len() != 8 {
        return None;
    }
    Some([
        u8::from_str_radix(value.get(0..2)?, 16).ok()?,
        u8::from_str_radix(value.get(2..4)?, 16).ok()?,
        u8::from_str_radix(value.get(4..6)?, 16).ok()?,
    ])
}

#[derive(Debug, Clone)]
struct OwnedTextureReference {
    reference: MaterialTextureReference,
    material_indices_by_lod: Vec<Vec<u32>>,
}

fn owned_preview_texture_references(
    sidecar: &MaterialSidecar,
    document: &MeshDocument,
    warnings: &mut Vec<String>,
) -> Vec<OwnedTextureReference> {
    for reference in sidecar
        .textures
        .iter()
        .filter(|reference| !is_preview_sampled_role(reference.role))
    {
        warnings.push(format!(
            "{:?} parameter {} is classified but is not sampled by the current material approximation; {} remains unbound",
            reference.role, reference.parameter_name, reference.path
        ));
    }
    let mut candidates = Vec::new();
    for reference in sidecar
        .textures
        .iter()
        .filter(|reference| is_preview_sampled_role(reference.role))
    {
        let ownership = material_indices_for_reference(reference, document);
        if ownership.iter().all(Vec::is_empty) {
            let owner = if !reference.submesh_name.trim().is_empty() {
                format!("submesh {}", reference.submesh_name)
            } else if !reference.material_name.trim().is_empty() {
                format!("material {}", reference.material_name)
            } else {
                "an unnamed multi-submesh owner".to_owned()
            };
            warnings.push(format!(
                "{:?} parameter {} for {owner} does not match a decoded material range; {} remains unbound",
                reference.role, reference.parameter_name, reference.path
            ));
            continue;
        }
        candidates.push(OwnedTextureReference {
            reference: reference.clone(),
            material_indices_by_lod: ownership,
        });
    }

    let mut claims = BTreeMap::<(usize, u32, TextureRole), BTreeSet<String>>::new();
    for candidate in &candidates {
        let normalized = normalize_virtual_path(&candidate.reference.path);
        for (lod_index, materials) in candidate.material_indices_by_lod.iter().enumerate() {
            for material in materials {
                claims
                    .entry((lod_index, *material, candidate.reference.role))
                    .or_default()
                    .insert(normalized.clone());
            }
        }
    }
    let ambiguous = claims
        .into_iter()
        .filter_map(|(owner, paths)| (paths.len() > 1).then_some(owner))
        .collect::<BTreeSet<_>>();
    if !ambiguous.is_empty() {
        warnings.push(format!(
            "{} decoded material-role assignment(s) claim more than one distinct texture; only those roles keep the approximation",
            ambiguous.len()
        ));
    }

    let mut grouped = BTreeMap::<(TextureRole, String), OwnedTextureReference>::new();
    for mut candidate in candidates {
        for (lod_index, materials) in candidate.material_indices_by_lod.iter_mut().enumerate() {
            materials.retain(|material| {
                !ambiguous.contains(&(lod_index, *material, candidate.reference.role))
            });
        }
        if candidate.material_indices_by_lod.iter().all(Vec::is_empty) {
            continue;
        }
        let normalized = normalize_virtual_path(&candidate.reference.path);
        let key = (candidate.reference.role, normalized);
        if let Some(existing) = grouped.get_mut(&key) {
            for (existing_materials, candidate_materials) in existing
                .material_indices_by_lod
                .iter_mut()
                .zip(candidate.material_indices_by_lod)
            {
                existing_materials.extend(candidate_materials);
                existing_materials.sort_unstable();
                existing_materials.dedup();
            }
        } else {
            grouped.insert(key, candidate);
        }
    }
    grouped.into_values().collect()
}

const fn is_preview_sampled_role(role: TextureRole) -> bool {
    matches!(
        role,
        TextureRole::BaseColor
            | TextureRole::Normal
            | TextureRole::Material
            | TextureRole::Roughness
            | TextureRole::Metalness
            | TextureRole::Occlusion
            | TextureRole::Emissive
    )
}

fn material_indices_for_reference(
    reference: &MaterialTextureReference,
    document: &MeshDocument,
) -> Vec<Vec<u32>> {
    material_indices_for_owner(&reference.submesh_name, &reference.material_name, document)
}

fn material_indices_for_owner(
    submesh_name: &str,
    material_name: &str,
    document: &MeshDocument,
) -> Vec<Vec<u32>> {
    document
        .lods
        .iter()
        .map(|lod| {
            lod.submeshes
                .iter()
                .enumerate()
                .filter(|(_, submesh)| {
                    if !submesh_name.trim().is_empty() {
                        submesh.name.eq_ignore_ascii_case(submesh_name)
                    } else if !material_name.trim().is_empty() {
                        submesh.material.eq_ignore_ascii_case(material_name)
                    } else {
                        lod.submeshes.len() == 1
                    }
                })
                .filter_map(|(index, _)| u32::try_from(index).ok())
                .collect()
        })
        .collect()
}

fn all_material_indices(document: &MeshDocument) -> Vec<Vec<u32>> {
    document
        .lods
        .iter()
        .map(|lod| {
            (0..lod.submeshes.len())
                .filter_map(|index| u32::try_from(index).ok())
                .collect()
        })
        .collect()
}

fn direct_material_sidecars(mesh_path: &Path) -> Vec<PathBuf> {
    let Some(extension) = material_sidecar_extension(mesh_path) else {
        return Vec::new();
    };
    let adjacent = mesh_path.with_extension(extension);
    let modelproperty = replace_component(&adjacent, "model", "modelproperty");
    let mut candidates = [Some(adjacent), modelproperty]
        .into_iter()
        .flatten()
        .filter(|path| path.is_file())
        .collect::<Vec<_>>();
    candidates.sort_by_key(|path| path.to_string_lossy().to_ascii_lowercase());
    candidates.dedup_by(|left, right| paths_equal(left, right));
    candidates
}

fn material_sidecar_extension(path: &Path) -> Option<&'static str> {
    match path
        .extension()
        .and_then(|value| value.to_str())?
        .to_ascii_lowercase()
        .as_str()
    {
        "pac" => Some("pac_xml"),
        "pam" => Some("pam_xml"),
        "pamlod" => Some("pamlod_xml"),
        _ => None,
    }
}

fn material_sidecar_virtual_reference(source: &str) -> Option<String> {
    let path = Path::new(source);
    let extension = material_sidecar_extension(path)?;
    let normalized = source.replace('\\', "/");
    let split = normalized.rfind('.')?;
    let with_extension = format!("{}.{extension}", normalized.get(..split)?);
    let mut parts = with_extension
        .split('/')
        .map(str::to_owned)
        .collect::<Vec<_>>();
    if let Some(model) = parts
        .iter_mut()
        .rev()
        .find(|part| part.eq_ignore_ascii_case("model"))
    {
        *model = "modelproperty".to_owned();
    }
    Some(parts.join("/"))
}

fn replace_component(path: &Path, from: &str, to: &str) -> Option<PathBuf> {
    let mut replace_index = None;
    for (index, component) in path.components().enumerate() {
        if let Component::Normal(value) = component
            && value.to_string_lossy().eq_ignore_ascii_case(from)
        {
            replace_index = Some(index);
        }
    }
    let replace_index = replace_index?;
    let mut output = PathBuf::new();
    for (index, component) in path.components().enumerate() {
        if index == replace_index {
            output.push(to);
        } else {
            output.push(component.as_os_str());
        }
    }
    Some(output)
}

enum DirectReferenceResolution {
    Resolved(PathBuf, ResolutionMethod),
    Missing,
    Ambiguous(usize),
    Rejected(String),
}

fn resolve_direct_reference(anchor: &Path, reference: &str) -> DirectReferenceResolution {
    if !is_safe_virtual_reference(reference) {
        return DirectReferenceResolution::Rejected(
            "absolute paths and parent traversal are not allowed".to_owned(),
        );
    }
    let reference_path = Path::new(reference);
    let Some(parent) = anchor.parent() else {
        return DirectReferenceResolution::Missing;
    };
    let mut candidates = BTreeMap::<String, (PathBuf, ResolutionMethod)>::new();
    let normal_components = reference_path
        .components()
        .filter(|component| matches!(component, Component::Normal(_)))
        .count();
    for (index, ancestor) in parent.ancestors().enumerate() {
        if index > 0 && normal_components < 2 {
            break;
        }
        let path = ancestor.join(reference_path);
        if path.is_file() {
            let method = if index == 0 {
                ResolutionMethod::SamePackageRelative
            } else {
                ResolutionMethod::NormalizedVirtualPath
            };
            candidates
                .entry(path_identity(&path))
                .or_insert((path, method));
        }
    }
    if let Some(file_name) = reference_path.file_name() {
        let path = parent.join(file_name);
        if path.is_file() {
            candidates
                .entry(path_identity(&path))
                .or_insert((path, ResolutionMethod::UnambiguousBasename));
        }
    }
    match candidates.len() {
        0 => DirectReferenceResolution::Missing,
        1 => {
            let (_, (path, method)) = candidates.into_iter().next().expect("one candidate");
            DirectReferenceResolution::Resolved(path, method)
        }
        count => DirectReferenceResolution::Ambiguous(count),
    }
}

fn resolve_archive_relation(
    catalog: &ArchiveCatalog,
    source: &str,
    reference: &str,
    kind: RelationKind,
    supported_extensions: &[&str],
) -> AssetRelation {
    let basename = normalize_virtual_path(reference)
        .rsplit('/')
        .next()
        .unwrap_or_default()
        .to_owned();
    let paths = catalog
        .entries
        .iter()
        .map(|entry| &entry.entry.virtual_path)
        .filter(|path| {
            normalize_virtual_path(path)
                .rsplit('/')
                .next()
                .is_some_and(|candidate| candidate == basename)
        })
        .cloned();
    AssetIndex::new(paths).resolve(source, reference, kind, supported_extensions)
}

fn unique_catalog_entry<'a>(
    catalog: &'a ArchiveCatalog,
    target: &str,
) -> Option<&'a cdmw_archive::CatalogEntry> {
    let normalized = normalize_virtual_path(target);
    let mut matches = catalog
        .entries
        .iter()
        .filter(|entry| normalize_virtual_path(&entry.entry.virtual_path) == normalized);
    let first = matches.next()?;
    matches.next().is_none().then_some(first)
}

fn read_catalog_entry(
    catalog: &ArchiveCatalog,
    entry: &cdmw_archive::CatalogEntry,
    max_bytes: usize,
    cancellation: &CancellationToken,
) -> Result<DecodedEntry, String> {
    cancellation.check().map_err(|error| error.to_string())?;
    let declared_size = entry.entry.original_size.max(entry.entry.stored_size);
    if declared_size > max_bytes as u64 {
        return Err(format!(
            "{} declares {declared_size} bytes, above the {max_bytes}-byte limit",
            entry.entry.virtual_path
        ));
    }
    let payload_root = catalog
        .indexes
        .get(entry.index_id)
        .ok_or_else(|| "asset relation references a missing archive index".to_owned())?
        .parent()
        .ok_or_else(|| "archive index has no payload directory".to_owned())?;
    let decode_limits = ArchiveLimits {
        max_entry_bytes: u64::try_from(max_bytes)
            .map_err(|_| format!("{max_bytes}-byte decode limit is not representable"))?,
        ..ArchiveLimits::default()
    };
    let decoded = read_entry_unverified(payload_root, &entry.entry, decode_limits, cancellation)
        .map_err(|error| error.to_string())?;
    cancellation.check().map_err(|error| error.to_string())?;
    if decoded.bytes.len() > max_bytes {
        return Err(format!(
            "{} decoded to {} bytes, above the {max_bytes}-byte limit",
            entry.entry.virtual_path,
            decoded.bytes.len()
        ));
    }
    Ok(decoded)
}

fn read_bounded_file(path: &Path, max_bytes: usize, kind: &str) -> Result<Vec<u8>, String> {
    let metadata = fs::metadata(path)
        .map_err(|error| format!("failed to inspect {kind} {}: {error}", path.display()))?;
    if metadata.len() > max_bytes as u64 {
        return Err(format!(
            "{kind} {} is {} bytes, above the {max_bytes}-byte limit",
            path.display(),
            metadata.len()
        ));
    }
    let bytes = fs::read(path)
        .map_err(|error| format!("failed to read {kind} {}: {error}", path.display()))?;
    if bytes.len() > max_bytes {
        return Err(format!(
            "{kind} {} is {} bytes, above the {max_bytes}-byte limit",
            path.display(),
            bytes.len()
        ));
    }
    Ok(bytes)
}

fn unresolved_relation_warning(source: &str, reference: &str, relation: &AssetRelation) -> String {
    if relation.ambiguity_count > 1 {
        format!(
            "Texture reference {reference} from {source} is ambiguous across {} archive entries; no texture was selected",
            relation.ambiguity_count
        )
    } else {
        format!(
            "Texture reference {reference} from {source} was not found; viewport keeps the material approximation"
        )
    }
}

fn relation_kind(role: TextureRole) -> RelationKind {
    match role {
        TextureRole::BaseColor => RelationKind::BaseColorTexture,
        TextureRole::Normal => RelationKind::NormalTexture,
        TextureRole::Material => RelationKind::MaterialTexture,
        TextureRole::Roughness => RelationKind::RoughnessTexture,
        TextureRole::Metalness => RelationKind::MetalnessTexture,
        TextureRole::Occlusion => RelationKind::OcclusionTexture,
        TextureRole::Specular => RelationKind::SpecularTexture,
        TextureRole::Glossiness => RelationKind::GlossinessTexture,
        TextureRole::Emissive => RelationKind::EmissiveTexture,
        TextureRole::Opacity => RelationKind::OpacityTexture,
        TextureRole::Height => RelationKind::HeightTexture,
        TextureRole::Unknown => RelationKind::Companion,
    }
}

fn is_safe_virtual_reference(reference: &str) -> bool {
    let path = Path::new(reference);
    !reference.trim().is_empty()
        && !path.is_absolute()
        && !path.components().any(|component| {
            matches!(
                component,
                Component::ParentDir | Component::RootDir | Component::Prefix(_)
            )
        })
        && !reference
            .replace('\\', "/")
            .split('/')
            .any(|part| part == "..")
}

fn normalize_virtual_path(value: &str) -> String {
    value
        .replace('\\', "/")
        .trim_start_matches('/')
        .to_ascii_lowercase()
}

fn path_identity(path: &Path) -> String {
    fs::canonicalize(path)
        .unwrap_or_else(|_| path.to_path_buf())
        .to_string_lossy()
        .replace('\\', "/")
        .to_ascii_lowercase()
}

fn paths_equal(left: &Path, right: &Path) -> bool {
    path_identity(left) == path_identity(right)
}

fn texture_references(document: &MeshDocument) -> Vec<String> {
    let mut references = document
        .lods
        .iter()
        .flat_map(|lod| &lod.submeshes)
        .flat_map(|submesh| [&submesh.name, &submesh.material])
        .filter(|value| value.to_ascii_lowercase().ends_with(".dds"))
        .cloned()
        .collect::<Vec<_>>();
    references.sort_by_key(|value| value.to_ascii_lowercase());
    references.dedup_by(|left, right| left.eq_ignore_ascii_case(right));
    references
}

#[cfg(test)]
mod tests {
    use super::*;
    use cdmw_formats::{MeshLod, SourceRange, Submesh};
    use std::sync::atomic::{AtomicU64, Ordering};

    static TEMP_ID: AtomicU64 = AtomicU64::new(1);

    struct TempTree(PathBuf);

    impl TempTree {
        fn new(label: &str) -> Result<Self, Box<dyn std::error::Error>> {
            let path = std::env::temp_dir().join(format!(
                "cdmw-rust-mesh-lab-{label}-{}-{}",
                std::process::id(),
                TEMP_ID.fetch_add(1, Ordering::Relaxed)
            ));
            fs::create_dir_all(&path)?;
            Ok(Self(path))
        }
    }

    impl Drop for TempTree {
        fn drop(&mut self) {
            if self.0.starts_with(std::env::temp_dir()) {
                let _ = fs::remove_dir_all(&self.0);
            }
        }
    }

    fn document_with_references(references: &[&str]) -> MeshDocument {
        MeshDocument {
            format: MeshFormat::Pac,
            source_sha256: String::new(),
            parser: "test".to_owned(),
            lod_count_reported: 1,
            lods: vec![MeshLod {
                level: 0,
                submeshes: references
                    .iter()
                    .enumerate()
                    .map(|(index, reference)| Submesh {
                        name: format!("part-{index}"),
                        material: (*reference).to_owned(),
                        positions: Vec::new(),
                        normals: Vec::new(),
                        uvs: Vec::new(),
                        indices: Vec::new(),
                        source_vertex_indices: Vec::new(),
                        source_range: SourceRange {
                            offset: 0,
                            length: 0,
                        },
                        vertex_stride: 0,
                        layout: String::new(),
                    })
                    .collect(),
            }],
            warnings: Vec::new(),
            structural_fingerprint: String::new(),
        }
    }

    fn catalog_with_paths(paths: &[&str]) -> ArchiveCatalog {
        ArchiveCatalog {
            root: PathBuf::from("archive"),
            indexes: Vec::new(),
            entries: paths
                .iter()
                .map(|path| cdmw_archive::CatalogEntry {
                    index_id: 0,
                    entry: cdmw_archive::ArchiveEntry {
                        virtual_path: (*path).to_owned(),
                        payload_index: 0,
                        offset: 0,
                        stored_size: 0,
                        original_size: 0,
                        flags: 0,
                    },
                })
                .collect(),
            warnings: Vec::new(),
        }
    }

    fn synthetic_partial_dds_header(block_size: u32) -> Vec<u8> {
        let mut header = vec![0_u8; 0x80];
        header[0..4].copy_from_slice(b"DDS ");
        header[4..8].copy_from_slice(&124_u32.to_le_bytes());
        header[8..12].copy_from_slice(&0x0008_1007_u32.to_le_bytes());
        header[12..16].copy_from_slice(&4_u32.to_le_bytes());
        header[16..20].copy_from_slice(&4_u32.to_le_bytes());
        header[20..24].copy_from_slice(&8_u32.to_le_bytes());
        header[28..32].copy_from_slice(&1_u32.to_le_bytes());
        header[32..36].copy_from_slice(&block_size.to_le_bytes());
        header[36..40].copy_from_slice(&block_size.to_le_bytes());
        header[76..80].copy_from_slice(&32_u32.to_le_bytes());
        header[80..84].copy_from_slice(&4_u32.to_le_bytes());
        header[84..88].copy_from_slice(b"DXT1");
        header[108..112].copy_from_slice(&0x0000_1000_u32.to_le_bytes());
        header
    }

    fn synthetic_pathc_header(texture_header: &[u8]) -> Vec<u8> {
        let mut pathc = Vec::new();
        pathc.extend_from_slice(&0_u32.to_le_bytes());
        pathc.extend_from_slice(&0_u32.to_le_bytes());
        pathc.extend_from_slice(&128_u32.to_le_bytes());
        pathc.extend_from_slice(&1_u32.to_le_bytes());
        pathc.extend_from_slice(&1_u32.to_le_bytes());
        pathc.extend_from_slice(&0_u32.to_le_bytes());
        pathc.extend_from_slice(&0_u32.to_le_bytes());
        pathc.extend_from_slice(texture_header);
        pathc.extend_from_slice(&0x54e1_1b82_u32.to_le_bytes());
        pathc.extend_from_slice(&0_u16.to_le_bytes());
        pathc.extend_from_slice(&0_u16.to_le_bytes());
        pathc.extend_from_slice(&[0_u8; 16]);
        pathc
    }

    fn direct_fixture(
        label: &str,
    ) -> Result<(TempTree, PathBuf, PathBuf, PathBuf), Box<dyn std::error::Error>> {
        let tree = TempTree::new(label)?;
        let model = tree.0.join("character/model");
        let modelproperty = tree.0.join("character/modelproperty");
        let texture = tree.0.join("character/texture");
        fs::create_dir_all(&model)?;
        fs::create_dir_all(&modelproperty)?;
        fs::create_dir_all(&texture)?;
        Ok((
            tree,
            model.join("body.pac"),
            modelproperty.join("body.pac_xml"),
            texture,
        ))
    }

    #[test]
    fn explicit_sidecar_base_color_outranks_a_decoded_fallback()
    -> Result<(), Box<dyn std::error::Error>> {
        let (_tree, mesh, sidecar, texture_directory) = direct_fixture("explicit")?;
        let expected = texture_directory.join("body.dds");
        fs::write(&expected, cdmw_texture::synthetic::rgba8_checker_dds())?;
        fs::write(
            mesh.parent().ok_or("model parent")?.join("fallback.dds"),
            cdmw_texture::synthetic::rgba8_checker_dds(),
        )?;
        fs::write(
            &sidecar,
            br#"<SkinnedMeshMaterialWrapper _subMeshName="part-0"><Material _materialName="SkinnedMeshStandard"><MaterialParameterTexture _name="_baseColorTexture"><ResourceReferencePath_ITexture _path="character/texture/body.dds"/></MaterialParameterTexture></Material></SkinnedMeshMaterialWrapper>"#,
        )?;

        let resolved = resolve_direct_texture(&mesh, &document_with_references(&["fallback.dds"]))?;
        let texture = resolved
            .textures
            .first()
            .ok_or("missing explicit texture")?;
        assert!(paths_equal(Path::new(&texture.label), &expected));
        assert_eq!(texture.requested_reference, "character/texture/body.dds");
        assert_eq!(texture.parameter_name.as_deref(), Some("_baseColorTexture"));
        assert!(texture.sidecar_label.is_some());
        assert_eq!(texture.archive_compression, None);
        assert_eq!(texture.role, TextureRole::BaseColor);
        assert_eq!(texture.material_indices_by_lod, vec![vec![0]]);
        Ok(())
    }

    #[test]
    fn archive_reader_reconstructs_uploadable_partial_dds_without_modifying_sources()
    -> Result<(), Box<dyn std::error::Error>> {
        let tree = TempTree::new("partial-dds-loader")?;
        let payload_root = tree.0.join("base");
        let meta_root = tree.0.join("meta");
        fs::create_dir_all(&payload_root)?;
        fs::create_dir_all(&meta_root)?;
        let header = synthetic_partial_dds_header(8);
        let mut payload = header.clone();
        payload.extend_from_slice(&[1_u8, 2, 3, 4, 5, 6, 7, 8]);
        let pathc = synthetic_pathc_header(&header);
        let payload_path = payload_root.join("0.paz");
        let pathc_path = meta_root.join("0.pathc");
        fs::write(&payload_path, &payload)?;
        fs::write(&pathc_path, &pathc)?;
        let catalog = ArchiveCatalog {
            root: tree.0.clone(),
            indexes: vec![payload_root.join("0.pamt")],
            entries: Vec::new(),
            warnings: Vec::new(),
        };
        let entry = cdmw_archive::CatalogEntry {
            index_id: 0,
            entry: cdmw_archive::ArchiveEntry {
                virtual_path: "texture/test.dds".to_owned(),
                payload_index: 0,
                offset: 0,
                stored_size: u64::try_from(payload.len())?,
                original_size: u64::try_from(payload.len() + 1)?,
                flags: 1,
            },
        };

        let decoded = read_catalog_entry(&catalog, &entry, 256, &CancellationToken::default())?;
        assert_eq!(
            decoded.compression,
            cdmw_archive::CompressionOutcome::PartialDds
        );
        assert_eq!(decoded.bytes, payload);
        assert!(inspect_dds(&decoded.bytes, TextureRole::BaseColor).is_ok());
        assert_eq!(fs::read(payload_path)?, payload);
        assert_eq!(fs::read(pathc_path)?, pathc);
        Ok(())
    }

    #[test]
    fn distinct_submesh_base_colors_keep_distinct_material_owners()
    -> Result<(), Box<dyn std::error::Error>> {
        let (_tree, mesh, sidecar, texture_directory) = direct_fixture("multi-material")?;
        for name in ["body_a.dds", "body_b.dds"] {
            fs::write(
                texture_directory.join(name),
                cdmw_texture::synthetic::rgba8_checker_dds(),
            )?;
        }
        fs::write(
            &sidecar,
            br#"<Root><SkinnedMeshMaterialWrapper _subMeshName="part-0"><MaterialParameterTexture _name="_baseColorTexture" Value="character/texture/body_a.dds"/></SkinnedMeshMaterialWrapper><SkinnedMeshMaterialWrapper _subMeshName="part-1"><MaterialParameterTexture _name="_baseColorTexture" Value="character/texture/body_b.dds"/></SkinnedMeshMaterialWrapper></Root>"#,
        )?;

        let resolved = resolve_direct_texture(
            &mesh,
            &document_with_references(&["decoded_a.dds", "decoded_b.dds"]),
        )?;
        assert_eq!(resolved.textures.len(), 2);
        let mut owners = resolved
            .textures
            .iter()
            .map(|texture| texture.material_indices_by_lod[0].clone())
            .collect::<Vec<_>>();
        owners.sort();
        assert_eq!(owners, vec![vec![0], vec![1]]);
        Ok(())
    }

    #[test]
    fn preview_material_roles_resolve_for_the_same_submesh_owner()
    -> Result<(), Box<dyn std::error::Error>> {
        let (_tree, mesh, sidecar, texture_directory) = direct_fixture("preview-roles")?;
        for name in [
            "body_base.dds",
            "body_n.dds",
            "body_sp.dds",
            "body_rough.dds",
            "body_metal.dds",
            "body_ao.dds",
            "body_emi.dds",
        ] {
            fs::write(
                texture_directory.join(name),
                cdmw_texture::synthetic::rgba8_checker_dds(),
            )?;
        }
        fs::write(
            &sidecar,
            br##"<SkinnedMeshMaterialWrapper _subMeshName="part-0"><Material _materialName="SkinnedMeshEmissive"><MaterialParameterTexture _name="_baseColorTexture" Value="character/texture/body_base.dds"/><MaterialParameterTexture _name="_normalTexture" Value="character/texture/body_n.dds"/><MaterialParameterTexture _name="_materialTexture" Value="character/texture/body_sp.dds"/><MaterialParameterTexture _name="_roughnessTexture" Value="character/texture/body_rough.dds"/><MaterialParameterTexture _name="_metalnessTexture" Value="character/texture/body_metal.dds"/><MaterialParameterTexture _name="_ambientOcclusionTexture" Value="character/texture/body_ao.dds"/><MaterialParameterTexture _name="_emissiveIntensityTexture" Value="character/texture/body_emi.dds"/><MaterialParameterTexture _name="_specularTexture" Value="character/texture/body_spec.dds"/><MaterialParameterTexture _name="_glossinessTexture" Value="character/texture/body_gloss.dds"/><MaterialParameterColor _name="_emissiveColor" _value="#204060ff"/><MaterialParameterFloat _name="_emissiveIntensity" _value="2.5"/></Material></SkinnedMeshMaterialWrapper>"##,
        )?;

        let resolved = resolve_direct_texture(&mesh, &document_with_references(&["fallback.dds"]))?;
        assert_eq!(resolved.textures.len(), 7);
        assert_eq!(resolved.material_parameters.len(), 2);
        assert_eq!(resolved.material_factors.len(), 1);
        assert_eq!(
            resolved.material_factors[0].material_indices_by_lod,
            vec![vec![0]]
        );
        assert_eq!(resolved.material_factors[0].emissive_intensity, Some(2.5));
        let roles = resolved
            .textures
            .iter()
            .map(|texture| {
                assert_eq!(texture.material_indices_by_lod, vec![vec![0]]);
                (texture.role, texture.metadata.color_space)
            })
            .collect::<BTreeMap<_, _>>();
        assert_eq!(
            roles.get(&TextureRole::BaseColor),
            Some(&cdmw_texture::ColorSpace::Srgb)
        );
        assert_eq!(
            roles.get(&TextureRole::Normal),
            Some(&cdmw_texture::ColorSpace::Linear)
        );
        assert_eq!(
            roles.get(&TextureRole::Material),
            Some(&cdmw_texture::ColorSpace::Linear)
        );
        assert_eq!(
            roles.get(&TextureRole::Roughness),
            Some(&cdmw_texture::ColorSpace::Linear)
        );
        assert_eq!(
            roles.get(&TextureRole::Metalness),
            Some(&cdmw_texture::ColorSpace::Linear)
        );
        assert_eq!(
            roles.get(&TextureRole::Occlusion),
            Some(&cdmw_texture::ColorSpace::Linear)
        );
        assert_eq!(
            roles.get(&TextureRole::Emissive),
            Some(&cdmw_texture::ColorSpace::Srgb)
        );
        assert!(resolved.warnings.iter().any(|warning| {
            warning.contains("Specular parameter _specularTexture")
                && warning.contains("body_spec.dds remains unbound")
        }));
        assert!(resolved.warnings.iter().any(|warning| {
            warning.contains("Glossiness parameter _glossinessTexture")
                && warning.contains("body_gloss.dds remains unbound")
        }));
        Ok(())
    }

    #[test]
    fn material_ownership_follows_submesh_names_when_lod_order_changes()
    -> Result<(), Box<dyn std::error::Error>> {
        let mut document = document_with_references(&["decoded_a.dds", "decoded_b.dds"]);
        let mut second_lod = document.lods[0].clone();
        second_lod.level = 1;
        second_lod.submeshes.reverse();
        document.lods.push(second_lod);
        let sidecar = parse_material_sidecar(
            br#"<Root><SkinnedMeshMaterialWrapper _subMeshName="part-0"><MaterialParameterTexture _name="_baseColorTexture" Value="character/texture/body_a.dds"/></SkinnedMeshMaterialWrapper><SkinnedMeshMaterialWrapper _subMeshName="part-1"><MaterialParameterTexture _name="_baseColorTexture" Value="character/texture/body_b.dds"/></SkinnedMeshMaterialWrapper></Root>"#,
        )?;
        let mut warnings = Vec::new();
        let owned = owned_preview_texture_references(&sidecar, &document, &mut warnings);
        assert!(warnings.is_empty());
        assert_eq!(owned.len(), 2);
        let first = owned
            .iter()
            .find(|owned| owned.reference.path.ends_with("body_a.dds"))
            .ok_or("missing first base color")?;
        assert_eq!(first.material_indices_by_lod, vec![vec![0], vec![1]]);
        Ok(())
    }

    #[test]
    fn material_parameters_preserve_unknowns_and_resolve_unique_preview_factors()
    -> Result<(), Box<dyn std::error::Error>> {
        let mut document = document_with_references(&["material-a", "material-b"]);
        let mut second_lod = document.lods[0].clone();
        second_lod.level = 1;
        second_lod.submeshes.reverse();
        document.lods.push(second_lod);
        let sidecar = parse_material_sidecar(
            br##"<Root>
              <SkinnedMeshMaterialWrapper _subMeshName="part-0">
                <Material _materialName="material-a">
                  <MaterialParameterColor _name="_emissiveColor" _value="#204060ff"/>
                  <MaterialParameterFloat _name="_emissiveIntensity" _value="2.5"/>
                  <MaterialParameterFloat _name="_roughness" _value="0"/>
                  <MaterialParameterByte4 _name="_metallic" _value="128"/>
                  <MaterialParameterFloat _name="_specularAmount" _value="0.9"/>
                  <MaterialParameterFuture _name="_future" _value="opaque"/>
                </Material>
              </SkinnedMeshMaterialWrapper>
              <SkinnedMeshMaterialWrapper _subMeshName="part-1">
                <MaterialParameterFloat _name="_emissivePower" _value="1"/>
                <MaterialParameterFloat _name="_glowIntensity" _value="2"/>
                <MaterialParameterFloat _name="_roughness" _value="0.2"/>
                <MaterialParameterFloat _name="_scratchRoughness" _value="0.6"/>
              </SkinnedMeshMaterialWrapper>
            </Root>"##,
        )?;
        let mut warnings = Vec::new();
        let (parameters, factors) = resolve_material_parameters(
            &sidecar,
            &document,
            "character/modelproperty/body.pac_xml",
            &mut warnings,
        );
        assert_eq!(parameters.len(), 10);
        assert_eq!(
            parameters[0].material_indices_by_lod,
            vec![vec![0], vec![1]]
        );
        assert_eq!(parameters[0].preview_semantic, Some("Emissive color"));
        let future = parameters
            .iter()
            .find(|loaded| loaded.parameter.parameter_name == "_future")
            .ok_or("missing preserved future parameter")?;
        assert_eq!(future.parameter.kind, MaterialParameterKind::Unknown);
        assert_eq!(future.preview_semantic, None);
        assert_eq!(factors.len(), 1);
        assert_eq!(factors[0].material_indices_by_lod, vec![vec![0], vec![1]]);
        assert_eq!(
            factors[0].emissive_color,
            Some([32.0 / 255.0, 64.0 / 255.0, 96.0 / 255.0])
        );
        assert_eq!(factors[0].emissive_intensity, Some(2.5));
        assert_eq!(factors[0].roughness, Some(0.0));
        assert_eq!(factors[0].metalness, Some(128.0 / 255.0));
        assert_eq!(factors[0].specular, Some(0.9));
        assert!(warnings.iter().any(|warning| {
            warning.contains("material range(s) claim conflicting emissive intensities")
        }));
        assert!(warnings.iter().any(|warning| {
            warning.contains("material range(s) claim conflicting roughness factors")
        }));
        Ok(())
    }

    #[test]
    fn multiple_sidecar_base_colors_do_not_fall_back_to_the_first_texture()
    -> Result<(), Box<dyn std::error::Error>> {
        let (_tree, mesh, sidecar, texture_directory) = direct_fixture("ambiguous")?;
        for name in ["body_a.dds", "body_b.dds"] {
            fs::write(
                texture_directory.join(name),
                cdmw_texture::synthetic::rgba8_checker_dds(),
            )?;
        }
        fs::write(
            mesh.parent().ok_or("model parent")?.join("fallback.dds"),
            cdmw_texture::synthetic::rgba8_checker_dds(),
        )?;
        fs::write(
            &sidecar,
            br#"<SkinnedMeshMaterialWrapper><MaterialParameterTexture _name="_baseColorTexture" Value="character/texture/body_a.dds"/><MaterialParameterTexture _name="_overlayColorTexture" Value="character/texture/body_b.dds"/></SkinnedMeshMaterialWrapper>"#,
        )?;

        let resolved = resolve_direct_texture(&mesh, &document_with_references(&["fallback.dds"]))?;
        assert!(resolved.textures.is_empty());
        assert!(
            resolved
                .warnings
                .iter()
                .any(|warning| warning.contains("claim more than one distinct texture"))
        );
        Ok(())
    }

    #[test]
    fn one_role_conflict_does_not_discard_other_authoritative_roles()
    -> Result<(), Box<dyn std::error::Error>> {
        let (_tree, mesh, sidecar, texture_directory) = direct_fixture("role-conflict")?;
        for name in ["body_a.dds", "body_b.dds", "body_n.dds"] {
            fs::write(
                texture_directory.join(name),
                cdmw_texture::synthetic::rgba8_checker_dds(),
            )?;
        }
        fs::write(
            &sidecar,
            br#"<SkinnedMeshMaterialWrapper><MaterialParameterTexture _name="_baseColorTexture" Value="character/texture/body_a.dds"/><MaterialParameterTexture _name="_overlayColorTexture" Value="character/texture/body_b.dds"/><MaterialParameterTexture _name="_normalTexture" Value="character/texture/body_n.dds"/></SkinnedMeshMaterialWrapper>"#,
        )?;

        let resolved = resolve_direct_texture(&mesh, &document_with_references(&["fallback.dds"]))?;
        assert_eq!(resolved.textures.len(), 1);
        assert_eq!(resolved.textures[0].role, TextureRole::Normal);
        assert_eq!(resolved.textures[0].material_indices_by_lod, vec![vec![0]]);
        assert!(
            resolved
                .warnings
                .iter()
                .any(|warning| warning.contains("claim more than one distinct texture"))
        );
        Ok(())
    }

    #[test]
    fn unresolved_explicit_sidecar_reference_keeps_the_placeholder()
    -> Result<(), Box<dyn std::error::Error>> {
        let (_tree, mesh, sidecar, _texture_directory) = direct_fixture("missing")?;
        fs::write(
            mesh.parent().ok_or("model parent")?.join("fallback.dds"),
            cdmw_texture::synthetic::rgba8_checker_dds(),
        )?;
        fs::write(
            &sidecar,
            br#"<SkinnedMeshMaterialWrapper><MaterialParameterTexture _name="_baseColorTexture" Value="character/texture/missing.dds"/></SkinnedMeshMaterialWrapper>"#,
        )?;

        let resolved = resolve_direct_texture(&mesh, &document_with_references(&["fallback.dds"]))?;
        assert!(resolved.textures.is_empty());
        assert!(
            resolved
                .warnings
                .iter()
                .any(|warning| warning.contains("no matching DDS exists"))
        );
        Ok(())
    }

    #[test]
    fn one_decoded_reference_remains_a_visible_fallback_without_a_sidecar()
    -> Result<(), Box<dyn std::error::Error>> {
        let (_tree, mesh, _sidecar, _texture_directory) = direct_fixture("fallback")?;
        let expected = mesh.parent().ok_or("model parent")?.join("fallback.dds");
        fs::write(&expected, cdmw_texture::synthetic::rgba8_checker_dds())?;

        let resolved = resolve_direct_texture(&mesh, &document_with_references(&["fallback.dds"]))?;
        let texture = resolved
            .textures
            .first()
            .ok_or("missing fallback texture")?;
        assert!(paths_equal(Path::new(&texture.label), &expected));
        assert!(texture.sidecar_label.is_none());
        assert!(
            resolved
                .warnings
                .iter()
                .any(|warning| warning.contains("No same-stem material sidecar"))
        );
        Ok(())
    }

    #[test]
    fn basename_fallback_never_walks_into_an_unrelated_ancestor()
    -> Result<(), Box<dyn std::error::Error>> {
        let (tree, mesh, _sidecar, _texture_directory) = direct_fixture("bounded-basename")?;
        fs::write(
            tree.0.join("fallback.dds"),
            cdmw_texture::synthetic::rgba8_checker_dds(),
        )?;

        assert!(matches!(
            resolve_direct_reference(&mesh, "fallback.dds"),
            DirectReferenceResolution::Missing
        ));
        assert!(matches!(
            resolve_direct_reference(&mesh, "../fallback.dds"),
            DirectReferenceResolution::Rejected(_)
        ));
        Ok(())
    }

    #[test]
    fn archive_model_path_derives_the_modelproperty_sidecar() {
        assert_eq!(
            material_sidecar_virtual_reference("character/model/body.pac").as_deref(),
            Some("character/modelproperty/body.pac_xml")
        );
        assert_eq!(
            material_sidecar_virtual_reference("object/model/prop.pamlod").as_deref(),
            Some("object/modelproperty/prop.pamlod_xml")
        );
        assert_eq!(
            replace_component(
                Path::new("model/extract/character/model/body.pac_xml"),
                "model",
                "modelproperty"
            )
            .as_deref(),
            Some(Path::new(
                "model/extract/character/modelproperty/body.pac_xml"
            ))
        );
    }

    #[test]
    fn archive_relation_prefers_an_exact_sidecar_path_over_same_name_candidates() {
        let catalog = catalog_with_paths(&[
            "character/modelproperty/body.pac_xml",
            "other/modelproperty/body.pac_xml",
        ]);
        let relation = resolve_archive_relation(
            &catalog,
            "character/model/body.pac",
            "character/modelproperty/body.pac_xml",
            RelationKind::MaterialSidecar,
            &["pac_xml"],
        );
        assert_eq!(
            relation.target_virtual_path.as_deref(),
            Some("character/modelproperty/body.pac_xml")
        );
        assert_eq!(relation.method, ResolutionMethod::ExplicitVirtualPath);
    }

    #[test]
    fn archive_relation_never_selects_an_ambiguous_texture_basename() {
        let catalog = catalog_with_paths(&["character/a/body.dds", "character/b/body.dds"]);
        let relation = resolve_archive_relation(
            &catalog,
            "character/modelproperty/body.pac_xml",
            "body.dds",
            RelationKind::BaseColorTexture,
            &["dds"],
        );
        assert!(relation.target_virtual_path.is_none());
        assert_eq!(relation.ambiguity_count, 2);
        assert_eq!(relation.method, ResolutionMethod::Unresolved);
    }

    #[test]
    #[ignore = "requires CDMW_RUST_MESH_PATH to name a caller-supplied mesh"]
    fn caller_selected_mesh_runs_the_real_headless_loader() -> Result<(), Box<dyn std::error::Error>>
    {
        let path = PathBuf::from(std::env::var("CDMW_RUST_MESH_PATH")?);
        let loaded = load_mesh(path, &CancellationToken::default())?;
        assert!(loaded.mesh.vertices().count() >= 3);
        assert!(loaded.mesh.faces().count() >= 1);
        assert_eq!(
            loaded.other_lod_meshes.len().saturating_add(1),
            loaded.document.lods.len()
        );
        if direct_material_sidecars(&loaded.path).is_empty()
            && texture_references(&loaded.document).is_empty()
        {
            assert!(loaded.textures.is_empty());
            assert!(loaded.document.warnings.iter().any(|warning| {
                warning.contains("No same-stem material sidecar")
                    || warning.contains("No decoded DDS reference")
            }));
        }
        assert!(
            !loaded.textures.is_empty()
                || loaded.document.warnings.iter().any(|warning| {
                    let lowered = warning.to_ascii_lowercase();
                    lowered.contains("texture") || lowered.contains("material sidecar")
                })
        );
        Ok(())
    }
}
