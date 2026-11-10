use super::*;
use cdmw_render_wgpu::{HeadlessMaterialCaptureCamera, LightingDepthSettings};
use cdmw_texture::TextureRole;

#[test]
#[ignore = "requires a D3D12 adapter"]
fn offscreen_shadow_and_ambient_depth_preserve_diagnostics() -> TestResult {
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
            cdmw_render_wgpu::run_headless_layered_material_capture_with_depth(
                &snapshot,
                &textures,
                &[],
                &[],
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
                cdmw_render_wgpu::run_headless_layered_material_capture_with_depth(
                    &snapshot,
                    &textures,
                    &factors,
                    &[],
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
    let compatibility_cases = pollster::block_on(
        cdmw_render_wgpu::verify_lighting_depth_compatibility(&snapshot),
    )?;
    assert!(compatibility_cases > 0);
    eprintln!("Verified {compatibility_cases} orthographic/MSAA/texture-limit combinations");
    Ok(())
}
