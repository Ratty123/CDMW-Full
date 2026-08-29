#![forbid(unsafe_code)]

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::fs::{self, File, OpenOptions};
use std::io::{self, Write};
use std::path::{Component, Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};
use thiserror::Error;

pub const EVIDENCE_SCHEMA_VERSION: u32 = 1;
static STAGING_SEQUENCE: AtomicU64 = AtomicU64::new(1);

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SourceFingerprint {
    pub sha256: String,
    pub byte_length: u64,
    pub modified_unix_nanos: Option<u128>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CommandEvidence {
    pub command: String,
    pub exit_code: i32,
    pub duration_ms: u64,
    pub passed: Option<u64>,
    pub failed: Option<u64>,
    pub skipped: Option<u64>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct EvidenceEnvelope<T> {
    pub schema_version: u32,
    pub kind: String,
    pub generated_unix_ms: u128,
    pub payload: T,
}

impl<T> EvidenceEnvelope<T> {
    #[must_use]
    pub fn new(kind: impl Into<String>, payload: T) -> Self {
        let generated_unix_ms = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_or(0, |duration| duration.as_millis());
        Self {
            schema_version: EVIDENCE_SCHEMA_VERSION,
            kind: kind.into(),
            generated_unix_ms,
            payload,
        }
    }
}

#[derive(Debug, Error)]
pub enum EvidenceError {
    #[error("I/O error: {0}")]
    Io(#[from] io::Error),
    #[error("JSON error: {0}")]
    Json(#[from] serde_json::Error),
    #[error("destination already exists; refusing non-atomic replacement: {0}")]
    DestinationExists(PathBuf),
    #[error("destination has no usable file name: {0}")]
    InvalidDestination(PathBuf),
}

#[must_use]
pub fn sha256_bytes(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    format!("{digest:x}")
}

pub fn fingerprint_file(path: &Path) -> Result<SourceFingerprint, EvidenceError> {
    let bytes = fs::read(path)?;
    let metadata = fs::metadata(path)?;
    let modified_unix_nanos = metadata
        .modified()
        .ok()
        .and_then(|modified| modified.duration_since(UNIX_EPOCH).ok())
        .map(|duration| duration.as_nanos());
    Ok(SourceFingerprint {
        sha256: sha256_bytes(&bytes),
        byte_length: metadata.len(),
        modified_unix_nanos,
    })
}

#[must_use]
pub fn redact_local_path(path: &Path) -> String {
    let mut retained = Vec::new();
    for component in path.components() {
        if let Component::Normal(value) = component {
            retained.push(value.to_string_lossy().into_owned());
        }
    }
    retained
        .into_iter()
        .rev()
        .take(2)
        .collect::<Vec<_>>()
        .into_iter()
        .rev()
        .collect::<Vec<_>>()
        .join("/")
}

pub fn write_json_atomic_new<T: Serialize>(
    destination: &Path,
    value: &T,
) -> Result<(), EvidenceError> {
    if destination.exists() {
        return Err(EvidenceError::DestinationExists(destination.to_path_buf()));
    }
    let parent = destination.parent().unwrap_or_else(|| Path::new("."));
    fs::create_dir_all(parent)?;
    let file_name = destination
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| EvidenceError::InvalidDestination(destination.to_path_buf()))?;
    let sequence = STAGING_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let staging = parent.join(format!(
        ".{file_name}.{}.{}.tmp",
        std::process::id(),
        sequence
    ));
    let result = (|| {
        let mut file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&staging)?;
        serde_json::to_writer_pretty(&mut file, value)?;
        file.write_all(b"\n")?;
        file.sync_all()?;
        drop(file);
        fs::rename(&staging, destination)?;
        sync_directory(parent);
        Ok(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(&staging);
    }
    result
}

fn sync_directory(path: &Path) {
    if let Ok(directory) = File::open(path) {
        let _ = directory.sync_all();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn redact_keeps_only_two_trailing_components() {
        let redacted = redact_local_path(Path::new(r"C:\Users\Private\Games\archive.pamt"));
        assert_eq!(redacted, "Games/archive.pamt");
        assert!(!redacted.contains("Private"));
    }

    #[test]
    fn atomic_json_refuses_to_replace_existing_evidence() -> Result<(), Box<dyn std::error::Error>>
    {
        let root = tempfile::tempdir()?;
        let output = root.path().join("report.json");
        write_json_atomic_new(&output, &EvidenceEnvelope::new("test", vec![1_u8, 2]))?;
        let error = write_json_atomic_new(&output, &EvidenceEnvelope::new("test", vec![3_u8]))
            .expect_err("second publication must be refused");
        assert!(matches!(error, EvidenceError::DestinationExists(_)));
        Ok(())
    }
}
