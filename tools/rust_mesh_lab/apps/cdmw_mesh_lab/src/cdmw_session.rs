#![forbid(unsafe_code)]

use cdmw_formats::{MeshDocument, MeshFormat, MeshLod, SourceRange, Submesh};
use cdmw_mesh::{Provenance, WorkingMesh};
use cdmw_texture::{DdsMetadata, TextureRole, inspect_dds};
use crossbeam_channel::{Receiver, Sender, TryRecvError, bounded};
use serde::{Deserialize, Serialize, de::IgnoredAny};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, OpenOptions};
use std::io::{BufRead, BufReader, BufWriter, Write};
use std::path::{Component, Path, PathBuf};
use std::thread;
use thiserror::Error;

pub const PROTOCOL: &str = "cdmw_rust_mesh_editor_protocol_v1";
pub const PACKAGE_SCHEMA: &str = "cdmw_rust_mesh_authoring_package_v1";
pub const PREVIEW_PROTOCOL: &str = "cdmw_rust_preview_protocol_v1";
pub const PREVIEW_PACKAGE_SCHEMA: &str = "cdmw_rust_preview_package_v1";
pub const PREVIEW_BACKEND: &str = "cdmw_rust_preview_0.1";
pub const CANDIDATE_SCHEMA: &str = "cdmw_rust_mesh_candidate_v1";
pub const RENDERER: &str = "wgpu_d3d12_rust";
pub const EDIT_BACKEND: &str = "cdmw_rust_mesh_0.1";
const MAX_PAYLOAD_BYTES: u64 = 512 * 1024 * 1024;
const MAX_MANIFEST_BYTES: u64 = 16 * 1024 * 1024;
const MAX_CONTROL_LINE_BYTES: usize = 256 * 1024;
const CONTROL_QUEUE_BOUND: usize = 256;
const OUTBOUND_QUEUE_BOUND: usize = 64;
const MAX_PROFILE_FILE_BYTES: u64 = 8 * 1024 * 1024;
const MAX_PROFILE_TOTAL_BYTES: u64 = 64 * 1024 * 1024;
const MAX_PROFILE_ENTRIES: usize = 4_096;
const MAX_PROFILE_DEPTH: usize = 4;
const MAX_TEXTURE_RESOURCES: usize = 4_096;
const MAX_TEXTURE_TOTAL_BYTES: u64 = 512 * 1024 * 1024;
const MAX_MATERIAL_PRESENTATIONS: usize = 2_048;
const MAX_PREVIEW_CORE_BATCHES: usize = 4_096;
const MAX_PREVIEW_CORE_VERTICES: usize = 2_000_000;
const PREVIEW_CORE_VERTEX_BYTES: usize = 23 * std::mem::size_of::<f32>();
const PREVIEW_CORE_IDENTITY_BYTES: usize = 2 * std::mem::size_of::<i32>();

#[derive(Debug, Error)]
pub enum SessionError {
    #[error("CDMW Rust session manifest is invalid: {0}")]
    InvalidManifest(String),
    #[error("CDMW Rust session payload is invalid: {0}")]
    InvalidPayload(String),
    #[error("CDMW Rust session protocol failed: {0}")]
    Protocol(String),
    #[error("CDMW Rust session IO failed: {0}")]
    Io(#[from] std::io::Error),
    #[error("CDMW Rust session JSON failed: {0}")]
    Json(#[from] serde_json::Error),
}

#[derive(Debug, Clone, Deserialize)]
pub struct FileReference {
    pub path: String,
    pub data_type: String,
    pub count: u64,
    pub byte_length: u64,
    pub sha256: String,
    pub content_type: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct SessionTextureReference {
    pub label: String,
    pub role: TextureRole,
    pub file: FileReference,
    pub material_indices_by_lod: Vec<Vec<u32>>,
}

#[derive(Debug, Clone)]
pub struct CdmwTextureResource {
    pub label: String,
    pub role: TextureRole,
    pub metadata: DdsMetadata,
    pub bytes: Vec<u8>,
    pub material_indices_by_lod: Vec<Vec<u32>>,
}

#[derive(Debug, Clone, Deserialize, PartialEq)]
pub struct SessionMaterialPresentation {
    pub lod_index: u32,
    pub material_index: u32,
    pub material_slot_index: u32,
    pub material_category: String,
    pub category_code: u32,
    pub category_confidence: f32,
    pub shader_family: String,
    pub normal_y_policy: String,
    pub normal_y_inverted: bool,
    pub alpha_mode: String,
    pub alpha_cutoff: Option<f32>,
    pub double_sided: bool,
    pub roughness: Option<f32>,
    pub metalness: Option<f32>,
    pub specular: Option<f32>,
    pub emissive_color: Option<[f32; 3]>,
    pub emissive_intensity: Option<f32>,
    pub height_scale: Option<f32>,
    pub texture_tint: Option<[f32; 3]>,
    pub base_tint_strength: Option<f32>,
    pub hair_anisotropy: bool,
    pub skin_detail_scale: Option<f32>,
    pub skin_detail_opacity: Option<f32>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct PreviewCoreGeometryBatch {
    pub index: u32,
    pub name: String,
    pub material: String,
    pub vertex_count: u64,
    pub vertices: FileReference,
    pub identity: Option<FileReference>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct PreviewCoreGeometry {
    pub schema_version: u64,
    pub format: String,
    #[serde(default)]
    pub source_sha256: String,
    pub normalization_center: [f32; 3],
    pub normalization_scale: f32,
    pub batches: Vec<PreviewCoreGeometryBatch>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct SessionManifest {
    pub schema: String,
    pub protocol: String,
    pub session_id: String,
    pub process_generation: u64,
    pub base_revision: u64,
    pub shadow_revision: u64,
    pub renderer: String,
    pub edit_backend: String,
    pub document: FileReference,
    pub channels: FileReference,
    #[serde(default)]
    pub preview_core_geometry: Option<PreviewCoreGeometry>,
    #[serde(default)]
    pub textures: Vec<SessionTextureReference>,
    #[serde(default)]
    pub material_presentations: Vec<SessionMaterialPresentation>,
    #[serde(default)]
    pub texture_status: Value,
    #[serde(default)]
    pub source: Value,
    #[serde(default)]
    pub output_policy: Value,
    #[serde(default)]
    pub theme: Value,
    #[serde(default)]
    pub state: Value,
    #[serde(default)]
    pub interaction_profile: String,
}

#[derive(Debug, Clone)]
enum Incoming {
    Message(Value),
    LocalError(String),
}

#[derive(Debug, Clone)]
enum Outbound {
    Message(Value),
    Transaction {
        request_id: u64,
        base_revision: u64,
        lod_index: usize,
        label: String,
        document: MeshDocument,
        mesh: Box<WorkingMesh>,
    },
}

#[derive(Debug, Clone)]
pub enum HostEvent {
    Hello,
    Ready,
    Theme(Value),
    Result {
        event: String,
        request_id: u64,
        base_revision: u64,
        ok: bool,
        payload: Value,
        error: String,
    },
    StateSnapshot(Value),
    Cancel(String),
    Fatal(String),
}

#[derive(Debug, Clone, Copy)]
pub struct PreparedRevision {
    previous_revision: u64,
    accepted_revision: u64,
    request_id: u64,
    state_snapshot: bool,
}

#[derive(Debug)]
pub struct PreparedHostResult {
    revision: PreparedRevision,
    state: Option<Value>,
    document: Option<MeshDocument>,
}

impl PreparedHostResult {
    #[must_use]
    pub fn into_parts(self) -> (PreparedRevision, Option<Value>, Option<MeshDocument>) {
        (self.revision, self.state, self.document)
    }
}

#[derive(Debug)]
pub struct LoadedCdmwSessionPackage {
    root: PathBuf,
    manifest: SessionManifest,
    document: MeshDocument,
    source_lod_index: usize,
    textures: Vec<CdmwTextureResource>,
}

impl LoadedCdmwSessionPackage {
    pub fn load(manifest_path: &Path) -> Result<Self, SessionError> {
        Self::load_for(manifest_path, PACKAGE_SCHEMA, PROTOCOL, EDIT_BACKEND)
    }

    pub fn load_preview(manifest_path: &Path) -> Result<Self, SessionError> {
        Self::load_for(
            manifest_path,
            PREVIEW_PACKAGE_SCHEMA,
            PREVIEW_PROTOCOL,
            PREVIEW_BACKEND,
        )
    }

    fn load_for(
        manifest_path: &Path,
        expected_schema: &str,
        expected_protocol: &str,
        expected_backend: &str,
    ) -> Result<Self, SessionError> {
        let manifest_path = fs::canonicalize(manifest_path)?;
        if manifest_path.file_name().and_then(|name| name.to_str()) != Some("manifest.json") {
            return Err(SessionError::InvalidManifest(
                "the manifest must be named manifest.json".to_owned(),
            ));
        }
        let root = manifest_path
            .parent()
            .ok_or_else(|| SessionError::InvalidManifest("manifest has no parent".to_owned()))?
            .to_path_buf();
        let manifest_bytes = read_limited(&manifest_path, MAX_MANIFEST_BYTES)?;
        let manifest: SessionManifest = serde_json::from_slice(&manifest_bytes)?;
        validate_manifest_for(
            &manifest,
            expected_schema,
            expected_protocol,
            expected_backend,
        )?;
        let document_bytes = read_json_reference(&root, &manifest.document)?;
        // Channels are integrity-checked authoring provenance. The renderer
        // consumes geometry from document.json, so validate the JSON stream
        // without allocating a second full serde Value tree during startup.
        let _: IgnoredAny =
            serde_json::from_slice(&read_json_reference(&root, &manifest.channels)?)?;
        reject_unexpected_initial_files(&root, &manifest)?;
        let document: MeshDocument = if expected_schema == PREVIEW_PACKAGE_SCHEMA {
            if let Some(geometry) = &manifest.preview_core_geometry {
                let _: IgnoredAny = serde_json::from_slice(&document_bytes)?;
                decode_preview_core_document(&root, geometry)?
            } else {
                serde_json::from_slice(&document_bytes)?
            }
        } else {
            serde_json::from_slice(&document_bytes)?
        };
        validate_document(&document)?;
        validate_material_presentations(&manifest, &document)?;
        let textures = read_texture_resources(&root, &manifest, &document)?;
        let source_lod_index = manifest_source_lod_index(&manifest)?;
        if source_lod_index >= document.lods.len() {
            return Err(SessionError::InvalidManifest(format!(
                "source LOD {source_lod_index} is not present in the authoring document"
            )));
        }
        Ok(Self {
            root,
            manifest,
            document,
            source_lod_index,
            textures,
        })
    }

    #[must_use]
    pub fn root(&self) -> &Path {
        &self.root
    }

    #[must_use]
    pub fn manifest(&self) -> &SessionManifest {
        &self.manifest
    }

    #[must_use]
    pub const fn source_lod_index(&self) -> usize {
        self.source_lod_index
    }

    #[must_use]
    pub fn document(&self) -> &MeshDocument {
        &self.document
    }

    pub fn take_textures(&mut self) -> Vec<CdmwTextureResource> {
        std::mem::take(&mut self.textures)
    }

    pub fn take_material_presentations(&mut self) -> Vec<SessionMaterialPresentation> {
        std::mem::take(&mut self.manifest.material_presentations)
    }
}

#[derive(Debug)]
pub struct CdmwBridge {
    root: PathBuf,
    manifest: SessionManifest,
    incoming: Receiver<Incoming>,
    outbound: Sender<Outbound>,
    next_request_id: u64,
    shadow_revision: u64,
    source_lod_index: usize,
    textures: Vec<CdmwTextureResource>,
    last_result_request_id: u64,
    state_snapshot_accepted: bool,
}

impl CdmwBridge {
    pub fn open(manifest_path: &Path) -> Result<(Self, MeshDocument), SessionError> {
        let package = LoadedCdmwSessionPackage::load(manifest_path)?;
        let LoadedCdmwSessionPackage {
            root,
            manifest,
            document,
            source_lod_index,
            textures,
        } = package;
        let (incoming_tx, incoming_rx) = bounded(CONTROL_QUEUE_BOUND);
        let (outbound_tx, outbound_rx) = bounded(OUTBOUND_QUEUE_BOUND);
        spawn_input_reader(incoming_tx.clone());
        spawn_output_writer(
            root.clone(),
            manifest.session_id.clone(),
            manifest.process_generation,
            incoming_tx,
            outbound_rx,
        );
        let shadow_revision = manifest.shadow_revision;
        Ok((
            Self {
                root,
                manifest,
                incoming: incoming_rx,
                outbound: outbound_tx,
                next_request_id: 0,
                shadow_revision,
                source_lod_index,
                textures,
                last_result_request_id: 0,
                state_snapshot_accepted: false,
            },
            document,
        ))
    }

    #[must_use]
    pub fn manifest(&self) -> &SessionManifest {
        &self.manifest
    }

    #[must_use]
    pub const fn shadow_revision(&self) -> u64 {
        self.shadow_revision
    }

    #[must_use]
    pub const fn source_lod_index(&self) -> usize {
        self.source_lod_index
    }

    pub fn take_textures(&mut self) -> Vec<CdmwTextureResource> {
        std::mem::take(&mut self.textures)
    }

    pub fn take_material_presentations(&mut self) -> Vec<SessionMaterialPresentation> {
        std::mem::take(&mut self.manifest.material_presentations)
    }

    pub fn prepare_host_result(
        &self,
        expected_event: &str,
        expected_request_id: u64,
        event: &str,
        request_id: u64,
        base_revision: u64,
        ok: bool,
        payload: &Value,
    ) -> Result<PreparedHostResult, SessionError> {
        if request_id == 0
            || request_id != expected_request_id
            || event != expected_event
            || !matches!(
                event,
                "transaction_result" | "command_result" | "finish_result"
            )
        {
            return Err(SessionError::Protocol(format!(
                "host result is out of order: expected {expected_event} for request \
                 {expected_request_id}, received {event} for request {request_id}"
            )));
        }
        if request_id <= self.last_result_request_id {
            return Err(SessionError::Protocol(format!(
                "host replayed result request {request_id}; last accepted request is {}",
                self.last_result_request_id
            )));
        }
        if base_revision < self.shadow_revision {
            return Err(SessionError::Protocol(format!(
                "host shadow revision moved backwards: current={}, received={base_revision}",
                self.shadow_revision
            )));
        }
        let state = result_state(event, ok, payload)?;
        let document = match &state {
            Some(state) => {
                validate_state_identity(state, &self.manifest, base_revision)?;
                self.document_from_state(state)?
            }
            None => None,
        };
        Ok(PreparedHostResult {
            revision: PreparedRevision {
                previous_revision: self.shadow_revision,
                accepted_revision: base_revision,
                request_id,
                state_snapshot: false,
            },
            state,
            document,
        })
    }

    pub fn prepare_state_snapshot(&self, state: Value) -> Result<PreparedHostResult, SessionError> {
        if self.state_snapshot_accepted || self.last_result_request_id != 0 {
            return Err(SessionError::Protocol(
                "host state snapshot was replayed or arrived after a result".to_owned(),
            ));
        }
        let base_revision = required_u64(&state, "base_revision")?;
        if base_revision < self.shadow_revision {
            return Err(SessionError::Protocol(format!(
                "host state snapshot is stale: current={}, received={base_revision}",
                self.shadow_revision
            )));
        }
        validate_state_identity(&state, &self.manifest, base_revision)?;
        let document = self.document_from_state(&state)?;
        Ok(PreparedHostResult {
            revision: PreparedRevision {
                previous_revision: self.shadow_revision,
                accepted_revision: base_revision,
                request_id: self.last_result_request_id,
                state_snapshot: true,
            },
            state: Some(state),
            document,
        })
    }

    pub fn accept_prepared_revision(
        &mut self,
        prepared: PreparedRevision,
    ) -> Result<(), SessionError> {
        if self.shadow_revision != prepared.previous_revision
            || prepared.accepted_revision < self.shadow_revision
            || prepared.request_id < self.last_result_request_id
            || (prepared.state_snapshot && self.state_snapshot_accepted)
        {
            return Err(SessionError::Protocol(
                "prepared host result became stale before publication".to_owned(),
            ));
        }
        self.shadow_revision = prepared.accepted_revision;
        if prepared.state_snapshot {
            self.state_snapshot_accepted = true;
        } else {
            self.last_result_request_id = self.last_result_request_id.max(prepared.request_id);
        }
        Ok(())
    }

    pub fn announce_ready(
        &self,
        child_hwnd: u64,
        embedded_parent_hwnd: u64,
    ) -> Result<(), SessionError> {
        self.send_message(json!({
            "event": "hello",
            "protocol": PROTOCOL,
            "session_id": self.manifest.session_id,
            "request_id": 0,
            "base_revision": self.shadow_revision,
            "process_generation": self.manifest.process_generation,
            "renderer": RENDERER,
            "edit_backend": EDIT_BACKEND,
            "child_hwnd": child_hwnd,
            "embedded_parent_hwnd": embedded_parent_hwnd,
            "capabilities": [
                "embedded_child_window_v1",
                "local_selection_v1",
                "local_sculpt_v1",
                "host_topology_v1",
                "host_layers_v1",
                "host_morph_refit_v1",
                "control_contract_v2"
            ]
        }))?;
        self.send_message(json!({
            "event": "ready",
            "protocol": PROTOCOL,
            "session_id": self.manifest.session_id,
            "request_id": 0,
            "base_revision": self.shadow_revision,
            "process_generation": self.manifest.process_generation,
            "renderer": RENDERER,
            "edit_backend": EDIT_BACKEND
        }))
    }

    pub fn submit_transaction(
        &mut self,
        document: &MeshDocument,
        mesh: &WorkingMesh,
        label: impl Into<String>,
    ) -> Result<u64, SessionError> {
        let request_id = self.take_request_id();
        self.outbound
            .try_send(Outbound::Transaction {
                request_id,
                base_revision: self.shadow_revision,
                lod_index: self.source_lod_index,
                label: label.into(),
                document: document.clone(),
                mesh: Box::new(mesh.clone()),
            })
            .map_err(|error| SessionError::Protocol(format!("outbound queue is busy: {error}")))?;
        Ok(request_id)
    }

    pub fn submit_command(&mut self, command: &str, arguments: Value) -> Result<u64, SessionError> {
        let request_id = self.take_request_id();
        self.send_message(json!({
            "event": "command_request",
            "protocol": PROTOCOL,
            "session_id": self.manifest.session_id,
            "request_id": request_id,
            "base_revision": self.shadow_revision,
            "process_generation": self.manifest.process_generation,
            "command": command,
            "arguments": arguments
        }))?;
        Ok(request_id)
    }

    pub fn submit_finish(&mut self) -> Result<u64, SessionError> {
        let request_id = self.take_request_id();
        self.send_message(json!({
            "event": "finish_request",
            "protocol": PROTOCOL,
            "session_id": self.manifest.session_id,
            "request_id": request_id,
            "base_revision": self.shadow_revision,
            "process_generation": self.manifest.process_generation
        }))?;
        Ok(request_id)
    }

    pub fn cancel(&mut self, reason: &str) -> Result<(), SessionError> {
        let request_id = self.take_request_id();
        self.send_message(json!({
            "event": "cancel",
            "protocol": PROTOCOL,
            "session_id": self.manifest.session_id,
            "request_id": request_id,
            "base_revision": self.shadow_revision,
            "process_generation": self.manifest.process_generation,
            "reason": reason
        }))
    }

    pub fn poll(&mut self) -> Vec<HostEvent> {
        let mut events = Vec::new();
        loop {
            match self.incoming.try_recv() {
                Ok(Incoming::Message(value)) => events.push(self.decode_host_event(value)),
                Ok(Incoming::LocalError(message)) => events.push(HostEvent::Fatal(message)),
                Err(TryRecvError::Empty) => break,
                Err(TryRecvError::Disconnected) => {
                    events.push(HostEvent::Fatal(
                        "CDMW control input disconnected".to_owned(),
                    ));
                    break;
                }
            }
        }
        events
    }

    pub fn document_from_state(&self, state: &Value) -> Result<Option<MeshDocument>, SessionError> {
        let Some(reference_value) = state.get("document") else {
            return Ok(None);
        };
        let reference: FileReference = serde_json::from_value(reference_value.clone())?;
        let bytes = read_json_reference(&self.root, &reference)?;
        let document: MeshDocument = serde_json::from_slice(&bytes)?;
        validate_document(&document)?;
        Ok(Some(document))
    }

    fn take_request_id(&mut self) -> u64 {
        self.next_request_id = self.next_request_id.saturating_add(1).max(1);
        self.next_request_id
    }

    fn send_message(&self, value: Value) -> Result<(), SessionError> {
        self.outbound
            .try_send(Outbound::Message(value))
            .map_err(|error| SessionError::Protocol(format!("outbound queue is busy: {error}")))
    }

    #[cfg(test)]
    pub(crate) fn for_test(
        root: PathBuf,
        session_id: &str,
        process_generation: u64,
        shadow_revision: u64,
    ) -> Self {
        let root = fs::canonicalize(&root).unwrap_or(root);
        let (_incoming_tx, incoming) = bounded(CONTROL_QUEUE_BOUND);
        let (outbound, outbound_rx) = bounded(OUTBOUND_QUEUE_BOUND);
        // Production drains this queue through the JSONL writer. Keep the test queue connected
        // so UI tests prove successful submission instead of a disconnected-channel path.
        drop(std::thread::spawn(
            move || {
                while outbound_rx.recv().is_ok() {}
            },
        ));
        let empty_reference = FileReference {
            path: "unused.json".to_owned(),
            data_type: "mesh_document_json".to_owned(),
            count: 1,
            byte_length: 0,
            sha256: String::new(),
            content_type: "application/json".to_owned(),
        };
        Self {
            root,
            manifest: SessionManifest {
                schema: PACKAGE_SCHEMA.to_owned(),
                protocol: PROTOCOL.to_owned(),
                session_id: session_id.to_owned(),
                process_generation,
                base_revision: shadow_revision,
                shadow_revision,
                renderer: RENDERER.to_owned(),
                edit_backend: EDIT_BACKEND.to_owned(),
                document: empty_reference.clone(),
                channels: empty_reference,
                preview_core_geometry: None,
                textures: Vec::new(),
                material_presentations: Vec::new(),
                texture_status: Value::Null,
                source: Value::Null,
                output_policy: Value::Null,
                theme: Value::Null,
                state: Value::Null,
                interaction_profile: String::new(),
            },
            incoming,
            outbound,
            next_request_id: 0,
            shadow_revision,
            source_lod_index: 0,
            textures: Vec::new(),
            last_result_request_id: 0,
            state_snapshot_accepted: false,
        }
    }

    #[cfg(test)]
    pub(crate) fn for_test_with_source_lod(
        root: PathBuf,
        session_id: &str,
        process_generation: u64,
        shadow_revision: u64,
        source_lod_index: usize,
    ) -> Self {
        let mut bridge = Self::for_test(root, session_id, process_generation, shadow_revision);
        bridge.source_lod_index = source_lod_index;
        bridge.manifest.source = json!({"lod_index": source_lod_index});
        bridge
    }

    #[cfg(test)]
    pub(crate) fn for_test_with_textures(
        root: PathBuf,
        session_id: &str,
        process_generation: u64,
        shadow_revision: u64,
        textures: Vec<CdmwTextureResource>,
    ) -> Self {
        let mut bridge = Self::for_test(root, session_id, process_generation, shadow_revision);
        bridge.textures = textures;
        bridge
    }

    fn decode_host_event(&mut self, value: Value) -> HostEvent {
        let result = (|| {
            validate_identity(&value, &self.manifest)?;
            let event = value
                .get("event")
                .and_then(Value::as_str)
                .ok_or_else(|| SessionError::Protocol("host event is missing".to_owned()))?;
            match event {
                "hello" => Ok(HostEvent::Hello),
                "ready" => Ok(HostEvent::Ready),
                "state_snapshot" => Ok(HostEvent::StateSnapshot(
                    value.get("payload").cloned().unwrap_or(Value::Null),
                )),
                "theme_update" => Ok(HostEvent::Theme(
                    value.get("payload").cloned().unwrap_or(Value::Null),
                )),
                "transaction_result" | "command_result" | "finish_result" => {
                    let request_id = required_u64(&value, "request_id")?;
                    let base_revision = required_u64(&value, "base_revision")?;
                    let ok = value.get("ok").and_then(Value::as_bool).unwrap_or(false);
                    Ok(HostEvent::Result {
                        event: event.to_owned(),
                        request_id,
                        base_revision,
                        ok,
                        payload: value.get("payload").cloned().unwrap_or(Value::Null),
                        error: value
                            .get("error")
                            .and_then(Value::as_str)
                            .unwrap_or_default()
                            .to_owned(),
                    })
                }
                "cancel" | "cancelled" => Ok(HostEvent::Cancel(
                    value
                        .get("reason")
                        .and_then(Value::as_str)
                        .unwrap_or("CDMW cancelled the Rust session")
                        .to_owned(),
                )),
                "error" => Ok(HostEvent::Fatal(
                    value
                        .get("error")
                        .or_else(|| value.get("message"))
                        .and_then(Value::as_str)
                        .unwrap_or("CDMW reported a protocol error")
                        .to_owned(),
                )),
                _ => Err(SessionError::Protocol(format!(
                    "host sent unsupported event {event}"
                ))),
            }
        })();
        result.unwrap_or_else(|error| HostEvent::Fatal(error.to_string()))
    }
}

fn validate_manifest_for(
    manifest: &SessionManifest,
    expected_schema: &str,
    expected_protocol: &str,
    expected_backend: &str,
) -> Result<(), SessionError> {
    if manifest.schema != expected_schema
        || manifest.protocol != expected_protocol
        || manifest.renderer != RENDERER
        || manifest.edit_backend != expected_backend
    {
        return Err(SessionError::InvalidManifest(
            "schema, protocol, renderer, or edit backend does not match".to_owned(),
        ));
    }
    if manifest.session_id.trim().is_empty() || manifest.process_generation == 0 {
        return Err(SessionError::InvalidManifest(
            "session id and process generation are required".to_owned(),
        ));
    }
    if manifest.preview_core_geometry.is_some() && expected_schema != PREVIEW_PACKAGE_SCHEMA {
        return Err(SessionError::InvalidManifest(
            "Preview Core geometry is allowed only in read-only preview packages".to_owned(),
        ));
    }
    Ok(())
}

fn manifest_source_lod_index(manifest: &SessionManifest) -> Result<usize, SessionError> {
    let Some(value) = manifest.source.get("lod_index") else {
        return Ok(0);
    };
    let raw = value.as_u64().ok_or_else(|| {
        SessionError::InvalidManifest("source.lod_index must be a non-negative integer".to_owned())
    })?;
    usize::try_from(raw).map_err(|_| {
        SessionError::InvalidManifest("source.lod_index exceeds this platform".to_owned())
    })
}

fn validate_document(document: &MeshDocument) -> Result<(), SessionError> {
    if document.lods.is_empty() || document.lods.iter().all(|lod| lod.submeshes.is_empty()) {
        return Err(SessionError::InvalidPayload(
            "mesh document is empty".to_owned(),
        ));
    }
    for submesh in document.lods.iter().flat_map(|lod| &lod.submeshes) {
        submesh
            .validate()
            .map_err(|error| SessionError::InvalidPayload(error.to_string()))?;
    }
    Ok(())
}

fn material_category_code(category: &str) -> Option<u32> {
    match category {
        "generic" => Some(0),
        "metal" => Some(1),
        "leather" => Some(2),
        "wood" => Some(3),
        "cloth" => Some(4),
        "skin" => Some(5),
        "hair" => Some(6),
        "glass" => Some(7),
        "gem" => Some(8),
        "stone" => Some(9),
        "eye" => Some(10),
        "tooth" => Some(11),
        _ => None,
    }
}

fn validate_optional_factor(
    value: Option<f32>,
    minimum: f32,
    maximum: f32,
    label: &str,
) -> Result<(), SessionError> {
    if value.is_some_and(|number| !number.is_finite() || number < minimum || number > maximum) {
        return Err(SessionError::InvalidManifest(format!(
            "material {label} is outside {minimum}..={maximum}"
        )));
    }
    Ok(())
}

fn validate_material_presentations(
    manifest: &SessionManifest,
    document: &MeshDocument,
) -> Result<(), SessionError> {
    let maximum_owned_rows = document
        .lods
        .iter()
        .try_fold(0_usize, |total, lod| total.checked_add(lod.submeshes.len()))
        .ok_or_else(|| {
            SessionError::InvalidManifest(
                "material presentation ownership exceeds this platform".to_owned(),
            )
        })?
        .min(MAX_MATERIAL_PRESENTATIONS);
    if manifest.material_presentations.len() > maximum_owned_rows {
        return Err(SessionError::InvalidManifest(
            "the session contains too many material presentation rows".to_owned(),
        ));
    }
    let mut owners = BTreeSet::new();
    for row in &manifest.material_presentations {
        let lod_index = usize::try_from(row.lod_index).map_err(|_| {
            SessionError::InvalidManifest(
                "material presentation LOD index exceeds this platform".to_owned(),
            )
        })?;
        let material_index = usize::try_from(row.material_index).map_err(|_| {
            SessionError::InvalidManifest(
                "material presentation index exceeds this platform".to_owned(),
            )
        })?;
        if document
            .lods
            .get(lod_index)
            .is_none_or(|lod| material_index >= lod.submeshes.len())
        {
            return Err(SessionError::InvalidManifest(format!(
                "LOD{} material presentation contains invalid material {}",
                row.lod_index, row.material_index
            )));
        }
        if !owners.insert((row.lod_index, row.material_index)) {
            return Err(SessionError::InvalidManifest(format!(
                "LOD{} material {} has duplicate presentation rows",
                row.lod_index, row.material_index
            )));
        }
        let Some(expected_category_code) = material_category_code(&row.material_category) else {
            return Err(SessionError::InvalidManifest(format!(
                "material category {:?} is not canonical",
                row.material_category
            )));
        };
        if row.category_code != expected_category_code {
            return Err(SessionError::InvalidManifest(format!(
                "material category {} does not match code {}",
                row.material_category, row.category_code
            )));
        }
        if !row.category_confidence.is_finite() || !(0.0..=1.0).contains(&row.category_confidence) {
            return Err(SessionError::InvalidManifest(
                "material category confidence is outside 0..=1".to_owned(),
            ));
        }
        let shader_family = row.shader_family.trim();
        if shader_family.is_empty()
            || shader_family.len() > 64
            || shader_family.chars().any(char::is_control)
        {
            return Err(SessionError::InvalidManifest(
                "material shader family is missing or invalid".to_owned(),
            ));
        }
        let expected_normal_y_inverted = match row.normal_y_policy.as_str() {
            "preserve" => false,
            "invert_green_for_directx" => true,
            _ => {
                return Err(SessionError::InvalidManifest(format!(
                    "material normal-Y policy {:?} is invalid",
                    row.normal_y_policy
                )));
            }
        };
        if row.normal_y_inverted != expected_normal_y_inverted {
            return Err(SessionError::InvalidManifest(
                "material normal-Y flag does not match its policy".to_owned(),
            ));
        }
        if !matches!(row.alpha_mode.as_str(), "opaque" | "cutout" | "blend") {
            return Err(SessionError::InvalidManifest(format!(
                "material alpha mode {:?} is invalid",
                row.alpha_mode
            )));
        }
        validate_optional_factor(row.alpha_cutoff, 0.0, 1.0, "alpha cutoff")?;
        validate_optional_factor(row.roughness, 0.0, 1.0, "roughness")?;
        validate_optional_factor(row.metalness, 0.0, 1.0, "metalness")?;
        validate_optional_factor(row.specular, 0.0, 1.0, "specular")?;
        validate_optional_factor(row.emissive_intensity, 0.0, 32.0, "emissive intensity")?;
        validate_optional_factor(row.height_scale, 0.0, 1.0, "height scale")?;
        validate_optional_factor(row.base_tint_strength, 0.0, 1.0, "base tint strength")?;
        validate_optional_factor(row.skin_detail_scale, 0.001, 1.0, "skin detail scale")?;
        validate_optional_factor(row.skin_detail_opacity, 0.0, 1.0, "skin detail opacity")?;
        if row.emissive_color.is_some_and(|color| {
            color
                .into_iter()
                .any(|component| !component.is_finite() || !(0.0..=2.0).contains(&component))
        }) {
            return Err(SessionError::InvalidManifest(
                "material emissive color is outside 0..=2".to_owned(),
            ));
        }
        if row.texture_tint.is_some_and(|color| {
            color
                .into_iter()
                .any(|component| !component.is_finite() || !(0.0..=2.0).contains(&component))
        }) {
            return Err(SessionError::InvalidManifest(
                "material texture tint is outside 0..=2".to_owned(),
            ));
        }
    }
    Ok(())
}

fn preview_core_f32(record: &[u8], offset: usize) -> f32 {
    let mut bytes = [0_u8; std::mem::size_of::<f32>()];
    bytes.copy_from_slice(&record[offset..offset + std::mem::size_of::<f32>()]);
    f32::from_le_bytes(bytes)
}

fn preview_core_i32(record: &[u8], offset: usize) -> i32 {
    let mut bytes = [0_u8; std::mem::size_of::<i32>()];
    bytes.copy_from_slice(&record[offset..offset + std::mem::size_of::<i32>()]);
    i32::from_le_bytes(bytes)
}

fn is_owned_preview_core_filename(value: &str, role: &str) -> bool {
    let Some(stem) = value.strip_suffix(".bin") else {
        return false;
    };
    let mut parts = stem.split('-');
    matches!(parts.next(), Some("preview"))
        && parts.next() == Some(role)
        && parts.next().is_some_and(|index| {
            index.len() == 4 && index.bytes().all(|byte| byte.is_ascii_digit())
        })
        && parts.next().is_some_and(|hash| {
            hash.len() == 12 && hash.bytes().all(|byte| byte.is_ascii_hexdigit())
        })
        && parts.next().is_none()
}

fn read_preview_core_reference(
    root: &Path,
    reference: &FileReference,
    role: &str,
    data_type: &str,
    element_count: u64,
    element_bytes: usize,
) -> Result<Vec<u8>, SessionError> {
    let expected_length = element_count
        .checked_mul(u64::try_from(element_bytes).map_err(|_| {
            SessionError::InvalidPayload(
                "Preview Core element size exceeds this platform".to_owned(),
            )
        })?)
        .ok_or_else(|| {
            SessionError::InvalidPayload("Preview Core payload size overflowed".to_owned())
        })?;
    if reference.content_type != "application/octet-stream"
        || reference.data_type != data_type
        || reference.count != element_count
        || reference.byte_length != expected_length
        || !is_owned_preview_core_filename(&reference.path, role)
    {
        return Err(SessionError::InvalidPayload(format!(
            "Preview Core {role} reference does not match its binary contract"
        )));
    }
    let relative = Path::new(&reference.path);
    let mut components = relative.components();
    if !matches!(components.next(), Some(Component::Normal(_))) || components.next().is_some() {
        return Err(SessionError::InvalidPayload(format!(
            "Preview Core {role} path must be one owned filename"
        )));
    }
    let candidate = fs::canonicalize(root.join(relative))?;
    if candidate.parent() != Some(root) || !candidate.is_file() {
        return Err(SessionError::InvalidPayload(format!(
            "Preview Core {role} path escaped the session root"
        )));
    }
    let metadata = candidate.metadata()?;
    if metadata.len() != expected_length || metadata.len() > MAX_PAYLOAD_BYTES {
        return Err(SessionError::InvalidPayload(format!(
            "Preview Core {role} size does not match"
        )));
    }
    let bytes = read_limited(&candidate, MAX_PAYLOAD_BYTES)?;
    if sha256_upper(&bytes) != reference.sha256.trim().to_ascii_uppercase() {
        return Err(SessionError::InvalidPayload(format!(
            "Preview Core {role} SHA-256 does not match"
        )));
    }
    Ok(bytes)
}

fn decode_preview_core_document(
    root: &Path,
    geometry: &PreviewCoreGeometry,
) -> Result<MeshDocument, SessionError> {
    if geometry.schema_version < 8
        || geometry.batches.is_empty()
        || geometry.batches.len() > MAX_PREVIEW_CORE_BATCHES
        || geometry
            .normalization_center
            .into_iter()
            .any(|component| !component.is_finite())
        || !geometry.normalization_scale.is_finite()
        || geometry.normalization_scale.abs() <= 1.0e-12
    {
        return Err(SessionError::InvalidManifest(
            "Preview Core geometry metadata is invalid".to_owned(),
        ));
    }
    let format = match geometry.format.trim().to_ascii_lowercase().as_str() {
        "pac" => MeshFormat::Pac,
        "pam" => MeshFormat::Pam,
        "pamlod" => MeshFormat::Pamlod,
        _ => {
            return Err(SessionError::InvalidManifest(
                "Preview Core geometry format is unsupported".to_owned(),
            ));
        }
    };
    let mut total_vertices = 0_usize;
    let mut owned_paths = BTreeSet::new();
    let mut batch_indices = BTreeSet::new();
    let mut fingerprint = Sha256::new();
    let mut submeshes = Vec::with_capacity(geometry.batches.len());
    for batch in &geometry.batches {
        let vertex_count = usize::try_from(batch.vertex_count).map_err(|_| {
            SessionError::InvalidPayload(
                "Preview Core vertex count exceeds this platform".to_owned(),
            )
        })?;
        total_vertices = total_vertices.checked_add(vertex_count).ok_or_else(|| {
            SessionError::InvalidPayload("Preview Core vertex count overflowed".to_owned())
        })?;
        if vertex_count == 0
            || !vertex_count.is_multiple_of(3)
            || total_vertices > MAX_PREVIEW_CORE_VERTICES
            || !batch_indices.insert(batch.index)
            || !owned_paths.insert(batch.vertices.path.as_str())
        {
            return Err(SessionError::InvalidPayload(
                "Preview Core batch geometry is invalid or duplicated".to_owned(),
            ));
        }
        let vertices = read_preview_core_reference(
            root,
            &batch.vertices,
            "geometry",
            "preview_core_vertices_f32x23_le",
            batch.vertex_count,
            PREVIEW_CORE_VERTEX_BYTES,
        )?;
        let identities = if let Some(reference) = &batch.identity {
            if !owned_paths.insert(reference.path.as_str()) {
                return Err(SessionError::InvalidPayload(
                    "Preview Core identity payload is duplicated".to_owned(),
                ));
            }
            Some(read_preview_core_reference(
                root,
                reference,
                "identity",
                "preview_core_identity_i32x2_le",
                batch.vertex_count,
                PREVIEW_CORE_IDENTITY_BYTES,
            )?)
        } else {
            None
        };
        fingerprint.update(batch.vertices.sha256.trim().to_ascii_uppercase().as_bytes());
        if let Some(reference) = &batch.identity {
            fingerprint.update(reference.sha256.trim().to_ascii_uppercase().as_bytes());
        }

        let mut positions = Vec::with_capacity(vertex_count);
        let mut normals = Vec::with_capacity(vertex_count);
        let mut uvs = Vec::with_capacity(vertex_count);
        let mut indices = Vec::with_capacity(vertex_count);
        let mut source_vertex_indices = Vec::with_capacity(vertex_count);
        for (index, record) in vertices.chunks_exact(PREVIEW_CORE_VERTEX_BYTES).enumerate() {
            positions.push([
                preview_core_f32(record, 0) / geometry.normalization_scale
                    + geometry.normalization_center[0],
                preview_core_f32(record, 4) / geometry.normalization_scale
                    + geometry.normalization_center[1],
                preview_core_f32(record, 8) / geometry.normalization_scale
                    + geometry.normalization_center[2],
            ]);
            normals.push([
                preview_core_f32(record, 12),
                preview_core_f32(record, 16),
                preview_core_f32(record, 20),
            ]);
            uvs.push([preview_core_f32(record, 36), preview_core_f32(record, 40)]);
            indices.push(u32::try_from(index).map_err(|_| {
                SessionError::InvalidPayload(
                    "Preview Core local vertex index exceeds u32".to_owned(),
                )
            })?);
            let source_index = if let Some(identity_bytes) = &identities {
                let offset = index * PREVIEW_CORE_IDENTITY_BYTES;
                preview_core_i32(
                    &identity_bytes[offset..offset + PREVIEW_CORE_IDENTITY_BYTES],
                    std::mem::size_of::<i32>(),
                )
            } else {
                i32::try_from(index).map_err(|_| {
                    SessionError::InvalidPayload(
                        "Preview Core source vertex index exceeds i32".to_owned(),
                    )
                })?
            };
            source_vertex_indices.push(source_index);
        }
        submeshes.push(Submesh {
            name: batch.name.clone(),
            material: batch.material.clone(),
            positions,
            normals,
            uvs,
            indices,
            source_vertex_indices,
            source_range: SourceRange {
                offset: 0,
                length: batch.vertices.byte_length,
            },
            vertex_stride: u32::try_from(PREVIEW_CORE_VERTEX_BYTES).map_err(|_| {
                SessionError::InvalidPayload("Preview Core vertex stride exceeds u32".to_owned())
            })?,
            layout: "preview_core_f32x23_le".to_owned(),
        });
    }
    let structural_fingerprint = format!("{:X}", fingerprint.finalize());
    Ok(MeshDocument {
        format,
        source_sha256: geometry.source_sha256.trim().to_ascii_uppercase(),
        parser: "cdmw_preview_core_direct_v1".to_owned(),
        lod_count_reported: 1,
        lods: vec![MeshLod {
            level: 0,
            submeshes,
        }],
        warnings: Vec::new(),
        structural_fingerprint,
    })
}

fn read_json_reference(root: &Path, reference: &FileReference) -> Result<Vec<u8>, SessionError> {
    if reference.content_type != "application/json"
        || !reference.data_type.ends_with("_json")
        || reference.count == 0
    {
        return Err(SessionError::InvalidPayload(
            "file reference type or count is invalid".to_owned(),
        ));
    }
    let path = simple_owned_path(root, &reference.path)?;
    let metadata = path.metadata()?;
    if metadata.len() != reference.byte_length || metadata.len() > MAX_PAYLOAD_BYTES {
        return Err(SessionError::InvalidPayload(
            "file reference size does not match".to_owned(),
        ));
    }
    let bytes = read_limited(&path, MAX_PAYLOAD_BYTES)?;
    if sha256_upper(&bytes) != reference.sha256.trim().to_ascii_uppercase() {
        return Err(SessionError::InvalidPayload(
            "file reference SHA-256 does not match".to_owned(),
        ));
    }
    Ok(bytes)
}

fn read_binary_reference(root: &Path, reference: &FileReference) -> Result<Vec<u8>, SessionError> {
    if reference.content_type != "image/vnd-ms.dds"
        || reference.data_type != "dds_texture"
        || reference.count != 1
    {
        return Err(SessionError::InvalidPayload(
            "texture reference type or count is invalid".to_owned(),
        ));
    }
    let relative = Path::new(&reference.path);
    let mut components = relative.components();
    if !matches!(components.next(), Some(Component::Normal(_)))
        || components.next().is_some()
        || relative.extension().and_then(|value| value.to_str()) != Some("dds")
        || !is_owned_texture_filename(&reference.path)
    {
        return Err(SessionError::InvalidPayload(
            "texture path must be one owned DDS filename".to_owned(),
        ));
    }
    let candidate = fs::canonicalize(root.join(relative))?;
    if candidate.parent() != Some(root) || !candidate.is_file() {
        return Err(SessionError::InvalidPayload(
            "texture path escaped the session root".to_owned(),
        ));
    }
    let metadata = candidate.metadata()?;
    if metadata.len() != reference.byte_length || metadata.len() > MAX_PAYLOAD_BYTES {
        return Err(SessionError::InvalidPayload(
            "texture reference size does not match".to_owned(),
        ));
    }
    let bytes = read_limited(&candidate, MAX_PAYLOAD_BYTES)?;
    if sha256_upper(&bytes) != reference.sha256.trim().to_ascii_uppercase() {
        return Err(SessionError::InvalidPayload(
            "texture reference SHA-256 does not match".to_owned(),
        ));
    }
    Ok(bytes)
}

fn is_owned_texture_filename(value: &str) -> bool {
    let Some(stem) = value.strip_suffix(".dds") else {
        return false;
    };
    let mut parts = stem.split('-');
    matches!(parts.next(), Some("texture"))
        && parts.next().is_some_and(|index| {
            index.len() == 4 && index.bytes().all(|byte| byte.is_ascii_digit())
        })
        && parts.next().is_some_and(|hash| {
            hash.len() == 12 && hash.bytes().all(|byte| byte.is_ascii_hexdigit())
        })
        && parts.next().is_none()
}

fn read_texture_resources(
    root: &Path,
    manifest: &SessionManifest,
    document: &MeshDocument,
) -> Result<Vec<CdmwTextureResource>, SessionError> {
    if manifest.textures.len() > MAX_TEXTURE_RESOURCES {
        return Err(SessionError::InvalidManifest(
            "the session contains too many texture resources".to_owned(),
        ));
    }
    let mut total_bytes = 0_u64;
    let mut owners = BTreeSet::new();
    let mut resources = Vec::with_capacity(manifest.textures.len());
    for texture in &manifest.textures {
        if texture.label.trim().is_empty()
            || texture.material_indices_by_lod.len() != document.lods.len()
        {
            return Err(SessionError::InvalidManifest(
                "texture label and one ownership list per LOD are required".to_owned(),
            ));
        }
        total_bytes = total_bytes.saturating_add(texture.file.byte_length);
        if total_bytes > MAX_TEXTURE_TOTAL_BYTES {
            return Err(SessionError::InvalidManifest(
                "session texture resources exceed the 512 MiB aggregate limit".to_owned(),
            ));
        }
        for (lod_index, material_indices) in texture.material_indices_by_lod.iter().enumerate() {
            for material_index in material_indices {
                if usize::try_from(*material_index).map_or(true, |index| {
                    index >= document.lods[lod_index].submeshes.len()
                }) {
                    return Err(SessionError::InvalidManifest(format!(
                        "LOD{lod_index} texture ownership contains invalid material {material_index}"
                    )));
                }
                if !owners.insert((lod_index, *material_index, texture.role)) {
                    return Err(SessionError::InvalidManifest(format!(
                        "LOD{lod_index} material {material_index} has duplicate {:?} texture ownership",
                        texture.role
                    )));
                }
            }
        }
        let bytes = read_binary_reference(root, &texture.file)?;
        let metadata = inspect_dds(&bytes, texture.role)
            .map_err(|error| SessionError::InvalidPayload(error.to_string()))?;
        resources.push(CdmwTextureResource {
            label: texture.label.clone(),
            role: texture.role,
            metadata,
            bytes,
            material_indices_by_lod: texture.material_indices_by_lod.clone(),
        });
    }
    Ok(resources)
}

fn simple_owned_path(root: &Path, name: &str) -> Result<PathBuf, SessionError> {
    let relative = Path::new(name);
    let mut components = relative.components();
    if !matches!(components.next(), Some(Component::Normal(_)))
        || components.next().is_some()
        || relative.extension().and_then(|value| value.to_str()) != Some("json")
    {
        return Err(SessionError::InvalidPayload(
            "payload path must be one owned JSON filename".to_owned(),
        ));
    }
    let candidate = fs::canonicalize(root.join(relative))?;
    if candidate.parent() != Some(root) || !candidate.is_file() {
        return Err(SessionError::InvalidPayload(
            "payload path escaped the session root".to_owned(),
        ));
    }
    Ok(candidate)
}

fn read_limited(path: &Path, maximum: u64) -> Result<Vec<u8>, SessionError> {
    let metadata = path.metadata()?;
    if metadata.len() > maximum {
        return Err(SessionError::InvalidPayload(format!(
            "{} exceeds the payload limit",
            path.display()
        )));
    }
    Ok(fs::read(path)?)
}

fn reject_unexpected_initial_files(
    root: &Path,
    manifest: &SessionManifest,
) -> Result<(), SessionError> {
    let allowed = [
        "manifest.json",
        manifest.document.path.as_str(),
        manifest.channels.path.as_str(),
        "shadow-mesh-layers.json",
    ]
    .into_iter()
    .chain(
        manifest
            .textures
            .iter()
            .map(|texture| texture.file.path.as_str()),
    )
    .chain(manifest.preview_core_geometry.iter().flat_map(|geometry| {
        geometry.batches.iter().flat_map(|batch| {
            std::iter::once(batch.vertices.path.as_str())
                .chain(batch.identity.iter().map(|identity| identity.path.as_str()))
        })
    }))
    .collect::<BTreeSet<_>>();
    for entry in fs::read_dir(root)? {
        let entry = entry?;
        let name = entry.file_name().to_string_lossy().into_owned();
        let file_type = entry.file_type()?;
        if file_type.is_file() && allowed.contains(name.as_str()) {
            continue;
        }
        if name == "mesh_slider_profiles" && file_type.is_dir() {
            validate_owned_profile_directory(&entry.path())?;
            continue;
        }
        return Err(SessionError::InvalidManifest(format!(
            "unexpected session entry {name}"
        )));
    }
    Ok(())
}

fn validate_owned_profile_directory(root: &Path) -> Result<(), SessionError> {
    let mut stack = vec![(root.to_path_buf(), 0_usize)];
    let mut entry_count = 0_usize;
    let mut total_bytes = 0_u64;
    while let Some((directory, depth)) = stack.pop() {
        for entry in fs::read_dir(&directory)? {
            let entry = entry?;
            entry_count = entry_count.saturating_add(1);
            if entry_count > MAX_PROFILE_ENTRIES {
                return Err(SessionError::InvalidManifest(
                    "mesh_slider_profiles contains too many entries".to_owned(),
                ));
            }
            let path = entry.path();
            let file_type = entry.file_type()?;
            if file_type.is_symlink() {
                return Err(SessionError::InvalidManifest(format!(
                    "mesh_slider_profiles contains a link at {}",
                    path.display()
                )));
            }
            if file_type.is_dir() {
                if depth >= MAX_PROFILE_DEPTH {
                    return Err(SessionError::InvalidManifest(format!(
                        "mesh_slider_profiles exceeds the directory-depth limit at {}",
                        path.display()
                    )));
                }
                stack.push((path, depth + 1));
                continue;
            }
            if !file_type.is_file()
                || path.extension().and_then(|value| value.to_str()) != Some("json")
            {
                return Err(SessionError::InvalidManifest(format!(
                    "mesh_slider_profiles contains an unexpected entry at {}",
                    path.display()
                )));
            }
            let length = entry.metadata()?.len();
            if length > MAX_PROFILE_FILE_BYTES {
                return Err(SessionError::InvalidManifest(format!(
                    "mesh_slider_profiles file exceeds the size limit at {}",
                    path.display()
                )));
            }
            total_bytes = total_bytes.saturating_add(length);
            if total_bytes > MAX_PROFILE_TOTAL_BYTES {
                return Err(SessionError::InvalidManifest(
                    "mesh_slider_profiles exceeds the total size limit".to_owned(),
                ));
            }
        }
    }
    Ok(())
}

fn validate_identity(value: &Value, manifest: &SessionManifest) -> Result<(), SessionError> {
    if value.get("protocol").and_then(Value::as_str) != Some(PROTOCOL)
        || value.get("session_id").and_then(Value::as_str) != Some(manifest.session_id.as_str())
        || required_u64(value, "process_generation")? != manifest.process_generation
    {
        return Err(SessionError::Protocol(
            "host message identity does not match".to_owned(),
        ));
    }
    Ok(())
}

fn result_state(event: &str, ok: bool, payload: &Value) -> Result<Option<Value>, SessionError> {
    if ok && event == "finish_result" {
        return Ok(None);
    }
    let state = if !ok || event == "command_result" {
        payload.get("state").cloned()
    } else {
        Some(payload.clone())
    };
    let state = state.filter(|value| !value.is_null()).ok_or_else(|| {
        SessionError::Protocol(if ok {
            format!("host {event} omitted its authoritative state")
        } else {
            format!("host rejected {event} without a recovery state")
        })
    })?;
    Ok(Some(state))
}

fn validate_state_identity(
    state: &Value,
    manifest: &SessionManifest,
    expected_revision: u64,
) -> Result<(), SessionError> {
    if state.get("session_id").and_then(Value::as_str) != Some(manifest.session_id.as_str()) {
        return Err(SessionError::Protocol(
            "host state session identity does not match".to_owned(),
        ));
    }
    let revision = required_u64(state, "base_revision")?;
    if revision != expected_revision {
        return Err(SessionError::Protocol(format!(
            "host result revision {expected_revision} does not match state revision {revision}"
        )));
    }
    Ok(())
}

fn required_u64(value: &Value, key: &str) -> Result<u64, SessionError> {
    value
        .get(key)
        .and_then(Value::as_u64)
        .ok_or_else(|| SessionError::Protocol(format!("host message {key} is invalid")))
}

fn spawn_input_reader(sender: Sender<Incoming>) {
    thread::Builder::new()
        .name("cdmw-rust-control-input".to_owned())
        .spawn(move || {
            let stdin = std::io::stdin();
            let mut reader = BufReader::new(stdin.lock());
            loop {
                let mut line = Vec::new();
                match reader.read_until(b'\n', &mut line) {
                    Ok(0) => break,
                    Ok(_) if line.len() > MAX_CONTROL_LINE_BYTES => {
                        let _ = sender.send(Incoming::LocalError(
                            "CDMW control line exceeded 256 KiB".to_owned(),
                        ));
                        break;
                    }
                    Ok(_) => {
                        while matches!(line.last(), Some(b'\n' | b'\r')) {
                            line.pop();
                        }
                        if line.is_empty() {
                            continue;
                        }
                        match serde_json::from_slice::<Value>(&line) {
                            Ok(value) => {
                                if sender.try_send(Incoming::Message(value)).is_err() {
                                    let _ = sender.send(Incoming::LocalError(
                                        "CDMW control queue overflowed".to_owned(),
                                    ));
                                    break;
                                }
                            }
                            Err(error) => {
                                let _ = sender.send(Incoming::LocalError(format!(
                                    "CDMW sent invalid JSON: {error}"
                                )));
                                break;
                            }
                        }
                    }
                    Err(error) => {
                        let _ = sender.send(Incoming::LocalError(format!(
                            "CDMW control input failed: {error}"
                        )));
                        break;
                    }
                }
            }
        })
        .expect("control input thread creation must succeed");
}

fn spawn_output_writer(
    root: PathBuf,
    session_id: String,
    process_generation: u64,
    error_sender: Sender<Incoming>,
    receiver: Receiver<Outbound>,
) {
    thread::Builder::new()
        .name("cdmw-rust-control-output".to_owned())
        .spawn(move || {
            let stdout = std::io::stdout();
            let mut writer = BufWriter::new(stdout.lock());
            for outbound in receiver {
                let result = match outbound {
                    Outbound::Message(value) => write_control_message(&mut writer, &value),
                    Outbound::Transaction {
                        request_id,
                        base_revision,
                        lod_index,
                        label,
                        document,
                        mesh,
                    } => write_transaction(
                        &root,
                        &session_id,
                        process_generation,
                        request_id,
                        base_revision,
                        lod_index,
                        &label,
                        &document,
                        &mesh,
                        &mut writer,
                    ),
                };
                if let Err(error) = result {
                    let _ = error_sender.send(Incoming::LocalError(error.to_string()));
                    break;
                }
            }
        })
        .expect("control output thread creation must succeed");
}

fn write_control_message(writer: &mut impl Write, value: &Value) -> Result<(), SessionError> {
    serde_json::to_writer(&mut *writer, value)?;
    writer.write_all(b"\n")?;
    writer.flush()?;
    Ok(())
}

#[derive(Debug, Serialize)]
struct Candidate {
    schema: &'static str,
    session_id: String,
    submeshes: Vec<CandidateSubmesh>,
    selection: CandidateSelection,
}

#[derive(Debug, Serialize)]
struct CandidateSubmesh {
    positions: Vec<[f32; 3]>,
    normals: Vec<[f32; 3]>,
    uvs: Vec<[f32; 2]>,
    indices: Vec<u32>,
}

#[derive(Debug, Default, Serialize)]
struct CandidateSelection {
    vertices_by_submesh: BTreeMap<String, Vec<u32>>,
    edges_by_submesh: BTreeMap<String, Vec<[u32; 2]>>,
    faces_by_submesh: BTreeMap<String, Vec<u32>>,
    source_indices: Vec<u32>,
}

fn write_transaction(
    root: &Path,
    session_id: &str,
    process_generation: u64,
    request_id: u64,
    base_revision: u64,
    lod_index: usize,
    label: &str,
    document: &MeshDocument,
    mesh: &WorkingMesh,
    writer: &mut impl Write,
) -> Result<(), SessionError> {
    let candidate = build_candidate(session_id, document, mesh, lod_index)?;
    let bytes = serde_json::to_vec(&candidate)?;
    if bytes.len() as u64 > MAX_PAYLOAD_BYTES {
        return Err(SessionError::InvalidPayload(
            "candidate exceeds 512 MiB".to_owned(),
        ));
    }
    let name = format!("candidate-{request_id}-rust{}.json", std::process::id());
    let destination = root.join(&name);
    let temporary = root.join(format!(".{name}.tmp"));
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&temporary)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    drop(file);
    fs::rename(&temporary, &destination)?;
    write_control_message(
        writer,
        &json!({
            "event": "transaction_request",
            "protocol": PROTOCOL,
            "session_id": session_id,
            "request_id": request_id,
            "base_revision": base_revision,
            "process_generation": process_generation,
            "label": label,
            "candidate": {
                "path": name,
                "data_type": "mesh_candidate_json",
                "count": candidate.submeshes.len(),
                "byte_length": bytes.len(),
                "sha256": sha256_upper(&bytes),
                "content_type": "application/json"
            }
        }),
    )
}

fn build_candidate(
    session_id: &str,
    document: &MeshDocument,
    mesh: &WorkingMesh,
    lod_index: usize,
) -> Result<Candidate, SessionError> {
    let lod = document.lods.get(lod_index).ok_or_else(|| {
        SessionError::InvalidPayload(format!("document has no source LOD {lod_index}"))
    })?;
    let mut submeshes = lod
        .submeshes
        .iter()
        .map(|submesh| CandidateSubmesh {
            positions: submesh.positions.clone(),
            normals: submesh.normals.clone(),
            uvs: submesh.uvs.clone(),
            indices: submesh.indices.clone(),
        })
        .collect::<Vec<_>>();
    for (_, vertex) in mesh.vertices() {
        let Provenance::Source { submesh, element } = vertex.provenance else {
            return Err(SessionError::InvalidPayload(
                "native topology must be committed through CDMW before export".to_owned(),
            ));
        };
        let target = submeshes
            .get_mut(submesh as usize)
            .ok_or_else(|| SessionError::InvalidPayload("vertex submesh is invalid".to_owned()))?;
        let index = element as usize;
        *target.positions.get_mut(index).ok_or_else(|| {
            SessionError::InvalidPayload("vertex source index is invalid".to_owned())
        })? = vertex.position;
        if let Some(normal) = target.normals.get_mut(index) {
            *normal = vertex.normal;
        }
        if let Some(uv) = target.uvs.get_mut(index) {
            *uv = vertex.uv;
        }
    }
    Ok(Candidate {
        schema: CANDIDATE_SCHEMA,
        session_id: session_id.to_owned(),
        submeshes,
        selection: candidate_selection(mesh)?,
    })
}

fn candidate_selection(mesh: &WorkingMesh) -> Result<CandidateSelection, SessionError> {
    let mut selection = CandidateSelection::default();
    for handle in &mesh.selection.vertices {
        let vertex = mesh
            .vertex(*handle)
            .ok_or_else(|| SessionError::InvalidPayload("selected vertex is stale".to_owned()))?;
        let Provenance::Source { submesh, element } = vertex.provenance else {
            continue;
        };
        selection
            .vertices_by_submesh
            .entry(submesh.to_string())
            .or_default()
            .push(element);
    }
    for handle in &mesh.selection.faces {
        let face = mesh
            .face(*handle)
            .ok_or_else(|| SessionError::InvalidPayload("selected face is stale".to_owned()))?;
        let Provenance::Source { element, .. } = face.provenance else {
            continue;
        };
        selection
            .faces_by_submesh
            .entry(face.submesh.to_string())
            .or_default()
            .push(element);
    }
    for handle in &mesh.selection.edges {
        let edge = mesh
            .edge(*handle)
            .ok_or_else(|| SessionError::InvalidPayload("selected edge is stale".to_owned()))?;
        let mut endpoints = [(0_u32, 0_u32); 2];
        for (index, vertex_handle) in edge.vertices.iter().enumerate() {
            let vertex = mesh.vertex(*vertex_handle).ok_or_else(|| {
                SessionError::InvalidPayload("selected edge vertex is stale".to_owned())
            })?;
            let Provenance::Source { submesh, element } = vertex.provenance else {
                continue;
            };
            endpoints[index] = (submesh, element);
        }
        if endpoints[0].0 == endpoints[1].0 {
            let submesh = endpoints[0].0;
            selection
                .edges_by_submesh
                .entry(submesh.to_string())
                .or_default()
                .push([endpoints[0].1, endpoints[1].1]);
        }
    }
    selection.source_indices = mesh.selection.submeshes.iter().copied().collect();
    selection.source_indices.sort_unstable();
    for values in selection.vertices_by_submesh.values_mut() {
        values.sort_unstable();
        values.dedup();
    }
    for values in selection.faces_by_submesh.values_mut() {
        values.sort_unstable();
        values.dedup();
    }
    for values in selection.edges_by_submesh.values_mut() {
        values.sort_unstable();
        values.dedup();
    }
    Ok(selection)
}

pub fn selection_payload(mesh: &WorkingMesh) -> Result<Value, SessionError> {
    Ok(serde_json::to_value(candidate_selection(mesh)?)?)
}

fn sha256_upper(bytes: &[u8]) -> String {
    format!("{:X}", Sha256::digest(bytes))
}

#[cfg(test)]
mod tests {
    use super::*;
    use cdmw_formats::{MeshFormat, MeshLod, SourceRange, Submesh};
    use tempfile::tempdir;

    fn document() -> MeshDocument {
        MeshDocument {
            format: MeshFormat::Pac,
            source_sha256: String::new(),
            parser: PACKAGE_SCHEMA.to_owned(),
            lod_count_reported: 1,
            lods: vec![MeshLod {
                level: 0,
                submeshes: vec![Submesh {
                    name: "triangle".to_owned(),
                    material: "mat".to_owned(),
                    positions: vec![[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                    normals: vec![[0.0, 0.0, 1.0]; 3],
                    uvs: vec![[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]],
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

    fn material_presentation() -> SessionMaterialPresentation {
        SessionMaterialPresentation {
            lod_index: 0,
            material_index: 0,
            material_slot_index: 0,
            material_category: "metal".to_owned(),
            category_code: 1,
            category_confidence: 0.92,
            shader_family: "standard_v2".to_owned(),
            normal_y_policy: "invert_green_for_directx".to_owned(),
            normal_y_inverted: true,
            alpha_mode: "cutout".to_owned(),
            alpha_cutoff: Some(0.17),
            double_sided: false,
            roughness: Some(0.22),
            metalness: Some(0.81),
            specular: Some(0.73),
            emissive_color: Some([0.1, 0.2, 0.3]),
            emissive_intensity: Some(2.5),
            height_scale: Some(0.08),
            texture_tint: Some([0.73, 0.44, 0.24]),
            base_tint_strength: Some(0.85),
            hair_anisotropy: false,
            skin_detail_scale: None,
            skin_detail_opacity: None,
        }
    }

    fn write_loaded_package_fixture(root: &Path) -> PathBuf {
        let document_bytes = serde_json::to_vec(&document()).expect("document bytes");
        let channels_bytes = serde_json::to_vec(&json!({"uv0": true})).expect("channel bytes");
        let texture_bytes = cdmw_texture::synthetic::rgba8_checker_dds();
        let texture_sha256 = sha256_upper(&texture_bytes);
        let texture_name = format!(
            "texture-0000-{}.dds",
            texture_sha256[..12].to_ascii_lowercase()
        );
        fs::write(root.join("document.json"), &document_bytes).expect("document");
        fs::write(root.join("channels.json"), &channels_bytes).expect("channels");
        fs::write(root.join(&texture_name), &texture_bytes).expect("texture");
        let reference = |path: &str, data_type: &str, bytes: &[u8]| {
            json!({
                "path": path,
                "data_type": data_type,
                "count": 1,
                "byte_length": bytes.len(),
                "sha256": sha256_upper(bytes),
                "content_type": "application/json"
            })
        };
        let presentation = material_presentation();
        let manifest = json!({
            "schema": PACKAGE_SCHEMA,
            "protocol": PROTOCOL,
            "session_id": "capture-session",
            "process_generation": 4,
            "base_revision": 0,
            "shadow_revision": 0,
            "renderer": RENDERER,
            "edit_backend": EDIT_BACKEND,
            "document": reference("document.json", "mesh_document_json", &document_bytes),
            "channels": reference("channels.json", "mesh_channels_json", &channels_bytes),
            "textures": [{
                "label": "body-base.dds",
                "role": "base_color",
                "file": {
                    "path": texture_name,
                    "data_type": "dds_texture",
                    "count": 1,
                    "byte_length": texture_bytes.len(),
                    "sha256": texture_sha256,
                    "content_type": "image/vnd-ms.dds"
                },
                "material_indices_by_lod": [[0]]
            }],
            "material_presentations": [{
                "lod_index": presentation.lod_index,
                "material_index": presentation.material_index,
                "material_slot_index": presentation.material_slot_index,
                "material_category": presentation.material_category,
                "category_code": presentation.category_code,
                "category_confidence": presentation.category_confidence,
                "shader_family": presentation.shader_family,
                "normal_y_policy": presentation.normal_y_policy,
                "normal_y_inverted": presentation.normal_y_inverted,
                "alpha_mode": presentation.alpha_mode,
                "alpha_cutoff": presentation.alpha_cutoff,
                "double_sided": presentation.double_sided,
                "roughness": presentation.roughness,
                "metalness": presentation.metalness,
                "specular": presentation.specular,
                "emissive_color": presentation.emissive_color,
                "emissive_intensity": presentation.emissive_intensity,
                "height_scale": presentation.height_scale,
                "texture_tint": presentation.texture_tint,
                "base_tint_strength": presentation.base_tint_strength,
                "hair_anisotropy": presentation.hair_anisotropy
            }],
            "texture_status": {"available": true},
            "source": {"path": "capture.pac", "lod_index": 0},
            "output_policy": {"policy": "exact_game_asset"},
            "theme": {},
            "state": {}
        });
        let manifest_path = root.join("manifest.json");
        fs::write(
            &manifest_path,
            serde_json::to_vec(&manifest).expect("manifest bytes"),
        )
        .expect("manifest");
        manifest_path
    }

    fn write_preview_core_package_fixture(root: &Path) -> PathBuf {
        let manifest_path = write_loaded_package_fixture(root);
        let mut vertex_bytes = Vec::new();
        for (position, uv) in [
            ([2.0_f32, 0.0, 0.0], [0.0_f32, 0.0]),
            ([0.0_f32, 2.0, 0.0], [1.0_f32, 0.0]),
            ([0.0_f32, 0.0, 2.0], [0.0_f32, 1.0]),
        ] {
            let mut record = [0.0_f32; 23];
            record[..3].copy_from_slice(&position);
            record[3..6].copy_from_slice(&[0.0, 0.0, 1.0]);
            record[9..11].copy_from_slice(&uv);
            for value in record {
                vertex_bytes.extend_from_slice(&value.to_le_bytes());
            }
        }
        let mut identity_bytes = Vec::new();
        for source_index in [7_i32, 8, 9] {
            identity_bytes.extend_from_slice(&4_i32.to_le_bytes());
            identity_bytes.extend_from_slice(&source_index.to_le_bytes());
        }
        let vertex_sha = sha256_upper(&vertex_bytes);
        let identity_sha = sha256_upper(&identity_bytes);
        let vertex_name = format!(
            "preview-geometry-0000-{}.bin",
            vertex_sha[..12].to_ascii_lowercase()
        );
        let identity_name = format!(
            "preview-identity-0000-{}.bin",
            identity_sha[..12].to_ascii_lowercase()
        );
        fs::write(root.join(&vertex_name), &vertex_bytes).expect("preview vertices");
        fs::write(root.join(&identity_name), &identity_bytes).expect("preview identities");

        let mut manifest: Value =
            serde_json::from_slice(&fs::read(&manifest_path).expect("manifest bytes"))
                .expect("manifest JSON");
        manifest["schema"] = json!(PREVIEW_PACKAGE_SCHEMA);
        manifest["protocol"] = json!(PREVIEW_PROTOCOL);
        manifest["edit_backend"] = json!(PREVIEW_BACKEND);
        manifest["preview_core_geometry"] = json!({
            "schema_version": 8,
            "format": "pac",
            "source_sha256": "SOURCE",
            "normalization_center": [10.0, 20.0, 30.0],
            "normalization_scale": 2.0,
            "batches": [{
                "index": 4,
                "name": "helmet",
                "material": "mat",
                "vertex_count": 3,
                "vertices": {
                    "path": vertex_name,
                    "data_type": "preview_core_vertices_f32x23_le",
                    "count": 3,
                    "byte_length": vertex_bytes.len(),
                    "sha256": vertex_sha,
                    "content_type": "application/octet-stream"
                },
                "identity": {
                    "path": identity_name,
                    "data_type": "preview_core_identity_i32x2_le",
                    "count": 3,
                    "byte_length": identity_bytes.len(),
                    "sha256": identity_sha,
                    "content_type": "application/octet-stream"
                }
            }]
        });
        fs::write(
            &manifest_path,
            serde_json::to_vec(&manifest).expect("direct manifest bytes"),
        )
        .expect("direct manifest");
        manifest_path
    }

    fn state_with_document(
        root: &Path,
        session_id: &str,
        revision: u64,
        document: &MeshDocument,
    ) -> Value {
        let name = format!("state-{revision}.json");
        let bytes = serde_json::to_vec(document).expect("serialize state document");
        fs::write(root.join(&name), &bytes).expect("write state document");
        json!({
            "session_id": session_id,
            "base_revision": revision,
            "selection": {
                "vertices_by_submesh": {},
                "edges_by_submesh": {},
                "faces_by_submesh": {},
                "source_indices": []
            },
            "document": {
                "path": name,
                "data_type": "mesh_document_json",
                "count": 1,
                "byte_length": bytes.len(),
                "sha256": sha256_upper(&bytes),
                "content_type": "application/json"
            }
        })
    }

    #[test]
    fn candidate_preserves_submesh_shape_and_maps_selected_source_vertex() {
        let document = document();
        let mut mesh = WorkingMesh::from_document(&document).expect("mesh");
        let selected = mesh
            .vertices()
            .next()
            .map(|(handle, _)| handle)
            .expect("vertex");
        let mut selection = cdmw_mesh::Selection::default();
        selection.vertices.insert(selected);
        mesh.set_selection(selection).expect("selection");
        let candidate = build_candidate("session", &document, &mesh, 0).expect("candidate");
        assert_eq!(candidate.submeshes.len(), 1);
        assert_eq!(candidate.submeshes[0].indices, vec![0, 1, 2]);
        assert_eq!(candidate.selection.vertices_by_submesh["0"], vec![0]);
        assert!(candidate.selection.source_indices.is_empty());
    }

    #[test]
    fn pure_package_loader_validates_and_returns_capture_resources_without_protocol_threads() {
        let root = tempdir().expect("root");
        let manifest_path = write_loaded_package_fixture(root.path());

        let mut package = LoadedCdmwSessionPackage::load(&manifest_path).expect("loaded package");

        assert_eq!(package.manifest().session_id, "capture-session");
        assert_eq!(package.source_lod_index(), 0);
        assert_eq!(package.document().lods[0].submeshes.len(), 1);
        let textures = package.take_textures();
        assert_eq!(textures.len(), 1);
        assert_eq!(textures[0].role, TextureRole::BaseColor);
        assert_eq!(textures[0].material_indices_by_lod, vec![vec![0]]);
        assert_eq!(
            package.take_material_presentations(),
            vec![material_presentation()]
        );
    }

    #[test]
    fn pure_preview_loader_accepts_predecoded_external_geometry() {
        let root = tempdir().expect("root");
        let manifest_path = write_loaded_package_fixture(root.path());
        let mut external_document = document();
        external_document.format = MeshFormat::Preview;
        let document_bytes = serde_json::to_vec(&external_document).expect("external document");
        fs::write(root.path().join("document.json"), &document_bytes).expect("document");
        let mut manifest: Value =
            serde_json::from_slice(&fs::read(&manifest_path).expect("manifest bytes"))
                .expect("manifest JSON");
        manifest["schema"] = json!(PREVIEW_PACKAGE_SCHEMA);
        manifest["protocol"] = json!(PREVIEW_PROTOCOL);
        manifest["edit_backend"] = json!(PREVIEW_BACKEND);
        manifest["interaction_profile"] = json!("read_only");
        manifest["output_policy"] = json!({"policy": "read_only_preview", "archive_writes": false});
        manifest["source"] = json!({"path": "scene.gltf", "format": "gltf", "lod_index": 0});
        manifest["document"]["byte_length"] = json!(document_bytes.len());
        manifest["document"]["sha256"] = json!(sha256_upper(&document_bytes));
        fs::write(
            &manifest_path,
            serde_json::to_vec(&manifest).expect("preview manifest bytes"),
        )
        .expect("preview manifest");

        let package = LoadedCdmwSessionPackage::load_preview(&manifest_path)
            .expect("external preview package");

        assert_eq!(package.document().format, MeshFormat::Preview);
        assert_eq!(package.document().lods[0].submeshes.len(), 1);
    }

    #[test]
    fn pure_preview_loader_decodes_preview_core_geometry_and_identity_directly() {
        let root = tempdir().expect("root");
        let manifest_path = write_preview_core_package_fixture(root.path());

        let package =
            LoadedCdmwSessionPackage::load_preview(&manifest_path).expect("direct preview package");
        let submesh = &package.document().lods[0].submeshes[0];

        assert_eq!(package.document().parser, "cdmw_preview_core_direct_v1");
        assert_eq!(submesh.name, "helmet");
        assert_eq!(submesh.material, "mat");
        assert_eq!(
            submesh.positions,
            vec![[11.0, 20.0, 30.0], [10.0, 21.0, 30.0], [10.0, 20.0, 31.0]]
        );
        assert_eq!(submesh.indices, vec![0, 1, 2]);
        assert_eq!(submesh.source_vertex_indices, vec![7, 8, 9]);
        assert_eq!(submesh.vertex_stride, 92);
        assert_eq!(submesh.layout, "preview_core_f32x23_le");
    }

    #[test]
    fn pure_preview_loader_rejects_changed_preview_core_geometry() {
        let root = tempdir().expect("root");
        let manifest_path = write_preview_core_package_fixture(root.path());
        let manifest: Value =
            serde_json::from_slice(&fs::read(&manifest_path).expect("manifest bytes"))
                .expect("manifest JSON");
        let geometry_name = manifest["preview_core_geometry"]["batches"][0]["vertices"]["path"]
            .as_str()
            .expect("geometry path");
        fs::write(
            root.path().join(geometry_name),
            vec![0_u8; PREVIEW_CORE_VERTEX_BYTES * 3],
        )
        .expect("replace geometry");

        let error = LoadedCdmwSessionPackage::load_preview(&manifest_path)
            .expect_err("geometry hash mismatch");

        assert!(error.to_string().contains("SHA-256 does not match"));
    }

    #[test]
    fn preview_manifest_accepts_realistic_overlay_payload_above_the_protocol_line_limit() {
        let root = tempdir().expect("root");
        let manifest_path = write_loaded_package_fixture(root.path());
        let mut manifest: Value =
            serde_json::from_slice(&fs::read(&manifest_path).expect("read manifest"))
                .expect("parse manifest");
        manifest["state"]["preview_overlays"] =
            Value::String("x".repeat(MAX_CONTROL_LINE_BYTES * 9));
        fs::write(
            &manifest_path,
            serde_json::to_vec(&manifest).expect("manifest bytes"),
        )
        .expect("expanded manifest");
        assert!(
            manifest_path.metadata().expect("manifest metadata").len()
                > MAX_CONTROL_LINE_BYTES as u64 * 8
        );

        let package = LoadedCdmwSessionPackage::load(&manifest_path)
            .expect("large preview manifest remains bounded and loadable");

        assert_eq!(package.manifest().session_id, "capture-session");
    }

    #[test]
    fn pure_package_loader_rejects_a_texture_changed_after_manifest_publication() {
        let root = tempdir().expect("root");
        let manifest_path = write_loaded_package_fixture(root.path());
        let manifest: Value =
            serde_json::from_slice(&fs::read(&manifest_path).expect("read manifest"))
                .expect("parse manifest");
        let texture_name = manifest["textures"][0]["file"]["path"]
            .as_str()
            .expect("texture path");
        fs::write(root.path().join(texture_name), b"changed").expect("replace texture");

        let error = LoadedCdmwSessionPackage::load(&manifest_path).expect_err("hash mismatch");

        assert!(error.to_string().contains("size does not match"));
    }

    #[test]
    fn element_selection_never_promotes_to_a_whole_part_selection() {
        let document = document();

        let mut face_mesh = WorkingMesh::from_document(&document).expect("face mesh");
        let face = face_mesh
            .faces()
            .next()
            .map(|(handle, _)| handle)
            .expect("face");
        let mut face_selection = cdmw_mesh::Selection::default();
        face_selection.faces.insert(face);
        face_mesh
            .set_selection(face_selection)
            .expect("face selection");
        let face_payload = candidate_selection(&face_mesh).expect("face payload");
        assert_eq!(face_payload.faces_by_submesh["0"], vec![0]);
        assert!(face_payload.source_indices.is_empty());

        let mut edge_mesh = WorkingMesh::from_document(&document).expect("edge mesh");
        let edge = edge_mesh
            .edges()
            .next()
            .map(|(handle, _)| handle)
            .expect("edge");
        let mut edge_selection = cdmw_mesh::Selection::default();
        edge_selection.edges.insert(edge);
        edge_mesh
            .set_selection(edge_selection)
            .expect("edge selection");
        let edge_payload = candidate_selection(&edge_mesh).expect("edge payload");
        assert_eq!(edge_payload.edges_by_submesh["0"].len(), 1);
        assert!(edge_payload.source_indices.is_empty());

        let mut part_mesh = WorkingMesh::from_document(&document).expect("part mesh");
        let mut part_selection = cdmw_mesh::Selection::default();
        part_selection.submeshes.insert(0);
        part_mesh
            .set_selection(part_selection)
            .expect("part selection");
        let part_payload = candidate_selection(&part_mesh).expect("part payload");
        assert_eq!(part_payload.source_indices, vec![0]);
    }

    #[test]
    fn candidate_edits_the_manifest_source_lod_in_a_multi_lod_document() {
        let document =
            cdmw_formats::decode_mesh(&cdmw_formats::synthetic::two_lod_pac(), MeshFormat::Pac)
                .expect("two LOD document");
        let mut mesh = WorkingMesh::from_document_lod(&document, 1).expect("LOD1 mesh");
        let (handle, source_element, position) = mesh
            .vertices()
            .next()
            .map(|(handle, vertex)| {
                let Provenance::Source { element, .. } = vertex.provenance else {
                    panic!("source provenance");
                };
                (handle, element as usize, vertex.position)
            })
            .expect("LOD1 vertex");
        let edited = [position[0] + 3.0, position[1], position[2]];
        mesh.apply_positions(&std::collections::HashMap::from([(handle, edited)]))
            .expect("edit LOD1");

        let candidate = build_candidate("session", &document, &mesh, 1).expect("LOD1 candidate");

        assert_eq!(candidate.submeshes.len(), document.lods[1].submeshes.len());
        assert_eq!(candidate.submeshes[0].positions[source_element], edited);
        assert_ne!(
            candidate.submeshes[0].positions, document.lods[0].submeshes[0].positions,
            "candidate was built from LOD0"
        );
    }

    #[test]
    fn owned_mesh_slider_profiles_are_allowed_but_remain_bounded_and_isolated() {
        let root = tempdir().expect("root");
        fs::write(root.path().join("manifest.json"), b"{}").expect("manifest");
        fs::write(root.path().join("unused.json"), b"{}").expect("payload");
        let bridge = CdmwBridge::for_test(root.path().to_path_buf(), "session", 1, 0);
        let presets = root
            .path()
            .join("mesh_slider_profiles")
            .join("presets")
            .join("body");
        fs::create_dir_all(&presets).expect("profile directories");
        fs::write(presets.join("standing.json"), b"{\"values\":{}}").expect("profile payload");

        reject_unexpected_initial_files(root.path(), bridge.manifest()).expect("owned profiles");

        fs::create_dir(root.path().join("unowned-directory")).expect("unowned directory");
        assert!(reject_unexpected_initial_files(root.path(), bridge.manifest()).is_err());
        fs::remove_dir(root.path().join("unowned-directory")).expect("remove unowned directory");

        let oversized = presets.join("oversized.json");
        OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&oversized)
            .expect("oversized file")
            .set_len(MAX_PROFILE_FILE_BYTES + 1)
            .expect("size oversized file");
        assert!(reject_unexpected_initial_files(root.path(), bridge.manifest()).is_err());
    }

    #[test]
    fn references_reject_path_escape_and_hash_mismatch() {
        let root = tempdir().expect("root");
        let file = root.path().join("document.json");
        fs::write(&file, b"{}").expect("write");
        let reference = FileReference {
            path: "../document.json".to_owned(),
            data_type: "mesh_document_json".to_owned(),
            count: 1,
            byte_length: 2,
            sha256: sha256_upper(b"{}"),
            content_type: "application/json".to_owned(),
        };
        assert!(read_json_reference(root.path(), &reference).is_err());
        let invalid_hash = FileReference {
            path: "document.json".to_owned(),
            sha256: "0".repeat(64),
            ..reference
        };
        assert!(read_json_reference(root.path(), &invalid_hash).is_err());
    }

    #[test]
    fn cdmw_textures_are_hash_checked_parsed_and_bound_to_owned_materials() {
        let root = tempdir().expect("root");
        let bytes = cdmw_texture::synthetic::rgba8_checker_dds();
        let sha256 = sha256_upper(&bytes);
        let name = format!("texture-0000-{}.dds", sha256[..12].to_ascii_lowercase());
        fs::write(root.path().join(&name), &bytes).expect("texture");
        let mut bridge = CdmwBridge::for_test(root.path().to_path_buf(), "session", 1, 0);
        bridge.manifest.textures = vec![SessionTextureReference {
            label: "body_base.dds".to_owned(),
            role: TextureRole::BaseColor,
            file: FileReference {
                path: name,
                data_type: "dds_texture".to_owned(),
                count: 1,
                byte_length: u64::try_from(bytes.len()).expect("length"),
                sha256,
                content_type: "image/vnd-ms.dds".to_owned(),
            },
            material_indices_by_lod: vec![vec![0]],
        }];

        let resources = read_texture_resources(&bridge.root, bridge.manifest(), &document())
            .expect("validated texture resources");
        assert_eq!(resources.len(), 1);
        assert_eq!(resources[0].role, TextureRole::BaseColor);
        assert_eq!(resources[0].material_indices_by_lod, vec![vec![0]]);
        assert_eq!(
            resources[0].metadata.source_sha256.to_ascii_uppercase(),
            sha256_upper(&resources[0].bytes)
        );
    }

    #[test]
    fn cdmw_material_presentations_are_validated_and_roundtrip_to_the_application() {
        let root = tempdir().expect("root");
        fs::write(root.path().join("unused.json"), b"{}").expect("payload");
        let mut bridge = CdmwBridge::for_test(root.path().to_path_buf(), "session", 1, 0);
        bridge.manifest.material_presentations = vec![material_presentation()];

        validate_material_presentations(bridge.manifest(), &document())
            .expect("canonical material presentation");
        let presentations = bridge.take_material_presentations();
        assert_eq!(presentations, vec![material_presentation()]);
        assert!(bridge.manifest.material_presentations.is_empty());
    }

    #[test]
    fn cdmw_material_presentations_reject_invalid_category_range_and_index() {
        let mut manifest = CdmwBridge::for_test(
            tempdir().expect("root").path().to_path_buf(),
            "session",
            1,
            0,
        )
        .manifest
        .clone();

        let mut invalid_category = material_presentation();
        invalid_category.material_category = "painted_metal".to_owned();
        manifest.material_presentations = vec![invalid_category];
        assert!(validate_material_presentations(&manifest, &document()).is_err());

        let mut invalid_range = material_presentation();
        invalid_range.roughness = Some(1.01);
        manifest.material_presentations = vec![invalid_range];
        assert!(validate_material_presentations(&manifest, &document()).is_err());

        let mut invalid_tint = material_presentation();
        invalid_tint.texture_tint = Some([0.5, f32::NAN, 0.5]);
        manifest.material_presentations = vec![invalid_tint];
        assert!(validate_material_presentations(&manifest, &document()).is_err());

        let mut invalid_tint_strength = material_presentation();
        invalid_tint_strength.base_tint_strength = Some(1.01);
        manifest.material_presentations = vec![invalid_tint_strength];
        assert!(validate_material_presentations(&manifest, &document()).is_err());

        let mut invalid_index = material_presentation();
        invalid_index.material_index = 1;
        manifest.material_presentations = vec![invalid_index];
        assert!(validate_material_presentations(&manifest, &document()).is_err());

        let mut valid_skin_detail = material_presentation();
        valid_skin_detail.material_category = "skin".to_owned();
        valid_skin_detail.category_code = 5;
        valid_skin_detail.skin_detail_scale = Some(0.02);
        valid_skin_detail.skin_detail_opacity = Some(1.0);
        manifest.material_presentations = vec![valid_skin_detail.clone()];
        validate_material_presentations(&manifest, &document())
            .expect("real body skin detail factors");

        let mut invalid_skin_scale = valid_skin_detail.clone();
        invalid_skin_scale.skin_detail_scale = Some(0.0);
        manifest.material_presentations = vec![invalid_skin_scale];
        assert!(validate_material_presentations(&manifest, &document()).is_err());

        let mut invalid_skin_opacity = valid_skin_detail;
        invalid_skin_opacity.skin_detail_opacity = Some(1.01);
        manifest.material_presentations = vec![invalid_skin_opacity];
        assert!(validate_material_presentations(&manifest, &document()).is_err());

        manifest.material_presentations = vec![material_presentation(), material_presentation()];
        assert!(validate_material_presentations(&manifest, &document()).is_err());
    }

    #[test]
    fn unmatched_stale_out_of_order_and_replayed_results_cannot_advance_revision() {
        let root = tempdir().expect("root");
        let mut bridge = CdmwBridge::for_test(root.path().to_path_buf(), "session", 3, 4);
        let state = json!({"session_id": "session", "base_revision": 5});
        let payload = json!({"state": state});

        let decoded = bridge.decode_host_event(json!({
            "event": "command_result",
            "protocol": PROTOCOL,
            "session_id": "session",
            "request_id": 99,
            "base_revision": 99,
            "process_generation": 3,
            "ok": true,
            "payload": {"state": {"session_id": "session", "base_revision": 99}}
        }));
        assert!(matches!(decoded, HostEvent::Result { request_id: 99, .. }));
        assert_eq!(bridge.shadow_revision(), 4);

        assert!(
            bridge
                .prepare_host_result("command_result", 10, "command_result", 9, 5, true, &payload)
                .is_err()
        );
        assert!(
            bridge
                .prepare_host_result(
                    "command_result",
                    10,
                    "transaction_result",
                    10,
                    5,
                    true,
                    &payload,
                )
                .is_err()
        );
        let stale_payload = json!({
            "state": {"session_id": "session", "base_revision": 3}
        });
        assert!(
            bridge
                .prepare_host_result(
                    "command_result",
                    10,
                    "command_result",
                    10,
                    3,
                    true,
                    &stale_payload,
                )
                .is_err()
        );
        assert_eq!(bridge.shadow_revision(), 4);

        let prepared = bridge
            .prepare_host_result(
                "command_result",
                10,
                "command_result",
                10,
                5,
                true,
                &payload,
            )
            .expect("matched result");
        assert_eq!(bridge.shadow_revision(), 4, "prepare must not publish");
        let (revision, _, _) = prepared.into_parts();
        bridge
            .accept_prepared_revision(revision)
            .expect("accept matched result");
        assert_eq!(bridge.shadow_revision(), 5);
        assert!(
            bridge
                .prepare_host_result(
                    "command_result",
                    10,
                    "command_result",
                    10,
                    5,
                    true,
                    &payload,
                )
                .is_err(),
            "accepted request replay was not rejected"
        );
        assert_eq!(bridge.shadow_revision(), 5);
    }

    #[test]
    fn correlated_theme_update_is_a_non_authoring_host_event() {
        let root = tempdir().expect("root");
        let mut bridge = CdmwBridge::for_test(root.path().to_path_buf(), "session", 3, 4);
        let decoded = bridge.decode_host_event(json!({
            "event": "theme_update",
            "protocol": PROTOCOL,
            "session_id": "session",
            "request_id": 7,
            "base_revision": 4,
            "process_generation": 3,
            "payload": {"theme": "nord", "variant": "dark"}
        }));
        assert!(matches!(
            decoded,
            HostEvent::Theme(theme)
                if theme.get("theme").and_then(Value::as_str) == Some("nord")
        ));
        assert_eq!(bridge.shadow_revision(), 4);
    }

    #[test]
    fn matched_rejection_prepares_validated_authoritative_recovery_document() {
        let root = tempdir().expect("root");
        let mut authoritative = document();
        authoritative.lods[0].submeshes[0].positions[0] = [7.0, 8.0, 9.0];
        let state = state_with_document(root.path(), "session", 7, &authoritative);
        let mut bridge = CdmwBridge::for_test(root.path().to_path_buf(), "session", 2, 6);

        let prepared = bridge
            .prepare_host_result(
                "transaction_result",
                41,
                "transaction_result",
                41,
                7,
                false,
                &json!({"state": state}),
            )
            .expect("validated recovery");
        assert_eq!(bridge.shadow_revision(), 6, "prepare advanced revision");
        let (revision, recovered_state, recovered_document) = prepared.into_parts();
        assert_eq!(recovered_state.expect("state")["base_revision"], 7);
        assert_eq!(
            recovered_document.expect("document").lods[0].submeshes[0].positions[0],
            [7.0, 8.0, 9.0]
        );
        bridge
            .accept_prepared_revision(revision)
            .expect("publish recovery revision");
        assert_eq!(bridge.shadow_revision(), 7);
    }

    #[test]
    fn rejection_without_matching_recovery_identity_is_refused() {
        let root = tempdir().expect("root");
        let bridge = CdmwBridge::for_test(root.path().to_path_buf(), "session", 2, 6);
        for payload in [
            json!({}),
            json!({"state": {"session_id": "other", "base_revision": 6}}),
            json!({"state": {"session_id": "session", "base_revision": 5}}),
        ] {
            assert!(
                bridge
                    .prepare_host_result(
                        "command_result",
                        5,
                        "command_result",
                        5,
                        6,
                        false,
                        &payload,
                    )
                    .is_err()
            );
            assert_eq!(bridge.shadow_revision(), 6);
        }
    }

    #[test]
    fn state_snapshot_is_single_use_and_cannot_replay_after_publication() {
        let root = tempdir().expect("root");
        let mut bridge = CdmwBridge::for_test(root.path().to_path_buf(), "session", 2, 4);
        let state = json!({"session_id": "session", "base_revision": 4});
        let prepared = bridge
            .prepare_state_snapshot(state.clone())
            .expect("initial state snapshot");
        assert_eq!(bridge.shadow_revision(), 4);
        let (revision, _, _) = prepared.into_parts();
        bridge
            .accept_prepared_revision(revision)
            .expect("publish initial state snapshot");
        assert!(bridge.prepare_state_snapshot(state).is_err());
        assert_eq!(bridge.shadow_revision(), 4);
    }
}
