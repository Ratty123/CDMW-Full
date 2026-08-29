#![forbid(unsafe_code)]

use cdmw_evidence::sha256_bytes;
use serde::{Deserialize, Serialize};
use thiserror::Error;

pub const DDS_MAX_DIMENSION: u32 = 16_384;
pub const DDS_MAX_PAYLOAD_BYTES: usize = 512 * 1024 * 1024;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TextureRole {
    BaseColor,
    Normal,
    Material,
    Roughness,
    Metalness,
    Occlusion,
    Emissive,
    Opacity,
    Height,
    Unknown,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ColorSpace {
    Srgb,
    Linear,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum DdsFormat {
    Bc1Unorm,
    Bc1Srgb,
    Bc2Unorm,
    Bc2Srgb,
    Bc3Unorm,
    Bc3Srgb,
    Bc4Unorm,
    Bc4Snorm,
    Bc5Unorm,
    Bc5Snorm,
    Bc6hUnsignedFloat,
    Bc6hSignedFloat,
    Bc7Unorm,
    Bc7Srgb,
    R8Unorm,
    Rg8Unorm,
    Rgba8Unorm,
    Rgba8Srgb,
    Bgra8Unorm,
    Bgra8Srgb,
    Rgba16Float,
    Rgba32Float,
    Unknown { four_cc: String, dxgi: Option<u32> },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DdsMetadata {
    pub width: u32,
    pub height: u32,
    pub depth: u32,
    pub mip_count: u32,
    pub array_size: u32,
    pub is_cube: bool,
    pub format: DdsFormat,
    pub color_space: ColorSpace,
    pub source_sha256: String,
    pub payload_offset: usize,
    pub warnings: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DdsMipLevel {
    pub level: u32,
    pub width: u32,
    pub height: u32,
    pub byte_offset: usize,
    pub byte_length: usize,
    pub bytes_per_row: u32,
    pub rows_per_image: u32,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DdsUploadPlan {
    pub metadata: DdsMetadata,
    pub levels: Vec<DdsMipLevel>,
}

#[derive(Debug, Error)]
pub enum TextureError {
    #[error("DDS payload exceeds the {DDS_MAX_PAYLOAD_BYTES}-byte resource limit")]
    ResourceLimit,
    #[error("DDS header is missing or truncated")]
    Truncated,
    #[error("DDS magic or header size is invalid")]
    InvalidHeader,
    #[error("DDS dimensions or mip count are invalid")]
    InvalidDimensions,
    #[error("DDS format or resource kind is not supported for direct 2D GPU upload")]
    UnsupportedUpload,
    #[error("DDS mip payload is truncated")]
    TruncatedPayload,
}

pub fn plan_2d_upload(bytes: &[u8], role: TextureRole) -> Result<DdsUploadPlan, TextureError> {
    let metadata = inspect_dds(bytes, role)?;
    if metadata.depth != 1 || metadata.array_size != 1 || metadata.is_cube {
        return Err(TextureError::UnsupportedUpload);
    }
    let (block_width, block_height, bytes_per_block) = format_block(&metadata.format)?;
    let mut offset = metadata.payload_offset;
    let mut width = metadata.width;
    let mut height = metadata.height;
    let mut levels = Vec::with_capacity(metadata.mip_count as usize);
    for level in 0..metadata.mip_count {
        let columns = width.div_ceil(block_width);
        let rows = height.div_ceil(block_height);
        let bytes_per_row = columns
            .checked_mul(bytes_per_block)
            .ok_or(TextureError::ResourceLimit)?;
        let byte_length_u32 = bytes_per_row
            .checked_mul(rows)
            .ok_or(TextureError::ResourceLimit)?;
        let byte_length =
            usize::try_from(byte_length_u32).map_err(|_| TextureError::ResourceLimit)?;
        let end = offset
            .checked_add(byte_length)
            .ok_or(TextureError::ResourceLimit)?;
        if end > bytes.len() {
            return Err(TextureError::TruncatedPayload);
        }
        levels.push(DdsMipLevel {
            level,
            width,
            height,
            byte_offset: offset,
            byte_length,
            bytes_per_row,
            rows_per_image: rows,
        });
        offset = end;
        width = (width / 2).max(1);
        height = (height / 2).max(1);
    }
    Ok(DdsUploadPlan { metadata, levels })
}

pub fn inspect_dds(bytes: &[u8], role: TextureRole) -> Result<DdsMetadata, TextureError> {
    if bytes.len() > DDS_MAX_PAYLOAD_BYTES {
        return Err(TextureError::ResourceLimit);
    }
    if bytes.len() < 128 {
        return Err(TextureError::Truncated);
    }
    if bytes.get(..4) != Some(b"DDS ") || read_u32(bytes, 4)? != 124 || read_u32(bytes, 76)? != 32 {
        return Err(TextureError::InvalidHeader);
    }
    let height = read_u32(bytes, 12)?;
    let width = read_u32(bytes, 16)?;
    let depth = read_u32(bytes, 24)?.max(1);
    let mip_count = read_u32(bytes, 28)?.max(1);
    validate_dimensions(width, height, mip_count)?;
    let caps2 = read_u32(bytes, 112)?;
    let four_cc_bytes = bytes.get(84..88).ok_or(TextureError::Truncated)?;
    let four_cc = String::from_utf8_lossy(four_cc_bytes).into_owned();
    let is_dx10 = four_cc_bytes == b"DX10";
    let (dxgi, array_size, payload_offset) = if is_dx10 {
        if bytes.len() < 148 {
            return Err(TextureError::Truncated);
        }
        (
            Some(read_u32(bytes, 128)?),
            read_u32(bytes, 140)?.max(1),
            148,
        )
    } else {
        (None, 1, 128)
    };
    let format = map_format(&four_cc, dxgi);
    let color_space = if matches!(
        format,
        DdsFormat::Bc1Srgb
            | DdsFormat::Bc2Srgb
            | DdsFormat::Bc3Srgb
            | DdsFormat::Bc7Srgb
            | DdsFormat::Rgba8Srgb
            | DdsFormat::Bgra8Srgb
    ) || matches!(role, TextureRole::BaseColor | TextureRole::Emissive)
    {
        ColorSpace::Srgb
    } else {
        ColorSpace::Linear
    };
    let mut warnings = Vec::new();
    if matches!(format, DdsFormat::Unknown { .. }) {
        warnings.push("DDS metadata is readable, but native decode/upload support is not proven for this format".to_owned());
    }
    Ok(DdsMetadata {
        width,
        height,
        depth,
        mip_count,
        array_size,
        is_cube: caps2 & 0x0000_fe00 != 0,
        format,
        color_space,
        source_sha256: sha256_bytes(bytes),
        payload_offset,
        warnings,
    })
}

fn validate_dimensions(width: u32, height: u32, mip_count: u32) -> Result<(), TextureError> {
    if width == 0 || height == 0 || width > DDS_MAX_DIMENSION || height > DDS_MAX_DIMENSION {
        return Err(TextureError::InvalidDimensions);
    }
    let maximum_mips = 32_u32.saturating_sub(width.max(height).leading_zeros());
    if mip_count == 0 || mip_count > maximum_mips {
        return Err(TextureError::InvalidDimensions);
    }
    Ok(())
}

fn map_format(four_cc: &str, dxgi: Option<u32>) -> DdsFormat {
    if let Some(value) = dxgi {
        return match value {
            2 => DdsFormat::Rgba32Float,
            10 => DdsFormat::Rgba16Float,
            28 => DdsFormat::Rgba8Unorm,
            29 => DdsFormat::Rgba8Srgb,
            49 => DdsFormat::Rg8Unorm,
            61 => DdsFormat::R8Unorm,
            71 => DdsFormat::Bc1Unorm,
            72 => DdsFormat::Bc1Srgb,
            74 => DdsFormat::Bc2Unorm,
            75 => DdsFormat::Bc2Srgb,
            77 => DdsFormat::Bc3Unorm,
            78 => DdsFormat::Bc3Srgb,
            80 => DdsFormat::Bc4Unorm,
            81 => DdsFormat::Bc4Snorm,
            83 => DdsFormat::Bc5Unorm,
            84 => DdsFormat::Bc5Snorm,
            87 => DdsFormat::Bgra8Unorm,
            91 => DdsFormat::Bgra8Srgb,
            95 => DdsFormat::Bc6hUnsignedFloat,
            96 => DdsFormat::Bc6hSignedFloat,
            98 => DdsFormat::Bc7Unorm,
            99 => DdsFormat::Bc7Srgb,
            _ => DdsFormat::Unknown {
                four_cc: four_cc.to_owned(),
                dxgi: Some(value),
            },
        };
    }
    match four_cc.trim_end_matches('\0') {
        "DXT1" => DdsFormat::Bc1Unorm,
        "DXT3" => DdsFormat::Bc2Unorm,
        "DXT5" => DdsFormat::Bc3Unorm,
        "ATI1" | "BC4U" => DdsFormat::Bc4Unorm,
        "BC4S" => DdsFormat::Bc4Snorm,
        "ATI2" | "BC5U" => DdsFormat::Bc5Unorm,
        "BC5S" => DdsFormat::Bc5Snorm,
        _ => DdsFormat::Unknown {
            four_cc: four_cc.to_owned(),
            dxgi: None,
        },
    }
}

fn format_block(format: &DdsFormat) -> Result<(u32, u32, u32), TextureError> {
    match format {
        DdsFormat::Bc1Unorm | DdsFormat::Bc1Srgb | DdsFormat::Bc4Unorm | DdsFormat::Bc4Snorm => {
            Ok((4, 4, 8))
        }
        DdsFormat::Bc2Unorm
        | DdsFormat::Bc2Srgb
        | DdsFormat::Bc3Unorm
        | DdsFormat::Bc3Srgb
        | DdsFormat::Bc5Unorm
        | DdsFormat::Bc5Snorm
        | DdsFormat::Bc6hUnsignedFloat
        | DdsFormat::Bc6hSignedFloat
        | DdsFormat::Bc7Unorm
        | DdsFormat::Bc7Srgb => Ok((4, 4, 16)),
        DdsFormat::R8Unorm => Ok((1, 1, 1)),
        DdsFormat::Rg8Unorm => Ok((1, 1, 2)),
        DdsFormat::Rgba8Unorm
        | DdsFormat::Rgba8Srgb
        | DdsFormat::Bgra8Unorm
        | DdsFormat::Bgra8Srgb => Ok((1, 1, 4)),
        DdsFormat::Rgba16Float => Ok((1, 1, 8)),
        DdsFormat::Rgba32Float => Ok((1, 1, 16)),
        DdsFormat::Unknown { .. } => Err(TextureError::UnsupportedUpload),
    }
}

fn read_u32(bytes: &[u8], offset: usize) -> Result<u32, TextureError> {
    let source = bytes
        .get(offset..offset.saturating_add(4))
        .ok_or(TextureError::Truncated)?;
    let array: [u8; 4] = source.try_into().map_err(|_| TextureError::Truncated)?;
    Ok(u32::from_le_bytes(array))
}

pub mod synthetic {
    #[must_use]
    pub fn rgba8_checker_dds() -> Vec<u8> {
        let mut bytes = vec![0_u8; 148 + 16];
        write_text(&mut bytes, 0, b"DDS ");
        write_u32(&mut bytes, 4, 124);
        write_u32(&mut bytes, 12, 2);
        write_u32(&mut bytes, 16, 2);
        write_u32(&mut bytes, 28, 1);
        write_u32(&mut bytes, 76, 32);
        write_text(&mut bytes, 84, b"DX10");
        write_u32(&mut bytes, 128, 28);
        write_u32(&mut bytes, 140, 1);
        let pixels: [u8; 16] = [
            230, 70, 70, 255, 60, 180, 230, 255, 60, 180, 230, 255, 230, 70, 70, 255,
        ];
        write_text(&mut bytes, 148, &pixels);
        bytes
    }

    fn write_u32(bytes: &mut [u8], offset: usize, value: u32) {
        if let Some(destination) = bytes.get_mut(offset..offset.saturating_add(4)) {
            destination.copy_from_slice(&value.to_le_bytes());
        }
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

    fn dds_dx10(dxgi: u32) -> Vec<u8> {
        let mut bytes = vec![0_u8; 148];
        if let Some(slot) = bytes.get_mut(..4) {
            slot.copy_from_slice(b"DDS ");
        }
        write(&mut bytes, 4, 124);
        write(&mut bytes, 12, 4);
        write(&mut bytes, 16, 4);
        write(&mut bytes, 28, 1);
        write(&mut bytes, 76, 32);
        if let Some(slot) = bytes.get_mut(84..88) {
            slot.copy_from_slice(b"DX10");
        }
        write(&mut bytes, 128, dxgi);
        write(&mut bytes, 140, 1);
        bytes
    }

    fn write(bytes: &mut [u8], offset: usize, value: u32) {
        if let Some(slot) = bytes.get_mut(offset..offset.saturating_add(4)) {
            slot.copy_from_slice(&value.to_le_bytes());
        }
    }

    #[test]
    fn dx10_bc7_srgb_is_color_data() -> Result<(), TextureError> {
        let metadata = inspect_dds(&dds_dx10(99), TextureRole::BaseColor)?;
        assert_eq!(metadata.format, DdsFormat::Bc7Srgb);
        assert_eq!(metadata.color_space, ColorSpace::Srgb);
        Ok(())
    }

    #[test]
    fn normal_role_is_linear_even_for_unknown_legacy_format() -> Result<(), TextureError> {
        let metadata = inspect_dds(&dds_dx10(83), TextureRole::Normal)?;
        assert_eq!(metadata.format, DdsFormat::Bc5Unorm);
        assert_eq!(metadata.color_space, ColorSpace::Linear);
        Ok(())
    }

    #[test]
    fn bc7_upload_plan_bounds_each_mip() -> Result<(), TextureError> {
        let mut bytes = dds_dx10(98);
        bytes.resize(148 + 16, 0x5a);
        let plan = plan_2d_upload(&bytes, TextureRole::BaseColor)?;
        assert_eq!(plan.levels.len(), 1);
        assert_eq!(plan.levels[0].byte_offset, 148);
        assert_eq!(plan.levels[0].byte_length, 16);
        assert_eq!(plan.levels[0].bytes_per_row, 16);
        Ok(())
    }
}
