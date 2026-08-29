#![forbid(unsafe_code)]

use cdmw_evidence::sha256_bytes;
use glam::Vec3;
use serde::{Deserialize, Serialize};
use std::cmp::Ordering;
use std::collections::HashSet;
use std::path::Path;
use thiserror::Error;

const MAX_VERTICES: usize = 10_000_000;
const MAX_INDICES: usize = 60_000_000;
const PAM_TABLE_OFFSET: usize = 1_040;
const PAM_RECORD_STRIDE: usize = 536;
const PAM_GEOMETRY_OFFSET: usize = 60;
const PAM_MESH_COUNT_OFFSET: usize = 16;
const PAM_BOUNDS_MIN_OFFSET: usize = 20;
const PAM_BOUNDS_MAX_OFFSET: usize = 32;
const PAML0D_TABLE_OFFSET: usize = 80;
const STATIC_STRIDES: [usize; 16] = [6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30, 32, 36, 40];

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum MeshFormat {
    Pac,
    Pam,
    Pamlod,
}

impl MeshFormat {
    pub fn from_path(path: &Path) -> Result<Self, FormatError> {
        match path
            .extension()
            .and_then(|extension| extension.to_str())
            .map(str::to_ascii_lowercase)
            .as_deref()
        {
            Some("pac") => Ok(Self::Pac),
            Some("pam") => Ok(Self::Pam),
            Some("pamlod") => Ok(Self::Pamlod),
            _ => Err(FormatError::UnsupportedExtension),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SourceRange {
    pub offset: u64,
    pub length: u64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Submesh {
    pub name: String,
    pub material: String,
    pub positions: Vec<[f32; 3]>,
    pub normals: Vec<[f32; 3]>,
    pub uvs: Vec<[f32; 2]>,
    pub indices: Vec<u32>,
    pub source_vertex_indices: Vec<i32>,
    pub source_range: SourceRange,
    pub vertex_stride: u32,
    pub layout: String,
}

impl Submesh {
    #[must_use]
    pub fn face_count(&self) -> usize {
        self.indices.len() / 3
    }

    pub fn validate(&self) -> Result<(), FormatError> {
        if self.positions.is_empty()
            || self.indices.len() < 3
            || !self.indices.len().is_multiple_of(3)
        {
            return Err(FormatError::EmptyGeometry);
        }
        if self.positions.len() > MAX_VERTICES || self.indices.len() > MAX_INDICES {
            return Err(FormatError::ResourceLimit);
        }
        if self
            .positions
            .iter()
            .flatten()
            .any(|value| !value.is_finite())
            || self
                .normals
                .iter()
                .flatten()
                .any(|value| !value.is_finite())
            || self.uvs.iter().flatten().any(|value| !value.is_finite())
        {
            return Err(FormatError::NonFiniteGeometry);
        }
        let count = u32::try_from(self.positions.len()).map_err(|_| FormatError::ResourceLimit)?;
        if self.indices.iter().any(|index| *index >= count) {
            return Err(FormatError::InvalidIndex);
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct MeshLod {
    pub level: u32,
    pub submeshes: Vec<Submesh>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct MeshDocument {
    pub format: MeshFormat,
    pub source_sha256: String,
    pub parser: String,
    pub lod_count_reported: u32,
    pub lods: Vec<MeshLod>,
    pub warnings: Vec<String>,
    pub structural_fingerprint: String,
}

impl MeshDocument {
    fn finish(&mut self) -> Result<(), FormatError> {
        if self.lods.is_empty() || self.lods.iter().all(|lod| lod.submeshes.is_empty()) {
            return Err(FormatError::EmptyGeometry);
        }
        for submesh in self.lods.iter().flat_map(|lod| &lod.submeshes) {
            submesh.validate()?;
        }
        let mut bytes = Vec::new();
        for lod in &self.lods {
            bytes.extend_from_slice(&lod.level.to_le_bytes());
            for submesh in &lod.submeshes {
                bytes.extend_from_slice(submesh.name.as_bytes());
                bytes.push(0);
                for position in &submesh.positions {
                    for component in position {
                        bytes.extend_from_slice(&component.to_le_bytes());
                    }
                }
                for index in &submesh.indices {
                    bytes.extend_from_slice(&index.to_le_bytes());
                }
            }
        }
        self.structural_fingerprint = sha256_bytes(&bytes);
        Ok(())
    }
}

#[derive(Debug, Error)]
pub enum FormatError {
    #[error("unsupported mesh extension")]
    UnsupportedExtension,
    #[error("{0} input is too small or truncated")]
    Truncated(&'static str),
    #[error("mesh container magic is unsupported")]
    InvalidMagic,
    #[error("mesh header is invalid")]
    InvalidHeader,
    #[error("mesh table exceeds configured resource limits")]
    ResourceLimit,
    #[error("mesh contains an out-of-range triangle index")]
    InvalidIndex,
    #[error("mesh contains non-finite decoded geometry")]
    NonFiniteGeometry,
    #[error("no validated renderable geometry was found")]
    EmptyGeometry,
    #[error("compressed PAR section failed to decompress: {0}")]
    ParDecompression(String),
    #[error("unsupported or ambiguous mesh layout: {0}")]
    UnsupportedLayout(String),
}

pub fn decode_mesh(bytes: &[u8], format: MeshFormat) -> Result<MeshDocument, FormatError> {
    match format {
        MeshFormat::Pac => decode_pac(bytes),
        MeshFormat::Pam => decode_pam(bytes),
        MeshFormat::Pamlod => decode_pamlod(bytes),
    }
}

fn decode_pam(bytes: &[u8]) -> Result<MeshDocument, FormatError> {
    require_magic(bytes)?;
    let mesh_count = usize::try_from(read_u32(bytes, PAM_MESH_COUNT_OFFSET)?)
        .map_err(|_| FormatError::ResourceLimit)?;
    let geometry_offset = usize::try_from(read_u32(bytes, PAM_GEOMETRY_OFFSET)?)
        .map_err(|_| FormatError::ResourceLimit)?;
    if mesh_count == 0 || mesh_count > 4_096 || geometry_offset >= bytes.len() {
        return Err(FormatError::InvalidHeader);
    }
    let bounds_min = read_vec3(bytes, PAM_BOUNDS_MIN_OFFSET)?;
    let bounds_max = read_vec3(bytes, PAM_BOUNDS_MAX_OFFSET)?;
    let records = read_pam_records(bytes, mesh_count)?;
    let (vertex_base, stride, index_base) = find_static_layout(bytes, geometry_offset, &records)
        .ok_or_else(|| {
            FormatError::UnsupportedLayout("PAM quantized layout was not validated".to_owned())
        })?;
    let mut submeshes = Vec::new();
    for record in &records {
        if record.vertex_count == 0 || record.index_count < 3 {
            continue;
        }
        submeshes.push(decode_static_submesh(
            bytes,
            record,
            vertex_base,
            stride,
            index_base,
            bounds_min,
            bounds_max,
        )?);
    }
    let mut document = MeshDocument {
        format: MeshFormat::Pam,
        source_sha256: sha256_bytes(bytes),
        parser: "rust_pam_quantized_v1".to_owned(),
        lod_count_reported: 1,
        lods: vec![MeshLod {
            level: 0,
            submeshes,
        }],
        warnings: Vec::new(),
        structural_fingerprint: String::new(),
    };
    document.finish()?;
    Ok(document)
}

fn decode_pamlod(bytes: &[u8]) -> Result<MeshDocument, FormatError> {
    if bytes.len() < PAML0D_TABLE_OFFSET {
        return Err(FormatError::Truncated("PAMLOD"));
    }
    let lod_count = read_u32(bytes, 0)?;
    let geometry_offset =
        usize::try_from(read_u32(bytes, 4)?).map_err(|_| FormatError::ResourceLimit)?;
    if lod_count == 0 || lod_count > 32 || geometry_offset >= bytes.len() {
        return Err(FormatError::InvalidHeader);
    }
    let bounds_min = read_vec3(bytes, 16)?;
    let bounds_max = read_vec3(bytes, 28)?;
    let records = scan_pamlod_records(bytes, geometry_offset)?;
    let groups = group_lod_records(
        &records,
        usize::try_from(lod_count).map_err(|_| FormatError::ResourceLimit)?,
    );
    let mut cursor = geometry_offset;
    let mut lods = Vec::new();
    for (level, group) in groups.iter().enumerate() {
        let Some((vertex_base, stride, index_base)) = find_static_layout(bytes, cursor, group)
        else {
            continue;
        };
        let mut submeshes = Vec::new();
        for record in group {
            submeshes.push(decode_static_submesh(
                bytes,
                record,
                vertex_base,
                stride,
                index_base,
                bounds_min,
                bounds_max,
            )?);
        }
        if !submeshes.is_empty() {
            lods.push(MeshLod {
                level: u32::try_from(level).map_err(|_| FormatError::ResourceLimit)?,
                submeshes,
            });
        }
        let total_indices = group.iter().try_fold(0_usize, |total, record| {
            total
                .checked_add(record.index_count)
                .ok_or(FormatError::ResourceLimit)
        })?;
        cursor = index_base
            .checked_add(
                total_indices
                    .checked_mul(2)
                    .ok_or(FormatError::ResourceLimit)?,
            )
            .ok_or(FormatError::ResourceLimit)?;
    }
    let mut warnings = Vec::new();
    if lods.len() != usize::try_from(lod_count).unwrap_or(usize::MAX) {
        warnings.push(format!(
            "decoded {} of {lod_count} declared LOD groups; unsupported groups remain view-only metadata",
            lods.len()
        ));
    }
    let mut document = MeshDocument {
        format: MeshFormat::Pamlod,
        source_sha256: sha256_bytes(bytes),
        parser: "rust_pamlod_quantized_v1".to_owned(),
        lod_count_reported: lod_count,
        lods,
        warnings,
        structural_fingerprint: String::new(),
    };
    document.finish()?;
    Ok(document)
}

fn decode_pac(source: &[u8]) -> Result<MeshDocument, FormatError> {
    require_magic(source)?;
    let normalized = normalize_par(source)?;
    let bytes = normalized.as_deref().unwrap_or(source);
    let sections = parse_par_sections(bytes)?;
    let metadata = sections
        .iter()
        .find(|section| section.index == 0)
        .ok_or(FormatError::InvalidHeader)?;
    let lod_offset = metadata
        .offset
        .checked_add(4)
        .ok_or(FormatError::ResourceLimit)?;
    let lod_count = u32::from(
        *bytes
            .get(lod_offset)
            .ok_or(FormatError::Truncated("PAC LOD count"))?,
    );
    if lod_count == 0 || lod_count > 10 {
        return Err(FormatError::InvalidHeader);
    }
    let descriptors = find_pac_descriptors(
        bytes,
        metadata,
        usize::try_from(lod_count).map_err(|_| FormatError::ResourceLimit)?,
    )?;
    if descriptors.is_empty() {
        return Err(FormatError::UnsupportedLayout(
            "PAC descriptor table was not proven".to_owned(),
        ));
    }
    let layouts = pac_layouts();
    let declared_lods = usize::try_from(lod_count).map_err(|_| FormatError::ResourceLimit)?;
    let mut lods = Vec::new();
    let mut lod_zero_parser = None;
    for lod in 0..declared_lods.min(4) {
        let section_index = 4_usize.saturating_sub(lod);
        let Some(section) = sections
            .iter()
            .find(|section| section.index == section_index)
        else {
            continue;
        };
        let mut candidates = Vec::new();
        for layout in &layouts {
            if let Ok(submeshes) = decode_pac_section(bytes, section, &descriptors, lod, layout) {
                let faces = submeshes.iter().map(Submesh::face_count).sum::<usize>();
                let vertices = submeshes
                    .iter()
                    .map(|mesh| mesh.positions.len())
                    .sum::<usize>();
                if faces > 0 && vertices > 0 {
                    candidates.push((faces, vertices, layout.name, submeshes));
                }
            }
        }
        candidates.sort_by(|left, right| right.0.cmp(&left.0).then_with(|| right.1.cmp(&left.1)));
        if let Some((_, _, layout_name, submeshes)) = candidates.into_iter().next() {
            if lod == 0 {
                lod_zero_parser = Some(format!("rust_pac_section_{section_index}_{layout_name}"));
            }
            lods.push(MeshLod {
                level: u32::try_from(lod).map_err(|_| FormatError::ResourceLimit)?,
                submeshes,
            });
        }
    }
    let parser = lod_zero_parser.ok_or_else(|| {
        FormatError::UnsupportedLayout(
            "PAC LOD0 geometry section and vertex layout were not proven".to_owned(),
        )
    })?;
    let mut warnings = vec![
        "PAC skin palette and extra influence decoding are not yet native in this readiness slice"
            .to_owned(),
        "PAC material and appearance relationships require the asset graph resolver".to_owned(),
    ];
    if normalized.is_some() {
        warnings.push("internal PAR LZ4 sections were normalized in memory".to_owned());
    }
    if lods.len() != declared_lods {
        warnings.push(format!(
            "decoded {} of {lod_count} declared PAC LODs; only proven section 4-to-1 mappings are editable",
            lods.len()
        ));
    }
    let mut document = MeshDocument {
        format: MeshFormat::Pac,
        source_sha256: sha256_bytes(source),
        parser,
        lod_count_reported: lod_count,
        lods,
        warnings,
        structural_fingerprint: String::new(),
    };
    document.finish()?;
    Ok(document)
}

#[derive(Debug, Clone)]
struct StaticRecord {
    index: usize,
    vertex_count: usize,
    index_count: usize,
    vertex_offset: usize,
    index_offset: usize,
    texture: String,
    material: String,
}

fn read_pam_records(bytes: &[u8], count: usize) -> Result<Vec<StaticRecord>, FormatError> {
    let table_length = count
        .checked_mul(PAM_RECORD_STRIDE)
        .ok_or(FormatError::ResourceLimit)?;
    let table_end = PAM_TABLE_OFFSET
        .checked_add(table_length)
        .ok_or(FormatError::ResourceLimit)?;
    if table_end > bytes.len() {
        return Err(FormatError::Truncated("PAM submesh table"));
    }
    (0..count)
        .map(|index| {
            let offset = PAM_TABLE_OFFSET
                .checked_add(
                    index
                        .checked_mul(PAM_RECORD_STRIDE)
                        .ok_or(FormatError::ResourceLimit)?,
                )
                .ok_or(FormatError::ResourceLimit)?;
            Ok(StaticRecord {
                index,
                vertex_count: usize::try_from(read_u32(bytes, offset)?)
                    .map_err(|_| FormatError::ResourceLimit)?,
                index_count: usize::try_from(read_u32(bytes, offset + 4)?)
                    .map_err(|_| FormatError::ResourceLimit)?,
                vertex_offset: usize::try_from(read_u32(bytes, offset + 8)?)
                    .map_err(|_| FormatError::ResourceLimit)?,
                index_offset: usize::try_from(read_u32(bytes, offset + 12)?)
                    .map_err(|_| FormatError::ResourceLimit)?,
                texture: read_c_string(bytes, offset + 16, 256)?,
                material: read_c_string(bytes, offset + 272, 256)?,
            })
        })
        .collect()
}

fn scan_pamlod_records(
    bytes: &[u8],
    geometry_offset: usize,
) -> Result<Vec<StaticRecord>, FormatError> {
    let search_end = geometry_offset
        .saturating_sub(5)
        .max(PAML0D_TABLE_OFFSET)
        .min(bytes.len());
    let mut records = Vec::new();
    for name_offset in PAML0D_TABLE_OFFSET..search_end {
        if !looks_like_dds(bytes, name_offset, 256) || name_offset < 16 {
            continue;
        }
        let record_offset = name_offset - 16;
        let vertex_count = usize::try_from(read_u32(bytes, record_offset)?)
            .map_err(|_| FormatError::ResourceLimit)?;
        let index_count = usize::try_from(read_u32(bytes, record_offset + 4)?)
            .map_err(|_| FormatError::ResourceLimit)?;
        if vertex_count == 0 || vertex_count > 131_072 || index_count == 0 || index_count % 3 != 0 {
            continue;
        }
        records.push(StaticRecord {
            index: records.len(),
            vertex_count,
            index_count,
            vertex_offset: usize::try_from(read_u32(bytes, name_offset - 8)?)
                .map_err(|_| FormatError::ResourceLimit)?,
            index_offset: usize::try_from(read_u32(bytes, name_offset - 4)?)
                .map_err(|_| FormatError::ResourceLimit)?,
            texture: read_c_string(bytes, name_offset, 256)?,
            material: read_c_string(bytes, name_offset + 256, 256)?,
        });
    }
    if records.is_empty() {
        Err(FormatError::UnsupportedLayout(
            "PAMLOD entry table was not proven".to_owned(),
        ))
    } else {
        Ok(records)
    }
}

fn group_lod_records(records: &[StaticRecord], lod_count: usize) -> Vec<Vec<StaticRecord>> {
    let mut groups = Vec::new();
    let mut current = Vec::new();
    let mut expected_vertex = 0_usize;
    let mut expected_index = 0_usize;
    for record in records {
        if !current.is_empty()
            && (record.vertex_offset != expected_vertex || record.index_offset != expected_index)
        {
            groups.push(std::mem::take(&mut current));
        }
        current.push(record.clone());
        expected_vertex = record.vertex_offset.saturating_add(record.vertex_count);
        expected_index = record.index_offset.saturating_add(record.index_count);
    }
    if !current.is_empty() {
        groups.push(current);
    }
    groups.truncate(lod_count);
    groups
}

fn find_static_layout(
    bytes: &[u8],
    cursor: usize,
    records: &[StaticRecord],
) -> Option<(usize, usize, usize)> {
    let total_vertices = records.iter().try_fold(0_usize, |total, record| {
        total.checked_add(record.vertex_count)
    })?;
    let total_indices = records.iter().try_fold(0_usize, |total, record| {
        total.checked_add(record.index_count)
    })?;
    let mut strides = STATIC_STRIDES;
    strides.sort_by_key(|stride| (stride.abs_diff(20), *stride));
    let paddings = (0..64)
        .step_by(2)
        .chain((64..512).step_by(4))
        .chain((512..4096).step_by(8));
    for padding in paddings {
        let vertex_base = cursor.checked_add(padding)?;
        for stride in strides {
            let index_base = vertex_base.checked_add(total_vertices.checked_mul(stride)?)?;
            let end = index_base.checked_add(total_indices.checked_mul(2)?)?;
            if end > bytes.len() {
                continue;
            }
            if records
                .iter()
                .all(|record| indices_fit(bytes, index_base, record))
            {
                return Some((vertex_base, stride, index_base));
            }
        }
    }
    None
}

fn indices_fit(bytes: &[u8], index_base: usize, record: &StaticRecord) -> bool {
    let Some(start) = index_base.checked_add(record.index_offset.saturating_mul(2)) else {
        return false;
    };
    (0..record.index_count).all(|position| {
        read_u16(bytes, start.saturating_add(position.saturating_mul(2)))
            .is_ok_and(|index| usize::from(index) < record.vertex_count)
    })
}

fn decode_static_submesh(
    bytes: &[u8],
    record: &StaticRecord,
    vertex_base: usize,
    stride: usize,
    index_base: usize,
    bounds_min: Vec3,
    bounds_max: Vec3,
) -> Result<Submesh, FormatError> {
    if record.vertex_count > MAX_VERTICES || record.index_count > MAX_INDICES {
        return Err(FormatError::ResourceLimit);
    }
    let vertex_start = vertex_base
        .checked_add(
            record
                .vertex_offset
                .checked_mul(stride)
                .ok_or(FormatError::ResourceLimit)?,
        )
        .ok_or(FormatError::ResourceLimit)?;
    let index_start = index_base
        .checked_add(
            record
                .index_offset
                .checked_mul(2)
                .ok_or(FormatError::ResourceLimit)?,
        )
        .ok_or(FormatError::ResourceLimit)?;
    let mut positions = Vec::with_capacity(record.vertex_count);
    let mut uvs = Vec::with_capacity(record.vertex_count);
    for vertex in 0..record.vertex_count {
        let offset = vertex_start
            .checked_add(
                vertex
                    .checked_mul(stride)
                    .ok_or(FormatError::ResourceLimit)?,
            )
            .ok_or(FormatError::ResourceLimit)?;
        let x = dequantize_u16(read_u16(bytes, offset)?, bounds_min.x, bounds_max.x);
        let y = dequantize_u16(read_u16(bytes, offset + 2)?, bounds_min.y, bounds_max.y);
        let z = dequantize_u16(read_u16(bytes, offset + 4)?, bounds_min.z, bounds_max.z);
        positions.push([x, y, z]);
        if stride >= 12 {
            uvs.push([
                half_to_f32(read_u16(bytes, offset + 8)?),
                half_to_f32(read_u16(bytes, offset + 10)?),
            ]);
        } else {
            uvs.push([0.0, 0.0]);
        }
    }
    let mut indices = Vec::with_capacity(record.index_count);
    for index in 0..record.index_count {
        indices.push(u32::from(read_u16(
            bytes,
            index_start + index.saturating_mul(2),
        )?));
    }
    let normals = compute_normals(&positions, &indices)?;
    let source_length = record
        .vertex_count
        .checked_mul(stride)
        .and_then(|vertex_bytes| vertex_bytes.checked_add(record.index_count.saturating_mul(2)))
        .ok_or(FormatError::ResourceLimit)?;
    Ok(Submesh {
        name: if record.texture.is_empty() {
            format!("submesh_{}", record.index)
        } else {
            record.texture.clone()
        },
        material: if record.material.is_empty() {
            record.texture.clone()
        } else {
            record.material.clone()
        },
        positions,
        normals,
        uvs,
        indices,
        source_vertex_indices: (0..record.vertex_count)
            .map(|value| i32::try_from(value).unwrap_or(-1))
            .collect(),
        source_range: SourceRange {
            offset: u64::try_from(vertex_start).map_err(|_| FormatError::ResourceLimit)?,
            length: u64::try_from(source_length).map_err(|_| FormatError::ResourceLimit)?,
        },
        vertex_stride: u32::try_from(stride).map_err(|_| FormatError::ResourceLimit)?,
        layout: "quantized_u16_static".to_owned(),
    })
}

#[derive(Debug, Clone)]
struct ParSection {
    index: usize,
    offset: usize,
    size: usize,
}

fn parse_par_sections(bytes: &[u8]) -> Result<Vec<ParSection>, FormatError> {
    require_magic(bytes)?;
    let mut offset = 0x50_usize;
    let mut sections = Vec::new();
    for index in 0..8_usize {
        let slot = 0x10_usize + index.saturating_mul(8);
        let compressed =
            usize::try_from(read_u32(bytes, slot)?).map_err(|_| FormatError::ResourceLimit)?;
        let decompressed =
            usize::try_from(read_u32(bytes, slot + 4)?).map_err(|_| FormatError::ResourceLimit)?;
        if decompressed == 0 {
            continue;
        }
        let stored = if compressed > 0 {
            compressed
        } else {
            decompressed
        };
        let end = offset
            .checked_add(stored)
            .ok_or(FormatError::ResourceLimit)?;
        if end > bytes.len() || (compressed > 0 && compressed < decompressed) {
            return Err(FormatError::Truncated("PAR section"));
        }
        sections.push(ParSection {
            index,
            offset,
            size: decompressed,
        });
        offset = end;
    }
    Ok(sections)
}

fn normalize_par(bytes: &[u8]) -> Result<Option<Vec<u8>>, FormatError> {
    require_magic(bytes)?;
    let mut slots = Vec::new();
    let mut source_offset = 0x50_usize;
    let mut normalized_size = 0x50_usize;
    let mut compressed_seen = false;
    for index in 0..8_usize {
        let slot = 0x10_usize + index.saturating_mul(8);
        let compressed =
            usize::try_from(read_u32(bytes, slot)?).map_err(|_| FormatError::ResourceLimit)?;
        let decompressed =
            usize::try_from(read_u32(bytes, slot + 4)?).map_err(|_| FormatError::ResourceLimit)?;
        if decompressed == 0 {
            continue;
        }
        let stored = if compressed > 0 {
            compressed
        } else {
            decompressed
        };
        if source_offset
            .checked_add(stored)
            .is_none_or(|end| end > bytes.len())
        {
            return Err(FormatError::Truncated("compressed PAR section"));
        }
        compressed_seen |= compressed > 0;
        slots.push((index, compressed, decompressed, source_offset));
        source_offset = source_offset.saturating_add(stored);
        normalized_size = normalized_size
            .checked_add(decompressed)
            .ok_or(FormatError::ResourceLimit)?;
    }
    if !compressed_seen {
        return Ok(None);
    }
    let mut normalized = bytes
        .get(..0x50)
        .ok_or(FormatError::Truncated("PAR header"))?
        .to_vec();
    normalized
        .try_reserve_exact(normalized_size.saturating_sub(0x50))
        .map_err(|_| FormatError::ResourceLimit)?;
    for (_, compressed, decompressed, offset) in &slots {
        let stored = if *compressed > 0 {
            *compressed
        } else {
            *decompressed
        };
        let chunk = bytes
            .get(*offset..offset.saturating_add(stored))
            .ok_or(FormatError::Truncated("PAR section"))?;
        if *compressed > 0 {
            let decoded = lz4_flex::block::decompress(chunk, *decompressed)
                .map_err(|error| FormatError::ParDecompression(error.to_string()))?;
            normalized.extend_from_slice(&decoded);
        } else {
            normalized.extend_from_slice(chunk);
        }
    }
    for (index, _, decompressed, _) in slots {
        let slot = 0x10_usize + index.saturating_mul(8);
        write_u32(&mut normalized, slot, 0)?;
        write_u32(
            &mut normalized,
            slot + 4,
            u32::try_from(decompressed).map_err(|_| FormatError::ResourceLimit)?,
        )?;
    }
    Ok(Some(normalized))
}

#[derive(Debug, Clone)]
struct PacDescriptor {
    name: String,
    material: String,
    bounds_min: Vec3,
    bounds_extent: Vec3,
    vertex_counts: [usize; 10],
    index_counts: [usize; 10],
}

fn find_pac_descriptors(
    bytes: &[u8],
    section: &ParSection,
    lod_count: usize,
) -> Result<Vec<PacDescriptor>, FormatError> {
    let end = section
        .offset
        .checked_add(section.size)
        .ok_or(FormatError::ResourceLimit)?;
    if end > bytes.len() {
        return Err(FormatError::Truncated("PAC metadata section"));
    }
    type DescriptorPattern<'a> = (&'a [u8], usize, usize, usize, Option<u8>);
    let specs: [DescriptorPattern<'_>; 4] = [
        (&[4, 0, 1, 2, 3], 4, 40, 48, None),
        (&[3, 0, 1, 1, 2], 3, 40, 46, None),
        (&[3, 0, 1, 2], 3, 40, 46, Some(4)),
        (&[2, 0, 1], 2, 40, 44, Some(3)),
    ];
    let mut seen = HashSet::new();
    let mut descriptors = Vec::new();
    let region = bytes
        .get(section.offset..end)
        .ok_or(FormatError::Truncated("PAC metadata"))?;
    for (pattern, stored_lods, vertex_offset, index_offset, reject_previous) in specs {
        for relative in find_all(region, pattern) {
            let absolute = section.offset.saturating_add(relative);
            if reject_previous.is_some_and(|reject| {
                absolute > section.offset && bytes.get(absolute - 1) == Some(&reject)
            }) {
                continue;
            }
            let Some(start) = absolute.checked_sub(35) else {
                continue;
            };
            if start < section.offset || !seen.insert(start) || bytes.get(start) != Some(&1) {
                continue;
            }
            let record_end = start
                .checked_add(index_offset)
                .and_then(|value| value.checked_add(stored_lods.saturating_mul(4)))
                .ok_or(FormatError::ResourceLimit)?;
            if record_end > end {
                continue;
            }
            let bounds_min = read_vec3(bytes, start + 11)?;
            let bounds_extent = read_vec3(bytes, start + 23)?;
            let mut vertex_counts = [0_usize; 10];
            let mut index_counts = [0_usize; 10];
            for level in 0..stored_lods.min(lod_count).min(10) {
                vertex_counts[level] = usize::from(read_u16(
                    bytes,
                    start + vertex_offset + level.saturating_mul(2),
                )?);
                index_counts[level] = usize::try_from(read_u32(
                    bytes,
                    start + index_offset + level.saturating_mul(4),
                )?)
                .map_err(|_| FormatError::ResourceLimit)?;
            }
            if vertex_counts.iter().all(|count| *count == 0)
                || vertex_counts.iter().any(|count| *count > 200_000)
                || index_counts.iter().any(|count| *count > 20_000_000)
            {
                continue;
            }
            let (name, material) = descriptor_names(bytes, section.offset, start);
            descriptors.push(PacDescriptor {
                name,
                material,
                bounds_min,
                bounds_extent,
                vertex_counts,
                index_counts,
            });
        }
    }
    Ok(descriptors)
}

fn descriptor_names(
    bytes: &[u8],
    region_start: usize,
    descriptor_start: usize,
) -> (String, String) {
    let mut names = Vec::new();
    let mut cursor = descriptor_start;
    for _ in 0..2 {
        let mut found = None;
        for back in 1..200_usize {
            let Some(position) = cursor.checked_sub(back) else {
                break;
            };
            if position < region_start {
                break;
            }
            let Some(length) = bytes.get(position).copied().map(usize::from) else {
                break;
            };
            if length == 0 || length != back.saturating_sub(1) {
                continue;
            }
            let Some(value) = bytes.get(position + 1..cursor) else {
                continue;
            };
            if value.iter().all(|byte| (32..127).contains(byte)) {
                found = Some((position, String::from_utf8_lossy(value).into_owned()));
                break;
            }
        }
        if let Some((position, value)) = found {
            names.push(value);
            cursor = position;
        }
    }
    names.reverse();
    let name = names
        .first()
        .cloned()
        .unwrap_or_else(|| format!("submesh_{descriptor_start:x}"));
    let material = names.get(1).cloned().unwrap_or_else(|| name.clone());
    (name, material)
}

#[derive(Debug, Clone, Copy)]
struct PacLayout {
    name: &'static str,
    stride: usize,
    uv_offset: usize,
    normal_offset: usize,
}

fn pac_layouts() -> Vec<PacLayout> {
    let mut layouts = Vec::new();
    for stride in [40_usize, 32, 36, 44, 48] {
        for uv_offset in (8..stride.saturating_sub(3)).step_by(4) {
            layouts.push(PacLayout {
                name: match stride {
                    32 => "pac32",
                    36 => "pac36",
                    40 => "pac40",
                    44 => "pac44",
                    _ => "pac48",
                },
                stride,
                uv_offset,
                normal_offset: 16,
            });
        }
    }
    layouts
}

fn decode_pac_section(
    bytes: &[u8],
    section: &ParSection,
    descriptors: &[PacDescriptor],
    lod: usize,
    layout: &PacLayout,
) -> Result<Vec<Submesh>, FormatError> {
    let total_vertices = descriptors.iter().try_fold(0_usize, |total, descriptor| {
        total
            .checked_add(descriptor.vertex_counts[lod])
            .ok_or(FormatError::ResourceLimit)
    })?;
    let total_indices = descriptors.iter().try_fold(0_usize, |total, descriptor| {
        total
            .checked_add(descriptor.index_counts[lod])
            .ok_or(FormatError::ResourceLimit)
    })?;
    let vertex_bytes = total_vertices
        .checked_mul(layout.stride)
        .ok_or(FormatError::ResourceLimit)?;
    let index_bytes = total_indices
        .checked_mul(2)
        .ok_or(FormatError::ResourceLimit)?;
    if vertex_bytes
        .checked_add(index_bytes)
        .is_none_or(|required| required > section.size)
    {
        return Err(FormatError::UnsupportedLayout(
            "PAC section is smaller than declared geometry".to_owned(),
        ));
    }
    let mut index_start = vertex_bytes;
    if section.size > vertex_bytes.saturating_add(index_bytes) {
        let gap = section.size - vertex_bytes - index_bytes;
        index_start =
            vertex_bytes.saturating_add((gap / layout.stride).saturating_mul(layout.stride));
    }
    let mut vertex_cursor = 0_usize;
    let mut index_cursor = index_start;
    let mut output = Vec::new();
    for descriptor in descriptors {
        let vertex_count = descriptor.vertex_counts[lod];
        let index_count = descriptor.index_counts[lod];
        if vertex_count == 0 || index_count < 3 {
            continue;
        }
        let absolute_vertices = section
            .offset
            .checked_add(vertex_cursor)
            .ok_or(FormatError::ResourceLimit)?;
        let absolute_indices = section
            .offset
            .checked_add(index_cursor)
            .ok_or(FormatError::ResourceLimit)?;
        let mut positions = Vec::with_capacity(vertex_count);
        let mut normals = Vec::with_capacity(vertex_count);
        let mut uvs = Vec::with_capacity(vertex_count);
        for vertex in 0..vertex_count {
            let record = absolute_vertices
                .checked_add(
                    vertex
                        .checked_mul(layout.stride)
                        .ok_or(FormatError::ResourceLimit)?,
                )
                .ok_or(FormatError::ResourceLimit)?;
            let x = decode_pac_position(
                read_u16(bytes, record)?,
                descriptor.bounds_min.x,
                descriptor.bounds_extent.x,
            );
            let y = decode_pac_position(
                read_u16(bytes, record + 2)?,
                descriptor.bounds_min.y,
                descriptor.bounds_extent.y,
            );
            let z = decode_pac_position(
                read_u16(bytes, record + 4)?,
                descriptor.bounds_min.z,
                descriptor.bounds_extent.z,
            );
            positions.push([x, y, z]);
            uvs.push([
                half_to_f32(read_u16(bytes, record + layout.uv_offset)?),
                half_to_f32(read_u16(bytes, record + layout.uv_offset + 2)?),
            ]);
            normals.push(decode_packed_normal(read_u32(
                bytes,
                record + layout.normal_offset,
            )?));
        }
        let mut indices = Vec::with_capacity(index_count);
        for index in 0..index_count {
            let value = u32::from(read_u16(bytes, absolute_indices + index.saturating_mul(2))?);
            if usize::try_from(value)
                .ok()
                .is_none_or(|value| value >= vertex_count)
            {
                return Err(FormatError::InvalidIndex);
            }
            indices.push(value);
        }
        let source_length = vertex_count
            .checked_mul(layout.stride)
            .and_then(|length| length.checked_add(index_count.saturating_mul(2)))
            .ok_or(FormatError::ResourceLimit)?;
        let submesh = Submesh {
            name: descriptor.name.clone(),
            material: descriptor.material.clone(),
            positions,
            normals,
            uvs,
            indices,
            source_vertex_indices: (0..vertex_count)
                .map(|value| i32::try_from(value).unwrap_or(-1))
                .collect(),
            source_range: SourceRange {
                offset: u64::try_from(absolute_vertices).map_err(|_| FormatError::ResourceLimit)?,
                length: u64::try_from(source_length).map_err(|_| FormatError::ResourceLimit)?,
            },
            vertex_stride: u32::try_from(layout.stride).map_err(|_| FormatError::ResourceLimit)?,
            layout: format!(
                "{}_uv{}_n{}",
                layout.name, layout.uv_offset, layout.normal_offset
            ),
        };
        submesh.validate()?;
        output.push(submesh);
        vertex_cursor = vertex_cursor
            .checked_add(
                vertex_count
                    .checked_mul(layout.stride)
                    .ok_or(FormatError::ResourceLimit)?,
            )
            .ok_or(FormatError::ResourceLimit)?;
        index_cursor = index_cursor
            .checked_add(
                index_count
                    .checked_mul(2)
                    .ok_or(FormatError::ResourceLimit)?,
            )
            .ok_or(FormatError::ResourceLimit)?;
    }
    if output.is_empty() {
        Err(FormatError::EmptyGeometry)
    } else {
        Ok(output)
    }
}

fn compute_normals(positions: &[[f32; 3]], indices: &[u32]) -> Result<Vec<[f32; 3]>, FormatError> {
    let mut normals = vec![Vec3::ZERO; positions.len()];
    for triangle in indices.chunks_exact(3) {
        let a = usize::try_from(*triangle.first().ok_or(FormatError::InvalidIndex)?)
            .map_err(|_| FormatError::InvalidIndex)?;
        let b = usize::try_from(*triangle.get(1).ok_or(FormatError::InvalidIndex)?)
            .map_err(|_| FormatError::InvalidIndex)?;
        let c = usize::try_from(*triangle.get(2).ok_or(FormatError::InvalidIndex)?)
            .map_err(|_| FormatError::InvalidIndex)?;
        let pa = Vec3::from_array(*positions.get(a).ok_or(FormatError::InvalidIndex)?);
        let pb = Vec3::from_array(*positions.get(b).ok_or(FormatError::InvalidIndex)?);
        let pc = Vec3::from_array(*positions.get(c).ok_or(FormatError::InvalidIndex)?);
        let face = (pb - pa).cross(pc - pa);
        if let Some(value) = normals.get_mut(a) {
            *value += face;
        }
        if let Some(value) = normals.get_mut(b) {
            *value += face;
        }
        if let Some(value) = normals.get_mut(c) {
            *value += face;
        }
    }
    Ok(normals
        .into_iter()
        .map(|normal| normal.try_normalize().unwrap_or(Vec3::Y).to_array())
        .collect())
}

fn decode_packed_normal(packed: u32) -> [f32; 3] {
    let nx = (packed & 0x3ff) as f32 / 511.5 - 1.0;
    let ny = ((packed >> 10) & 0x3ff) as f32 / 511.5 - 1.0;
    let nz = ((packed >> 20) & 0x3ff) as f32 / 511.5 - 1.0;
    Vec3::new(ny, nz, nx)
        .try_normalize()
        .unwrap_or(Vec3::Y)
        .to_array()
}

fn decode_pac_position(value: u16, minimum: f32, extent: f32) -> f32 {
    if extent.abs() < 1.0e-8 {
        minimum
    } else {
        minimum + (f32::from(value) / 32_767.0) * extent
    }
}

fn dequantize_u16(value: u16, minimum: f32, maximum: f32) -> f32 {
    minimum + (f32::from(value) / 65_535.0) * (maximum - minimum)
}

fn half_to_f32(value: u16) -> f32 {
    let sign = u32::from(value & 0x8000) << 16;
    let exponent = u32::from((value >> 10) & 0x1f);
    let fraction = u32::from(value & 0x03ff);
    let bits = match exponent.cmp(&0) {
        Ordering::Equal if fraction == 0 => sign,
        Ordering::Equal => {
            let mut mantissa = fraction;
            let mut shift = 0_u32;
            while mantissa & 0x0400 == 0 {
                mantissa <<= 1;
                shift = shift.saturating_add(1);
            }
            sign | ((127_u32.saturating_sub(15).saturating_sub(shift)) << 23)
                | ((mantissa & 0x03ff) << 13)
        }
        Ordering::Greater if exponent == 0x1f => sign | 0x7f80_0000 | (fraction << 13),
        Ordering::Greater => sign | ((exponent + 112) << 23) | (fraction << 13),
        Ordering::Less => sign,
    };
    f32::from_bits(bits)
}

fn require_magic(bytes: &[u8]) -> Result<(), FormatError> {
    if bytes.get(..4) == Some(b"PAR ") {
        Ok(())
    } else {
        Err(FormatError::InvalidMagic)
    }
}

fn read_vec3(bytes: &[u8], offset: usize) -> Result<Vec3, FormatError> {
    Ok(Vec3::new(
        read_f32(bytes, offset)?,
        read_f32(bytes, offset + 4)?,
        read_f32(bytes, offset + 8)?,
    ))
}

fn read_f32(bytes: &[u8], offset: usize) -> Result<f32, FormatError> {
    Ok(f32::from_bits(read_u32(bytes, offset)?))
}

fn read_u32(bytes: &[u8], offset: usize) -> Result<u32, FormatError> {
    let source = bytes
        .get(offset..offset.saturating_add(4))
        .ok_or(FormatError::Truncated("u32"))?;
    let array: [u8; 4] = source
        .try_into()
        .map_err(|_| FormatError::Truncated("u32"))?;
    Ok(u32::from_le_bytes(array))
}

fn read_u16(bytes: &[u8], offset: usize) -> Result<u16, FormatError> {
    let source = bytes
        .get(offset..offset.saturating_add(2))
        .ok_or(FormatError::Truncated("u16"))?;
    let array: [u8; 2] = source
        .try_into()
        .map_err(|_| FormatError::Truncated("u16"))?;
    Ok(u16::from_le_bytes(array))
}

fn write_u32(bytes: &mut [u8], offset: usize, value: u32) -> Result<(), FormatError> {
    let destination = bytes
        .get_mut(offset..offset.saturating_add(4))
        .ok_or(FormatError::Truncated("u32"))?;
    destination.copy_from_slice(&value.to_le_bytes());
    Ok(())
}

fn read_c_string(bytes: &[u8], offset: usize, maximum: usize) -> Result<String, FormatError> {
    let end = offset
        .checked_add(maximum)
        .ok_or(FormatError::ResourceLimit)?
        .min(bytes.len());
    let value = bytes
        .get(offset..end)
        .ok_or(FormatError::Truncated("string"))?;
    let length = value
        .iter()
        .position(|byte| *byte == 0)
        .unwrap_or(value.len());
    Ok(String::from_utf8_lossy(
        value
            .get(..length)
            .ok_or(FormatError::Truncated("string"))?,
    )
    .into_owned())
}

fn looks_like_dds(bytes: &[u8], offset: usize, maximum: usize) -> bool {
    read_c_string(bytes, offset, maximum).is_ok_and(|value| {
        value.len() >= 5
            && value.to_ascii_lowercase().ends_with(".dds")
            && value.bytes().all(|byte| {
                byte == b'/'
                    || byte == b'\\'
                    || byte == b'.'
                    || byte == b'_'
                    || byte == b'-'
                    || byte.is_ascii_alphanumeric()
            })
    })
}

fn find_all(region: &[u8], pattern: &[u8]) -> Vec<usize> {
    if pattern.is_empty() || pattern.len() > region.len() {
        return Vec::new();
    }
    region
        .windows(pattern.len())
        .enumerate()
        .filter_map(|(index, window)| (window == pattern).then_some(index))
        .collect()
}

pub mod synthetic {
    use super::{
        PAM_BOUNDS_MAX_OFFSET, PAM_BOUNDS_MIN_OFFSET, PAM_GEOMETRY_OFFSET, PAM_MESH_COUNT_OFFSET,
        PAM_TABLE_OFFSET,
    };

    #[must_use]
    pub fn triangle_pam(texture_name: &str) -> Vec<u8> {
        let geometry_offset = 1_600_usize;
        let stride = 20_usize;
        let mut bytes = vec![0_u8; geometry_offset + 3 * stride + 6];
        write_text(&mut bytes, 0, b"PAR ");
        write_u32(&mut bytes, PAM_MESH_COUNT_OFFSET, 1);
        for offset in [
            PAM_BOUNDS_MIN_OFFSET,
            PAM_BOUNDS_MIN_OFFSET + 4,
            PAM_BOUNDS_MIN_OFFSET + 8,
        ] {
            write_f32(&mut bytes, offset, -1.0);
        }
        for offset in [
            PAM_BOUNDS_MAX_OFFSET,
            PAM_BOUNDS_MAX_OFFSET + 4,
            PAM_BOUNDS_MAX_OFFSET + 8,
        ] {
            write_f32(&mut bytes, offset, 1.0);
        }
        write_u32(&mut bytes, PAM_GEOMETRY_OFFSET, geometry_offset as u32);
        write_u32(&mut bytes, PAM_TABLE_OFFSET, 3);
        write_u32(&mut bytes, PAM_TABLE_OFFSET + 4, 3);
        write_text(&mut bytes, PAM_TABLE_OFFSET + 16, texture_name.as_bytes());
        write_text(&mut bytes, PAM_TABLE_OFFSET + 272, b"synthetic_material");
        for (vertex, coordinates) in [[0_u16, 0, 0], [u16::MAX, 0, 0], [0, u16::MAX, 0]]
            .into_iter()
            .enumerate()
        {
            let offset = geometry_offset + vertex * stride;
            write_u16(&mut bytes, offset, coordinates[0]);
            write_u16(&mut bytes, offset + 2, coordinates[1]);
            write_u16(&mut bytes, offset + 4, coordinates[2]);
            let uv = match vertex {
                1 => [0x3c00, 0],
                2 => [0, 0x3c00],
                _ => [0, 0],
            };
            write_u16(&mut bytes, offset + 8, uv[0]);
            write_u16(&mut bytes, offset + 10, uv[1]);
        }
        let index_offset = geometry_offset + 3 * stride;
        write_u16(&mut bytes, index_offset, 0);
        write_u16(&mut bytes, index_offset + 2, 1);
        write_u16(&mut bytes, index_offset + 4, 2);
        bytes
    }

    #[must_use]
    pub fn two_lod_pac() -> Vec<u8> {
        let metadata_size = 128_usize;
        let lod_one_size = 172_usize;
        let lod_zero_size = 126_usize;
        let metadata_offset = 0x50_usize;
        let lod_one_offset = metadata_offset + metadata_size;
        let lod_zero_offset = lod_one_offset + lod_one_size;
        let mut bytes = vec![0_u8; lod_zero_offset + lod_zero_size];
        write_text(&mut bytes, 0, b"PAR ");
        write_u32(&mut bytes, 0x14, metadata_size as u32);
        write_u32(&mut bytes, 0x2c, lod_one_size as u32);
        write_u32(&mut bytes, 0x34, lod_zero_size as u32);
        bytes[metadata_offset + 4] = 2;

        let descriptor = metadata_offset + 40;
        bytes[descriptor] = 1;
        for offset in [descriptor + 11, descriptor + 15, descriptor + 19] {
            write_f32(&mut bytes, offset, -1.0);
        }
        for offset in [descriptor + 23, descriptor + 27, descriptor + 31] {
            write_f32(&mut bytes, offset, 1.0);
        }
        write_text(&mut bytes, descriptor + 35, &[2, 0, 1]);
        write_u16(&mut bytes, descriptor + 40, 3);
        write_u16(&mut bytes, descriptor + 42, 4);
        write_u32(&mut bytes, descriptor + 44, 3);
        write_u32(&mut bytes, descriptor + 48, 6);

        write_geometry(
            &mut bytes,
            lod_one_offset,
            &[
                [0, 0, 0],
                [u16::MAX, 0, 0],
                [u16::MAX, u16::MAX, 0],
                [0, u16::MAX, 0],
            ],
            &[0, 1, 2, 0, 2, 3],
        );
        write_geometry(
            &mut bytes,
            lod_zero_offset,
            &[[0, 0, 0], [u16::MAX, 0, 0], [0, u16::MAX, 0]],
            &[0, 1, 2],
        );
        bytes
    }

    fn write_geometry(
        bytes: &mut [u8],
        vertex_base: usize,
        coordinates: &[[u16; 3]],
        indices: &[u16],
    ) {
        let stride = 40_usize;
        for (vertex, coordinate) in coordinates.iter().enumerate() {
            let offset = vertex_base + vertex * stride;
            write_u16(bytes, offset, coordinate[0]);
            write_u16(bytes, offset + 2, coordinate[1]);
            write_u16(bytes, offset + 4, coordinate[2]);
            write_u16(bytes, offset + 8, 0);
            write_u16(bytes, offset + 10, 0);
        }
        let index_base = vertex_base + coordinates.len() * stride;
        for (index, value) in indices.iter().copied().enumerate() {
            write_u16(bytes, index_base + index * 2, value);
        }
    }

    fn write_u16(bytes: &mut [u8], offset: usize, value: u16) {
        if let Some(destination) = bytes.get_mut(offset..offset.saturating_add(2)) {
            destination.copy_from_slice(&value.to_le_bytes());
        }
    }

    fn write_u32(bytes: &mut [u8], offset: usize, value: u32) {
        if let Some(destination) = bytes.get_mut(offset..offset.saturating_add(4)) {
            destination.copy_from_slice(&value.to_le_bytes());
        }
    }

    fn write_f32(bytes: &mut [u8], offset: usize, value: f32) {
        write_u32(bytes, offset, value.to_bits());
    }

    fn write_text(bytes: &mut [u8], offset: usize, value: &[u8]) {
        if let Some(destination) = bytes.get_mut(offset..offset.saturating_add(value.len())) {
            destination.copy_from_slice(value);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn write_u16_at(bytes: &mut [u8], offset: usize, value: u16) {
        if let Some(destination) = bytes.get_mut(offset..offset.saturating_add(2)) {
            destination.copy_from_slice(&value.to_le_bytes());
        }
    }

    fn write_u32_at(bytes: &mut [u8], offset: usize, value: u32) {
        if let Some(destination) = bytes.get_mut(offset..offset.saturating_add(4)) {
            destination.copy_from_slice(&value.to_le_bytes());
        }
    }

    fn write_f32_at(bytes: &mut [u8], offset: usize, value: f32) {
        write_u32_at(bytes, offset, value.to_bits());
    }

    fn write_text(bytes: &mut [u8], offset: usize, value: &[u8]) {
        if let Some(destination) = bytes.get_mut(offset..offset.saturating_add(value.len())) {
            destination.copy_from_slice(value);
        }
    }

    fn write_triangle_geometry(bytes: &mut [u8], vertex_base: usize, stride: usize) {
        for (vertex, coordinates) in [[0_u16, 0, 0], [u16::MAX, 0, 0], [0, u16::MAX, 0]]
            .into_iter()
            .enumerate()
        {
            let offset = vertex_base + vertex * stride;
            write_u16_at(bytes, offset, coordinates[0]);
            write_u16_at(bytes, offset + 2, coordinates[1]);
            write_u16_at(bytes, offset + 4, coordinates[2]);
            write_u16_at(bytes, offset + 8, 0);
            write_u16_at(bytes, offset + 10, 0);
        }
        let index_base = vertex_base + 3 * stride;
        write_u16_at(bytes, index_base, 0);
        write_u16_at(bytes, index_base + 2, 1);
        write_u16_at(bytes, index_base + 4, 2);
    }

    #[test]
    fn half_float_contract_decodes_common_values() {
        assert_eq!(half_to_f32(0), 0.0);
        assert_eq!(half_to_f32(0x3c00), 1.0);
        assert_eq!(half_to_f32(0xc000), -2.0);
    }

    #[test]
    fn submesh_validation_rejects_stale_indices() {
        let mesh = Submesh {
            name: "bad".to_owned(),
            material: String::new(),
            positions: vec![[0.0, 0.0, 0.0]],
            normals: vec![[0.0, 1.0, 0.0]],
            uvs: vec![[0.0, 0.0]],
            indices: vec![0, 1, 0],
            source_vertex_indices: vec![0],
            source_range: SourceRange {
                offset: 0,
                length: 1,
            },
            vertex_stride: 12,
            layout: "synthetic".to_owned(),
        };
        assert!(matches!(mesh.validate(), Err(FormatError::InvalidIndex)));
    }

    #[test]
    fn synthetic_pam_decodes_the_proven_quantized_layout() -> Result<(), FormatError> {
        let geometry_offset = 1_600_usize;
        let mut bytes = vec![0_u8; geometry_offset + 66];
        write_text(&mut bytes, 0, b"PAR ");
        write_u32_at(&mut bytes, PAM_MESH_COUNT_OFFSET, 1);
        for offset in [
            PAM_BOUNDS_MIN_OFFSET,
            PAM_BOUNDS_MIN_OFFSET + 4,
            PAM_BOUNDS_MIN_OFFSET + 8,
        ] {
            write_f32_at(&mut bytes, offset, -1.0);
        }
        for offset in [
            PAM_BOUNDS_MAX_OFFSET,
            PAM_BOUNDS_MAX_OFFSET + 4,
            PAM_BOUNDS_MAX_OFFSET + 8,
        ] {
            write_f32_at(&mut bytes, offset, 1.0);
        }
        write_u32_at(&mut bytes, PAM_GEOMETRY_OFFSET, geometry_offset as u32);
        write_u32_at(&mut bytes, PAM_TABLE_OFFSET, 3);
        write_u32_at(&mut bytes, PAM_TABLE_OFFSET + 4, 3);
        write_text(&mut bytes, PAM_TABLE_OFFSET + 16, b"synthetic.dds\0");
        write_text(&mut bytes, PAM_TABLE_OFFSET + 272, b"synthetic_material\0");
        write_triangle_geometry(&mut bytes, geometry_offset, 20);

        let document = decode_mesh(&bytes, MeshFormat::Pam)?;
        let mesh = document
            .lods
            .first()
            .and_then(|lod| lod.submeshes.first())
            .ok_or(FormatError::EmptyGeometry)?;
        assert_eq!(mesh.positions.len(), 3);
        assert_eq!(mesh.indices, vec![0, 1, 2]);
        assert_eq!(mesh.vertex_stride, 20);
        Ok(())
    }

    #[test]
    fn synthetic_pamlod_reports_and_decodes_lod_zero() -> Result<(), FormatError> {
        let geometry_offset = 800_usize;
        let mut bytes = vec![0_u8; geometry_offset + 66];
        write_u32_at(&mut bytes, 0, 1);
        write_u32_at(&mut bytes, 4, geometry_offset as u32);
        for offset in [16_usize, 20, 24] {
            write_f32_at(&mut bytes, offset, -1.0);
        }
        for offset in [28_usize, 32, 36] {
            write_f32_at(&mut bytes, offset, 1.0);
        }
        write_u32_at(&mut bytes, 80, 3);
        write_u32_at(&mut bytes, 84, 3);
        write_u32_at(&mut bytes, 88, 0);
        write_u32_at(&mut bytes, 92, 0);
        write_text(&mut bytes, 96, b"synthetic.dds\0");
        write_text(&mut bytes, 352, b"synthetic_material\0");
        write_triangle_geometry(&mut bytes, geometry_offset, 20);

        let document = decode_mesh(&bytes, MeshFormat::Pamlod)?;
        assert_eq!(document.lod_count_reported, 1);
        assert_eq!(document.lods.len(), 1);
        assert_eq!(document.lods[0].submeshes[0].indices, vec![0, 1, 2]);
        Ok(())
    }

    #[test]
    fn synthetic_pac_decodes_each_proven_lod_section() -> Result<(), FormatError> {
        let document = decode_mesh(&synthetic::two_lod_pac(), MeshFormat::Pac)?;
        assert_eq!(document.lod_count_reported, 2);
        assert_eq!(document.lods.len(), 2);
        assert_eq!(document.lods[0].level, 0);
        assert_eq!(document.lods[0].submeshes[0].positions.len(), 3);
        assert_eq!(document.lods[0].submeshes[0].indices, vec![0, 1, 2]);
        assert_eq!(document.lods[1].level, 1);
        assert_eq!(document.lods[1].submeshes[0].positions.len(), 4);
        assert_eq!(
            document.lods[1].submeshes[0].indices,
            vec![0, 1, 2, 0, 2, 3]
        );
        assert_eq!(document.parser, "rust_pac_section_4_pac40");
        Ok(())
    }

    #[test]
    fn pac_does_not_relabel_a_lower_lod_as_lod_zero() {
        let mut bytes = synthetic::two_lod_pac();
        write_u32_at(&mut bytes, 0x34, 0);
        assert!(matches!(
            decode_mesh(&bytes, MeshFormat::Pac),
            Err(FormatError::UnsupportedLayout(message)) if message.contains("LOD0")
        ));
    }
}
