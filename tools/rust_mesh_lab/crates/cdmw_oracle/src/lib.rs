#![forbid(unsafe_code)]

use cdmw_evidence::{EvidenceError, sha256_bytes, write_json_atomic_new};
use cdmw_formats::MeshDocument;
use cdmw_mesh::WorkingMesh;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::fs::{self, OpenOptions};
use std::io::{self, BufRead, BufReader, BufWriter, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use thiserror::Error;

pub const ORACLE_SCHEMA_VERSION: u32 = 1;
static EXPORT_SEQUENCE: AtomicU64 = AtomicU64::new(1);

struct OwnedStaging(PathBuf);

impl Drop for OwnedStaging {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BinaryDescriptor {
    pub relative_path: String,
    pub scalar_type: String,
    pub endianness: String,
    pub components: u32,
    pub count: u64,
    pub byte_length: u64,
    pub sha256: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MeshSummary {
    pub lod_count: u32,
    pub submesh_count: u64,
    pub vertex_count: u64,
    pub index_count: u64,
    pub face_count: u64,
    pub structural_fingerprint: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct NeutralManifest {
    pub schema_version: u32,
    pub oracle_version: String,
    pub source_content_hash: String,
    pub virtual_archive_path: Option<String>,
    pub source_format: String,
    pub parser: String,
    pub provenance_level: String,
    pub warnings: Vec<String>,
    pub mesh: MeshSummary,
    pub buffers: Vec<BinaryDescriptor>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ParityReport {
    pub schema_version: u32,
    pub equal: bool,
    pub mismatches: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct WorkingObjManifest {
    pub schema_version: u32,
    pub format: String,
    pub vertex_count: u64,
    pub face_count: u64,
    pub structural_fingerprint: String,
    pub source_assets_embedded: bool,
    pub source_writeback: bool,
}

#[derive(Debug, Error)]
pub enum OracleError {
    #[error("I/O error: {0}")]
    Io(#[from] io::Error),
    #[error("evidence error: {0}")]
    Evidence(#[from] EvidenceError),
    #[error("JSON error: {0}")]
    Json(#[from] serde_json::Error),
    #[error("output already exists: {0}")]
    DestinationExists(PathBuf),
    #[error("resource count is not representable")]
    CountOverflow,
    #[error("export cancelled")]
    Cancelled,
}

pub fn write_mesh_package(
    destination: &Path,
    document: &MeshDocument,
    virtual_archive_path: Option<String>,
) -> Result<NeutralManifest, OracleError> {
    if destination.exists() {
        return Err(OracleError::DestinationExists(destination.to_path_buf()));
    }
    let parent = destination.parent().unwrap_or_else(|| Path::new("."));
    fs::create_dir_all(parent)?;
    let name = destination
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("oracle-package");
    let sequence = EXPORT_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let staging = parent.join(format!(
        ".{name}.{}.{}.staging",
        std::process::id(),
        sequence
    ));
    fs::create_dir(&staging)?;
    let _owned_staging = OwnedStaging(staging.clone());
    fs::create_dir(staging.join("mesh"))?;

    let mut position_bytes = Vec::new();
    let mut normal_bytes = Vec::new();
    let mut uv_bytes = Vec::new();
    let mut index_bytes = Vec::new();
    let mut vertex_count = 0_u64;
    let mut index_count = 0_u64;
    let mut submesh_count = 0_u64;
    for submesh in document.lods.iter().flat_map(|lod| &lod.submeshes) {
        submesh_count = submesh_count.saturating_add(1);
        vertex_count = vertex_count
            .checked_add(
                u64::try_from(submesh.positions.len()).map_err(|_| OracleError::CountOverflow)?,
            )
            .ok_or(OracleError::CountOverflow)?;
        index_count = index_count
            .checked_add(
                u64::try_from(submesh.indices.len()).map_err(|_| OracleError::CountOverflow)?,
            )
            .ok_or(OracleError::CountOverflow)?;
        for position in &submesh.positions {
            for component in position {
                position_bytes.extend_from_slice(&component.to_le_bytes());
            }
        }
        for normal in &submesh.normals {
            for component in normal {
                normal_bytes.extend_from_slice(&component.to_le_bytes());
            }
        }
        for uv in &submesh.uvs {
            for component in uv {
                uv_bytes.extend_from_slice(&component.to_le_bytes());
            }
        }
        for index in &submesh.indices {
            index_bytes.extend_from_slice(&index.to_le_bytes());
        }
    }
    let buffers = [
        ("mesh/positions.bin", "f32", 3, vertex_count, position_bytes),
        ("mesh/normals.bin", "f32", 3, vertex_count, normal_bytes),
        ("mesh/uvs.bin", "f32", 2, vertex_count, uv_bytes),
        ("mesh/indices.bin", "u32", 1, index_count, index_bytes),
    ];
    let mut descriptors = Vec::new();
    for (relative, scalar, components, count, bytes) in buffers {
        write_new_bytes(&staging.join(relative), &bytes)?;
        descriptors.push(BinaryDescriptor {
            relative_path: relative.to_owned(),
            scalar_type: scalar.to_owned(),
            endianness: "little".to_owned(),
            components,
            count,
            byte_length: u64::try_from(bytes.len()).map_err(|_| OracleError::CountOverflow)?,
            sha256: sha256_bytes(&bytes),
        });
    }
    let manifest = NeutralManifest {
        schema_version: ORACLE_SCHEMA_VERSION,
        oracle_version: env!("CARGO_PKG_VERSION").to_owned(),
        source_content_hash: document.source_sha256.clone(),
        virtual_archive_path,
        source_format: format!("{:?}", document.format).to_ascii_lowercase(),
        parser: document.parser.clone(),
        provenance_level: "native-rust-structural".to_owned(),
        warnings: document.warnings.clone(),
        mesh: MeshSummary {
            lod_count: document.lod_count_reported,
            submesh_count,
            vertex_count,
            index_count,
            face_count: index_count / 3,
            structural_fingerprint: document.structural_fingerprint.clone(),
        },
        buffers: descriptors,
    };
    write_json_atomic_new(&staging.join("manifest.json"), &manifest)?;
    fs::rename(&staging, destination)?;
    Ok(manifest)
}

pub fn read_manifest(path: &Path) -> Result<NeutralManifest, OracleError> {
    Ok(serde_json::from_slice(&fs::read(path)?)?)
}

pub fn export_working_obj(
    destination: &Path,
    mesh: &WorkingMesh,
) -> Result<WorkingObjManifest, OracleError> {
    export_working_obj_cancellable(destination, mesh, || false)
}

pub fn export_working_obj_cancellable(
    destination: &Path,
    mesh: &WorkingMesh,
    mut is_cancelled: impl FnMut() -> bool,
) -> Result<WorkingObjManifest, OracleError> {
    if destination.exists() {
        return Err(OracleError::DestinationExists(destination.to_path_buf()));
    }
    mesh.validate()
        .map_err(|error| io::Error::other(error.to_string()))?;
    let parent = destination.parent().unwrap_or_else(|| Path::new("."));
    fs::create_dir_all(parent)?;
    let name = destination
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("cdmw-rust-mesh-export");
    let sequence = EXPORT_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let staging = parent.join(format!(
        ".{name}.{}.{}.staging",
        std::process::id(),
        sequence
    ));
    fs::create_dir(&staging)?;
    let result = (|| {
        if is_cancelled() {
            return Err(OracleError::Cancelled);
        }
        let snapshot = mesh.draw_snapshot();
        write_obj(&staging.join("mesh.obj"), &snapshot, &mut is_cancelled)?;
        if is_cancelled() {
            return Err(OracleError::Cancelled);
        }
        write_new_bytes(
            &staging.join("mesh.mtl"),
            b"newmtl cdmw_material\nKd 0.82 0.84 0.88\nKs 0.08 0.08 0.08\nNs 32\n",
        )?;
        let (vertex_count, face_count, fingerprint) = reparse_obj(&staging.join("mesh.obj"))?;
        if fingerprint != snapshot.fingerprint
            || vertex_count != snapshot.positions.len()
            || face_count != snapshot.indices.len() / 3
        {
            return Err(OracleError::Io(io::Error::other(
                "reparsed OBJ does not match the edited working mesh",
            )));
        }
        let manifest = WorkingObjManifest {
            schema_version: ORACLE_SCHEMA_VERSION,
            format: "obj+mtl".to_owned(),
            vertex_count: u64::try_from(vertex_count).map_err(|_| OracleError::CountOverflow)?,
            face_count: u64::try_from(face_count).map_err(|_| OracleError::CountOverflow)?,
            structural_fingerprint: fingerprint,
            source_assets_embedded: false,
            source_writeback: false,
        };
        if is_cancelled() {
            return Err(OracleError::Cancelled);
        }
        write_json_atomic_new(&staging.join("manifest.json"), &manifest)?;
        if is_cancelled() {
            return Err(OracleError::Cancelled);
        }
        fs::rename(&staging, destination)?;
        Ok(manifest)
    })();
    if result.is_err() {
        let _ = fs::remove_dir_all(&staging);
    }
    result
}

#[must_use]
pub fn compare_manifests(expected: &NeutralManifest, actual: &NeutralManifest) -> ParityReport {
    let mut mismatches = Vec::new();
    compare_field(
        &mut mismatches,
        "source format",
        &expected.source_format,
        &actual.source_format,
    );
    compare_field(
        &mut mismatches,
        "LOD count",
        &expected.mesh.lod_count,
        &actual.mesh.lod_count,
    );
    compare_field(
        &mut mismatches,
        "submesh count",
        &expected.mesh.submesh_count,
        &actual.mesh.submesh_count,
    );
    compare_field(
        &mut mismatches,
        "vertex count",
        &expected.mesh.vertex_count,
        &actual.mesh.vertex_count,
    );
    compare_field(
        &mut mismatches,
        "index count",
        &expected.mesh.index_count,
        &actual.mesh.index_count,
    );
    compare_field(
        &mut mismatches,
        "structural fingerprint",
        &expected.mesh.structural_fingerprint,
        &actual.mesh.structural_fingerprint,
    );
    ParityReport {
        schema_version: ORACLE_SCHEMA_VERSION,
        equal: mismatches.is_empty(),
        mismatches,
    }
}

fn compare_field<T: PartialEq + std::fmt::Debug>(
    mismatches: &mut Vec<String>,
    label: &str,
    expected: &T,
    actual: &T,
) {
    if expected != actual {
        mismatches.push(format!("{label}: expected {expected:?}, actual {actual:?}"));
    }
}

fn write_new_bytes(path: &Path, bytes: &[u8]) -> Result<(), OracleError> {
    let mut file = OpenOptions::new().create_new(true).write(true).open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(())
}

fn write_obj(
    path: &Path,
    snapshot: &cdmw_mesh::DrawSnapshot,
    is_cancelled: &mut impl FnMut() -> bool,
) -> Result<(), OracleError> {
    let file = OpenOptions::new().create_new(true).write(true).open(path)?;
    let mut writer = BufWriter::new(file);
    writeln!(writer, "mtllib mesh.mtl")?;
    writeln!(writer, "usemtl cdmw_material")?;
    for (index, position) in snapshot.positions.iter().enumerate() {
        if index.is_multiple_of(4_096) && is_cancelled() {
            return Err(OracleError::Cancelled);
        }
        writeln!(writer, "v {} {} {}", position[0], position[1], position[2])?;
    }
    for uv in &snapshot.uvs {
        writeln!(writer, "vt {} {}", uv[0], uv[1])?;
    }
    for normal in &snapshot.normals {
        writeln!(writer, "vn {} {} {}", normal[0], normal[1], normal[2])?;
    }
    for (index, triangle) in snapshot.indices.chunks_exact(3).enumerate() {
        if index.is_multiple_of(4_096) && is_cancelled() {
            return Err(OracleError::Cancelled);
        }
        let first = triangle
            .first()
            .copied()
            .ok_or(OracleError::CountOverflow)?
            + 1;
        let second = triangle.get(1).copied().ok_or(OracleError::CountOverflow)? + 1;
        let third = triangle.get(2).copied().ok_or(OracleError::CountOverflow)? + 1;
        writeln!(
            writer,
            "f {first}/{first}/{first} {second}/{second}/{second} {third}/{third}/{third}"
        )?;
    }
    writer.flush()?;
    let file = writer
        .into_inner()
        .map_err(|error| OracleError::Io(error.into_error()))?;
    file.sync_all()?;
    Ok(())
}

fn reparse_obj(path: &Path) -> Result<(usize, usize, String), OracleError> {
    let file = OpenOptions::new().read(true).open(path)?;
    let mut hasher = Sha256::new();
    let mut vertices = 0_usize;
    let mut faces = 0_usize;
    let mut deferred_indices = Vec::new();
    for line in BufReader::new(file).lines() {
        let line = line?;
        if let Some(value) = line.strip_prefix("v ") {
            let components = value
                .split_whitespace()
                .map(str::parse::<f32>)
                .collect::<Result<Vec<_>, _>>()
                .map_err(|error| OracleError::Io(io::Error::other(error)))?;
            if components.len() != 3 {
                return Err(OracleError::Io(io::Error::other(
                    "OBJ vertex does not have three components",
                )));
            }
            for component in components {
                hasher.update(component.to_le_bytes());
            }
            vertices = vertices.saturating_add(1);
        } else if let Some(value) = line.strip_prefix("f ") {
            let tokens = value.split_whitespace().collect::<Vec<_>>();
            if tokens.len() != 3 {
                return Err(OracleError::Io(io::Error::other(
                    "OBJ face is not a triangle",
                )));
            }
            for token in tokens {
                let vertex = token
                    .split('/')
                    .next()
                    .ok_or_else(|| OracleError::Io(io::Error::other("OBJ face is malformed")))?
                    .parse::<u32>()
                    .map_err(|error| OracleError::Io(io::Error::other(error)))?;
                let zero_based = vertex
                    .checked_sub(1)
                    .ok_or_else(|| OracleError::Io(io::Error::other("OBJ face uses index zero")))?;
                deferred_indices.extend_from_slice(&zero_based.to_le_bytes());
            }
            faces = faces.saturating_add(1);
        }
    }
    hasher.update(&deferred_indices);
    Ok((vertices, faces, format!("{:x}", hasher.finalize())))
}

#[cfg(test)]
mod tests {
    use super::*;
    use cdmw_formats::{MeshFormat, decode_mesh};

    #[test]
    fn compare_reports_count_and_fingerprint_drift() {
        let summary = MeshSummary {
            lod_count: 1,
            submesh_count: 1,
            vertex_count: 3,
            index_count: 3,
            face_count: 1,
            structural_fingerprint: "a".to_owned(),
        };
        let expected = NeutralManifest {
            schema_version: 1,
            oracle_version: "1".to_owned(),
            source_content_hash: "source".to_owned(),
            virtual_archive_path: None,
            source_format: "pam".to_owned(),
            parser: "oracle".to_owned(),
            provenance_level: "strict".to_owned(),
            warnings: Vec::new(),
            mesh: summary.clone(),
            buffers: Vec::new(),
        };
        let mut actual = expected.clone();
        actual.mesh = MeshSummary {
            vertex_count: 4,
            structural_fingerprint: "b".to_owned(),
            ..summary
        };
        let report = compare_manifests(&expected, &actual);
        assert!(!report.equal);
        assert_eq!(report.mismatches.len(), 2);
    }

    #[test]
    fn working_obj_export_reparses_before_atomic_publication()
    -> Result<(), Box<dyn std::error::Error>> {
        let document = decode_mesh(
            &cdmw_formats::synthetic::triangle_pam("synthetic.dds"),
            MeshFormat::Pam,
        )?;
        let mesh = WorkingMesh::from_document(&document)?;
        let root = tempfile::tempdir()?;
        let destination = root.path().join("export");
        let manifest = export_working_obj(&destination, &mesh)?;
        assert_eq!(manifest.vertex_count, 3);
        assert_eq!(manifest.face_count, 1);
        assert!(destination.join("mesh.obj").is_file());
        assert!(destination.join("mesh.mtl").is_file());
        assert!(destination.join("manifest.json").is_file());
        assert!(matches!(
            export_working_obj(&destination, &mesh),
            Err(OracleError::DestinationExists(_))
        ));
        Ok(())
    }
}
