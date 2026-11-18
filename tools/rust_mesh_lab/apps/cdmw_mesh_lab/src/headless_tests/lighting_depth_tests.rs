use super::*;
use cdmw_render_wgpu::{HeadlessMaterialCaptureCamera, LightingDepthSettings, LightingPreset};
use cdmw_texture::TextureRole;

#[test]
#[ignore = "requires a D3D12 adapter"]
fn offscreen_shadow_and_ambient_depth_preserve_diagnostics() -> TestResult {
    verify_depth(LightingPreset::NeutralStudio)
}

#[test]
#[ignore = "requires a D3D12 adapter"]
fn offscreen_fixed_studio_depth_preserves_diagnostics() -> TestResult {
    verify_depth(LightingPreset::StudioFixed)
}

#[test]
#[ignore = "requires a D3D12 adapter"]
fn offscreen_all_hidden_parts_keep_lighting_depth_background() -> TestResult {
    let mut snapshot = triangle_application()?
        .mesh
        .as_ref()
        .unwrap()
        .draw_snapshot();
    snapshot.positions.clear();
    snapshot.normals.clear();
    snapshot.uvs.clear();
    snapshot.shader_masks.clear();
    snapshot.indices.clear();
    snapshot.triangle_materials.clear();
    snapshot.selected_vertices.clear();
    let folder = tempdir()?;
    for preset in [LightingPreset::NeutralStudio, LightingPreset::StudioFixed] {
        let lit = folder.path().join("empty-lit.bmp");
        let base = folder.path().join("empty-base.bmp");
        let parts = folder.path().join("empty-parts.bmp");
        let result = pollster::block_on(
            cdmw_render_wgpu::run_headless_layered_material_capture_with_lighting(
                &snapshot,
                &[],
                &[],
                &[],
                preset,
                LightingDepthSettings::default(),
                HeadlessMaterialCaptureOptions {
                    width: 64,
                    height: 64,
                    ..Default::default()
                },
                HeadlessMaterialCaptureOutput {
                    textured_bmp: &lit,
                    base_color_bmp: &base,
                    part_id_bmp: &parts,
                    normal_map: None,
                    material_response: None,
                    layer_mask: None,
                },
            ),
        );
        // Capture validation intentionally rejects a blank model after rendering
        // and writing its images. GPU errors and panics must not reach this check.
        assert!(
            matches!(result, Err(cdmw_render_wgpu::RenderError::Device(message))
            if message == "material capture contained only the clear color")
        );
        for path in [lit, base, parts] {
            let image = std::fs::read(path)?;
            let pixels = &image[54..];
            assert_eq!(pixels.len(), 64 * 64 * 4);
            let background = &pixels[..4];
            assert_eq!(background[3], 255);
            assert!(pixels.chunks_exact(4).all(|pixel| pixel == background));
        }
    }
    Ok(())
}

fn verify_depth(preset: LightingPreset) -> TestResult {
    let mut snapshot = triangle_application()?
        .mesh
        .as_ref()
        .unwrap()
        .draw_snapshot();
    snapshot.positions.clear();
    snapshot.normals.clear();
    snapshot.uvs.clear();
    snapshot.shader_masks.clear();
    snapshot.indices.clear();
    snapshot.triangle_materials.clear();
    let mut quad = |corners: [[f32; 3]; 4], normal: [f32; 3], material: u32| {
        let start = snapshot.positions.len() as u32;
        snapshot.positions.extend(corners);
        snapshot.normals.extend([normal; 4]);
        snapshot.uvs.extend([[0.5, 0.5]; 4]);
        snapshot.shader_masks.extend([[1.0, 1.0, 0.0]; 4]);
        snapshot
            .indices
            .extend([0, 1, 2, 0, 2, 3].map(|i| i + start));
        snapshot.triangle_materials.extend([material; 2]);
    };
    quad(
        [
            [-2.0, -0.5, 2.0],
            [2.0, -0.5, 2.0],
            [2.0, -0.5, -2.0],
            [-2.0, -0.5, -2.0],
        ],
        [0.0, 1.0, 0.0],
        0,
    );
    quad(
        [
            [-0.4, -0.5, 0.4],
            [0.4, -0.5, 0.4],
            [0.4, 0.5, 0.4],
            [-0.4, 0.5, 0.4],
        ],
        [0.0, 0.0, 1.0],
        1,
    );
    quad(
        [
            [0.4, -0.5, -0.4],
            [-0.4, -0.5, -0.4],
            [-0.4, 0.5, -0.4],
            [0.4, 0.5, -0.4],
        ],
        [0.0, 0.0, -1.0],
        1,
    );
    quad(
        [
            [-0.4, -0.5, -0.4],
            [-0.4, -0.5, 0.4],
            [-0.4, 0.5, 0.4],
            [-0.4, 0.5, -0.4],
        ],
        [-1.0, 0.0, 0.0],
        1,
    );
    quad(
        [
            [0.4, -0.5, 0.4],
            [0.4, -0.5, -0.4],
            [0.4, 0.5, -0.4],
            [0.4, 0.5, 0.4],
        ],
        [1.0, 0.0, 0.0],
        1,
    );
    quad(
        [
            [-0.4, 0.5, 0.4],
            [0.4, 0.5, 0.4],
            [0.4, 0.5, -0.4],
            [-0.4, 0.5, -0.4],
        ],
        [0.0, 1.0, 0.0],
        1,
    );
    let floor =
        cdmw_texture::encode_rgba8_dds(1, 1, &[190, 190, 190, 255], TextureRole::BaseColor)?;
    let cube = cdmw_texture::encode_rgba8_dds(1, 1, &[190, 50, 50, 255], TextureRole::BaseColor)?;
    let floor_owner = [vec![0]];
    let cube_owner = [vec![1]];
    let textures = [
        HeadlessMaterialTexture {
            bytes: &floor,
            role: TextureRole::BaseColor,
            material_indices_by_lod: &floor_owner,
        },
        HeadlessMaterialTexture {
            bytes: &cube,
            role: TextureRole::BaseColor,
            material_indices_by_lod: &cube_owner,
        },
    ];
    let temporary = tempdir()?;
    let folder = std::env::var_os("CDMW_DEPTH_TEST_OUTPUT")
        .map(PathBuf::from)
        .unwrap_or_else(|| temporary.path().to_owned());
    std::fs::create_dir_all(&folder)?;
    let mut frames = Vec::new();
    let mut diagnostic_reference = None;
    let mut ground_mask = Vec::new();
    for (name, shadows, ambient_occlusion) in [
        ("off", false, false),
        ("shadow", true, false),
        ("ambient", false, true),
    ] {
        let lit = folder.join(format!("{name}-lit.bmp"));
        let base = folder.join(format!("{name}-base.bmp"));
        let parts = folder.join(format!("{name}-parts.bmp"));
        pollster::block_on(
            cdmw_render_wgpu::run_headless_layered_material_capture_with_lighting(
                &snapshot,
                &textures,
                &[],
                &[],
                preset,
                LightingDepthSettings {
                    shadows,
                    ambient_occlusion,
                },
                HeadlessMaterialCaptureOptions {
                    width: 256,
                    height: 256,
                    camera: Some(HeadlessMaterialCaptureCamera {
                        yaw_degrees: 0.0,
                        pitch_degrees: -30.0,
                    }),
                    ..Default::default()
                },
                HeadlessMaterialCaptureOutput {
                    textured_bmp: &lit,
                    base_color_bmp: &base,
                    part_id_bmp: &parts,
                    normal_map: None,
                    material_response: None,
                    layer_mask: None,
                },
            ),
        )?;
        let base = std::fs::read(base)?;
        let diagnostics = (base.clone(), std::fs::read(parts)?);
        if let Some(reference) = &diagnostic_reference {
            assert_eq!(
                reference, &diagnostics,
                "unlit diagnostics changed with {name}"
            );
        } else {
            ground_mask = base[54..]
                .chunks_exact(4)
                .map(|p| {
                    p[0].abs_diff(190) <= 1 && p[1].abs_diff(190) <= 1 && p[2].abs_diff(190) <= 1
                })
                .collect();
            diagnostic_reference = Some(diagnostics);
        }
        frames.push(std::fs::read(lit)?);
    }
    for (index, label) in [
        (1, "box shadow on plane"),
        (2, "ambient occlusion in concave contact corner"),
    ] {
        let mut darker = 0;
        let mut unchanged = 0;
        for ((before, after), ground) in frames[0][54..]
            .chunks_exact(4)
            .zip(frames[index][54..].chunks_exact(4))
            .zip(&ground_mask)
        {
            if !ground {
                continue;
            }
            let a = before[..3].iter().map(|v| u32::from(*v)).sum::<u32>();
            let b = after[..3].iter().map(|v| u32::from(*v)).sum::<u32>();
            if a > b + 6 {
                darker += 1;
            }
            if a.abs_diff(b) <= 1 {
                unchanged += 1;
            }
            assert_eq!(before[3], after[3], "alpha changed");
        }
        eprintln!("{label}: {darker} darkened plane pixels, {unchanged} unchanged plane pixels");
        assert!(darker > 20, "{label} was absent");
        assert!(unchanged > 100, "{label} affected the whole plane");
    }
    let empty_cube =
        cdmw_texture::encode_rgba8_dds(1, 1, &[190, 50, 50, 0], TextureRole::BaseColor)?;
    for (name, bytes, factors) in [
        (
            "cutout",
            empty_cube.as_slice(),
            MaterialPreviewFactors {
                alpha_cutoff: Some(0.5),
                ..Default::default()
            },
        ),
        (
            "blended",
            cube.as_slice(),
            MaterialPreviewFactors {
                alpha_blend: Some(true),
                opacity: Some(0.5),
                ..Default::default()
            },
        ),
        (
            "glass",
            cube.as_slice(),
            MaterialPreviewFactors {
                translucency: Some([0.5, 0.5]),
                ..Default::default()
            },
        ),
    ] {
        let textures = [
            textures[0],
            HeadlessMaterialTexture {
                bytes,
                role: TextureRole::BaseColor,
                material_indices_by_lod: &cube_owner,
            },
        ];
        let factors = [cdmw_render_wgpu::HeadlessMaterialFactors {
            factors,
            material_indices_by_lod: &cube_owner,
        }];
        let mut reference: Option<Vec<u8>> = None;
        for shadows in [false, true] {
            let lit = folder.join(format!("{name}-{shadows}.bmp"));
            pollster::block_on(
                cdmw_render_wgpu::run_headless_layered_material_capture_with_lighting(
                    &snapshot,
                    &textures,
                    &factors,
                    &[],
                    preset,
                    LightingDepthSettings {
                        shadows,
                        ambient_occlusion: false,
                    },
                    HeadlessMaterialCaptureOptions {
                        width: 256,
                        height: 256,
                        camera: Some(HeadlessMaterialCaptureCamera {
                            yaw_degrees: 0.0,
                            pitch_degrees: -30.0,
                        }),
                        ..Default::default()
                    },
                    HeadlessMaterialCaptureOutput {
                        textured_bmp: &lit,
                        base_color_bmp: &folder.join(format!("{name}-base.bmp")),
                        part_id_bmp: &folder.join(format!("{name}-parts.bmp")),
                        normal_map: None,
                        material_response: None,
                        layer_mask: None,
                    },
                ),
            )?;
            let frame = std::fs::read(lit)?;
            if let Some(reference) = &reference {
                // Blended/glass surfaces can receive the plane's shadow. Only
                // the plane outside their projected coverage must stay lit.
                let base = std::fs::read(folder.join(format!("{name}-base.bmp")))?;
                let changed = reference[54..]
                    .chunks_exact(4)
                    .zip(frame[54..].chunks_exact(4))
                    .zip(base[54..].chunks_exact(4))
                    .filter(|((a, b), base)| {
                        a != b && base[..3].iter().all(|v| v.abs_diff(190) <= 1)
                    })
                    .count();
                assert_eq!(
                    changed, 0,
                    "{name} must not cast opaque shadows on the plane"
                );
            } else {
                reference = Some(frame);
            }
        }
    }
    if preset == LightingPreset::NeutralStudio {
        let compatibility_cases = pollster::block_on(
            cdmw_render_wgpu::verify_lighting_depth_compatibility(&snapshot),
        )?;
        assert!(compatibility_cases > 0);
        eprintln!("Verified {compatibility_cases} orthographic/MSAA/texture-limit combinations");
    }
    Ok(())
}

/// A part classed metal carried the class's scalar floor on every texel: metal at
/// least 0.56, roughness pulled towards 0.32, a raised specular colour. With its
/// own surface map the map alone decides, as in the game, so a leather strap the
/// map marks rough and not metal draws so. A metal part without a map keeps the
/// floor, and another class is untouched.
#[test]
#[ignore = "requires a D3D12 adapter"]
fn offscreen_metal_class_floor_yields_to_the_parts_surface_map() -> TestResult {
    let mut snapshot = triangle_application()?
        .mesh
        .as_ref()
        .unwrap()
        .draw_snapshot();
    snapshot.positions = vec![
        [-1.0, -1.0, 0.0],
        [1.0, -1.0, 0.0],
        [1.0, 1.0, 0.0],
        [-1.0, 1.0, 0.0],
    ];
    snapshot.normals = vec![[0.0, 0.0, 1.0]; 4];
    snapshot.uvs = vec![[0.5, 0.5]; 4];
    snapshot.shader_masks = vec![[1.0, 1.0, 0.0]; 4];
    snapshot.indices = vec![0, 1, 2, 0, 2, 3];
    snapshot.triangle_materials = vec![0, 0];
    let owner = [vec![0]];
    let leather = cdmw_texture::encode_rgba8_dds(1, 1, &[96, 64, 40, 255], TextureRole::BaseColor)?;
    // The strap in the part's packed map: roughness 200/255, metal 0.
    let strap = cdmw_texture::encode_rgba8_dds(1, 1, &[255, 200, 0, 255], TextureRole::Material)?;
    let folder = tempdir()?;
    let response_of = |name: &str,
                       category: u32,
                       with_map: bool|
     -> Result<[u8; 3], Box<dyn std::error::Error>> {
        let mut textures = vec![HeadlessMaterialTexture {
            bytes: &leather,
            role: TextureRole::BaseColor,
            material_indices_by_lod: &owner,
        }];
        if with_map {
            textures.push(HeadlessMaterialTexture {
                bytes: &strap,
                role: TextureRole::Material,
                material_indices_by_lod: &owner,
            });
        }
        // The scalars Preview Core states for a part classed metal.
        let factors = [HeadlessMaterialFactors {
            factors: MaterialPreviewFactors {
                roughness: Some(0.24),
                metalness: Some(0.68),
                specular: Some(0.68),
                category_code: Some(category),
                category_confidence: Some(1.0),
                ..MaterialPreviewFactors::default()
            },
            material_indices_by_lod: &owner,
        }];
        let response = folder.path().join(format!("{name}-response.bmp"));
        pollster::block_on(cdmw_render_wgpu::run_headless_layered_material_capture(
            &snapshot,
            &textures,
            &factors,
            &[],
            HeadlessMaterialCaptureOptions {
                width: 64,
                height: 64,
                ..Default::default()
            },
            HeadlessMaterialCaptureOutput {
                textured_bmp: &folder.path().join(format!("{name}-lit.bmp")),
                base_color_bmp: &folder.path().join(format!("{name}-base.bmp")),
                part_id_bmp: &folder.path().join(format!("{name}-parts.bmp")),
                normal_map: None,
                material_response: Some(&response),
                layer_mask: None,
            },
        ))?;
        let bytes = std::fs::read(response)?;
        let pixel = &bytes[54 + (32 * 64 + 32) * 4..][..4];
        // The response picture is metal, roughness and the specular colour's peak.
        Ok([pixel[2], pixel[1], pixel[0]])
    };
    const METAL: u32 = 1;
    let [metal, roughness, specular] = response_of("metal-with-map", METAL, true)?;
    assert!(metal <= 3, "the map says not metal; drawn metal {metal}");
    assert!(
        roughness.abs_diff(200) <= 3,
        "the map says roughness 200; drawn {roughness}"
    );
    assert!(
        specular <= 80,
        "a non-metal texel keeps a dielectric specular colour; drawn {specular}"
    );
    let [metal, roughness, _] = response_of("metal-without-map", METAL, false)?;
    assert!(
        metal >= 150,
        "a metal part without a map keeps the floor; drawn metal {metal}"
    );
    assert!(roughness <= 120, "and stays smooth; drawn {roughness}");
    // Another class never had the floor: its scalars still meet its map as before.
    let cloth = response_of("cloth-with-map", 4, true)?;
    assert!(
        cloth[0] >= 150 && cloth[1] < 197,
        "a class other than metal is untouched; drawn {cloth:?}"
    );
    Ok(())
}

/// The game's hair dye (PSMainHairStandard, permutation 75b7a093c17d73a3):
/// `_hairDyeingColor` is overlaid in display space on the base texture greyed
/// 80%, and mixed in by the colour's alpha; the brightest channel is capped at
/// 0.8. A mid-grey strand dyed `#d2bb60ff` (the buffalo mask's mane) is that
/// gold. The hue bias this replaces kept the strand near grey, and the package
/// stated the dye's strength as 0, which multiplied the texture by the colour.
#[test]
#[ignore = "requires a D3D12 adapter"]
fn offscreen_hair_dye_overlays_the_colour_on_the_greyed_texture() -> TestResult {
    let mut snapshot = triangle_application()?
        .mesh
        .as_ref()
        .unwrap()
        .draw_snapshot();
    snapshot.positions = vec![
        [-1.0, -1.0, 0.0],
        [1.0, -1.0, 0.0],
        [1.0, 1.0, 0.0],
        [-1.0, 1.0, 0.0],
    ];
    snapshot.normals = vec![[0.0, 0.0, 1.0]; 4];
    snapshot.uvs = vec![[0.5, 0.5]; 4];
    snapshot.shader_masks = vec![[1.0, 1.0, 0.0]; 4];
    snapshot.indices = vec![0, 1, 2, 0, 2, 3];
    snapshot.triangle_materials = vec![0, 0];
    let owner = [vec![0]];
    let folder = tempdir()?;
    const HAIR: u32 = 6;
    let base_colour_of = |name: &str,
                          strand: [u8; 3],
                          dye: [f32; 3],
                          alpha: f32|
     -> Result<[u8; 3], Box<dyn std::error::Error>> {
        let texture = cdmw_texture::encode_rgba8_dds(
            1,
            1,
            &[strand[0], strand[1], strand[2], 255],
            TextureRole::BaseColor,
        )?;
        let textures = [HeadlessMaterialTexture {
            bytes: &texture,
            role: TextureRole::BaseColor,
            material_indices_by_lod: &owner,
        }];
        let factors = [HeadlessMaterialFactors {
            factors: MaterialPreviewFactors {
                texture_tint: Some(dye),
                base_tint_strength: Some(alpha),
                category_code: Some(HAIR),
                category_confidence: Some(1.0),
                ..MaterialPreviewFactors::default()
            },
            material_indices_by_lod: &owner,
        }];
        let base = folder.path().join(format!("{name}-base.bmp"));
        pollster::block_on(cdmw_render_wgpu::run_headless_layered_material_capture(
            &snapshot,
            &textures,
            &factors,
            &[],
            HeadlessMaterialCaptureOptions {
                width: 64,
                height: 64,
                ..Default::default()
            },
            HeadlessMaterialCaptureOutput {
                textured_bmp: &folder.path().join(format!("{name}-lit.bmp")),
                base_color_bmp: &base,
                part_id_bmp: &folder.path().join(format!("{name}-parts.bmp")),
                normal_map: None,
                material_response: None,
                layer_mask: None,
            },
        ))?;
        let bytes = std::fs::read(base)?;
        let pixel = &bytes[54 + (32 * 64 + 32) * 4..][..4];
        Ok([pixel[2], pixel[1], pixel[0]])
    };
    let near = |drawn: [u8; 3], expected: [u8; 3]| {
        drawn
            .iter()
            .zip(expected)
            .all(|(value, wanted)| value.abs_diff(wanted) <= 3)
    };
    let gold = [210.0 / 255.0, 187.0 / 255.0, 96.0 / 255.0];
    // Grey 128 is above the overlay's midpoint: 1 - 2 (1 - 0.502) (1 - c).
    let dyed = base_colour_of("gold", [128, 128, 128], gold, 1.0)?;
    assert!(
        near(dyed, [210, 187, 97]),
        "a mid-grey strand takes the dye's colour whole; drawn {dyed:?}"
    );
    // Below the midpoint the overlay multiplies: 2 * 0.251 * c.
    let dark = base_colour_of("dark", [64, 64, 64], gold, 1.0)?;
    assert!(
        near(dark, [105, 94, 48]),
        "a dark strand stays dark in the dye's hue; drawn {dark:?}"
    );
    // The texture's own colour is greyed 80% first, so a red strand dyed black
    // is black, not dark red.
    let black = base_colour_of("black", [160, 40, 40], [0.0, 0.0, 0.0], 1.0)?;
    assert!(
        black.iter().all(|value| *value <= 3),
        "black dye draws black; drawn {black:?}"
    );
    // The dye's alpha mixes texture and dyed colour in linear light.
    let half = base_colour_of("half", [128, 128, 128], gold, 0.5)?;
    assert!(
        near(half, [175, 162, 114]),
        "half the alpha is half way between strand and dye; drawn {half:?}"
    );
    // No cap: the game's 0.8 cap on the brightest channel belongs to the
    // buff overlay only, so white dye on a near-white strand draws white.
    let white = base_colour_of("white", [250, 250, 250], [1.0, 1.0, 1.0], 1.0)?;
    assert!(
        white.iter().all(|value| *value >= 252),
        "hair albedo is not capped at 0.8; drawn {white:?}"
    );
    Ok(())
}

/// A polished conductor has no diffuse term: away from the highlights its colour
/// is its reflectance times the room. Mid-grey steel (the Ver2 plate layer:
/// roughness 0.18, metal 1) facing the camera used to draw near-black navy.
#[test]
#[ignore = "requires a D3D12 adapter"]
fn offscreen_fixed_studio_polished_steel_reflects_a_lit_room() -> TestResult {
    let mut snapshot = triangle_application()?
        .mesh
        .as_ref()
        .unwrap()
        .draw_snapshot();
    snapshot.positions.clear();
    snapshot.normals.clear();
    snapshot.uvs.clear();
    snapshot.shader_masks.clear();
    snapshot.indices.clear();
    snapshot.triangle_materials.clear();
    // One plate towards each side, so the test does not depend on the camera's side.
    for (z, facing) in [(0.01_f32, 1.0_f32), (-0.01, -1.0)] {
        let start = snapshot.positions.len() as u32;
        snapshot.positions.extend([
            [-facing, -1.0, z],
            [facing, -1.0, z],
            [facing, 1.0, z],
            [-facing, 1.0, z],
        ]);
        snapshot.normals.extend([[0.0, 0.0, facing]; 4]);
        snapshot.uvs.extend([[0.5, 0.5]; 4]);
        snapshot.shader_masks.extend([[1.0, 1.0, 0.0]; 4]);
        snapshot
            .indices
            .extend([0, 1, 2, 0, 2, 3].map(|i| i + start));
        snapshot.triangle_materials.extend([0; 2]);
    }
    let steel =
        cdmw_texture::encode_rgba8_dds(1, 1, &[128, 128, 128, 255], TextureRole::BaseColor)?;
    let owner = [vec![0]];
    let textures = [HeadlessMaterialTexture {
        bytes: &steel,
        role: TextureRole::BaseColor,
        material_indices_by_lod: &owner,
    }];
    let factors = [HeadlessMaterialFactors {
        factors: MaterialPreviewFactors {
            translucency_surface: Some([Some(0.18), Some(1.0)]),
            ..MaterialPreviewFactors::default()
        },
        material_indices_by_lod: &owner,
    }];
    let folder = tempdir()?;
    let lit = folder.path().join("steel-lit.bmp");
    let base = folder.path().join("steel-base.bmp");
    let parts = folder.path().join("steel-parts.bmp");
    pollster::block_on(
        cdmw_render_wgpu::run_headless_layered_material_capture_with_lighting(
            &snapshot,
            &textures,
            &factors,
            &[],
            LightingPreset::StudioFixed,
            LightingDepthSettings {
                shadows: false,
                ambient_occlusion: false,
            },
            HeadlessMaterialCaptureOptions {
                width: 64,
                height: 64,
                camera: Some(HeadlessMaterialCaptureCamera {
                    yaw_degrees: 0.0,
                    pitch_degrees: 0.0,
                }),
                ..Default::default()
            },
            HeadlessMaterialCaptureOutput {
                textured_bmp: &lit,
                base_color_bmp: &base,
                part_id_bmp: &parts,
                normal_map: None,
                material_response: None,
                layer_mask: None,
            },
        ),
    )?;
    let image = std::fs::read(lit)?;
    let centre = 54 + (32 * 64 + 32) * 4;
    let (blue, green, red) = (
        i32::from(image[centre]),
        i32::from(image[centre + 1]),
        i32::from(image[centre + 2]),
    );
    // Reflectance 0.216 of a room at about 0.66 radiance, at the preset's 0.7
    // environment scale: about (85, 86, 88) on screen. It was (55, 58, 62).
    for channel in [red, green, blue] {
        assert!(
            (76..=100).contains(&channel),
            "steel centre is ({red}, {green}, {blue})"
        );
    }
    assert!(
        blue - red <= 5,
        "steel centre is tinted blue: ({red}, {green}, {blue})"
    );
    Ok(())
}

/// Draws a square plate, one face towards each side, with one flat material, and
/// returns the (red, green, blue) level at the centre of a 64 px capture.
fn plate_centre(
    colour: [u8; 3],
    roughness: f32,
    metalness: f32,
    preset: LightingPreset,
    yaw_degrees: f32,
) -> Result<(i32, i32, i32), Box<dyn std::error::Error>> {
    plate_centre_of(colour, roughness, metalness, None, preset, yaw_degrees)
}

/// `plate_centre` for a material of a given category code (10 is an eye).
fn plate_centre_of(
    colour: [u8; 3],
    roughness: f32,
    metalness: f32,
    category_code: Option<u32>,
    preset: LightingPreset,
    yaw_degrees: f32,
) -> Result<(i32, i32, i32), Box<dyn std::error::Error>> {
    let mut snapshot = triangle_application()?
        .mesh
        .as_ref()
        .unwrap()
        .draw_snapshot();
    snapshot.positions.clear();
    snapshot.normals.clear();
    snapshot.uvs.clear();
    snapshot.shader_masks.clear();
    snapshot.indices.clear();
    snapshot.triangle_materials.clear();
    for (z, facing) in [(0.01_f32, 1.0_f32), (-0.01, -1.0)] {
        let start = snapshot.positions.len() as u32;
        snapshot.positions.extend([
            [-facing, -1.0, z],
            [facing, -1.0, z],
            [facing, 1.0, z],
            [-facing, 1.0, z],
        ]);
        snapshot.normals.extend([[0.0, 0.0, facing]; 4]);
        snapshot.uvs.extend([[0.5, 0.5]; 4]);
        snapshot.shader_masks.extend([[1.0, 1.0, 0.0]; 4]);
        snapshot
            .indices
            .extend([0, 1, 2, 0, 2, 3].map(|i| i + start));
        snapshot.triangle_materials.extend([0; 2]);
    }
    let [red, green, blue] = colour;
    let texture =
        cdmw_texture::encode_rgba8_dds(1, 1, &[red, green, blue, 255], TextureRole::BaseColor)?;
    let owner = [vec![0]];
    let textures = [HeadlessMaterialTexture {
        bytes: &texture,
        role: TextureRole::BaseColor,
        material_indices_by_lod: &owner,
    }];
    let factors = [HeadlessMaterialFactors {
        factors: MaterialPreviewFactors {
            translucency_surface: Some([Some(roughness), Some(metalness)]),
            category_code,
            category_confidence: category_code.map(|_| 1.0),
            ..MaterialPreviewFactors::default()
        },
        material_indices_by_lod: &owner,
    }];
    let folder = tempdir()?;
    let lit = folder.path().join("plate-lit.bmp");
    let base = folder.path().join("plate-base.bmp");
    let parts = folder.path().join("plate-parts.bmp");
    pollster::block_on(
        cdmw_render_wgpu::run_headless_layered_material_capture_with_lighting(
            &snapshot,
            &textures,
            &factors,
            &[],
            preset,
            LightingDepthSettings {
                shadows: false,
                ambient_occlusion: false,
            },
            HeadlessMaterialCaptureOptions {
                width: 64,
                height: 64,
                camera: Some(HeadlessMaterialCaptureCamera {
                    yaw_degrees,
                    pitch_degrees: 0.0,
                }),
                ..Default::default()
            },
            HeadlessMaterialCaptureOutput {
                textured_bmp: &lit,
                base_color_bmp: &base,
                part_id_bmp: &parts,
                normal_map: None,
                material_response: None,
                layer_mask: None,
            },
        ),
    )?;
    let image = std::fs::read(lit)?;
    let centre = 54 + (32 * 64 + 32) * 4;
    Ok((
        i32::from(image[centre + 2]),
        i32::from(image[centre + 1]),
        i32::from(image[centre]),
    ))
}

/// A rough, non-metal card seen almost edge-on keeps its own colour. The fixed
/// studio's grazing term used to reflect the room at 1 - roughness there, which
/// washed red feather and hair cards towards grey-white as the view turned: on
/// this dark red card the green level rose from 40 at 80 degrees to 54 at 88.5.
#[test]
#[ignore = "requires a D3D12 adapter"]
fn offscreen_fixed_studio_rough_card_keeps_its_colour_at_a_grazing_angle() -> TestResult {
    let preset = LightingPreset::StudioFixed;
    let turned = plate_centre([150, 3, 3], 0.8, 0.0, preset, 80.0)?;
    let edge_on = plate_centre([150, 3, 3], 0.8, 0.0, preset, 88.5)?;
    for (red, green, blue) in [turned, edge_on] {
        assert!(
            red >= 100 && green <= 40 && blue <= 42,
            "red card is ({red}, {green}, {blue})"
        );
    }
    assert!(
        edge_on.1 - turned.1 <= 6,
        "the card greys as it turns edge-on: {turned:?} then {edge_on:?}"
    );
    Ok(())
}

/// Game icon studio: one room lights the metal and the cloth beside it. Steel
/// facing the camera mirrors the room and the edge of the key box, brighter
/// than under the fixed studio and neutral. White cloth is brighter than the
/// steel's body, the lights follow the camera, and a rough red card keeps its
/// colour at a grazing angle.
#[test]
#[ignore = "requires a D3D12 adapter"]
fn offscreen_icon_studio_lights_steel_and_cloth_from_one_room() -> TestResult {
    let preset = LightingPreset::IconStudio;
    let (red, green, blue) = plate_centre([128, 128, 128], 0.18, 1.0, preset, 0.0)?;
    let fixed = plate_centre([128, 128, 128], 0.18, 1.0, LightingPreset::StudioFixed, 0.0)?;
    assert!(
        (160..=205).contains(&green) && green >= fixed.1 + 18,
        "steel is ({red}, {green}, {blue}); fixed studio draws {fixed:?}"
    );
    assert!(
        (red - blue).abs() <= 6 && (red - green).abs() <= 6,
        "steel is tinted: ({red}, {green}, {blue})"
    );
    let cloth = plate_centre([200, 200, 200], 0.9, 0.0, preset, 0.0)?;
    assert!(
        cloth.1 >= green + 8 && cloth.1 <= 252,
        "white cloth is {cloth:?} beside steel at {green}"
    );
    // The boxes turn with the camera: the plate's two faces, seen from opposite
    // sides at the same angle, are lit alike. (Offscreen captures fill in only the
    // view direction of the camera's basis, so the studio derives the rest.)
    let one_side = plate_centre([128, 128, 128], 0.18, 1.0, preset, 30.0)?;
    let other_side = plate_centre([128, 128, 128], 0.18, 1.0, preset, 210.0)?;
    assert!(
        (one_side.1 - other_side.1).abs() <= 3,
        "the studio does not follow the camera: {one_side:?} against {other_side:?}"
    );
    for yaw in [60.0, 75.0, 82.0] {
        let (red, green, blue) = plate_centre([200, 16, 16], 0.8, 0.0, preset, yaw)?;
        assert!(
            red >= 40 && green * 3 <= red && blue * 3 <= red,
            "red card at yaw {yaw} is ({red}, {green}, {blue})"
        );
    }
    Ok(())
}

const PUPIL_LIMIT: i32 = 76;

/// A soft box has no edge, so on a mirror-smooth eyeball it would lie as a grey
/// veil over the pupil. An eye takes about a third of the studio's reflection:
/// a black, glossy eye surface facing the camera stays dark.
#[test]
#[ignore = "requires a D3D12 adapter"]
fn offscreen_icon_studio_keeps_a_pupil_dark() -> TestResult {
    let preset = LightingPreset::IconStudio;
    let plain = plate_centre_of([2, 2, 2], 0.1, 0.0, None, preset, 0.0)?;
    let eye = plate_centre_of([2, 2, 2], 0.1, 0.0, Some(10), preset, 0.0)?;
    assert!(
        eye.1 <= PUPIL_LIMIT && eye.1 + 20 <= plain.1,
        "a black eye surface is {eye:?}; the same surface uncategorised is {plain:?}"
    );
    Ok(())
}
