use cdmw_archive::{
    ArchiveCatalog, ArchiveLimits, CancellationToken, CatalogProgress, open_archive_root,
    read_entry_unverified,
};
use cdmw_formats::{MeshDocument, MeshFormat, decode_mesh};
use cdmw_mesh::WorkingMesh;
use cdmw_oracle::export_working_obj_cancellable;
use cdmw_texture::{DdsMetadata, TextureRole, inspect_dds};
use crossbeam_channel::{Receiver, Sender, TrySendError, bounded};
use std::fs;
use std::path::PathBuf;
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
    pub texture: Option<LoadedTexture>,
}

#[derive(Debug)]
pub struct LoadedTexture {
    pub label: String,
    pub metadata: DdsMetadata,
    pub bytes: Vec<u8>,
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
    let texture = resolve_archive_texture(catalog, catalog_entry, &document, cancellation)?;
    if let Some(texture) = &texture {
        document.warnings.push(format!(
            "viewport uses the exact archive DDS reference {}; multi-material composition is not yet implemented",
            texture.label
        ));
    }
    Ok(LoadedMesh {
        path,
        document,
        mesh,
        other_lod_meshes,
        texture,
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
    let texture = resolve_direct_texture(&path, &document)?;
    if let Some(texture) = &texture {
        document.warnings.push(format!(
            "viewport uses the explicit decoded DDS reference {}; multi-material composition is not yet implemented",
            texture.label
        ));
    }
    Ok(LoadedMesh {
        path,
        document,
        mesh,
        other_lod_meshes,
        texture,
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
    mesh_path: &std::path::Path,
    document: &MeshDocument,
) -> Result<Option<LoadedTexture>, String> {
    let Some(parent) = mesh_path.parent() else {
        return Ok(None);
    };
    for reference in texture_references(document) {
        let reference_path = std::path::Path::new(&reference);
        if reference_path.is_absolute()
            || reference_path.components().any(|component| {
                matches!(
                    component,
                    std::path::Component::ParentDir
                        | std::path::Component::RootDir
                        | std::path::Component::Prefix(_)
                )
            })
        {
            continue;
        }
        let candidates = [
            parent.join(reference_path),
            reference_path
                .file_name()
                .map_or_else(|| parent.join(""), |name| parent.join(name)),
        ];
        for candidate in candidates {
            if !candidate.is_file() {
                continue;
            }
            let bytes = fs::read(&candidate)
                .map_err(|error| format!("failed to read DDS {}: {error}", candidate.display()))?;
            let metadata = inspect_dds(&bytes, TextureRole::BaseColor)
                .map_err(|error| format!("DDS {} is unsupported: {error}", candidate.display()))?;
            return Ok(Some(LoadedTexture {
                label: candidate
                    .file_name()
                    .and_then(|name| name.to_str())
                    .unwrap_or("texture.dds")
                    .to_owned(),
                metadata,
                bytes,
            }));
        }
    }
    Ok(None)
}

fn resolve_archive_texture(
    catalog: &ArchiveCatalog,
    source: &cdmw_archive::CatalogEntry,
    document: &MeshDocument,
    cancellation: &CancellationToken,
) -> Result<Option<LoadedTexture>, String> {
    let source_directory = source
        .entry
        .virtual_path
        .rsplit_once('/')
        .map_or("", |(directory, _)| directory);
    for reference in texture_references(document) {
        let normalized = reference
            .replace('\\', "/")
            .trim_start_matches('/')
            .to_ascii_lowercase();
        if normalized.split('/').any(|component| component == "..") {
            continue;
        }
        let relative = format!("{source_directory}/{normalized}")
            .trim_start_matches('/')
            .to_owned();
        let matches = catalog
            .entries
            .iter()
            .filter(|candidate| {
                let path = candidate.entry.virtual_path.to_ascii_lowercase();
                path == normalized || path == relative
            })
            .collect::<Vec<_>>();
        let Some(candidate) = matches.first().filter(|_| matches.len() == 1) else {
            continue;
        };
        let payload_root = catalog
            .indexes
            .get(candidate.index_id)
            .ok_or_else(|| "DDS selection references a missing archive index".to_owned())?
            .parent()
            .ok_or_else(|| "DDS archive index has no payload directory".to_owned())?;
        let decoded = read_entry_unverified(
            payload_root,
            &candidate.entry,
            ArchiveLimits::default(),
            cancellation,
        )
        .map_err(|error| error.to_string())?;
        let metadata = inspect_dds(&decoded.bytes, TextureRole::BaseColor)
            .map_err(|error| error.to_string())?;
        return Ok(Some(LoadedTexture {
            label: candidate.entry.virtual_path.clone(),
            metadata,
            bytes: decoded.bytes,
        }));
    }
    Ok(None)
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
