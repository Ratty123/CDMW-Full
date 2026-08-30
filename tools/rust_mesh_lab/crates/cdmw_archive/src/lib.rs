#![forbid(unsafe_code)]

use cdmw_evidence::{SourceFingerprint, fingerprint_file};
use chacha20::cipher::{KeyIvInit, StreamCipher, StreamCipherSeek};
use chacha20::{ChaCha20Legacy, Key, LegacyNonce};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, HashMap, HashSet};
use std::fs::{self, File};
use std::io::{self, Read, Seek, SeekFrom};
use std::path::{Component, Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use thiserror::Error;

pub const INDEX_SCHEMA_VERSION: u32 = 1;
pub const DEFAULT_MAX_INDEX_BYTES: u64 = 512 * 1024 * 1024;
pub const DEFAULT_MAX_ENTRY_BYTES: u64 = 2 * 1024 * 1024 * 1024;
const LOOKUP3_INIT: u32 = 0x000c_5ede;
const CHACHA_IV_XOR: u32 = 0x6061_6263;
const DDS_MAGIC: &[u8; 4] = b"DDS ";
const DDS_LEGACY_HEADER_BYTES: usize = 0x80;
const DDS_DX10_HEADER_BYTES: usize = 0x94;
const DDS_MAX_DIMENSION: u32 = 16_384;
const PATHC_FIXED_HEADER_BYTES: usize = 28;
const PATHC_MAX_TEXTURE_HEADER_BYTES: usize = 4_096;
const CHACHA_XOR_DELTAS: [u32; 8] = [
    0,
    0x0a0a_0a0a,
    0x0c0c_0c0c,
    0x0606_0606,
    0x0e0e_0e0e,
    0x0a0a_0a0a,
    0x0606_0606,
    0x0202_0202,
];

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct ArchiveLimits {
    pub max_index_bytes: u64,
    pub max_entries: usize,
    pub max_entry_bytes: u64,
    pub max_path_depth: usize,
    pub max_path_bytes: usize,
}

impl Default for ArchiveLimits {
    fn default() -> Self {
        Self {
            max_index_bytes: DEFAULT_MAX_INDEX_BYTES,
            max_entries: 20_000_000,
            max_entry_bytes: DEFAULT_MAX_ENTRY_BYTES,
            max_path_depth: 256,
            max_path_bytes: 32_768,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PazRecord {
    pub checksum: u32,
    pub file_count: u32,
    pub reserved: u32,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ArchiveEntry {
    pub virtual_path: String,
    pub payload_index: u16,
    pub offset: u64,
    pub stored_size: u64,
    pub original_size: u64,
    pub flags: u16,
}

impl ArchiveEntry {
    #[must_use]
    pub const fn compression_type(&self) -> u8 {
        (self.flags & 0x0f) as u8
    }

    #[must_use]
    pub const fn encryption_type(&self) -> u8 {
        ((self.flags >> 4) & 0x0f) as u8
    }

    #[must_use]
    pub const fn is_compressed(&self) -> bool {
        self.stored_size != self.original_size
    }

    #[must_use]
    pub const fn is_encrypted(&self) -> bool {
        (self.flags >> 4) != 0
    }

    #[must_use]
    pub fn basename(&self) -> &str {
        self.virtual_path
            .rsplit('/')
            .next()
            .unwrap_or(self.virtual_path.as_str())
    }

    #[must_use]
    pub fn extension(&self) -> &str {
        self.basename()
            .rfind('.')
            .map_or("", |position| self.basename().get(position..).unwrap_or(""))
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ArchiveIndex {
    pub schema_version: u32,
    pub header_crc: u32,
    pub reserved: u32,
    pub paz_records: Vec<PazRecord>,
    pub entries: Vec<ArchiveEntry>,
    pub duplicate_paths: Vec<String>,
    pub case_collisions: Vec<Vec<String>>,
}

#[derive(Debug, Clone)]
pub struct CatalogEntry {
    pub index_id: usize,
    pub entry: ArchiveEntry,
}

#[derive(Debug, Clone)]
pub struct ArchiveCatalog {
    pub root: PathBuf,
    pub indexes: Vec<PathBuf>,
    pub entries: Vec<CatalogEntry>,
    pub warnings: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CatalogProgress {
    pub indexes_complete: usize,
    pub indexes_total: usize,
    pub entries_loaded: usize,
    pub label: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DecodedEntry {
    pub bytes: Vec<u8>,
    pub compression: CompressionOutcome,
    pub encryption: EncryptionOutcome,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CompressionOutcome {
    Stored,
    PartialRaw,
    PartialDds,
    SparseDds,
    Lz4,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EncryptionOutcome {
    None,
    ChaCha20,
}

#[derive(Debug, Error)]
pub enum ArchiveError {
    #[error("I/O error: {0}")]
    Io(#[from] io::Error),
    #[error("archive index exceeds configured limit ({actual} > {limit} bytes)")]
    IndexTooLarge { actual: u64, limit: u64 },
    #[error("archive entry exceeds configured limit ({actual} > {limit} bytes)")]
    EntryTooLarge { actual: u64, limit: u64 },
    #[error("archive index is truncated while reading {0}")]
    Truncated(&'static str),
    #[error("archive table count is not representable")]
    CountOverflow,
    #[error("archive contains {actual} entries, exceeding configured limit {limit}")]
    TooManyEntries { actual: usize, limit: usize },
    #[error("invalid virtual path record at offset {0}")]
    InvalidPathOffset(u32),
    #[error("virtual path parent cycle at offset {0}")]
    PathCycle(u32),
    #[error("virtual path exceeds configured depth or byte limit")]
    PathLimit,
    #[error("virtual path is empty for entry {0}")]
    EmptyPath(usize),
    #[error("payload index {payload_index} is outside the PAZ table")]
    InvalidPayloadIndex { payload_index: u16 },
    #[error("payload range is outside {path}: offset={offset}, size={size}, file={file_size}")]
    PayloadRange {
        path: PathBuf,
        offset: u64,
        size: u64,
        file_size: u64,
    },
    #[error("unsupported archive compression type {0}")]
    UnsupportedCompression(u8),
    #[error("unsupported archive encryption type {0}")]
    UnsupportedEncryption(u8),
    #[error("LZ4 block failed: {0}")]
    Lz4(String),
    #[error("Partial DDS reconstruction failed: {0}")]
    PartialDds(String),
    #[error("Sparse DDS reconstruction failed: {0}")]
    SparseDds(String),
    #[error("decoded entry size mismatch: expected {expected}, actual {actual}")]
    DecodedSize { expected: u64, actual: u64 },
    #[error("operation cancelled")]
    Cancelled,
    #[error("source file changed during read: {0}")]
    SourceChanged(PathBuf),
    #[error("invalid archive root: {0}")]
    InvalidArchiveRoot(PathBuf),
}

#[derive(Debug, Default)]
pub struct CancellationToken {
    cancelled: AtomicBool,
}

impl CancellationToken {
    pub fn cancel(&self) {
        self.cancelled.store(true, Ordering::Release);
    }

    pub fn check(&self) -> Result<(), ArchiveError> {
        if self.cancelled.load(Ordering::Acquire) {
            Err(ArchiveError::Cancelled)
        } else {
            Ok(())
        }
    }
}

impl ArchiveIndex {
    pub fn read(path: &Path, limits: ArchiveLimits) -> Result<Self, ArchiveError> {
        let metadata = fs::metadata(path)?;
        if metadata.len() > limits.max_index_bytes {
            return Err(ArchiveError::IndexTooLarge {
                actual: metadata.len(),
                limit: limits.max_index_bytes,
            });
        }
        let bytes = fs::read(path)?;
        Self::parse(&bytes, limits)
    }

    pub fn parse(bytes: &[u8], limits: ArchiveLimits) -> Result<Self, ArchiveError> {
        let mut cursor = Cursor::new(bytes);
        let header_crc = cursor.u32("header")?;
        let paz_count =
            usize::try_from(cursor.u32("PAZ count")?).map_err(|_| ArchiveError::CountOverflow)?;
        let reserved = cursor.u32("header")?;
        let mut paz_records = Vec::new();
        paz_records
            .try_reserve_exact(paz_count)
            .map_err(|_| ArchiveError::CountOverflow)?;
        for _ in 0..paz_count {
            paz_records.push(PazRecord {
                checksum: cursor.u32("PAZ table")?,
                file_count: cursor.u32("PAZ table")?,
                reserved: cursor.u32("PAZ table")?,
            });
        }

        let directory_data = cursor.length_prefixed_block("directory block")?;
        let file_name_data = cursor.length_prefixed_block("file-name block")?;
        let folder_count = usize::try_from(cursor.u32("folder count")?)
            .map_err(|_| ArchiveError::CountOverflow)?;
        let folder_bytes = folder_count
            .checked_mul(16)
            .ok_or(ArchiveError::CountOverflow)?;
        let folder_table = cursor.take(folder_bytes, "folder table")?;
        let file_count =
            usize::try_from(cursor.u32("file count")?).map_err(|_| ArchiveError::CountOverflow)?;
        if file_count > limits.max_entries {
            return Err(ArchiveError::TooManyEntries {
                actual: file_count,
                limit: limits.max_entries,
            });
        }
        let file_bytes = file_count
            .checked_mul(20)
            .ok_or(ArchiveError::CountOverflow)?;
        let file_table = cursor.take(file_bytes, "file table")?;

        let mut directory_resolver = PathResolver::new(directory_data, limits);
        let mut file_resolver = PathResolver::new(file_name_data, limits);
        let mut folders = Vec::with_capacity(folder_count);
        for record in folder_table.chunks_exact(16) {
            let name_offset = read_u32(record, 4, "folder table")?;
            let start = usize::try_from(read_u32(record, 8, "folder table")?)
                .map_err(|_| ArchiveError::CountOverflow)?;
            let count = usize::try_from(read_u32(record, 12, "folder table")?)
                .map_err(|_| ArchiveError::CountOverflow)?;
            if count == 0 {
                continue;
            }
            let end = start
                .checked_add(count)
                .ok_or(ArchiveError::CountOverflow)?;
            let directory = normalize_virtual_path(&directory_resolver.resolve(name_offset)?)?;
            folders.push((start, end, directory));
        }
        folders.sort_by_key(|(start, _, _)| *start);

        let mut entries = Vec::with_capacity(file_count);
        let mut folder_cursor = 0_usize;
        for (entry_index, record) in file_table.chunks_exact(20).enumerate() {
            let name_offset = read_u32(record, 0, "file table")?;
            let offset = u64::from(read_u32(record, 4, "file table")?);
            let stored_size = u64::from(read_u32(record, 8, "file table")?);
            let original_size = u64::from(read_u32(record, 12, "file table")?);
            let payload_index = read_u16(record, 16, "file table")?;
            let flags = read_u16(record, 18, "file table")?;
            if usize::from(payload_index) >= paz_records.len() {
                return Err(ArchiveError::InvalidPayloadIndex { payload_index });
            }
            if stored_size > limits.max_entry_bytes || original_size > limits.max_entry_bytes {
                return Err(ArchiveError::EntryTooLarge {
                    actual: stored_size.max(original_size),
                    limit: limits.max_entry_bytes,
                });
            }
            while let Some((_, end, _)) = folders.get(folder_cursor) {
                if entry_index < *end {
                    break;
                }
                folder_cursor = folder_cursor.saturating_add(1);
            }
            let file_path = normalize_virtual_path(&file_resolver.resolve(name_offset)?)?;
            let directory = folders
                .get(folder_cursor)
                .filter(|(start, end, _)| *start <= entry_index && entry_index < *end)
                .map(|(_, _, path)| path.as_str())
                .unwrap_or("");
            let virtual_path = if directory.is_empty() {
                file_path
            } else {
                format!("{directory}/{file_path}")
            };
            if virtual_path.is_empty() {
                return Err(ArchiveError::EmptyPath(entry_index));
            }
            entries.push(ArchiveEntry {
                virtual_path,
                payload_index,
                offset,
                stored_size,
                original_size,
                flags,
            });
        }

        let (duplicate_paths, case_collisions) = find_path_collisions(&entries);
        Ok(Self {
            schema_version: INDEX_SCHEMA_VERSION,
            header_crc,
            reserved,
            paz_records,
            entries,
            duplicate_paths,
            case_collisions,
        })
    }

    pub fn search<'a>(&'a self, needle: &str) -> impl Iterator<Item = &'a ArchiveEntry> {
        let needle = needle.replace('\\', "/").to_lowercase();
        self.entries
            .iter()
            .filter(move |entry| entry.virtual_path.to_lowercase().contains(&needle))
    }
}

pub fn read_entry(
    payload_root: &Path,
    entry: &ArchiveEntry,
    limits: ArchiveLimits,
    cancellation: &CancellationToken,
) -> Result<(DecodedEntry, SourceFingerprint, SourceFingerprint), ArchiveError> {
    let payload_path = payload_root.join(format!("{}.paz", entry.payload_index));
    let before = fingerprint_file(&payload_path).map_err(|error| match error {
        cdmw_evidence::EvidenceError::Io(io_error) => ArchiveError::Io(io_error),
        other => ArchiveError::Io(io::Error::other(other)),
    })?;
    let decoded = read_entry_unverified(payload_root, entry, limits, cancellation)?;
    let after = fingerprint_file(&payload_path).map_err(|error| match error {
        cdmw_evidence::EvidenceError::Io(io_error) => ArchiveError::Io(io_error),
        other => ArchiveError::Io(io::Error::other(other)),
    })?;
    if before != after {
        return Err(ArchiveError::SourceChanged(payload_path));
    }
    Ok((decoded, before, after))
}

pub fn read_entry_unverified(
    payload_root: &Path,
    entry: &ArchiveEntry,
    limits: ArchiveLimits,
    cancellation: &CancellationToken,
) -> Result<DecodedEntry, ArchiveError> {
    cancellation.check()?;
    validate_archive_root(payload_root)?;
    if entry.stored_size > limits.max_entry_bytes || entry.original_size > limits.max_entry_bytes {
        return Err(ArchiveError::EntryTooLarge {
            actual: entry.stored_size.max(entry.original_size),
            limit: limits.max_entry_bytes,
        });
    }
    let payload_path = payload_root.join(format!("{}.paz", entry.payload_index));
    let mut file = File::open(&payload_path)?;
    let file_size = file.metadata()?.len();
    let end =
        entry
            .offset
            .checked_add(entry.stored_size)
            .ok_or_else(|| ArchiveError::PayloadRange {
                path: payload_path.clone(),
                offset: entry.offset,
                size: entry.stored_size,
                file_size,
            })?;
    if end > file_size {
        return Err(ArchiveError::PayloadRange {
            path: payload_path,
            offset: entry.offset,
            size: entry.stored_size,
            file_size,
        });
    }
    let buffer_size =
        usize::try_from(entry.stored_size).map_err(|_| ArchiveError::EntryTooLarge {
            actual: entry.stored_size,
            limit: limits.max_entry_bytes,
        })?;
    let mut bytes = vec![0_u8; buffer_size];
    file.seek(SeekFrom::Start(entry.offset))?;
    file.read_exact(&mut bytes)?;
    drop(file);
    cancellation.check()?;

    let encryption = if entry.is_encrypted() {
        if entry.encryption_type() != 3 {
            return Err(ArchiveError::UnsupportedEncryption(entry.encryption_type()));
        }
        crypt_chacha20_filename(&mut bytes, entry.basename());
        EncryptionOutcome::ChaCha20
    } else {
        EncryptionOutcome::None
    };
    cancellation.check()?;

    let (bytes, compression) = if !entry.is_compressed() {
        (bytes, CompressionOutcome::Stored)
    } else {
        match entry.compression_type() {
            0 => (
                reconstruct_sparse_dds(entry, bytes, limits.max_entry_bytes)?,
                CompressionOutcome::SparseDds,
            ),
            1 if entry.extension().eq_ignore_ascii_case(".dds") => (
                reconstruct_partial_dds(payload_root, entry, &bytes, limits, cancellation)?,
                CompressionOutcome::PartialDds,
            ),
            1 => (bytes, CompressionOutcome::PartialRaw),
            2 => {
                let expected = usize::try_from(entry.original_size).map_err(|_| {
                    ArchiveError::EntryTooLarge {
                        actual: entry.original_size,
                        limit: limits.max_entry_bytes,
                    }
                })?;
                let decoded = lz4_flex::block::decompress(&bytes, expected)
                    .map_err(|error| ArchiveError::Lz4(error.to_string()))?;
                (decoded, CompressionOutcome::Lz4)
            }
            other => return Err(ArchiveError::UnsupportedCompression(other)),
        }
    };
    if !matches!(
        compression,
        CompressionOutcome::PartialRaw | CompressionOutcome::PartialDds
    ) && entry.original_size > 0
        && u64::try_from(bytes.len()).ok() != Some(entry.original_size)
    {
        return Err(ArchiveError::DecodedSize {
            expected: entry.original_size,
            actual: u64::try_from(bytes.len()).unwrap_or(u64::MAX),
        });
    }
    Ok(DecodedEntry {
        bytes,
        compression,
        encryption,
    })
}

#[derive(Debug, Clone)]
struct PathcEntry {
    texture_header_index: u16,
    compressed_block_infos: [u8; 16],
}

#[derive(Debug)]
struct PathcCollisionEntry {
    filename_offset: usize,
    entry: PathcEntry,
}

#[derive(Debug)]
struct PathcCollection {
    header_size: usize,
    headers: Vec<Vec<u8>>,
    entries: HashMap<u32, PathcEntry>,
    collisions: HashMap<String, PathcEntry>,
}

impl PathcCollection {
    fn parse(bytes: &[u8], max_records: usize) -> Result<Self, ArchiveError> {
        if bytes.len() < PATHC_FIXED_HEADER_BYTES {
            return Err(ArchiveError::PartialDds(
                "PATHC file is smaller than its fixed header".to_owned(),
            ));
        }
        let header_size = usize::try_from(read_u32(bytes, 8, "PATHC fixed header")?)
            .map_err(|_| ArchiveError::CountOverflow)?;
        if !(DDS_LEGACY_HEADER_BYTES..=PATHC_MAX_TEXTURE_HEADER_BYTES).contains(&header_size) {
            return Err(ArchiveError::PartialDds(format!(
                "PATHC texture header size {header_size} is unsupported"
            )));
        }
        let header_count = usize::try_from(read_u32(bytes, 12, "PATHC fixed header")?)
            .map_err(|_| ArchiveError::CountOverflow)?;
        let entry_count = usize::try_from(read_u32(bytes, 16, "PATHC fixed header")?)
            .map_err(|_| ArchiveError::CountOverflow)?;
        let collision_count = usize::try_from(read_u32(bytes, 20, "PATHC fixed header")?)
            .map_err(|_| ArchiveError::CountOverflow)?;
        let filenames_length = usize::try_from(read_u32(bytes, 24, "PATHC fixed header")?)
            .map_err(|_| ArchiveError::CountOverflow)?;
        let record_count = header_count
            .checked_add(entry_count)
            .and_then(|value| value.checked_add(collision_count))
            .ok_or(ArchiveError::CountOverflow)?;
        if record_count > max_records {
            return Err(ArchiveError::PartialDds(format!(
                "PATHC contains {record_count} records, above the configured limit {max_records}"
            )));
        }
        let expected_bytes = PATHC_FIXED_HEADER_BYTES
            .checked_add(
                header_count
                    .checked_mul(header_size)
                    .ok_or(ArchiveError::CountOverflow)?,
            )
            .and_then(|value| value.checked_add(entry_count.checked_mul(4)?))
            .and_then(|value| value.checked_add(entry_count.checked_mul(20)?))
            .and_then(|value| value.checked_add(collision_count.checked_mul(24)?))
            .and_then(|value| value.checked_add(filenames_length))
            .ok_or(ArchiveError::CountOverflow)?;
        if expected_bytes > bytes.len() {
            return Err(ArchiveError::PartialDds(format!(
                "PATHC tables require {expected_bytes} bytes but only {} are present",
                bytes.len()
            )));
        }

        let mut cursor = Cursor {
            bytes,
            offset: PATHC_FIXED_HEADER_BYTES,
        };
        let mut headers = Vec::with_capacity(header_count);
        for _ in 0..header_count {
            headers.push(
                cursor
                    .take(header_size, "PATHC texture header table")?
                    .to_vec(),
            );
        }
        let mut checksums = Vec::with_capacity(entry_count);
        for _ in 0..entry_count {
            checksums.push(cursor.u32("PATHC checksum table")?);
        }
        let mut entries = HashMap::with_capacity(entry_count);
        for checksum in checksums {
            let row = cursor.take(20, "PATHC entry table")?;
            let texture_header_index = read_u16(row, 0, "PATHC entry table")?;
            let compressed_block_infos = row
                .get(4..20)
                .ok_or(ArchiveError::Truncated("PATHC entry table"))?
                .try_into()
                .map_err(|_| ArchiveError::Truncated("PATHC entry table"))?;
            entries.insert(
                checksum,
                PathcEntry {
                    texture_header_index,
                    compressed_block_infos,
                },
            );
        }
        let mut collision_rows = Vec::with_capacity(collision_count);
        for _ in 0..collision_count {
            let row = cursor.take(24, "PATHC collision table")?;
            let filename_offset = usize::try_from(read_u32(row, 0, "PATHC collision table")?)
                .map_err(|_| ArchiveError::CountOverflow)?;
            let texture_header_index = read_u16(row, 4, "PATHC collision table")?;
            let compressed_block_infos = row
                .get(8..24)
                .ok_or(ArchiveError::Truncated("PATHC collision table"))?
                .try_into()
                .map_err(|_| ArchiveError::Truncated("PATHC collision table"))?;
            collision_rows.push(PathcCollisionEntry {
                filename_offset,
                entry: PathcEntry {
                    texture_header_index,
                    compressed_block_infos,
                },
            });
        }
        let filenames = cursor.take(filenames_length, "PATHC filename table")?;
        let mut collisions = HashMap::with_capacity(collision_rows.len());
        for collision in collision_rows {
            let Some(remainder) = filenames.get(collision.filename_offset..) else {
                continue;
            };
            let end = remainder
                .iter()
                .position(|value| *value == 0)
                .unwrap_or(remainder.len());
            let path =
                std::str::from_utf8(remainder.get(..end).unwrap_or_default()).map_err(|_| {
                    ArchiveError::PartialDds(
                        "PATHC collision filename is not valid UTF-8".to_owned(),
                    )
                })?;
            let normalized = path.replace('\\', "/").trim_start_matches('/').to_owned();
            if !normalized.is_empty() {
                collisions.insert(normalized, collision.entry);
            }
        }
        Ok(Self {
            header_size,
            headers,
            entries,
            collisions,
        })
    }

    fn header_for(&self, virtual_path: &str) -> Result<Vec<u8>, ArchiveError> {
        let normalized = virtual_path
            .replace('\\', "/")
            .trim_start_matches('/')
            .to_owned();
        let lookup_path = format!("/{normalized}");
        let direct = self
            .entries
            .get(&hashlittle(lookup_path.as_bytes(), LOOKUP3_INIT))
            .ok_or_else(|| {
                ArchiveError::PartialDds(format!("PATHC has no entry for {virtual_path}"))
            })?;
        let entry = if direct.texture_header_index == u16::MAX {
            self.collisions.get(&normalized).ok_or_else(|| {
                ArchiveError::PartialDds(format!(
                    "PATHC collision table has no entry for {virtual_path}"
                ))
            })?
        } else {
            direct
        };
        let mut header = self
            .headers
            .get(usize::from(entry.texture_header_index))
            .cloned()
            .ok_or_else(|| {
                ArchiveError::PartialDds(format!(
                    "PATHC texture header index {} is outside its table",
                    entry.texture_header_index
                ))
            })?;
        if self.header_size == DDS_DX10_HEADER_BYTES {
            let destination = header.get_mut(0x20..0x30).ok_or_else(|| {
                ArchiveError::PartialDds("PATHC DX10 texture header is truncated".to_owned())
            })?;
            destination.copy_from_slice(&entry.compressed_block_infos);
        }
        Ok(header)
    }
}

fn read_pathc_collection(
    payload_root: &Path,
    limits: ArchiveLimits,
) -> Result<PathcCollection, ArchiveError> {
    let archive_root = payload_root.parent().ok_or_else(|| {
        ArchiveError::PartialDds(format!(
            "archive payload directory {} has no package parent",
            payload_root.display()
        ))
    })?;
    let path = archive_root.join("meta").join("0.pathc");
    let metadata = fs::metadata(&path).map_err(|error| {
        ArchiveError::PartialDds(format!(
            "metadata file {} is unavailable: {error}",
            path.display()
        ))
    })?;
    if metadata.len() > limits.max_index_bytes {
        return Err(ArchiveError::PartialDds(format!(
            "metadata file {} exceeds the {}-byte limit",
            path.display(),
            limits.max_index_bytes
        )));
    }
    let bytes = fs::read(&path).map_err(|error| {
        ArchiveError::PartialDds(format!(
            "failed to read metadata file {}: {error}",
            path.display()
        ))
    })?;
    if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > limits.max_index_bytes {
        return Err(ArchiveError::PartialDds(format!(
            "metadata file {} grew beyond the {}-byte limit while it was read",
            path.display(),
            limits.max_index_bytes
        )));
    }
    PathcCollection::parse(&bytes, limits.max_entries)
}

fn reconstruct_partial_dds(
    payload_root: &Path,
    entry: &ArchiveEntry,
    payload: &[u8],
    limits: ArchiveLimits,
    cancellation: &CancellationToken,
) -> Result<Vec<u8>, ArchiveError> {
    cancellation.check()?;
    let collection = read_pathc_collection(payload_root, limits)?;
    let header = collection.header_for(&entry.virtual_path)?;
    if header.len() < DDS_LEGACY_HEADER_BYTES
        || header.get(..4) != Some(DDS_MAGIC.as_slice())
        || read_u32(&header, 4, "Partial DDS header")? != 124
    {
        return Err(ArchiveError::PartialDds(
            "PATHC texture header is missing or invalid".to_owned(),
        ));
    }
    let height = read_u32(&header, 12, "Partial DDS header")?;
    let width = read_u32(&header, 16, "Partial DDS header")?;
    let pitch_or_linear_size = read_u32(&header, 20, "Partial DDS header")?;
    let depth = read_u32(&header, 24, "Partial DDS header")?;
    let mip_count = read_u32(&header, 28, "Partial DDS header")?.max(1);
    validate_dds_dimensions(width, height, depth, mip_count, "Partial DDS")
        .map_err(ArchiveError::PartialDds)?;
    let reserved = (0..11)
        .map(|index| read_u32(&header, 32 + index * 4, "Partial DDS header"))
        .collect::<Result<Vec<_>, _>>()?;
    let pixel_flags = read_u32(&header, 80, "Partial DDS pixel format")?;
    let four_cc: [u8; 4] = header
        .get(84..88)
        .ok_or(ArchiveError::Truncated("Partial DDS pixel format"))?
        .try_into()
        .map_err(|_| ArchiveError::Truncated("Partial DDS pixel format"))?;
    let rgb_bit_count = read_u32(&header, 88, "Partial DDS pixel format")?;
    let caps2 = read_u32(&header, 112, "Partial DDS caps")?;
    let is_dx10 = &four_cc == b"DX10";
    let header_size = if is_dx10 {
        DDS_DX10_HEADER_BYTES
    } else {
        DDS_LEGACY_HEADER_BYTES
    };
    if header.len() < header_size || payload.len() < header_size {
        return Err(ArchiveError::PartialDds(
            "texture header or payload is truncated".to_owned(),
        ));
    }
    let dxgi_format = if is_dx10 {
        read_u32(&header, 0x80, "Partial DDS DX10 header")?
    } else {
        0
    };
    let array_size = if is_dx10 {
        read_u32(&header, 0x8c, "Partial DDS DX10 header")?
    } else {
        1
    };
    let single_chunk = (is_dx10 && array_size >= 2) || mip_count <= 5 || caps2 != 0 || depth >= 2;
    let mut compressed_sizes = Vec::new();
    let mut decoded_sizes = Vec::new();
    if single_chunk {
        compressed_sizes
            .push(usize::try_from(reserved[0]).map_err(|_| ArchiveError::CountOverflow)?);
        decoded_sizes.push(usize::try_from(reserved[1]).map_err(|_| ArchiveError::CountOverflow)?);
    } else {
        compressed_sizes.extend(
            reserved
                .iter()
                .take(4)
                .map(|value| usize::try_from(*value).map_err(|_| ArchiveError::CountOverflow))
                .collect::<Result<Vec<_>, _>>()?,
        );
        let mut mip_width = width;
        let mut mip_height = height;
        for mip_level in 0..mip_count.min(4) {
            decoded_sizes.push(dds_surface_size(
                mip_width,
                mip_height,
                dxgi_format,
                four_cc,
                pixel_flags,
                rgb_bit_count,
                pitch_or_linear_size,
                mip_level,
            )?);
            mip_width = (mip_width >> 1).max(1);
            mip_height = (mip_height >> 1).max(1);
        }
    }

    if payload.get(..4) == Some(DDS_MAGIC.as_slice()) {
        let payload_reserved = (0..11)
            .map(|index| read_u32(payload, 32 + index * 4, "Partial DDS payload header"))
            .collect::<Result<Vec<_>, _>>()?;
        let payload_compressed = payload_reserved
            .iter()
            .take(compressed_sizes.len())
            .map(|value| usize::try_from(*value).map_err(|_| ArchiveError::CountOverflow))
            .collect::<Result<Vec<_>, _>>()?;
        let mut payload_decoded = decoded_sizes.clone();
        if single_chunk {
            payload_decoded = vec![
                usize::try_from(payload_reserved[1]).map_err(|_| ArchiveError::CountOverflow)?,
            ];
        }
        let payload_bytes = checked_sum(&payload_compressed)?;
        let payload_decoded_bytes = checked_sum(&payload_decoded)?;
        let current_bytes = checked_sum(&compressed_sizes)?;
        let available_payload = payload.len().saturating_sub(header_size);
        if payload_bytes > 0
            && payload_decoded_bytes > 0
            && payload_bytes <= payload_decoded_bytes
            && payload_bytes <= available_payload
            && (current_bytes == 0
                || current_bytes > available_payload
                || payload_bytes < current_bytes)
        {
            compressed_sizes = payload_compressed;
            if single_chunk {
                decoded_sizes = payload_decoded;
            }
        }
    }

    let maximum_output =
        usize::try_from(limits.max_entry_bytes).map_err(|_| ArchiveError::CountOverflow)?;
    let mut source_offset = header_size;
    let mut output_size = header_size;
    for (&compressed_size, &decoded_size) in compressed_sizes.iter().zip(&decoded_sizes) {
        if compressed_size == 0 || decoded_size == 0 {
            continue;
        }
        source_offset = source_offset
            .checked_add(compressed_size)
            .ok_or(ArchiveError::CountOverflow)?;
        if source_offset > payload.len() {
            return Err(ArchiveError::PartialDds(
                "compressed block is truncated".to_owned(),
            ));
        }
        output_size = output_size
            .checked_add(decoded_size)
            .ok_or(ArchiveError::CountOverflow)?;
        if output_size > maximum_output {
            return Err(ArchiveError::PartialDds(format!(
                "decoded output exceeds the {}-byte limit",
                limits.max_entry_bytes
            )));
        }
    }
    output_size = output_size
        .checked_add(payload.len().saturating_sub(source_offset))
        .ok_or(ArchiveError::CountOverflow)?;
    if output_size > maximum_output {
        return Err(ArchiveError::PartialDds(format!(
            "decoded output exceeds the {}-byte limit",
            limits.max_entry_bytes
        )));
    }

    let mut output = Vec::with_capacity(output_size);
    output.extend_from_slice(
        header
            .get(..header_size)
            .ok_or(ArchiveError::Truncated("Partial DDS texture header"))?,
    );
    source_offset = header_size;
    for (&compressed_size, &decoded_size) in compressed_sizes.iter().zip(&decoded_sizes) {
        if compressed_size == 0 || decoded_size == 0 {
            continue;
        }
        cancellation.check()?;
        let end = source_offset
            .checked_add(compressed_size)
            .ok_or(ArchiveError::CountOverflow)?;
        let block = payload
            .get(source_offset..end)
            .ok_or_else(|| ArchiveError::PartialDds("compressed block is truncated".to_owned()))?;
        if compressed_size == decoded_size {
            output.extend_from_slice(block);
        } else {
            let decoded = lz4_flex::block::decompress(block, decoded_size)
                .map_err(|error| ArchiveError::PartialDds(format!("LZ4 block failed: {error}")))?;
            if decoded.len() != decoded_size {
                return Err(ArchiveError::PartialDds(format!(
                    "LZ4 block decoded to {} bytes instead of {decoded_size}",
                    decoded.len()
                )));
            }
            output.extend_from_slice(&decoded);
        }
        source_offset = end;
    }
    if let Some(trailing) = payload.get(source_offset..) {
        output.extend_from_slice(trailing);
    }
    cancellation.check()?;
    Ok(output)
}

fn reconstruct_sparse_dds(
    entry: &ArchiveEntry,
    mut payload: Vec<u8>,
    max_entry_bytes: u64,
) -> Result<Vec<u8>, ArchiveError> {
    if !entry.extension().eq_ignore_ascii_case(".dds")
        || payload.get(..4) != Some(DDS_MAGIC.as_slice())
    {
        return Err(ArchiveError::UnsupportedCompression(0));
    }
    if payload.len() < DDS_LEGACY_HEADER_BYTES {
        return Err(ArchiveError::SparseDds(
            "DDS header is truncated".to_owned(),
        ));
    }
    let height = read_u32(&payload, 12, "Sparse DDS header")?;
    let width = read_u32(&payload, 16, "Sparse DDS header")?;
    let depth = read_u32(&payload, 24, "Sparse DDS header")?;
    let mip_count = read_u32(&payload, 28, "Sparse DDS header")?.max(1);
    validate_dds_dimensions(width, height, depth, mip_count, "Sparse DDS")
        .map_err(ArchiveError::SparseDds)?;
    if entry.original_size > max_entry_bytes {
        return Err(ArchiveError::SparseDds(format!(
            "output exceeds the {max_entry_bytes}-byte limit"
        )));
    }
    let output_size = usize::try_from(entry.original_size).map_err(|_| {
        ArchiveError::SparseDds("declared output size is not representable".to_owned())
    })?;
    if output_size <= payload.len() {
        return Err(ArchiveError::SparseDds(format!(
            "declared output size {output_size} is not larger than the {} stored bytes",
            payload.len()
        )));
    }
    payload.resize(output_size, 0);
    Ok(payload)
}

fn validate_dds_dimensions(
    width: u32,
    height: u32,
    depth: u32,
    mip_count: u32,
    label: &str,
) -> Result<(), String> {
    if width == 0
        || height == 0
        || width > DDS_MAX_DIMENSION
        || height > DDS_MAX_DIMENSION
        || depth > DDS_MAX_DIMENSION
    {
        return Err(format!(
            "{label} dimensions {width}x{height}x{depth} are invalid"
        ));
    }
    let maximum_mips = 32_u32.saturating_sub(width.max(height).leading_zeros());
    if mip_count == 0 || mip_count > maximum_mips {
        return Err(format!(
            "{label} mip count {mip_count} is invalid for {width}x{height}"
        ));
    }
    Ok(())
}

fn dds_surface_size(
    width: u32,
    height: u32,
    dxgi_format: u32,
    four_cc: [u8; 4],
    pixel_flags: u32,
    rgb_bit_count: u32,
    pitch_or_linear_size: u32,
    mip_level: u32,
) -> Result<usize, ArchiveError> {
    let bytes_per_block = match dxgi_format {
        71 | 72 | 80 | 81 => Some(8_u32),
        74 | 75 | 77 | 78 | 83 | 84 | 94 | 95 | 96 | 98 | 99 => Some(16_u32),
        _ => match four_cc.map(|value| value.to_ascii_lowercase()) {
            value
                if value == *b"dxt1"
                    || value == *b"bc4u"
                    || value == *b"bc4s"
                    || value == *b"ati1" =>
            {
                Some(8)
            }
            value
                if value == *b"dxt3"
                    || value == *b"dxt5"
                    || value == *b"bc5u"
                    || value == *b"bc5s"
                    || value == *b"ati2"
                    || value == *b"rxgb" =>
            {
                Some(16)
            }
            _ => None,
        },
    };
    if let Some(bytes_per_block) = bytes_per_block {
        let block_width = width.saturating_add(3).checked_div(4).unwrap_or(0).max(1);
        let block_height = height.saturating_add(3).checked_div(4).unwrap_or(0).max(1);
        return usize::try_from(
            u64::from(block_width)
                .checked_mul(u64::from(block_height))
                .and_then(|value| value.checked_mul(u64::from(bytes_per_block)))
                .ok_or(ArchiveError::CountOverflow)?,
        )
        .map_err(|_| ArchiveError::CountOverflow);
    }
    const RAW_PIXEL_FLAGS: u32 = 0x1 | 0x2 | 0x40 | 0x2_0000;
    if pixel_flags & RAW_PIXEL_FLAGS != 0 && rgb_bit_count > 0 && rgb_bit_count.is_multiple_of(8) {
        return usize::try_from(
            u64::from(width)
                .checked_mul(u64::from(height))
                .and_then(|value| value.checked_mul(u64::from(rgb_bit_count / 8)))
                .ok_or(ArchiveError::CountOverflow)?,
        )
        .map_err(|_| ArchiveError::CountOverflow);
    }
    if pitch_or_linear_size > 0 {
        let pitch = (pitch_or_linear_size >> mip_level.min(31)).max(1);
        return usize::try_from(
            u64::from(pitch)
                .checked_mul(u64::from(height))
                .ok_or(ArchiveError::CountOverflow)?,
        )
        .map_err(|_| ArchiveError::CountOverflow);
    }
    Err(ArchiveError::PartialDds(format!(
        "unsupported pixel format DXGI={dxgi_format} FOURCC={:?}",
        String::from_utf8_lossy(&four_cc)
    )))
}

fn checked_sum(values: &[usize]) -> Result<usize, ArchiveError> {
    values.iter().try_fold(0_usize, |total, value| {
        total.checked_add(*value).ok_or(ArchiveError::CountOverflow)
    })
}

pub fn validate_archive_root(root: &Path) -> Result<(), ArchiveError> {
    if !root.is_dir()
        || root
            .components()
            .any(|component| matches!(component, Component::ParentDir))
    {
        return Err(ArchiveError::InvalidArchiveRoot(root.to_path_buf()));
    }
    Ok(())
}

pub fn open_archive_root(
    root: &Path,
    limits: ArchiveLimits,
    cancellation: &CancellationToken,
    mut progress: impl FnMut(CatalogProgress),
) -> Result<ArchiveCatalog, ArchiveError> {
    validate_archive_root(root)?;
    let mut pending = vec![root.to_path_buf()];
    let mut indexes = Vec::new();
    while let Some(directory) = pending.pop() {
        cancellation.check()?;
        for item in fs::read_dir(&directory)? {
            cancellation.check()?;
            let item = item?;
            let file_type = item.file_type()?;
            let path = item.path();
            if file_type.is_symlink() {
                continue;
            }
            if file_type.is_dir() {
                let ignored = path
                    .strip_prefix(root)
                    .ok()
                    .and_then(|relative| relative.components().next())
                    .is_some_and(|component| {
                        component
                            .as_os_str()
                            .to_string_lossy()
                            .eq_ignore_ascii_case("cdmods")
                    });
                if !ignored {
                    pending.push(path);
                }
            } else if file_type.is_file()
                && path
                    .extension()
                    .and_then(|extension| extension.to_str())
                    .is_some_and(|extension| extension.eq_ignore_ascii_case("pamt"))
            {
                indexes.push(path);
            }
        }
    }
    indexes.sort_by_key(|path| path.to_string_lossy().to_lowercase());
    if indexes.is_empty() {
        return Err(ArchiveError::InvalidArchiveRoot(root.to_path_buf()));
    }
    let mut entries = Vec::new();
    let mut warnings = Vec::new();
    if root.join("meta").join("0.papgt").is_file() {
        warnings.push(
            "meta/0.papgt mount precedence is not yet native; indexes use deterministic path order"
                .to_owned(),
        );
    }
    for (position, index_path) in indexes.iter().enumerate() {
        cancellation.check()?;
        let index = ArchiveIndex::read(index_path, limits)?;
        warnings.extend(
            index
                .duplicate_paths
                .iter()
                .map(|path| format!("duplicate path in index: {path}")),
        );
        warnings.extend(
            index
                .case_collisions
                .iter()
                .map(|paths| format!("case-folding collision: {}", paths.join(" | "))),
        );
        let payload_root = index_path.parent().unwrap_or(root);
        let mut payload_sizes = HashMap::new();
        for entry in index.entries {
            if entries.len().is_multiple_of(4_096) {
                cancellation.check()?;
            }
            let file_size = if let Some(size) = payload_sizes.get(&entry.payload_index) {
                *size
            } else {
                let payload_path = payload_root.join(format!("{}.paz", entry.payload_index));
                let size = fs::metadata(&payload_path)?.len();
                payload_sizes.insert(entry.payload_index, size);
                size
            };
            let end = entry.offset.checked_add(entry.stored_size).ok_or_else(|| {
                ArchiveError::PayloadRange {
                    path: payload_root.join(format!("{}.paz", entry.payload_index)),
                    offset: entry.offset,
                    size: entry.stored_size,
                    file_size,
                }
            })?;
            if end > file_size {
                return Err(ArchiveError::PayloadRange {
                    path: payload_root.join(format!("{}.paz", entry.payload_index)),
                    offset: entry.offset,
                    size: entry.stored_size,
                    file_size,
                });
            }
            entries.push(CatalogEntry {
                index_id: position,
                entry,
            });
        }
        progress(CatalogProgress {
            indexes_complete: position.saturating_add(1),
            indexes_total: indexes.len(),
            entries_loaded: entries.len(),
            label: index_path
                .strip_prefix(root)
                .unwrap_or(index_path)
                .to_string_lossy()
                .replace('\\', "/"),
        });
    }
    Ok(ArchiveCatalog {
        root: root.to_path_buf(),
        indexes,
        entries,
        warnings,
    })
}

fn crypt_chacha20_filename(bytes: &mut [u8], filename: &str) {
    let seed = hashlittle(filename.to_lowercase().as_bytes(), LOOKUP3_INIT);
    let key_base = seed ^ CHACHA_IV_XOR;
    let mut key_bytes = [0_u8; 32];
    for (chunk, delta) in key_bytes.chunks_exact_mut(4).zip(CHACHA_XOR_DELTAS) {
        chunk.copy_from_slice(&(key_base ^ delta).to_le_bytes());
    }
    let mut nonce_bytes = [0_u8; 8];
    if let Some(chunk) = nonce_bytes.get_mut(..4) {
        chunk.copy_from_slice(&seed.to_le_bytes());
    }
    if let Some(chunk) = nonce_bytes.get_mut(4..) {
        chunk.copy_from_slice(&seed.to_le_bytes());
    }
    let counter = u64::from(seed) | (u64::from(seed) << 32);
    let key = Key::from(key_bytes);
    let nonce = LegacyNonce::from(nonce_bytes);
    let mut cipher = ChaCha20Legacy::new(&key, &nonce);
    cipher.seek(u128::from(counter) * 64);
    cipher.apply_keystream(bytes);
}

fn hashlittle(data: &[u8], init: u32) -> u32 {
    let length = data.len();
    let length32 = u32::try_from(length).unwrap_or(u32::MAX);
    let mut a = 0xdead_beefu32.wrapping_add(length32).wrapping_add(init);
    let mut b = a;
    let mut c = a;
    let mut offset = 0_usize;
    while length.saturating_sub(offset) > 12 {
        a = a.wrapping_add(read_u32_lossy(data, offset));
        b = b.wrapping_add(read_u32_lossy(data, offset.saturating_add(4)));
        c = c.wrapping_add(read_u32_lossy(data, offset.saturating_add(8)));
        (a, b, c) = mix(a, b, c);
        offset = offset.saturating_add(12);
    }
    let remaining = data.get(offset..).unwrap_or(&[]);
    if remaining.is_empty() {
        return c;
    }
    let mut tail = [0_u8; 12];
    let copy_length = remaining.len().min(tail.len());
    if let (Some(destination), Some(source)) =
        (tail.get_mut(..copy_length), remaining.get(..copy_length))
    {
        destination.copy_from_slice(source);
    }
    a = a.wrapping_add(u32::from_le_bytes([tail[0], tail[1], tail[2], tail[3]]));
    b = b.wrapping_add(u32::from_le_bytes([tail[4], tail[5], tail[6], tail[7]]));
    c = c.wrapping_add(u32::from_le_bytes([tail[8], tail[9], tail[10], tail[11]]));
    final_mix(a, b, c).2
}

fn mix(mut a: u32, mut b: u32, mut c: u32) -> (u32, u32, u32) {
    a = a.wrapping_sub(c) ^ c.rotate_left(4);
    c = c.wrapping_add(b);
    b = b.wrapping_sub(a) ^ a.rotate_left(6);
    a = a.wrapping_add(c);
    c = c.wrapping_sub(b) ^ b.rotate_left(8);
    b = b.wrapping_add(a);
    a = a.wrapping_sub(c) ^ c.rotate_left(16);
    c = c.wrapping_add(b);
    b = b.wrapping_sub(a) ^ a.rotate_left(19);
    a = a.wrapping_add(c);
    c = c.wrapping_sub(b) ^ b.rotate_left(4);
    b = b.wrapping_add(a);
    (a, b, c)
}

fn final_mix(mut a: u32, mut b: u32, mut c: u32) -> (u32, u32, u32) {
    c = (c ^ b).wrapping_sub(b.rotate_left(14));
    a = (a ^ c).wrapping_sub(c.rotate_left(11));
    b = (b ^ a).wrapping_sub(a.rotate_left(25));
    c = (c ^ b).wrapping_sub(b.rotate_left(16));
    a = (a ^ c).wrapping_sub(c.rotate_left(4));
    b = (b ^ a).wrapping_sub(a.rotate_left(14));
    c = (c ^ b).wrapping_sub(b.rotate_left(24));
    (a, b, c)
}

fn read_u32_lossy(bytes: &[u8], offset: usize) -> u32 {
    let mut value = [0_u8; 4];
    if let Some(source) = bytes.get(offset..offset.saturating_add(4)) {
        value.copy_from_slice(source);
    }
    u32::from_le_bytes(value)
}

fn find_path_collisions(entries: &[ArchiveEntry]) -> (Vec<String>, Vec<Vec<String>>) {
    let mut exact = HashSet::new();
    let mut duplicates = Vec::new();
    let mut folded: BTreeMap<String, Vec<String>> = BTreeMap::new();
    for entry in entries {
        if !exact.insert(entry.virtual_path.clone()) {
            duplicates.push(entry.virtual_path.clone());
        }
        folded
            .entry(entry.virtual_path.to_lowercase())
            .or_default()
            .push(entry.virtual_path.clone());
    }
    duplicates.sort();
    duplicates.dedup();
    let collisions = folded
        .into_values()
        .filter(|paths| paths.iter().collect::<HashSet<_>>().len() > 1)
        .collect();
    (duplicates, collisions)
}

fn normalize_virtual_path(value: &str) -> Result<String, ArchiveError> {
    let normalized = value.replace('\\', "/");
    let mut parts = Vec::new();
    for part in normalized.split('/') {
        match part {
            "" | "." => {}
            ".." => return Err(ArchiveError::PathLimit),
            other if other.contains(':') || other.contains('\0') => {
                return Err(ArchiveError::PathLimit);
            }
            other => parts.push(other),
        }
    }
    Ok(parts.join("/"))
}

struct PathResolver<'a> {
    data: &'a [u8],
    limits: ArchiveLimits,
    cache: HashMap<u32, String>,
}

impl<'a> PathResolver<'a> {
    fn new(data: &'a [u8], limits: ArchiveLimits) -> Self {
        let mut cache = HashMap::new();
        cache.insert(u32::MAX, String::new());
        Self {
            data,
            limits,
            cache,
        }
    }

    fn resolve(&mut self, offset: u32) -> Result<String, ArchiveError> {
        if let Some(cached) = self.cache.get(&offset) {
            return Ok(cached.clone());
        }
        let mut current = offset;
        let mut parts = Vec::new();
        let mut seen = HashSet::new();
        let mut base = String::new();
        while current != u32::MAX {
            if let Some(cached) = self.cache.get(&current) {
                base = cached.clone();
                break;
            }
            if !seen.insert(current) {
                return Err(ArchiveError::PathCycle(current));
            }
            if parts.len() >= self.limits.max_path_depth {
                return Err(ArchiveError::PathLimit);
            }
            let position =
                usize::try_from(current).map_err(|_| ArchiveError::InvalidPathOffset(current))?;
            let header = self
                .data
                .get(position..position.saturating_add(5))
                .ok_or(ArchiveError::InvalidPathOffset(current))?;
            let parent = read_u32(header, 0, "path record")?;
            let length = usize::from(
                *header
                    .get(4)
                    .ok_or(ArchiveError::InvalidPathOffset(current))?,
            );
            let start = position.saturating_add(5);
            let bytes = self
                .data
                .get(start..start.saturating_add(length))
                .ok_or(ArchiveError::InvalidPathOffset(current))?;
            let part = String::from_utf8_lossy(bytes).into_owned();
            parts.push((current, part));
            current = parent;
        }
        for (part_offset, part) in parts.into_iter().rev() {
            if base.len().saturating_add(part.len()) > self.limits.max_path_bytes {
                return Err(ArchiveError::PathLimit);
            }
            base.push_str(&part);
            self.cache.insert(part_offset, base.clone());
        }
        Ok(base)
    }
}

struct Cursor<'a> {
    bytes: &'a [u8],
    offset: usize,
}

impl<'a> Cursor<'a> {
    const fn new(bytes: &'a [u8]) -> Self {
        Self { bytes, offset: 0 }
    }

    fn take(&mut self, length: usize, label: &'static str) -> Result<&'a [u8], ArchiveError> {
        let end = self
            .offset
            .checked_add(length)
            .ok_or(ArchiveError::CountOverflow)?;
        let result = self
            .bytes
            .get(self.offset..end)
            .ok_or(ArchiveError::Truncated(label))?;
        self.offset = end;
        Ok(result)
    }

    fn u32(&mut self, label: &'static str) -> Result<u32, ArchiveError> {
        read_u32(self.take(4, label)?, 0, label)
    }

    fn length_prefixed_block(&mut self, label: &'static str) -> Result<&'a [u8], ArchiveError> {
        let length = usize::try_from(self.u32(label)?).map_err(|_| ArchiveError::CountOverflow)?;
        self.take(length, label)
    }
}

fn read_u32(bytes: &[u8], offset: usize, label: &'static str) -> Result<u32, ArchiveError> {
    let source = bytes
        .get(offset..offset.saturating_add(4))
        .ok_or(ArchiveError::Truncated(label))?;
    let array: [u8; 4] = source
        .try_into()
        .map_err(|_| ArchiveError::Truncated(label))?;
    Ok(u32::from_le_bytes(array))
}

fn read_u16(bytes: &[u8], offset: usize, label: &'static str) -> Result<u16, ArchiveError> {
    let source = bytes
        .get(offset..offset.saturating_add(2))
        .ok_or(ArchiveError::Truncated(label))?;
    let array: [u8; 2] = source
        .try_into()
        .map_err(|_| ArchiveError::Truncated(label))?;
    Ok(u16::from_le_bytes(array))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn path_record(parent: u32, value: &[u8]) -> Vec<u8> {
        let mut bytes = parent.to_le_bytes().to_vec();
        bytes.push(u8::try_from(value.len()).unwrap_or(u8::MAX));
        bytes.extend_from_slice(value);
        bytes
    }

    fn synthetic_index(flags: u16) -> Vec<u8> {
        let directory = path_record(u32::MAX, b"character/");
        let file_name = path_record(u32::MAX, b"hero.pac");
        let mut bytes = Vec::new();
        bytes.extend_from_slice(&0x1234_5678_u32.to_le_bytes());
        bytes.extend_from_slice(&1_u32.to_le_bytes());
        bytes.extend_from_slice(&0_u32.to_le_bytes());
        bytes.extend_from_slice(&11_u32.to_le_bytes());
        bytes.extend_from_slice(&1_u32.to_le_bytes());
        bytes.extend_from_slice(&0_u32.to_le_bytes());
        bytes.extend_from_slice(&u32::try_from(directory.len()).unwrap_or(0).to_le_bytes());
        bytes.extend_from_slice(&directory);
        bytes.extend_from_slice(&u32::try_from(file_name.len()).unwrap_or(0).to_le_bytes());
        bytes.extend_from_slice(&file_name);
        bytes.extend_from_slice(&1_u32.to_le_bytes());
        bytes.extend_from_slice(&0_u32.to_le_bytes());
        bytes.extend_from_slice(&0_u32.to_le_bytes());
        bytes.extend_from_slice(&0_u32.to_le_bytes());
        bytes.extend_from_slice(&1_u32.to_le_bytes());
        bytes.extend_from_slice(&1_u32.to_le_bytes());
        bytes.extend_from_slice(&0_u32.to_le_bytes());
        bytes.extend_from_slice(&0_u32.to_le_bytes());
        bytes.extend_from_slice(&4_u32.to_le_bytes());
        bytes.extend_from_slice(&4_u32.to_le_bytes());
        bytes.extend_from_slice(&0_u16.to_le_bytes());
        bytes.extend_from_slice(&flags.to_le_bytes());
        bytes
    }

    fn synthetic_dxt1_header(compressed_size: u32, decoded_size: u32) -> Vec<u8> {
        let mut header = vec![0_u8; DDS_LEGACY_HEADER_BYTES];
        header[0..4].copy_from_slice(DDS_MAGIC);
        header[4..8].copy_from_slice(&124_u32.to_le_bytes());
        header[8..12].copy_from_slice(&0x0008_1007_u32.to_le_bytes());
        header[12..16].copy_from_slice(&4_u32.to_le_bytes());
        header[16..20].copy_from_slice(&4_u32.to_le_bytes());
        header[20..24].copy_from_slice(&8_u32.to_le_bytes());
        header[28..32].copy_from_slice(&1_u32.to_le_bytes());
        header[32..36].copy_from_slice(&compressed_size.to_le_bytes());
        header[36..40].copy_from_slice(&decoded_size.to_le_bytes());
        header[76..80].copy_from_slice(&32_u32.to_le_bytes());
        header[80..84].copy_from_slice(&4_u32.to_le_bytes());
        header[84..88].copy_from_slice(b"DXT1");
        header[108..112].copy_from_slice(&0x0000_1000_u32.to_le_bytes());
        header
    }

    fn synthetic_pathc(virtual_path: &str, texture_header: &[u8]) -> Vec<u8> {
        let mut pathc = Vec::new();
        pathc.extend_from_slice(&0_u32.to_le_bytes());
        pathc.extend_from_slice(&0_u32.to_le_bytes());
        pathc.extend_from_slice(
            &u32::try_from(texture_header.len())
                .unwrap_or(u32::MAX)
                .to_le_bytes(),
        );
        pathc.extend_from_slice(&1_u32.to_le_bytes());
        pathc.extend_from_slice(&1_u32.to_le_bytes());
        pathc.extend_from_slice(&0_u32.to_le_bytes());
        pathc.extend_from_slice(&0_u32.to_le_bytes());
        pathc.extend_from_slice(texture_header);
        let normalized = virtual_path.replace('\\', "/");
        let lookup = format!("/{}", normalized.trim_start_matches('/'));
        pathc.extend_from_slice(&hashlittle(lookup.as_bytes(), LOOKUP3_INIT).to_le_bytes());
        pathc.extend_from_slice(&0_u16.to_le_bytes());
        pathc.extend_from_slice(&0_u16.to_le_bytes());
        pathc.extend_from_slice(&[0_u8; 16]);
        pathc
    }

    fn partial_dds_fixture(
        pathc_decoded_size: u32,
        payload_decoded_size: u32,
    ) -> (Vec<u8>, Vec<u8>, Vec<u8>) {
        let pixels = vec![7_u8; 64];
        // Current CDMW Python oracle: lz4.block.compress(pixels, store_size=False).
        let compressed = vec![
            0x1f, 0x07, 0x01, 0x00, 0x27, 0x50, 0x07, 0x07, 0x07, 0x07, 0x07,
        ];
        let payload_compressed_size = u32::try_from(compressed.len()).unwrap_or(u32::MAX);
        let pathc_compressed_size = if pathc_decoded_size == payload_decoded_size {
            payload_compressed_size
        } else {
            payload_compressed_size.saturating_add(1)
        };
        let pathc_header = synthetic_dxt1_header(pathc_compressed_size, pathc_decoded_size);
        let payload_header = synthetic_dxt1_header(payload_compressed_size, payload_decoded_size);
        let mut payload = payload_header;
        payload.extend_from_slice(&compressed);
        (
            payload,
            synthetic_pathc("texture/test.dds", &pathc_header),
            pixels,
        )
    }

    #[test]
    fn parses_current_pamt_table_contract() -> Result<(), ArchiveError> {
        let index = ArchiveIndex::parse(&synthetic_index(0), ArchiveLimits::default())?;
        assert_eq!(index.entries.len(), 1);
        let entry = index.entries.first().ok_or(ArchiveError::EmptyPath(0))?;
        assert_eq!(entry.virtual_path, "character/hero.pac");
        assert_eq!(entry.payload_index, 0);
        assert_eq!(entry.stored_size, 4);
        assert_eq!(entry.compression_type(), 0);
        Ok(())
    }

    #[test]
    fn rejects_invalid_payload_index() {
        let mut bytes = synthetic_index(0);
        let length = bytes.len();
        if let Some(slot) = bytes.get_mut(length.saturating_sub(4)..length.saturating_sub(2)) {
            slot.copy_from_slice(&1_u16.to_le_bytes());
        }
        assert!(matches!(
            ArchiveIndex::parse(&bytes, ArchiveLimits::default()),
            Err(ArchiveError::InvalidPayloadIndex { payload_index: 1 })
        ));
    }

    #[test]
    fn rejects_parent_cycle() {
        let record = path_record(0, b"x");
        let mut resolver = PathResolver::new(&record, ArchiveLimits::default());
        assert!(matches!(
            resolver.resolve(0),
            Err(ArchiveError::PathCycle(0))
        ));
    }

    #[test]
    fn lookup3_matches_current_cdmw_empty_contract() {
        assert_eq!(
            hashlittle(b"", LOOKUP3_INIT),
            0xdead_beefu32.wrapping_add(LOOKUP3_INIT)
        );
    }

    #[test]
    fn lookup3_matches_the_existing_pathc_contract_vector() {
        assert_eq!(hashlittle(b"/texture/test.dds", LOOKUP3_INIT), 0x54e1_1b82);
    }

    #[test]
    fn lookup3_matches_current_cdmw_at_block_boundaries() {
        let vectors = [
            (0_usize, 0xdeba_1dcd),
            (1, 0x2679_4444),
            (4, 0xf467_23ed),
            (5, 0x849e_0ed4),
            (8, 0xbb92_ca7f),
            (9, 0x74df_c7f5),
            (12, 0x38c3_433f),
            (13, 0xe61e_ab3a),
            (24, 0x7735_2176),
            (25, 0x9927_5788),
            (64, 0xa5f5_4175),
        ];
        for (length, expected) in vectors {
            let bytes = (0..length)
                .map(|value| u8::try_from(value).unwrap_or_default())
                .collect::<Vec<_>>();
            assert_eq!(
                hashlittle(&bytes, LOOKUP3_INIT),
                expected,
                "length {length}"
            );
        }
    }

    #[test]
    fn chacha20_filename_contract_matches_the_current_cdmw_oracle() {
        let mut bytes = (0_u8..64).collect::<Vec<_>>();
        crypt_chacha20_filename(&mut bytes, "hero.pac");
        assert_eq!(
            encode_hex(&bytes),
            "2b114314891124692792a8b52f4a6eaf0efc4db35400b1cd80ca5eb351e84650184a07632033dc524e62ff59eeca7725221cec9a94f1eaf32cd67ba340266384"
        );
    }

    #[test]
    fn chacha20_long_filename_contract_matches_the_current_cdmw_oracle() {
        let mut bytes = (0_u8..64).collect::<Vec<_>>();
        crypt_chacha20_filename(&mut bytes, "character_body.dds");
        assert_eq!(
            encode_hex(&bytes),
            "afbefc5edbd087c93a7ebc8bec48c6f55bae8f90241967c49fe42a08e41386fbaa9feaea8b1ef62be023ee92c4985ecaffe8bb731ef306054541f04dd067cd1d"
        );
    }

    #[test]
    fn lz4_entry_decodes_without_modifying_the_payload() -> Result<(), Box<dyn std::error::Error>> {
        let root = tempfile::tempdir()?;
        let original = b"synthetic archive payload".repeat(32);
        let compressed = lz4_flex::block::compress(&original);
        fs::write(root.path().join("0.paz"), &compressed)?;
        let entry = ArchiveEntry {
            virtual_path: "synthetic/example.pam".to_owned(),
            payload_index: 0,
            offset: 0,
            stored_size: u64::try_from(compressed.len())?,
            original_size: u64::try_from(original.len())?,
            flags: 2,
        };
        let token = CancellationToken::default();
        let (decoded, before, after) =
            read_entry(root.path(), &entry, ArchiveLimits::default(), &token)?;
        assert_eq!(decoded.bytes, original);
        assert_eq!(decoded.compression, CompressionOutcome::Lz4);
        assert_eq!(before, after);
        Ok(())
    }

    #[test]
    fn partial_dds_uses_pathc_and_payload_chunk_authority_without_modifying_sources()
    -> Result<(), Box<dyn std::error::Error>> {
        let root = tempfile::tempdir()?;
        let payload_root = root.path().join("base");
        let meta_root = root.path().join("meta");
        fs::create_dir_all(&payload_root)?;
        fs::create_dir_all(&meta_root)?;
        let (payload, pathc, pixels) = partial_dds_fixture(4_096, 64);
        let payload_path = payload_root.join("0.paz");
        let pathc_path = meta_root.join("0.pathc");
        fs::write(&payload_path, &payload)?;
        fs::write(&pathc_path, &pathc)?;
        let entry = ArchiveEntry {
            virtual_path: "texture/test.dds".to_owned(),
            payload_index: 0,
            offset: 0,
            stored_size: u64::try_from(payload.len())?,
            original_size: u64::try_from(DDS_LEGACY_HEADER_BYTES + pixels.len())?,
            flags: 1,
        };
        let token = CancellationToken::default();
        let (decoded, before, after) =
            read_entry(&payload_root, &entry, ArchiveLimits::default(), &token)?;
        assert_eq!(decoded.compression, CompressionOutcome::PartialDds);
        assert_eq!(decoded.bytes.get(..4), Some(DDS_MAGIC.as_slice()));
        assert_eq!(
            decoded.bytes.get(DDS_LEGACY_HEADER_BYTES..),
            Some(pixels.as_slice())
        );
        assert_eq!(
            cdmw_evidence::sha256_bytes(&decoded.bytes),
            "c9096e57e46707bd071a94b7274c6e8af0ddf01766137a186b58e993893b21a5"
        );
        assert_eq!(before, after);
        assert_eq!(fs::read(payload_path)?, payload);
        assert_eq!(fs::read(pathc_path)?, pathc);
        Ok(())
    }

    #[test]
    fn pathc_record_counts_respect_the_active_limit() {
        let header = synthetic_dxt1_header(8, 8);
        let pathc = synthetic_pathc("texture/test.dds", &header);
        assert!(matches!(
            PathcCollection::parse(&pathc, 1),
            Err(ArchiveError::PartialDds(message))
                if message.contains("2 records") && message.contains("limit 1")
        ));
    }

    #[test]
    fn partial_dds_rejects_missing_metadata_and_truncated_blocks()
    -> Result<(), Box<dyn std::error::Error>> {
        let root = tempfile::tempdir()?;
        let payload_root = root.path().join("base");
        fs::create_dir_all(&payload_root)?;
        let (payload, pathc, pixels) = partial_dds_fixture(64, 64);
        fs::write(payload_root.join("0.paz"), &payload)?;
        let entry = ArchiveEntry {
            virtual_path: "texture/test.dds".to_owned(),
            payload_index: 0,
            offset: 0,
            stored_size: u64::try_from(payload.len())?,
            original_size: u64::try_from(DDS_LEGACY_HEADER_BYTES + pixels.len())?,
            flags: 1,
        };
        let token = CancellationToken::default();
        assert!(matches!(
            read_entry_unverified(
                &payload_root,
                &entry,
                ArchiveLimits::default(),
                &token
            ),
            Err(ArchiveError::PartialDds(message)) if message.contains("unavailable")
        ));

        let meta_root = root.path().join("meta");
        fs::create_dir_all(&meta_root)?;
        fs::write(meta_root.join("0.pathc"), pathc)?;
        let truncated_length = payload.len().saturating_sub(1);
        fs::write(payload_root.join("0.paz"), &payload[..truncated_length])?;
        let truncated_entry = ArchiveEntry {
            stored_size: u64::try_from(truncated_length)?,
            ..entry
        };
        assert!(matches!(
            read_entry_unverified(
                &payload_root,
                &truncated_entry,
                ArchiveLimits::default(),
                &token
            ),
            Err(ArchiveError::PartialDds(message)) if message.contains("truncated")
        ));
        Ok(())
    }

    #[test]
    fn partial_dds_rejects_declared_output_above_the_active_limit()
    -> Result<(), Box<dyn std::error::Error>> {
        let root = tempfile::tempdir()?;
        let payload_root = root.path().join("base");
        let meta_root = root.path().join("meta");
        fs::create_dir_all(&payload_root)?;
        fs::create_dir_all(&meta_root)?;
        let (payload, pathc, _) = partial_dds_fixture(300, 300);
        fs::write(payload_root.join("0.paz"), &payload)?;
        fs::write(meta_root.join("0.pathc"), pathc)?;
        let entry = ArchiveEntry {
            virtual_path: "texture/test.dds".to_owned(),
            payload_index: 0,
            offset: 0,
            stored_size: u64::try_from(payload.len())?,
            original_size: 136,
            flags: 1,
        };
        let token = CancellationToken::default();
        let limits = ArchiveLimits {
            max_entry_bytes: 256,
            ..ArchiveLimits::default()
        };
        assert!(matches!(
            read_entry_unverified(&payload_root, &entry, limits, &token),
            Err(ArchiveError::PartialDds(message)) if message.contains("256-byte limit")
        ));
        Ok(())
    }

    #[test]
    fn sparse_dds_padding_is_bounded_and_preserves_the_stored_prefix()
    -> Result<(), Box<dyn std::error::Error>> {
        let root = tempfile::tempdir()?;
        let header = synthetic_dxt1_header(0, 0);
        let mut stored = header;
        stored.extend_from_slice(&[9_u8, 8, 7, 6]);
        fs::write(root.path().join("0.paz"), &stored)?;
        let entry = ArchiveEntry {
            virtual_path: "texture/sparse.dds".to_owned(),
            payload_index: 0,
            offset: 0,
            stored_size: u64::try_from(stored.len())?,
            original_size: u64::try_from(stored.len() + 4)?,
            flags: 0,
        };
        let token = CancellationToken::default();
        let (decoded, before, after) =
            read_entry(root.path(), &entry, ArchiveLimits::default(), &token)?;
        assert_eq!(decoded.compression, CompressionOutcome::SparseDds);
        assert_eq!(decoded.bytes.len(), stored.len() + 4);
        assert_eq!(decoded.bytes.get(..stored.len()), Some(stored.as_slice()));
        assert_eq!(
            decoded.bytes.get(stored.len()..),
            Some([0_u8; 4].as_slice())
        );
        assert_eq!(
            cdmw_evidence::sha256_bytes(&decoded.bytes),
            "2880a12980fe3145ebafbe2a3d9cf177337608e9037db99a9d5e717ecfc522cb"
        );
        assert_eq!(before, after);
        assert_eq!(fs::read(root.path().join("0.paz"))?, stored);
        Ok(())
    }

    #[test]
    fn archive_root_opens_indexes_without_reading_payload_content()
    -> Result<(), Box<dyn std::error::Error>> {
        let root = tempfile::tempdir()?;
        fs::write(root.path().join("0.pamt"), synthetic_index(0))?;
        fs::write(root.path().join("0.paz"), [1_u8, 2, 3, 4])?;
        let token = CancellationToken::default();
        let mut progress = Vec::new();
        let catalog = open_archive_root(root.path(), ArchiveLimits::default(), &token, |event| {
            progress.push(event);
        })?;
        assert_eq!(catalog.indexes.len(), 1);
        assert_eq!(catalog.entries.len(), 1);
        assert_eq!(catalog.entries[0].index_id, 0);
        assert_eq!(catalog.entries[0].entry.virtual_path, "character/hero.pac");
        assert_eq!(progress.len(), 1);
        Ok(())
    }

    #[test]
    fn archive_root_honors_pre_cancelled_requests() -> Result<(), Box<dyn std::error::Error>> {
        let root = tempfile::tempdir()?;
        fs::write(root.path().join("0.pamt"), synthetic_index(0))?;
        fs::write(root.path().join("0.paz"), [1_u8, 2, 3, 4])?;
        let token = CancellationToken::default();
        token.cancel();
        assert!(matches!(
            open_archive_root(root.path(), ArchiveLimits::default(), &token, |_| {}),
            Err(ArchiveError::Cancelled)
        ));
        Ok(())
    }

    fn encode_hex(bytes: &[u8]) -> String {
        bytes.iter().map(|byte| format!("{byte:02x}")).collect()
    }
}
