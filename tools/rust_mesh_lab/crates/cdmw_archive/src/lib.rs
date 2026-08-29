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
    if !matches!(compression, CompressionOutcome::PartialRaw)
        && entry.original_size > 0
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
    a = (a ^ c.rotate_left(4)).wrapping_sub(c);
    c = c.wrapping_add(b);
    b = (b ^ a.rotate_left(6)).wrapping_sub(a);
    a = a.wrapping_add(c);
    c = (c ^ b.rotate_left(8)).wrapping_sub(b);
    b = b.wrapping_add(a);
    a = (a ^ c.rotate_left(16)).wrapping_sub(c);
    c = c.wrapping_add(b);
    b = (b ^ a.rotate_left(19)).wrapping_sub(a);
    a = a.wrapping_add(c);
    c = (c ^ b.rotate_left(4)).wrapping_sub(b);
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
    fn chacha20_filename_contract_matches_the_current_cdmw_oracle() {
        let mut bytes = (0_u8..64).collect::<Vec<_>>();
        crypt_chacha20_filename(&mut bytes, "hero.pac");
        assert_eq!(
            encode_hex(&bytes),
            "2b114314891124692792a8b52f4a6eaf0efc4db35400b1cd80ca5eb351e84650184a07632033dc524e62ff59eeca7725221cec9a94f1eaf32cd67ba340266384"
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
