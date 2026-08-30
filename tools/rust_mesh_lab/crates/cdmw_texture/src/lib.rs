#![forbid(unsafe_code)]

use cdmw_evidence::sha256_bytes;
use serde::{Deserialize, Serialize};
use thiserror::Error;

pub const DDS_MAX_DIMENSION: u32 = 16_384;
pub const DDS_MAX_PAYLOAD_BYTES: usize = 512 * 1024 * 1024;
pub const MATERIAL_SIDECAR_MAX_BYTES: usize = 16 * 1024 * 1024;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TextureRole {
    BaseColor,
    Normal,
    Material,
    Roughness,
    Metalness,
    Occlusion,
    Specular,
    Glossiness,
    Emissive,
    Opacity,
    Height,
    Unknown,
}

impl TextureRole {
    #[must_use]
    pub fn from_parameter_name(value: &str) -> Self {
        let normalized = value
            .chars()
            .filter(char::is_ascii_alphanumeric)
            .flat_map(char::to_lowercase)
            .collect::<String>();
        if normalized.contains("normal") {
            Self::Normal
        } else if normalized.contains("roughness") {
            Self::Roughness
        } else if normalized.contains("metalness") || normalized.contains("metallic") {
            Self::Metalness
        } else if normalized.contains("ambientocclusion")
            || normalized.contains("occlusion")
            || normalized == "aotexture"
        {
            Self::Occlusion
        } else if normalized.contains("emissive") {
            Self::Emissive
        } else if normalized.contains("opacity") || normalized.contains("alpha") {
            Self::Opacity
        } else if normalized.contains("height") || normalized.contains("displacement") {
            Self::Height
        } else if normalized.contains("specular") {
            Self::Specular
        } else if normalized.contains("gloss") {
            Self::Glossiness
        } else if normalized.contains("materialtexture") || normalized == "sptexture" {
            Self::Material
        } else if normalized.contains("mask")
            || normalized.contains("blend")
            || normalized == "rgbtexture"
        {
            Self::Unknown
        } else if normalized.contains("basecolor")
            || normalized.contains("overlaycolor")
            || normalized.contains("diffuse")
            || normalized.contains("albedo")
            || normalized.ends_with("colortexture")
        {
            Self::BaseColor
        } else {
            Self::Unknown
        }
    }
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

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MaterialTextureReference {
    pub wrapper_type: String,
    pub submesh_name: String,
    pub material_name: String,
    pub parameter_name: String,
    pub path: String,
    pub role: TextureRole,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MaterialParameterKind {
    Float,
    Float2,
    Float3,
    Half2,
    Color,
    Byte4,
    BitFlag32,
    UnsignedInteger,
    SignedInteger,
    Boolean,
    Unknown,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MaterialParameterConfidence {
    Explicit,
    Incomplete,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MaterialParameter {
    pub wrapper_type: String,
    pub submesh_name: String,
    pub material_name: String,
    pub parameter_type: String,
    pub parameter_name: String,
    pub raw_value: Option<String>,
    pub attributes: Vec<(String, String)>,
    pub kind: MaterialParameterKind,
    pub confidence: MaterialParameterConfidence,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MaterialSidecar {
    pub textures: Vec<MaterialTextureReference>,
    pub parameters: Vec<MaterialParameter>,
    pub warnings: Vec<String>,
}

#[derive(Debug, Error)]
pub enum MaterialSidecarError {
    #[error("material sidecar exceeds the {MATERIAL_SIDECAR_MAX_BYTES}-byte resource limit")]
    ResourceLimit,
    #[error("material sidecar is not valid UTF-8")]
    InvalidEncoding,
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
    let header_is_srgb = matches!(
        format,
        DdsFormat::Bc1Srgb
            | DdsFormat::Bc2Srgb
            | DdsFormat::Bc3Srgb
            | DdsFormat::Bc7Srgb
            | DdsFormat::Rgba8Srgb
            | DdsFormat::Bgra8Srgb
    );
    let color_space = match role {
        TextureRole::BaseColor | TextureRole::Emissive => ColorSpace::Srgb,
        TextureRole::Normal
        | TextureRole::Material
        | TextureRole::Roughness
        | TextureRole::Metalness
        | TextureRole::Occlusion
        | TextureRole::Specular
        | TextureRole::Glossiness
        | TextureRole::Opacity
        | TextureRole::Height => ColorSpace::Linear,
        TextureRole::Unknown if header_is_srgb => ColorSpace::Srgb,
        TextureRole::Unknown => ColorSpace::Linear,
    };
    let mut warnings = Vec::new();
    if header_is_srgb && color_space == ColorSpace::Linear {
        warnings.push(format!(
            "DDS sRGB header is overridden to linear sampling for the {role:?} texture role"
        ));
    }
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

pub fn parse_material_sidecar(bytes: &[u8]) -> Result<MaterialSidecar, MaterialSidecarError> {
    if bytes.len() > MATERIAL_SIDECAR_MAX_BYTES {
        return Err(MaterialSidecarError::ResourceLimit);
    }
    let text = std::str::from_utf8(bytes).map_err(|_| MaterialSidecarError::InvalidEncoding)?;
    let mut textures = Vec::new();
    let mut material_parameters = Vec::new();
    let mut warnings = Vec::new();
    let mut wrappers = Vec::<WrapperContext>::new();
    let mut materials = Vec::<String>::new();
    let mut parameters = Vec::<ParameterContext>::new();
    let mut cursor = 0_usize;

    while let Some(start_offset) = text.get(cursor..).and_then(|rest| rest.find('<')) {
        let start = cursor.saturating_add(start_offset);
        if text
            .get(start..)
            .is_some_and(|remaining| remaining.starts_with("<!--"))
        {
            if let Some(end_offset) = text
                .get(start.saturating_add(4)..)
                .and_then(|remaining| remaining.find("-->"))
            {
                cursor = start
                    .saturating_add(4)
                    .saturating_add(end_offset)
                    .saturating_add(3);
                continue;
            }
            warnings.push("material sidecar ends inside an XML comment".to_owned());
            break;
        }
        let Some(end) = find_xml_tag_end(text, start.saturating_add(1)) else {
            warnings.push("material sidecar ends inside an XML tag".to_owned());
            break;
        };
        cursor = end.saturating_add(1);
        let Some(tag_text) = text.get(start.saturating_add(1)..end) else {
            continue;
        };
        let Some(tag) = parse_xml_tag(tag_text) else {
            continue;
        };
        let lowered = tag.name.to_ascii_lowercase();

        if tag.closing {
            if lowered == "materialparametertexture" {
                if let Some(parameter) = parameters.pop() {
                    finish_parameter(parameter, &mut textures, &mut warnings);
                }
            } else if lowered == "material" {
                let _ = materials.pop();
            } else if lowered.ends_with("materialwrapper") {
                let _ = wrappers.pop();
            }
            continue;
        }

        if lowered.ends_with("materialwrapper") {
            wrappers.push(WrapperContext {
                wrapper_type: tag.name.clone(),
                submesh_name: attribute(&tag.attributes, &["_subMeshName", "subMeshName"])
                    .unwrap_or_default(),
            });
            if tag.self_closing {
                let _ = wrappers.pop();
            }
            continue;
        }
        if lowered == "material" {
            materials.push(
                attribute(
                    &tag.attributes,
                    &["_materialName", "materialName", "shader", "Shader"],
                )
                .unwrap_or_default(),
            );
            if tag.self_closing {
                let _ = materials.pop();
            }
            continue;
        }
        if lowered == "materialparametertexture" {
            let wrapper = wrappers.last().cloned().unwrap_or_default();
            let parameter_name =
                attribute(&tag.attributes, &["StringItemID", "_name", "Name", "name"])
                    .unwrap_or_else(|| "(unnamed)".to_owned());
            let parameter = ParameterContext {
                wrapper,
                material_name: materials.last().cloned().unwrap_or_default(),
                parameter_name,
                path: texture_path_attribute(&tag.attributes),
            };
            if tag.self_closing {
                finish_parameter(parameter, &mut textures, &mut warnings);
            } else {
                parameters.push(parameter);
            }
            continue;
        }
        if lowered == "resourcereferencepath_itexture" {
            let path = texture_path_attribute(&tag.attributes);
            if let Some(parameter) = parameters.last_mut() {
                if let Some(path) = path {
                    if parameter
                        .path
                        .as_ref()
                        .is_some_and(|existing| !existing.eq_ignore_ascii_case(&path))
                    {
                        warnings.push(format!(
                            "texture parameter {} contains more than one path; the first path is preserved",
                            parameter.parameter_name
                        ));
                    } else if parameter.path.is_none() {
                        parameter.path = Some(path);
                    }
                }
            } else if let Some(path) = path {
                let wrapper = wrappers.last().cloned().unwrap_or_default();
                textures.push(MaterialTextureReference {
                    wrapper_type: wrapper.wrapper_type,
                    submesh_name: wrapper.submesh_name,
                    material_name: materials.last().cloned().unwrap_or_default(),
                    parameter_name: "(unknown)".to_owned(),
                    path,
                    role: TextureRole::Unknown,
                });
            }
            continue;
        }
        if let Some(kind) = material_parameter_kind(&lowered) {
            material_parameters.push(material_parameter_from_tag(
                &tag,
                kind,
                wrappers.last().cloned().unwrap_or_default(),
                materials.last().cloned().unwrap_or_default(),
            ));
        }
    }

    if !parameters.is_empty() {
        warnings.push(format!(
            "recovered {} unterminated material texture parameter(s)",
            parameters.len()
        ));
    }
    while let Some(parameter) = parameters.pop() {
        finish_parameter(parameter, &mut textures, &mut warnings);
    }
    Ok(MaterialSidecar {
        textures,
        parameters: material_parameters,
        warnings,
    })
}

#[derive(Debug, Clone, Default)]
struct WrapperContext {
    wrapper_type: String,
    submesh_name: String,
}

#[derive(Debug)]
struct ParameterContext {
    wrapper: WrapperContext,
    material_name: String,
    parameter_name: String,
    path: Option<String>,
}

#[derive(Debug)]
struct XmlTag {
    name: String,
    attributes: Vec<(String, String)>,
    closing: bool,
    self_closing: bool,
}

fn finish_parameter(
    parameter: ParameterContext,
    textures: &mut Vec<MaterialTextureReference>,
    warnings: &mut Vec<String>,
) {
    let Some(path) = parameter.path.filter(|value| !value.trim().is_empty()) else {
        warnings.push(format!(
            "texture parameter {} has no resource path",
            parameter.parameter_name
        ));
        return;
    };
    textures.push(MaterialTextureReference {
        wrapper_type: parameter.wrapper.wrapper_type,
        submesh_name: parameter.wrapper.submesh_name,
        material_name: parameter.material_name,
        role: TextureRole::from_parameter_name(&parameter.parameter_name),
        parameter_name: parameter.parameter_name,
        path,
    });
}

fn material_parameter_kind(lowered_tag: &str) -> Option<MaterialParameterKind> {
    match lowered_tag {
        "materialparameterfloat" => Some(MaterialParameterKind::Float),
        "materialparameterfloat2" => Some(MaterialParameterKind::Float2),
        "materialparameterfloat3" => Some(MaterialParameterKind::Float3),
        "materialparameterhalf2" => Some(MaterialParameterKind::Half2),
        "materialparametercolor" | "representcolor" => Some(MaterialParameterKind::Color),
        "materialparameterbyte4" => Some(MaterialParameterKind::Byte4),
        "materialparameterbitflag32" => Some(MaterialParameterKind::BitFlag32),
        "materialparameteruint" | "materialparameteruint32" => {
            Some(MaterialParameterKind::UnsignedInteger)
        }
        "materialparameterint" | "materialparameterint32" => {
            Some(MaterialParameterKind::SignedInteger)
        }
        "materialparameterbool" => Some(MaterialParameterKind::Boolean),
        value if value.starts_with("materialparameter") => Some(MaterialParameterKind::Unknown),
        _ => None,
    }
}

fn material_parameter_from_tag(
    tag: &XmlTag,
    kind: MaterialParameterKind,
    wrapper: WrapperContext,
    material_name: String,
) -> MaterialParameter {
    let explicit_name = attribute(&tag.attributes, &["StringItemID", "_name", "Name", "name"]);
    let raw_value = material_parameter_value(&tag.attributes);
    let inherent_name = tag.name.eq_ignore_ascii_case("RepresentColor");
    let confidence = if (explicit_name.is_some() || inherent_name) && raw_value.is_some() {
        MaterialParameterConfidence::Explicit
    } else {
        MaterialParameterConfidence::Incomplete
    };
    MaterialParameter {
        wrapper_type: wrapper.wrapper_type,
        submesh_name: wrapper.submesh_name,
        material_name,
        parameter_type: tag.name.clone(),
        parameter_name: explicit_name.unwrap_or_else(|| tag.name.clone()),
        raw_value,
        attributes: tag.attributes.clone(),
        kind,
        confidence,
    }
}

fn material_parameter_value(attributes: &[(String, String)]) -> Option<String> {
    if let Some(value) = attribute(attributes, &["_value", "Value", "DefaultValue"]) {
        return Some(value);
    }
    let components = ["x", "y", "z", "w"]
        .into_iter()
        .filter_map(|name| attribute(attributes, &[name]))
        .collect::<Vec<_>>();
    (!components.is_empty()).then(|| components.join(" "))
}

fn find_xml_tag_end(text: &str, mut cursor: usize) -> Option<usize> {
    let bytes = text.as_bytes();
    let mut quote = None;
    while let Some(value) = bytes.get(cursor).copied() {
        match (quote, value) {
            (Some(active), current) if active == current => quote = None,
            (None, b'\'' | b'"') => quote = Some(value),
            (None, b'>') => return Some(cursor),
            _ => {}
        }
        cursor = cursor.saturating_add(1);
    }
    None
}

fn parse_xml_tag(value: &str) -> Option<XmlTag> {
    let mut trimmed = value.trim();
    if trimmed.is_empty() || trimmed.starts_with('!') || trimmed.starts_with('?') {
        return None;
    }
    let closing = trimmed.starts_with('/');
    if closing {
        trimmed = trimmed.get(1..)?.trim_start();
    }
    let self_closing = !closing && trimmed.ends_with('/');
    if self_closing {
        trimmed = trimmed.get(..trimmed.len().saturating_sub(1))?.trim_end();
    }
    let name_end = trimmed.find(char::is_whitespace).unwrap_or(trimmed.len());
    let name = trimmed.get(..name_end)?.trim();
    if name.is_empty() {
        return None;
    }
    let attributes = if closing {
        Vec::new()
    } else {
        parse_xml_attributes(trimmed.get(name_end..).unwrap_or_default())
    };
    Some(XmlTag {
        name: name.to_owned(),
        attributes,
        closing,
        self_closing,
    })
}

fn parse_xml_attributes(value: &str) -> Vec<(String, String)> {
    let bytes = value.as_bytes();
    let mut attributes = Vec::new();
    let mut cursor = 0_usize;
    while cursor < bytes.len() {
        while bytes.get(cursor).is_some_and(u8::is_ascii_whitespace) {
            cursor = cursor.saturating_add(1);
        }
        let key_start = cursor;
        while bytes
            .get(cursor)
            .is_some_and(|value| !value.is_ascii_whitespace() && *value != b'=')
        {
            cursor = cursor.saturating_add(1);
        }
        let key_end = cursor;
        while bytes.get(cursor).is_some_and(u8::is_ascii_whitespace) {
            cursor = cursor.saturating_add(1);
        }
        if bytes.get(cursor) != Some(&b'=') {
            cursor = cursor.saturating_add(1);
            continue;
        }
        cursor = cursor.saturating_add(1);
        while bytes.get(cursor).is_some_and(u8::is_ascii_whitespace) {
            cursor = cursor.saturating_add(1);
        }
        let quote = bytes.get(cursor).copied();
        let (value_start, value_end) = if matches!(quote, Some(b'\'' | b'"')) {
            cursor = cursor.saturating_add(1);
            let start = cursor;
            while bytes.get(cursor).is_some_and(|value| Some(*value) != quote) {
                cursor = cursor.saturating_add(1);
            }
            let end = cursor;
            cursor = cursor.saturating_add(1);
            (start, end)
        } else {
            let start = cursor;
            while bytes
                .get(cursor)
                .is_some_and(|value| !value.is_ascii_whitespace())
            {
                cursor = cursor.saturating_add(1);
            }
            (start, cursor)
        };
        if let (Some(key), Some(attribute_value)) = (
            value.get(key_start..key_end),
            value.get(value_start..value_end),
        ) && !key.is_empty()
        {
            attributes.push((key.to_owned(), decode_xml_entities(attribute_value)));
        }
    }
    attributes
}

fn decode_xml_entities(value: &str) -> String {
    let mut decoded = String::with_capacity(value.len());
    let mut cursor = 0_usize;
    while let Some(relative_start) = value.get(cursor..).and_then(|rest| rest.find('&')) {
        let start = cursor.saturating_add(relative_start);
        decoded.push_str(value.get(cursor..start).unwrap_or_default());
        let Some(relative_end) = value
            .get(start.saturating_add(1)..)
            .and_then(|rest| rest.find(';'))
            .filter(|offset| *offset <= 12)
        else {
            decoded.push('&');
            cursor = start.saturating_add(1);
            continue;
        };
        let end = start.saturating_add(1).saturating_add(relative_end);
        let entity = value.get(start.saturating_add(1)..end).unwrap_or_default();
        let replacement = match entity {
            "amp" => Some('&'),
            "quot" => Some('"'),
            "apos" => Some('\''),
            "lt" => Some('<'),
            "gt" => Some('>'),
            numeric if numeric.starts_with("#x") => u32::from_str_radix(&numeric[2..], 16)
                .ok()
                .and_then(char::from_u32),
            numeric if numeric.starts_with('#') => {
                numeric[1..].parse().ok().and_then(char::from_u32)
            }
            _ => None,
        };
        if let Some(replacement) = replacement {
            decoded.push(replacement);
        } else {
            decoded.push_str(value.get(start..=end).unwrap_or_default());
        }
        cursor = end.saturating_add(1);
    }
    decoded.push_str(value.get(cursor..).unwrap_or_default());
    decoded
}

fn attribute(attributes: &[(String, String)], names: &[&str]) -> Option<String> {
    names.iter().find_map(|name| {
        attributes
            .iter()
            .find(|(candidate, _)| candidate.eq_ignore_ascii_case(name))
            .map(|(_, value)| value.clone())
    })
}

fn texture_path_attribute(attributes: &[(String, String)]) -> Option<String> {
    attribute(
        attributes,
        &["_path", "path", "Path", "_value", "value", "Value"],
    )
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
    fn technical_role_overrides_an_srgb_dds_header() -> Result<(), TextureError> {
        let metadata = inspect_dds(&dds_dx10(99), TextureRole::Normal)?;
        assert_eq!(metadata.format, DdsFormat::Bc7Srgb);
        assert_eq!(metadata.color_space, ColorSpace::Linear);
        assert!(
            metadata
                .warnings
                .iter()
                .any(|warning| warning.contains("overridden to linear"))
        );
        Ok(())
    }

    #[test]
    fn unknown_role_honors_an_srgb_dds_header() -> Result<(), TextureError> {
        let metadata = inspect_dds(&dds_dx10(99), TextureRole::Unknown)?;
        assert_eq!(metadata.color_space, ColorSpace::Srgb);
        assert!(metadata.warnings.is_empty());
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

    #[test]
    fn texture_parameter_roles_are_conservative() {
        assert_eq!(
            TextureRole::from_parameter_name("_baseColorTexture"),
            TextureRole::BaseColor
        );
        assert_eq!(
            TextureRole::from_parameter_name("_overlayColorTexture"),
            TextureRole::BaseColor
        );
        assert_eq!(
            TextureRole::from_parameter_name("_normalTexture"),
            TextureRole::Normal
        );
        assert_eq!(
            TextureRole::from_parameter_name("_materialTexture"),
            TextureRole::Material
        );
        assert_eq!(
            TextureRole::from_parameter_name("_roughnessTexture"),
            TextureRole::Roughness
        );
        assert_eq!(
            TextureRole::from_parameter_name("_metalnessTexture"),
            TextureRole::Metalness
        );
        assert_eq!(
            TextureRole::from_parameter_name("_ambientOcclusionTexture"),
            TextureRole::Occlusion
        );
        assert_eq!(
            TextureRole::from_parameter_name("_specularTexture"),
            TextureRole::Specular
        );
        assert_eq!(
            TextureRole::from_parameter_name("_glossinessTexture"),
            TextureRole::Glossiness
        );
        assert_eq!(
            TextureRole::from_parameter_name("_emissiveIntensityTexture"),
            TextureRole::Emissive
        );
        assert_eq!(
            TextureRole::from_parameter_name("_colorBlendingMaskTexture"),
            TextureRole::Unknown
        );
        assert_eq!(
            TextureRole::from_parameter_name("_rgbTexture"),
            TextureRole::Unknown
        );
    }

    #[test]
    fn material_sidecar_preserves_wrapper_shader_parameter_and_path()
    -> Result<(), MaterialSidecarError> {
        let sidecar = parse_material_sidecar(
            br#"<Root>
                <SkinnedMeshMaterialWrapper _subMeshName="Body &amp; Cloth">
                  <Material _materialName="SkinnedMeshStandard_Ver2">
                    <MaterialParameterTexture StringItemID="_baseColorTexture" _name="ignored">
                      <ResourceReferencePath_ITexture _path="character/texture/body&amp;skin.dds"/>
                    </MaterialParameterTexture>
                    <MaterialParameterTexture Name="_normalTexture" Value="character/texture/body_n.dds"/>
                  </Material>
                </SkinnedMeshMaterialWrapper>
              </Root>"#,
        )?;
        assert!(sidecar.warnings.is_empty());
        assert_eq!(sidecar.textures.len(), 2);
        assert_eq!(
            sidecar.textures[0].wrapper_type,
            "SkinnedMeshMaterialWrapper"
        );
        assert_eq!(sidecar.textures[0].submesh_name, "Body & Cloth");
        assert_eq!(
            sidecar.textures[0].material_name,
            "SkinnedMeshStandard_Ver2"
        );
        assert_eq!(sidecar.textures[0].parameter_name, "_baseColorTexture");
        assert_eq!(sidecar.textures[0].path, "character/texture/body&skin.dds");
        assert_eq!(sidecar.textures[0].role, TextureRole::BaseColor);
        assert_eq!(sidecar.textures[1].role, TextureRole::Normal);
        Ok(())
    }

    #[test]
    fn material_sidecar_recovers_an_unterminated_texture_parameter()
    -> Result<(), MaterialSidecarError> {
        let sidecar = parse_material_sidecar(
            br#"<CDMaterialWrapper _subMeshName="Body"><MaterialParameterTexture _name="_baseColorTexture"><ResourceReferencePath_ITexture value="body.dds"/>"#,
        )?;
        assert_eq!(sidecar.textures.len(), 1);
        assert_eq!(sidecar.textures[0].wrapper_type, "CDMaterialWrapper");
        assert_eq!(sidecar.textures[0].role, TextureRole::BaseColor);
        assert!(
            sidecar
                .warnings
                .iter()
                .any(|warning| warning.contains("unterminated"))
        );
        Ok(())
    }

    #[test]
    fn material_sidecar_preserves_typed_vector_and_unknown_parameters()
    -> Result<(), MaterialSidecarError> {
        let sidecar = parse_material_sidecar(
            br##"<SkinnedMeshMaterialWrapper _subMeshName="Body">
                <Material _materialName="SkinnedMeshEmissive">
                  <MaterialParameterColor StringItemID="_emissiveColor" _value="#05ff9fff" Index="3"/>
                  <MaterialParameterFloat _name="_emissiveIntensity" Value="1.25"/>
                  <MaterialParameterFloat3 Name="_windDirection" Value="1.0 0.0 0.5"/>
                  <MaterialParameterHalf2 Name="_layerOffset" x="0.25" y="0.75"/>
                  <MaterialParameterFuture _name="_future" _value="opaque" FutureFlag="yes"/>
                  <MaterialParameterFloat _name="_missing"/>
                </Material>
              </SkinnedMeshMaterialWrapper>"##,
        )?;
        assert_eq!(sidecar.parameters.len(), 6);
        let color = &sidecar.parameters[0];
        assert_eq!(color.wrapper_type, "SkinnedMeshMaterialWrapper");
        assert_eq!(color.submesh_name, "Body");
        assert_eq!(color.material_name, "SkinnedMeshEmissive");
        assert_eq!(color.parameter_type, "MaterialParameterColor");
        assert_eq!(color.parameter_name, "_emissiveColor");
        assert_eq!(color.raw_value.as_deref(), Some("#05ff9fff"));
        assert_eq!(color.kind, MaterialParameterKind::Color);
        assert_eq!(color.confidence, MaterialParameterConfidence::Explicit);
        assert!(
            color
                .attributes
                .iter()
                .any(|(name, value)| name == "Index" && value == "3")
        );
        assert_eq!(sidecar.parameters[1].kind, MaterialParameterKind::Float);
        assert_eq!(sidecar.parameters[2].kind, MaterialParameterKind::Float3);
        assert_eq!(
            sidecar.parameters[2].raw_value.as_deref(),
            Some("1.0 0.0 0.5")
        );
        assert_eq!(sidecar.parameters[3].kind, MaterialParameterKind::Half2);
        assert_eq!(
            sidecar.parameters[3].raw_value.as_deref(),
            Some("0.25 0.75")
        );
        assert_eq!(sidecar.parameters[4].kind, MaterialParameterKind::Unknown);
        assert_eq!(
            sidecar.parameters[4].parameter_type,
            "MaterialParameterFuture"
        );
        assert!(
            sidecar.parameters[4]
                .attributes
                .iter()
                .any(|(name, value)| name == "FutureFlag" && value == "yes")
        );
        assert_eq!(
            sidecar.parameters[5].confidence,
            MaterialParameterConfidence::Incomplete
        );
        assert_eq!(sidecar.parameters[5].raw_value, None);
        Ok(())
    }

    #[test]
    fn material_sidecar_rejects_oversized_and_non_utf8_inputs() {
        assert!(matches!(
            parse_material_sidecar(&vec![0_u8; MATERIAL_SIDECAR_MAX_BYTES + 1]),
            Err(MaterialSidecarError::ResourceLimit)
        ));
        assert!(matches!(
            parse_material_sidecar(&[0xff]),
            Err(MaterialSidecarError::InvalidEncoding)
        ));
    }
}
