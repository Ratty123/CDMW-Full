use image::{imageops::FilterType, RgbaImage};
use image_dds::ddsfile::{D3D10ResourceDimension, Dds, DxgiFormat};
use serde::Serialize;
use std::fs::File;
use std::io::BufReader;
use std::path::Path;

pub const BACKEND_ID: &str = "cd_texture_rust_0.1";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TextureSlot {
    Base,
    Normal,
    Material,
    Height,
}

impl TextureSlot {
    pub fn parse(value: &str) -> Self {
        match value.trim().to_ascii_lowercase().as_str() {
            "normal" => Self::Normal,
            "material" | "mask" | "packed" => Self::Material,
            "height" | "disp" | "displacement" => Self::Height,
            _ => Self::Base,
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Self::Base => "base",
            Self::Normal => "normal",
            Self::Material => "material",
            Self::Height => "height",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SrgbMode {
    Auto,
    On,
    Off,
}

impl SrgbMode {
    pub fn parse(value: &str) -> Self {
        match value.trim().to_ascii_lowercase().as_str() {
            "on" | "true" | "srgb" => Self::On,
            "off" | "false" | "linear" => Self::Off,
            _ => Self::Auto,
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Self::Auto => "auto",
            Self::On => "on",
            Self::Off => "off",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NormalSpace {
    Auto,
    DirectX,
    OpenGL,
}

impl NormalSpace {
    pub fn parse(value: &str) -> Self {
        match value.trim().to_ascii_lowercase().as_str() {
            "directx" | "dx" => Self::DirectX,
            "opengl" | "gl" => Self::OpenGL,
            _ => Self::Auto,
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Self::Auto => "auto",
            Self::DirectX => "directx",
            Self::OpenGL => "opengl",
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct ChannelStats {
    pub min: [u8; 4],
    pub max: [u8; 4],
    pub mean: [f32; 4],
    pub alpha_coverage: f32,
    pub luma_min: f32,
    pub luma_max: f32,
    pub luma_mean: f32,
}

#[derive(Debug, Clone, Serialize)]
pub struct NativeTextureReport {
    pub backend: String,
    pub status: String,
    pub source_path: String,
    pub output_path: String,
    pub format: String,
    pub width: u32,
    pub height: u32,
    pub output_width: u32,
    pub output_height: u32,
    pub mip_count: u32,
    pub has_alpha: bool,
    pub colorspace_intent: String,
    pub supported_decode: bool,
    pub slot: String,
    pub srgb: String,
    pub normal_space: String,
    pub likely_normal_space: String,
    pub normal_strength: f32,
    pub scalar_range: [f32; 2],
    pub channel_stats: Option<ChannelStats>,
    pub material_channel_hint: String,
    pub error: String,
}

impl NativeTextureReport {
    fn base(path: &Path) -> Self {
        Self {
            backend: BACKEND_ID.to_string(),
            status: "inspected".to_string(),
            source_path: path.display().to_string(),
            output_path: String::new(),
            format: String::new(),
            width: 0,
            height: 0,
            output_width: 0,
            output_height: 0,
            mip_count: 0,
            has_alpha: false,
            colorspace_intent: "linear".to_string(),
            supported_decode: false,
            slot: "base".to_string(),
            srgb: "auto".to_string(),
            normal_space: "auto".to_string(),
            likely_normal_space: String::new(),
            normal_strength: 0.0,
            scalar_range: [0.0, 0.0],
            channel_stats: None,
            material_channel_hint: String::new(),
            error: String::new(),
        }
    }
}

pub fn read_dds(path: &Path) -> Result<Dds, String> {
    let file = File::open(path).map_err(|error| format!("failed to open DDS: {error}"))?;
    Dds::read(&mut BufReader::new(file)).map_err(|error| format!("failed to parse DDS: {error}"))
}

pub fn inspect_dds(path: &Path) -> NativeTextureReport {
    let mut report = NativeTextureReport::base(path);
    match read_dds(path) {
        Ok(dds) => fill_dds_metadata(&mut report, &dds),
        Err(error) => {
            report.status = "error".to_string();
            report.error = error;
        }
    }
    report
}

pub fn preview_png(
    input_path: &Path,
    output_path: &Path,
    max_dim: u32,
    slot: TextureSlot,
    srgb: SrgbMode,
    normal_space: NormalSpace,
) -> NativeTextureReport {
    let mut report = NativeTextureReport::base(input_path);
    report.output_path = output_path.display().to_string();
    report.slot = slot.as_str().to_string();
    report.srgb = srgb.as_str().to_string();
    report.normal_space = normal_space.as_str().to_string();

    let dds = match read_dds(input_path) {
        Ok(dds) => dds,
        Err(error) => {
            report.status = "error".to_string();
            report.error = error;
            return report;
        }
    };
    fill_dds_metadata(&mut report, &dds);

    let image = match image_dds::image_from_dds(&dds, 0) {
        Ok(image) => image,
        Err(error) => {
            report.status = "unsupported".to_string();
            report.error = format!("Rust DDS decode failed: {error}");
            return report;
        }
    };
    report.supported_decode = true;

    let prepared = prepare_image(image, max_dim, slot, normal_space, &mut report);
    report.output_width = prepared.width();
    report.output_height = prepared.height();
    if let Some(parent) = output_path.parent() {
        if let Err(error) = std::fs::create_dir_all(parent) {
            report.status = "error".to_string();
            report.error = format!("failed to create output directory: {error}");
            return report;
        }
    }
    if let Err(error) = prepared.save(output_path) {
        report.status = "error".to_string();
        report.error = format!("failed to write PNG: {error}");
        return report;
    }
    report.status = "decoded".to_string();
    report
}

fn fill_dds_metadata(report: &mut NativeTextureReport, dds: &Dds) {
    report.width = dds.get_width();
    report.height = dds.get_height();
    report.mip_count = dds.get_num_mipmap_levels().max(1);
    report.format = dds_format_name(dds);
    report.has_alpha = format_has_alpha(&report.format);
    report.colorspace_intent = if report.format.to_ascii_uppercase().contains("SRGB") {
        "srgb".to_string()
    } else {
        "linear".to_string()
    };
    report.supported_decode = image_dds::dds_image_format(dds).is_ok();
}

fn dds_format_name(dds: &Dds) -> String {
    if let Some(format) = dds.get_dxgi_format() {
        return format!("{format:?}");
    }
    if dds.header10.is_some() {
        let dimension = dds
            .header10
            .as_ref()
            .map(|header| header.resource_dimension)
            .unwrap_or(D3D10ResourceDimension::Texture2D);
        return format!("DX10_{dimension:?}");
    }
    "legacy_or_fourcc".to_string()
}

fn format_has_alpha(format: &str) -> bool {
    let upper = format.to_ascii_uppercase();
    upper.contains("RGBA")
        || upper.contains("BGRA")
        || upper.contains("BC1")
        || upper.contains("BC2")
        || upper.contains("BC3")
        || upper.contains("BC7")
        || upper.contains("A8")
}

fn prepare_image(
    image: RgbaImage,
    max_dim: u32,
    slot: TextureSlot,
    normal_space: NormalSpace,
    report: &mut NativeTextureReport,
) -> RgbaImage {
    let mut prepared = maybe_resize(image, max_dim);
    if slot == TextureSlot::Normal {
        let likely_space = infer_normal_space(&prepared);
        report.likely_normal_space = likely_space.to_string();
        if normal_space == NormalSpace::OpenGL
            || (normal_space == NormalSpace::Auto && likely_space == "directx")
        {
            for pixel in prepared.pixels_mut() {
                pixel[1] = 255u8.saturating_sub(pixel[1]);
            }
            report.likely_normal_space = "opengl".to_string();
        }
    }
    let stats = channel_stats(&prepared);
    report.normal_strength = if slot == TextureSlot::Normal {
        normal_strength(&prepared)
    } else {
        0.0
    };
    report.scalar_range = if matches!(slot, TextureSlot::Height | TextureSlot::Material) {
        [stats.luma_min, stats.luma_max]
    } else {
        [0.0, 0.0]
    };
    report.material_channel_hint = if slot == TextureSlot::Material {
        material_hint(&stats)
    } else {
        String::new()
    };
    report.channel_stats = Some(stats);
    prepared
}

fn maybe_resize(image: RgbaImage, max_dim: u32) -> RgbaImage {
    if max_dim == 0 {
        return image;
    }
    let longest = image.width().max(image.height());
    if longest <= max_dim {
        return image;
    }
    let scale = max_dim as f32 / longest as f32;
    let width = ((image.width() as f32 * scale).round() as u32).max(1);
    let height = ((image.height() as f32 * scale).round() as u32).max(1);
    image::imageops::resize(&image, width, height, FilterType::Lanczos3)
}

pub fn channel_stats(image: &RgbaImage) -> ChannelStats {
    let mut min = [255u8; 4];
    let mut max = [0u8; 4];
    let mut sum = [0f64; 4];
    let mut alpha_covered = 0u64;
    let mut luma_min = 1.0f32;
    let mut luma_max = 0.0f32;
    let mut luma_sum = 0.0f64;
    let count = image.width().saturating_mul(image.height()).max(1) as f64;
    for pixel in image.pixels() {
        for channel in 0..4 {
            let value = pixel[channel];
            min[channel] = min[channel].min(value);
            max[channel] = max[channel].max(value);
            sum[channel] += value as f64;
        }
        if pixel[3] >= 128 {
            alpha_covered += 1;
        }
        let luma =
            ((pixel[0] as f32 * 0.2126) + (pixel[1] as f32 * 0.7152) + (pixel[2] as f32 * 0.0722))
                / 255.0;
        luma_min = luma_min.min(luma);
        luma_max = luma_max.max(luma);
        luma_sum += luma as f64;
    }
    ChannelStats {
        min,
        max,
        mean: [
            (sum[0] / count) as f32,
            (sum[1] / count) as f32,
            (sum[2] / count) as f32,
            (sum[3] / count) as f32,
        ],
        alpha_coverage: alpha_covered as f32 / count as f32,
        luma_min,
        luma_max,
        luma_mean: (luma_sum / count) as f32,
    }
}

fn normal_strength(image: &RgbaImage) -> f32 {
    let count = image.width().saturating_mul(image.height()).max(1) as f32;
    let mut sum = 0.0f32;
    for pixel in image.pixels() {
        let x = (pixel[0] as f32 / 255.0) * 2.0 - 1.0;
        let y = (pixel[1] as f32 / 255.0) * 2.0 - 1.0;
        sum += (x * x + y * y).sqrt().min(1.0);
    }
    sum / count
}

fn infer_normal_space(image: &RgbaImage) -> &'static str {
    let count = image.width().saturating_mul(image.height()).max(1) as f32;
    let mut green_sum = 0.0f32;
    for pixel in image.pixels() {
        green_sum += pixel[1] as f32 / 255.0;
    }
    if green_sum / count > 0.54 {
        "directx"
    } else {
        "opengl"
    }
}

fn material_hint(stats: &ChannelStats) -> String {
    let means = stats.mean;
    let dominant = means
        .iter()
        .take(3)
        .enumerate()
        .max_by(|a, b| a.1.partial_cmp(b.1).unwrap_or(std::cmp::Ordering::Equal))
        .map(|(index, _)| index)
        .unwrap_or(0);
    match dominant {
        0 => "red-dominant packed material/mask".to_string(),
        1 => "green-dominant packed material/mask".to_string(),
        2 => "blue-dominant packed material/mask".to_string(),
        _ => "packed material/mask".to_string(),
    }
}

#[allow(dead_code)]
fn _dxgi_name(format: DxgiFormat) -> String {
    format!("{format:?}")
}

#[cfg(test)]
mod tests {
    use super::*;
    use image::Rgba;

    #[test]
    fn channel_stats_reports_alpha_and_luma() {
        let mut image = RgbaImage::new(2, 1);
        image.put_pixel(0, 0, Rgba([0, 128, 255, 255]));
        image.put_pixel(1, 0, Rgba([255, 128, 0, 0]));
        let stats = channel_stats(&image);
        assert_eq!(stats.min, [0, 128, 0, 0]);
        assert_eq!(stats.max, [255, 128, 255, 255]);
        assert!((stats.alpha_coverage - 0.5).abs() < 0.001);
        assert!(stats.luma_max > stats.luma_min);
    }

    #[test]
    fn parses_modes_conservatively() {
        assert_eq!(TextureSlot::parse("normal"), TextureSlot::Normal);
        assert_eq!(TextureSlot::parse("unknown"), TextureSlot::Base);
        assert_eq!(SrgbMode::parse("linear"), SrgbMode::Off);
        assert_eq!(NormalSpace::parse("dx"), NormalSpace::DirectX);
    }
}
