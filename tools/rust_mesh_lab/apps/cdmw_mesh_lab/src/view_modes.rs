//! One list of view modes for every viewport (P4 V3).
//!
//! Browse's preview and the Mesh Editor draw with the same renderer, so they
//! offer the same modes, stored once by CDMW as `preview/view_mode`. The ids
//! match `cdmw/domain/preview_view_modes.py`. "Island colors" is Part ID with
//! the editor's mesh islands; a viewport without islands draws part colours.

use cdmw_render_wgpu::ViewMode;

/// (id, mode, label, islands), in menu order.
pub(crate) const SHARED_VIEW_MODES: [(&str, ViewMode, &str, bool); 16] = [
    (
        "textured",
        ViewMode::TexturedSolid,
        "Solid (Textured)",
        false,
    ),
    (
        "game_outdoor",
        ViewMode::GameOutdoor,
        "Game Outdoor Approx",
        false,
    ),
    ("base_color", ViewMode::BaseColor, "Base Color", false),
    ("normal_map", ViewMode::NormalMap, "Normals", false),
    ("uv_checker", ViewMode::UvChecker, "UV Checker", false),
    ("base_alpha", ViewMode::BaseAlpha, "Alpha", false),
    ("part_colors", ViewMode::PartId, "Part colors", false),
    ("island_colors", ViewMode::PartId, "Island colors", true),
    (
        "material_response",
        ViewMode::MaterialResponse,
        "Material Response",
        false,
    ),
    ("layer_mask", ViewMode::LayerMask, "Layer Mask", false),
    ("faces", ViewMode::Solid, "Faces (No Textures)", false),
    ("faces_wire", ViewMode::SolidWire, "Faces + Wire", false),
    ("wire", ViewMode::Wireframe, "Wire", false),
    ("vertices", ViewMode::Vertices, "Vertices", false),
    (
        "wire_vertices",
        ViewMode::WireVertices,
        "Wire + Vertices",
        false,
    ),
    ("xray", ViewMode::XRay, "X-Ray", false),
];

/// The mode and whether it colours islands, for a shared id.
pub(crate) fn from_shared_id(id: &str) -> Option<(ViewMode, bool)> {
    SHARED_VIEW_MODES
        .iter()
        .find(|(candidate, ..)| *candidate == id)
        .map(|(_, mode, _, islands)| (*mode, *islands))
}

/// The shared id of a mode.
pub(crate) fn shared_id(mode: ViewMode, islands: bool) -> &'static str {
    SHARED_VIEW_MODES
        .iter()
        .find(|(_, candidate, _, candidate_islands)| {
            *candidate == mode && (mode != ViewMode::PartId || *candidate_islands == islands)
        })
        .map_or("textured", |(id, ..)| *id)
}

/// `#RRGGBB` for a background colour, as CDMW stores it.
pub(crate) fn hex_colour(colour: [u8; 3]) -> String {
    format!("#{:02X}{:02X}{:02X}", colour[0], colour[1], colour[2])
}

/// The colour of `#RRGGBB` (or `RRGGBB`).
pub(crate) fn parse_hex_colour(text: &str) -> Option<[u8; 3]> {
    let digits = text.trim().trim_start_matches('#');
    if digits.len() != 6 || !digits.chars().all(|c| c.is_ascii_hexdigit()) {
        return None;
    }
    let channel = |start: usize| u8::from_str_radix(&digits[start..start + 2], 16).ok();
    Some([channel(0)?, channel(2)?, channel(4)?])
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_id_round_trips_and_the_list_is_the_union_of_both_viewports() {
        for (id, mode, _, islands) in SHARED_VIEW_MODES {
            assert_eq!(from_shared_id(id), Some((mode, islands)));
            assert_eq!(shared_id(mode, islands), id);
        }
        // Browse's diagnostics and the editor's geometry modes are both offered.
        for mode in [
            ViewMode::GameOutdoor,
            ViewMode::NormalMap,
            ViewMode::LayerMask,
            ViewMode::Wireframe,
            ViewMode::XRay,
        ] {
            assert!(SHARED_VIEW_MODES.iter().any(|(_, m, ..)| *m == mode));
        }
        assert_eq!(
            from_shared_id("lit"),
            None,
            "CDMW migrates old ids before sending them"
        );
    }

    #[test]
    fn background_colours_round_trip_as_hex() {
        assert_eq!(parse_hex_colour("#3B3B3B"), Some([0x3B, 0x3B, 0x3B]));
        assert_eq!(parse_hex_colour("0a0b0c"), Some([10, 11, 12]));
        assert_eq!(parse_hex_colour("#12345"), None);
        assert_eq!(hex_colour([6, 8, 10]), "#06080A");
    }
}
