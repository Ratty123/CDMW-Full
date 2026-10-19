//! Versioned authoring transport. Bounds and ownership are checked before decode.

use super::{MAX_MANIFEST_BYTES, MAX_PAYLOAD_BYTES, SessionError, validate_document};
use cdmw_formats::{MeshDocument, MeshFormat, MeshLod, SourceRange, Submesh};
use serde::Deserialize;
use sha2::{Digest, Sha256};

pub(super) const DATA_TYPE: &str = "mesh_document_binary_v1";
const SCHEMA: &str = "cdmw_mesh_document_binary_v1";
const MAGIC: &[u8; 8] = b"CDMWMSH1";
const HEADER_BYTES: usize = 16;
const MAX_VERTICES: u64 = 10_000_000;
const MAX_INDICES: u64 = 60_000_000;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ArrayDescriptor {
    dtype: String,
    components: u32,
    count: u64,
    offset: u64,
    byte_length: u64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct BinarySourceRange {
    offset: u64,
    length: u64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct BinarySubmesh {
    name: String,
    material: String,
    positions: ArrayDescriptor,
    normals: ArrayDescriptor,
    uvs: ArrayDescriptor,
    indices: ArrayDescriptor,
    source_vertex_indices: ArrayDescriptor,
    shader_masks: ArrayDescriptor,
    source_range: BinarySourceRange,
    vertex_stride: u32,
    layout: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct BinaryLod {
    level: u32,
    submeshes: Vec<BinarySubmesh>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Metadata {
    schema: String,
    format: MeshFormat,
    source_sha256: String,
    parser: String,
    lod_count_reported: u32,
    lods: Vec<BinaryLod>,
    warnings: Vec<String>,
    structural_fingerprint: String,
}

fn invalid(detail: &str) -> SessionError {
    SessionError::InvalidPayload(format!("binary mesh document {detail}"))
}

impl ArrayDescriptor {
    fn validate(
        &self,
        dtype: &str,
        components: u32,
        width: u64,
        cursor: &mut u64,
        payload_length: u64,
    ) -> Result<(), SessionError> {
        let length = self.count.checked_mul(u64::from(components))
            .and_then(|value| value.checked_mul(width))
            .ok_or_else(|| invalid("array size overflows"))?;
        let end = self.offset.checked_add(length)
            .ok_or_else(|| invalid("array range overflows"))?;
        if self.dtype != dtype || self.components != components
            || self.offset != *cursor || self.byte_length != length || end > payload_length
        {
            return Err(invalid("array type, count, order, or range is invalid"));
        }
        *cursor = end;
        Ok(())
    }

    fn bytes<'a>(&self, payload: &'a [u8]) -> Result<&'a [u8], SessionError> {
        let start = usize::try_from(self.offset).map_err(|_| invalid("array offset is too large"))?;
        let length = usize::try_from(self.byte_length).map_err(|_| invalid("array is too large"))?;
        let end = start.checked_add(length).ok_or_else(|| invalid("array range overflows"))?;
        payload.get(start..end).ok_or_else(|| invalid("array is truncated"))
    }

    fn reserve<T>(&self) -> Result<Vec<T>, SessionError> {
        let count = usize::try_from(self.count).map_err(|_| invalid("array count is too large"))?;
        let mut values = Vec::new();
        values.try_reserve_exact(count).map_err(|_| invalid("array allocation exceeds available memory"))?;
        Ok(values)
    }

    fn floats<const N: usize>(&self, payload: &[u8]) -> Result<Vec<[f32; N]>, SessionError> {
        let mut values = self.reserve()?;
        for record in self.bytes(payload)?.chunks_exact(N * 8) {
            let mut row = [0.0_f32; N];
            for (component, bytes) in row.iter_mut().zip(record.chunks_exact(8)) {
                let value = f64::from_le_bytes(bytes.try_into().map_err(|_| invalid("float is truncated"))?);
                *component = value as f32;
                if !value.is_finite() || !component.is_finite() {
                    return Err(invalid("contains non-finite geometry"));
                }
            }
            values.push(row);
        }
        Ok(values)
    }

    fn indices(&self, payload: &[u8]) -> Result<Vec<u32>, SessionError> {
        let mut values = self.reserve()?;
        for bytes in self.bytes(payload)?.chunks_exact(4) {
            values.push(u32::from_le_bytes(bytes.try_into().map_err(|_| invalid("index is truncated"))?));
        }
        Ok(values)
    }

    fn sources(&self, payload: &[u8]) -> Result<Vec<i32>, SessionError> {
        let mut values = self.reserve()?;
        for bytes in self.bytes(payload)?.chunks_exact(4) {
            values.push(i32::from_le_bytes(bytes.try_into().map_err(|_| invalid("source index is truncated"))?));
        }
        Ok(values)
    }
}

fn validate_layout(metadata: &Metadata, payload: &[u8], expected_count: u64) -> Result<(), SessionError> {
    if metadata.schema != SCHEMA || metadata.lods.is_empty()
        || u32::try_from(metadata.lods.len()).is_err()
    {
        return Err(invalid("schema or LOD collection is invalid"));
    }
    let mut cursor = 0;
    let mut total_parts = 0_u64;
    for lod in &metadata.lods {
        if u32::try_from(lod.submeshes.len()).is_err() {
            return Err(invalid("submesh collection is too large"));
        }
        total_parts = total_parts.checked_add(lod.submeshes.len() as u64)
            .ok_or_else(|| invalid("submesh count overflows"))?;
        for part in &lod.submeshes {
            // Fully deleted authoring slots retain source/material indices for
            // history. Residual channels and ordinary asset empties stay invalid.
            let empty_authoring_part = metadata.parser == super::PACKAGE_SCHEMA
                && [&part.positions, &part.normals, &part.uvs, &part.indices,
                    &part.source_vertex_indices, &part.shader_masks]
                    .iter().all(|array| array.count == 0);
            if !empty_authoring_part && (!(1..=MAX_VERTICES).contains(&part.positions.count)
                || !(3..=MAX_INDICES).contains(&part.indices.count)
                || !part.indices.count.is_multiple_of(3)
                || (part.shader_masks.count != 0 && part.shader_masks.count != part.positions.count)) {
                return Err(invalid("geometry counts exceed the supported bounds"));
            }
            for (array, dtype, components, width) in [
                (&part.positions, "f64_le", 3, 8),
                (&part.normals, "f64_le", 3, 8),
                (&part.uvs, "f64_le", 2, 8),
                (&part.indices, "u32_le", 1, 4),
                (&part.source_vertex_indices, "i32_le", 1, 4),
                (&part.shader_masks, "f64_le", 3, 8),
            ] {
                array.validate(dtype, components, width, &mut cursor, payload.len() as u64)?;
            }
        }
    }
    if total_parts == 0 || total_parts != expected_count || cursor != payload.len() as u64 {
        return Err(invalid("submesh count or trailing payload length does not match"));
    }
    Ok(())
}

fn fingerprint(metadata: &Metadata, payload: &[u8]) -> Result<String, SessionError> {
    let mut hash = Sha256::new();
    hash.update(b"cdmw_mesh_document_binary_v1\0");
    hash.update((metadata.lods.len() as u32).to_le_bytes());
    for lod in &metadata.lods {
        hash.update(lod.level.to_le_bytes());
        hash.update((lod.submeshes.len() as u32).to_le_bytes());
        for part in &lod.submeshes {
            hash.update(part.positions.count.to_le_bytes());
            hash.update(part.indices.count.to_le_bytes());
            hash.update(part.positions.bytes(payload)?);
            hash.update(part.indices.bytes(payload)?);
        }
    }
    Ok(format!("{:X}", hash.finalize()))
}

pub(super) fn decode(bytes: &[u8], expected_count: u64) -> Result<MeshDocument, SessionError> {
    if bytes.len() < HEADER_BYTES || bytes.len() as u64 > MAX_PAYLOAD_BYTES
        || &bytes[..8] != MAGIC
    {
        return Err(invalid("magic or size is invalid"));
    }
    let version = u16::from_le_bytes([bytes[8], bytes[9]]);
    let flags = u16::from_le_bytes([bytes[10], bytes[11]]);
    let metadata_length = u32::from_le_bytes([bytes[12], bytes[13], bytes[14], bytes[15]]) as usize;
    if version != 1 || flags != 0 || metadata_length == 0 || metadata_length as u64 > MAX_MANIFEST_BYTES {
        return Err(invalid("version, flags, or metadata length is invalid"));
    }
    let end = HEADER_BYTES.checked_add(metadata_length).ok_or_else(|| invalid("metadata range overflows"))?;
    let metadata_bytes = bytes.get(HEADER_BYTES..end).ok_or_else(|| invalid("metadata is truncated"))?;
    let payload = bytes.get(end..).ok_or_else(|| invalid("payload is truncated"))?;
    let metadata: Metadata = serde_json::from_slice(metadata_bytes)?;
    validate_layout(&metadata, payload, expected_count)?;
    if fingerprint(&metadata, payload)? != metadata.structural_fingerprint {
        return Err(invalid("structural fingerprint does not match"));
    }
    // No large channel is allocated until every descriptor and the complete
    // structural witness have passed. Work from the original immutable bytes.
    let mut lods = Vec::with_capacity(metadata.lods.len());
    for lod in metadata.lods {
        let mut submeshes = Vec::with_capacity(lod.submeshes.len());
        for part in lod.submeshes {
            submeshes.push(Submesh {
                name: part.name,
                material: part.material,
                positions: part.positions.floats(payload)?,
                normals: part.normals.floats(payload)?,
                uvs: part.uvs.floats(payload)?,
                indices: part.indices.indices(payload)?,
                source_vertex_indices: part.source_vertex_indices.sources(payload)?,
                shader_masks: part.shader_masks.floats(payload)?,
                source_range: SourceRange { offset: part.source_range.offset, length: part.source_range.length },
                vertex_stride: part.vertex_stride,
                layout: part.layout,
            });
        }
        lods.push(MeshLod { level: lod.level, submeshes });
    }
    let document = MeshDocument {
        format: metadata.format,
        source_sha256: metadata.source_sha256,
        parser: metadata.parser,
        lod_count_reported: metadata.lod_count_reported,
        lods,
        warnings: metadata.warnings,
        structural_fingerprint: metadata.structural_fingerprint,
    };
    validate_document(&document)?;
    Ok(document)
}

#[cfg(test)]
pub(super) fn encode_test_document(document: &MeshDocument) -> Vec<u8> {
    use serde_json::json;
    let mut metadata = serde_json::to_value(document).unwrap();
    metadata["schema"] = json!(SCHEMA);
    let mut payload = Vec::new();
    for lod in metadata["lods"].as_array_mut().unwrap() {
        for part in lod["submeshes"].as_array_mut().unwrap() {
            for (name, dtype, components) in [
                ("positions", "f64_le", 3), ("normals", "f64_le", 3),
                ("uvs", "f64_le", 2), ("indices", "u32_le", 1),
                ("source_vertex_indices", "i32_le", 1), ("shader_masks", "f64_le", 3),
            ] {
                let rows = part[name].as_array().unwrap();
                let count = rows.len();
                let offset = payload.len();
                for row in rows {
                    match dtype {
                        "f64_le" => for component in row.as_array().unwrap() {
                            payload.extend_from_slice(&component.as_f64().unwrap().to_le_bytes());
                        },
                        "u32_le" => payload.extend_from_slice(&(row.as_u64().unwrap() as u32).to_le_bytes()),
                        "i32_le" => payload.extend_from_slice(&(row.as_i64().unwrap() as i32).to_le_bytes()),
                        _ => unreachable!(),
                    }
                }
                part[name] = json!({"dtype": dtype, "components": components, "count": count,
                    "offset": offset, "byte_length": payload.len() - offset});
            }
        }
    }
    let parsed: Metadata = serde_json::from_value(metadata.clone()).unwrap();
    metadata["structural_fingerprint"] = json!(fingerprint(&parsed, &payload).unwrap());
    frame_test_metadata(&metadata, &payload)
}

#[cfg(test)]
fn frame_test_metadata(metadata: &serde_json::Value, payload: &[u8]) -> Vec<u8> {
    let encoded = serde_json::to_vec(metadata).unwrap();
    let mut bytes = Vec::new();
    bytes.extend_from_slice(MAGIC);
    bytes.extend_from_slice(&1_u16.to_le_bytes());
    bytes.extend_from_slice(&0_u16.to_le_bytes());
    bytes.extend_from_slice(&(encoded.len() as u32).to_le_bytes());
    bytes.extend_from_slice(&encoded);
    bytes.extend_from_slice(payload);
    bytes
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::{Value, json};

    fn document() -> MeshDocument {
        let mut document = super::super::tests::document();
        let part = &mut document.lods[0].submeshes[0];
        part.positions[0] = [-0.0, f32::from_bits(1), -f32::from_bits(1)];
        part.normals.truncate(1);
        part.uvs.truncate(2);
        part.source_vertex_indices = vec![-1, 7, i32::MAX, i32::MIN];
        part.shader_masks = vec![[0.2, 0.5, 0.8]; 3];
        part.source_range = SourceRange { offset: 0x1_0000_0001, length: 48 };
        document
    }

    fn split(bytes: &[u8]) -> (Value, &[u8]) {
        let length = u32::from_le_bytes(bytes[12..16].try_into().unwrap()) as usize;
        (serde_json::from_slice(&bytes[16..16 + length]).unwrap(), &bytes[16 + length..])
    }

    #[test]
    fn binary_mesh_document_preserves_empty_authoring_part_slots() {
        let original = serde_json::to_value(document()).unwrap();
        let channels = ["positions", "normals", "uvs", "indices", "source_vertex_indices", "shader_masks"];
        for part_index in 0..2 {
            let mut value = original.clone();
            let part = value["lods"][0]["submeshes"][0].clone();
            value["lods"][0]["submeshes"] = json!([part.clone(), part.clone()]);
            for channel in channels {
                value["lods"][0]["submeshes"][part_index][channel] = json!([]);
            }
            let expected: MeshDocument = serde_json::from_value(value.clone()).unwrap();
            let actual = decode(&encode_test_document(&expected), 2).unwrap();
            assert_eq!(actual.lods, expected.lods);
            // Generic asset validation still refuses these non-renderable slots.
            assert!(actual.lods[0].submeshes[part_index].validate().is_err());
            for channel in channels {
                let mut invalid = value.clone();
                invalid["lods"][0]["submeshes"][part_index][channel] = part[channel].clone();
                let document: MeshDocument = serde_json::from_value(invalid).unwrap();
                assert!(decode(&encode_test_document(&document), 2).is_err(), "{channel}");
            }
            value["parser"] = json!("game_parser");
            let document: MeshDocument = serde_json::from_value(value).unwrap();
            assert!(decode(&encode_test_document(&document), 2).is_err());
        }
    }

    #[test]
    fn binary_mesh_document_preserves_all_channels_and_partial_attribute_lengths() {
        let mut expected = document();
        let bytes = encode_test_document(&expected);
        let actual = decode(&bytes, 1).unwrap();
        assert_eq!(actual.structural_fingerprint.len(), 64);
        expected.structural_fingerprint.clone_from(&actual.structural_fingerprint);
        assert_eq!(actual, expected);
        assert_eq!(actual.lods[0].submeshes[0].positions[0][0].to_bits(), (-0.0_f32).to_bits());
        assert_eq!(actual.lods[0].submeshes[0].positions[0][1].to_bits(), 1);
    }

    #[test]
    fn binary_mesh_document_refuses_versions_ranges_types_and_count_overflow() {
        let bytes = encode_test_document(&document());
        for offset in [0, 8, 10] {
            let mut changed = bytes.clone();
            changed[offset] ^= 2;
            assert!(decode(&changed, 1).is_err());
        }
        assert!(decode(&bytes[..15], 1).is_err());
        assert!(decode(&bytes[..bytes.len() - 1], 1).is_err());
        assert!(decode(&bytes, 2).is_err());
        let mut trailing = bytes.clone();
        trailing.push(0);
        assert!(decode(&trailing, 1).is_err());
        let (metadata, payload) = split(&bytes);
        for (field, value) in [
            ("offset", json!(1)), ("byte_length", json!(1)), ("dtype", json!("f32_le")),
            ("components", json!(2)), ("count", json!(u64::MAX)), ("unknown", json!(true)),
        ] {
            let mut changed = metadata.clone();
            changed["lods"][0]["submeshes"][0]["normals"][field] = value;
            assert!(decode(&frame_test_metadata(&changed, payload), 1).is_err(), "{field}");
        }
        let mut changed = metadata;
        changed["schema"] = json!("cdmw_mesh_document_binary_v2");
        assert!(decode(&frame_test_metadata(&changed, payload), 1).is_err());
    }

    #[test]
    fn binary_mesh_document_checks_fingerprint_nonfinite_attributes_and_index_bounds() {
        let bytes = encode_test_document(&document());
        let (metadata, original) = split(&bytes);
        let part = &metadata["lods"][0]["submeshes"][0];
        let mut payload = original.to_vec();
        payload[0] ^= 1;
        assert!(decode(&frame_test_metadata(&metadata, &payload), 1).is_err());
        // Normals are outside the structural fingerprint but remain validated.
        for value in [f64::NAN, f64::INFINITY, f64::MAX] {
            let mut payload = original.to_vec();
            let offset = part["normals"]["offset"].as_u64().unwrap() as usize;
            payload[offset..offset + 8].copy_from_slice(&value.to_le_bytes());
            assert!(decode(&frame_test_metadata(&metadata, &payload), 1).is_err());
        }
        let mut payload = original.to_vec();
        let offset = part["shader_masks"]["offset"].as_u64().unwrap() as usize;
        payload[offset..offset + 8].copy_from_slice(&(-0.5_f64).to_le_bytes());
        assert!(decode(&frame_test_metadata(&metadata, &payload), 1).is_err());
        let mut invalid_index = document();
        invalid_index.lods[0].submeshes[0].indices[2] = 3;
        assert!(decode(&encode_test_document(&invalid_index), 1).is_err());
    }

    #[test]
    fn binary_mesh_document_python_fixture_parity() {
        #[derive(Deserialize)]
        struct Fixture {
            binary_hex: String,
            expected_document: MeshDocument,
        }
        let fixture: Fixture = serde_json::from_str(include_str!(concat!(env!("CARGO_MANIFEST_DIR"),
            "/tests/fixtures/mesh-document-binary-v1.json"))).unwrap();
        assert!(fixture.binary_hex.len().is_multiple_of(2));
        let bytes: Vec<_> = fixture.binary_hex.as_bytes().chunks_exact(2)
            .map(|pair| u8::from_str_radix(std::str::from_utf8(pair).unwrap(), 16).unwrap()).collect();
        let expected = fixture.expected_document;
        let count = expected.lods.iter().map(|lod| lod.submeshes.len() as u64).sum();
        let actual = decode(&bytes, count).unwrap();
        assert_eq!(actual, expected);
        fn check_bits<const N: usize>(name: &str, actual: &[[f32; N]], expected: &[[f32; N]]) {
            assert_eq!(actual.len(), expected.len());
            for (index, (actual, expected)) in actual.iter().flatten().zip(expected.iter().flatten()).enumerate() {
                assert_eq!(actual.to_bits(), expected.to_bits(), "{name} component {index}");
            }
        }
        for (actual, expected) in actual.lods.iter().zip(&expected.lods) {
            for (actual, expected) in actual.submeshes.iter().zip(&expected.submeshes) {
                check_bits("positions", &actual.positions, &expected.positions);
                check_bits("normals", &actual.normals, &expected.normals);
                check_bits("uvs", &actual.uvs, &expected.uvs);
                check_bits("shader_masks", &actual.shader_masks, &expected.shader_masks);
            }
        }
    }

    #[test]
    #[ignore = "release measurement of typed document decode versus JSON decode"]
    fn binary_mesh_document_decode_benchmark() {
        use std::time::Instant;
        for count in [99_999_u32, 300_000_u32] {
            let mut source = super::super::tests::document();
            let part = &mut source.lods[0].submeshes[0];
            part.positions = (0..count).map(|index| [index as f32 * 0.01, (index % 257) as f32 * 0.03125, 0.2]).collect();
            part.normals = vec![[0.0, 0.0, 1.0]; count as usize];
            part.uvs = vec![[0.25, 0.75]; count as usize];
            part.indices = (0..count).collect();
            part.source_vertex_indices = (0..count as i32).collect();
            let json = serde_json::to_vec(&source).unwrap();
            let binary = encode_test_document(&source);
            let started = Instant::now();
            let from_json: MeshDocument = serde_json::from_slice(&json).unwrap();
            validate_document(&from_json).unwrap();
            let json_time = started.elapsed();
            let started = Instant::now();
            let from_binary = decode(&binary, 1).unwrap();
            let binary_time = started.elapsed();
            assert_eq!(from_binary.lods, from_json.lods);
            println!("binary_mesh_document_decode vertices={count} json_bytes={} binary_bytes={} json_decode_validate_ms={:.3} binary_decode_validate_ms={:.3}",
                json.len(), binary.len(), json_time.as_secs_f64() * 1_000.0, binary_time.as_secs_f64() * 1_000.0);
        }
    }
}
