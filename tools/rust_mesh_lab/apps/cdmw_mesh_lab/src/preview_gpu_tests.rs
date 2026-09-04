//! Explicit synthetic GPU verification; never part of the default unit run.
use crate::camera::OrbitCamera;
use cdmw_formats::{MeshFormat, decode_mesh};
use cdmw_mesh::WorkingMesh;
use cdmw_render_wgpu::{EffectLineVertex, ViewMode, WindowRenderer};
use cdmw_texture::TextureRole;
use glam::{Mat4, Vec3};
use std::sync::Arc;
use winit::application::ApplicationHandler;
use winit::event::WindowEvent;
use winit::event_loop::{ActiveEventLoop, EventLoop};
use winit::platform::windows::EventLoopBuilderExtWindows;
use winit::window::{Window, WindowId};

#[derive(Default)]
struct CaptureProbe {
    result: Option<Result<(), String>>,
}

impl ApplicationHandler for CaptureProbe {
    fn resumed(&mut self, event_loop: &ActiveEventLoop) {
        self.result = Some((|| -> Result<(), String> {
            let window = Arc::new(
                event_loop
                    .create_window(
                        Window::default_attributes()
                            .with_title("CDMW synthetic capture verification")
                            .with_visible(false)
                            .with_inner_size(winit::dpi::PhysicalSize::new(256, 256)),
                    )
                    .map_err(|e| e.to_string())?,
            );
            let mut renderer =
                pollster::block_on(WindowRenderer::new(window)).map_err(|e| e.to_string())?;
            let document = decode_mesh(
                &cdmw_formats::synthetic::triangle_pam("synthetic.dds"),
                MeshFormat::Pam,
            )
            .map_err(|e| e.to_string())?;
            let mesh = WorkingMesh::from_document(&document).map_err(|e| e.to_string())?;
            let snapshot = mesh.draw_snapshot();
            let mut camera = OrbitCamera::default();
            let viewport = egui::Rect::from_min_size(egui::Pos2::ZERO, egui::vec2(256., 256.));
            camera.frame_all_in_viewport(&mesh, viewport);
            renderer
                .set_snapshot_with_scene_roles(&snapshot, &vec![1; snapshot.positions.len()])
                .map_err(|e| e.to_string())?;
            renderer.set_view_mode(ViewMode::TexturedSolid);
            renderer.set_camera_with_basis(
                camera.view_projection(viewport),
                camera.right(),
                camera.up(),
            );
            renderer.set_clear_colour([0.02, 0.02, 0.02, 1.]);
            let directory = tempfile::tempdir().map_err(|e| e.to_string())?;
            let capture = |renderer: &mut WindowRenderer, name: &str| -> Result<Vec<u8>, String> {
                let path = directory.path().join(name);
                renderer
                    .capture_frame(256, 256, None)
                    .map_err(|e| e.to_string())?
                    .write(&path)
                    .map_err(|e| e.to_string())?;
                std::fs::read(path).map_err(|e| e.to_string())
            };
            let baseline = capture(&mut renderer, "baseline.png")?;
            if !baseline.starts_with(b"\x89PNG") || baseline.len() < 512 {
                return Err("Baseline capture is not a rendered PNG".into());
            }
            renderer
                .set_scene_transform(Mat4::from_translation(Vec3::X * 0.6))
                .map_err(|e| e.to_string())?;
            let resident_particles = crate::preview_effects::effect_emitter_billboards(
                &serde_json::json!({"loop":false,"alpha_over_life":[1.0],"color_over_life":[[1.0,0.0,0.0]],"scale":[[0.1,0.3,0.1],[0.1,0.3,0.1]],"spread":[0.,0.,0.]}),
                0,
                0.,
                0.,
                0,
                Mat4::IDENTITY,
                Vec3::X,
                Vec3::Y,
                Vec3::Z,
            );
            renderer
                .set_effect_particles(&resident_particles)
                .map_err(|e| e.to_string())?;
            let moved = capture(&mut renderer, "moved.png")?;
            if moved == baseline {
                return Err("Capture ignored live placement".into());
            }
            let failure = renderer.replace_preview_scene(|candidate| {
                candidate.set_snapshot(&snapshot)?;
                candidate.set_scene_transform(Mat4::IDENTITY)?;
                let mut changed = resident_particles.clone();
                changed[0].center = [100., 0., 0.];
                candidate.set_effect_particles(&changed)?;
                candidate.add_dds_texture(b"invalid DDS", TextureRole::BaseColor, &[vec![0]])?;
                Ok(())
            });
            if failure.is_ok() {
                return Err("Invalid replacement was accepted".into());
            }
            if capture(&mut renderer, "rollback.png")? != moved {
                return Err("Failed replacement changed the resident frame".into());
            }
            renderer
                .set_effect_lines(&[
                    EffectLineVertex {
                        position: [-0.5, 0., 0.],
                        colour: [1., 0., 0., 1.],
                    },
                    EffectLineVertex {
                        position: [0.5, 0., 0.],
                        colour: [1., 0., 0., 1.],
                    },
                ])
                .map_err(|e| e.to_string())?;
            if capture(&mut renderer, "effects.png")? == moved {
                return Err("Capture omitted live effect lines".into());
            }
            Ok(())
        })());
        event_loop.exit();
    }
    fn window_event(&mut self, _: &ActiveEventLoop, _: WindowId, _: WindowEvent) {}
}

#[test]
#[ignore = "explicit hidden-window D3D12 capture and rollback verification"]
fn resident_capture_keeps_live_transform_effects_and_failed_upload_state() {
    let event_loop = EventLoop::builder()
        .with_any_thread(true)
        .build()
        .expect("event loop");
    let mut probe = CaptureProbe::default();
    event_loop.run_app(&mut probe).expect("probe event loop");
    probe
        .result
        .expect("probe ran")
        .expect("resident GPU capture contract");
}

#[derive(Default)]
struct AuthoringRefreshProbe {
    result: Option<anyhow::Result<()>>,
}

impl ApplicationHandler for AuthoringRefreshProbe {
    fn resumed(&mut self, event_loop: &ActiveEventLoop) {
        self.result = Some((|| -> anyhow::Result<()> {
            let window = Arc::new(
                event_loop.create_window(
                    Window::default_attributes()
                        .with_visible(false)
                        .with_inner_size(winit::dpi::PhysicalSize::new(256, 256)),
                )?,
            );
            let root = tempfile::tempdir()?;
            let mut document = decode_mesh(
                &cdmw_formats::synthetic::triangle_pam("owned.dds"),
                MeshFormat::Pam,
            )?;
            document.lods[0].submeshes[0].name = "Part A".to_owned();
            let mut second = document.lods[0].submeshes[0].clone();
            second.name = "Part B".to_owned();
            for position in &mut second.positions {
                position[0] += 2.0;
            }
            document.lods[0].submeshes.push(second);
            let bytes = cdmw_texture::synthetic::rgba8_checker_dds();
            let bridge = crate::cdmw_session::CdmwBridge::for_test_with_textures(
                root.path().to_path_buf(),
                "gpu-authoring-refresh",
                1,
                0,
                vec![crate::cdmw_session::CdmwTextureResource {
                    label: "owned.dds".to_owned(),
                    role: TextureRole::BaseColor,
                    metadata: cdmw_texture::inspect_dds(&bytes, TextureRole::BaseColor)?,
                    bytes,
                    material_indices_by_lod: vec![vec![0]],
                }],
            );
            let mut app = crate::LabApplication::new_cdmw(bridge, document.clone(), None)?;
            let viewport = egui::Rect::from_min_size(egui::Pos2::ZERO, egui::vec2(256.0, 256.0));
            app.update_viewport_rect(viewport);
            app.renderer = Some(pollster::block_on(WindowRenderer::new(window))?);
            app.install_cdmw_document(document.clone())?;
            let capture = |app: &mut crate::LabApplication| -> anyhow::Result<Vec<u8>> {
                let camera = app.camera.view_projection(viewport);
                let renderer = app.renderer.as_mut().expect("renderer");
                renderer.set_camera(camera);
                renderer.set_view_mode(ViewMode::TexturedSolid);
                Ok(renderer.capture_frame(256, 256, None)?.read_rgba()?)
            };
            let baseline = capture(&mut app)?;
            anyhow::ensure!(
                app.cdmw_textured_mode_available,
                "initial texture did not bind"
            );
            anyhow::ensure!(
                app.material_reload_count == 1,
                "initial materials not uploaded once"
            );
            anyhow::ensure!(
                baseline
                    .chunks_exact(4)
                    .any(|pixel| pixel != &baseline[..4]),
                "blank capture"
            );

            let selection_revision = app.mesh.as_ref().expect("mesh").selection_revision;
            app.install_validated_cdmw_state(serde_json::json!({"selection": {}}), None)?;
            anyhow::ensure!(
                app.mesh.as_ref().expect("mesh").selection_revision == selection_revision,
                "state-only result rewrote selection"
            );
            anyhow::ensure!(
                capture(&mut app)? == baseline,
                "state-only result changed pixels"
            );

            app.install_cdmw_document(document.clone())?;
            anyhow::ensure!(
                capture(&mut app)? == baseline,
                "same document changed pixels"
            );
            let mut edited = document.clone();
            edited.lods[0].submeshes[0].positions[0][0] += 0.4;
            app.install_cdmw_document(edited)?;
            anyhow::ensure!(
                capture(&mut app)? != baseline,
                "edited mesh did not reach GPU"
            );
            app.install_cdmw_document(document.clone())?;
            anyhow::ensure!(
                capture(&mut app)? == baseline,
                "undo did not restore pixels"
            );
            anyhow::ensure!(
                app.material_reload_count == 1,
                "unchanged textures were re-uploaded"
            );

            document.lods[0].submeshes.swap(0, 1);
            app.install_cdmw_document(document)?;
            anyhow::ensure!(
                app.material_reload_count == 2,
                "ownership change did not refresh bindings"
            );
            anyhow::ensure!(
                app.cdmw_texture_resources[0].material_indices_by_lod == vec![vec![1]],
                "texture remained on the old part"
            );
            anyhow::ensure!(
                app.cdmw_textured_mode_available,
                "remapped texture did not bind"
            );
            Ok(())
        })());
        event_loop.exit();
    }
    fn window_event(&mut self, _: &ActiveEventLoop, _: WindowId, _: WindowEvent) {}
}

#[test]
#[ignore = "explicit hidden-window D3D12 authoring texture reuse verification"]
fn authoring_refresh_reuses_textures_and_updates_geometry_pixels() {
    let event_loop = EventLoop::builder()
        .with_any_thread(true)
        .build()
        .expect("event loop");
    let mut probe = AuthoringRefreshProbe::default();
    event_loop.run_app(&mut probe).expect("probe event loop");
    probe
        .result
        .expect("probe ran")
        .expect("authoring GPU refresh contract");
}

#[derive(Default)]
struct EffectProbe {
    result: Option<anyhow::Result<()>>,
}

impl ApplicationHandler for EffectProbe {
    fn resumed(&mut self, event_loop: &ActiveEventLoop) {
        self.result = Some((|| -> anyhow::Result<()> {
            let root = std::path::PathBuf::from(std::env::var("CDMW_EFFECT_PROBE_DIR")?);
            let label = std::env::var("CDMW_EFFECT_PROBE_LABEL")?;
            anyhow::ensure!(
                matches!(label.as_str(), "before" | "after"),
                "invalid capture label"
            );
            let window = Arc::new(
                event_loop.create_window(
                    Window::default_attributes()
                        .with_title("CDMW effect capture verification")
                        .with_visible(false)
                        .with_inner_size(winit::dpi::PhysicalSize::new(640, 480)),
                )?,
            );
            let mut renderer = pollster::block_on(WindowRenderer::new(window))?;
            // The production preview has a resident item mesh. Keep a fixture
            // mesh outside the view so captures exercise the same scene path.
            let document = decode_mesh(
                &cdmw_formats::synthetic::triangle_pam("synthetic.dds"),
                MeshFormat::Pam,
            )?;
            let mut snapshot = WorkingMesh::from_document(&document)?.draw_snapshot();
            for p in &mut snapshot.positions {
                *p = [10000.0, 10000.0, 10000.0];
            }
            renderer.set_snapshot(&snapshot)?;
            renderer.set_scene_transform(Mat4::from_translation(Vec3::splat(10_000.0)))?;
            renderer.set_camera_with_basis(
                Mat4::orthographic_rh(-1., 1., -1., 1., 0.1, 10.)
                    * Mat4::look_at_rh(Vec3::Z * 2., Vec3::ZERO, Vec3::Y),
                Vec3::X,
                Vec3::Y,
            );
            let sentinel = crate::preview_effects::effect_emitter_billboards(
                &serde_json::json!({"loop":false,"alpha_over_life":[1.0],"color_over_life":[[1.0,0.0,0.0]],"scale":[[0.5,0.5,0.5],[0.5,0.5,0.5]],"spread":[0.0,0.0,0.0]}),
                0,
                0.0,
                0.01,
                0,
                Mat4::IDENTITY,
                Vec3::X,
                Vec3::Y,
                -Vec3::Z,
            );
            renderer.set_effect_particles(&sentinel)?;
            renderer
                .capture_frame(640, 480, None)?
                .write(&root.join("sentinel.png"))?;
            for entry in std::fs::read_dir(&root)? {
                let dir = entry?.path();
                if !dir.join("effect.json").is_file() {
                    continue;
                }
                let effect: serde_json::Value =
                    serde_json::from_slice(&std::fs::read(dir.join("effect.json"))?)?;
                let inputs: serde_json::Value =
                    serde_json::from_slice(&std::fs::read(dir.join("inputs.json"))?)?;
                renderer.reset_effect_textures();
                let mut textures = std::collections::HashMap::new();
                for (name, path) in inputs["textures"].as_object().expect("texture map") {
                    textures.insert(
                        name.as_str(),
                        renderer.add_effect_dds_texture(&std::fs::read(
                            path.as_str().expect("path"),
                        )?)?,
                    );
                }
                let mut low = Vec3::splat(f32::MAX);
                let mut high = Vec3::splat(f32::MIN);
                for time in [0.15, 0.5, 1.0, 2.5] {
                    for (index, emitter) in effect["emitters"]
                        .as_array()
                        .expect("emitters")
                        .iter()
                        .enumerate()
                    {
                        for p in crate::preview_effects::effect_emitter_billboards(
                            emitter,
                            index,
                            time,
                            0.001,
                            0,
                            Mat4::IDENTITY,
                            Vec3::X,
                            Vec3::Y,
                            -Vec3::Z,
                        ) {
                            let center = Vec3::from_array(p.center);
                            let radius = Vec3::from_array(p.axis_right).abs()
                                + Vec3::from_array(p.axis_up).abs();
                            low = low.min(center - radius);
                            high = high.max(center + radius);
                        }
                    }
                }
                anyhow::ensure!(
                    low.is_finite() && high.is_finite() && low.cmple(high).all(),
                    "effect has no finite particle bounds"
                );
                let target = (low + high) * 0.5;
                let extent = (high - low).max_element().clamp(0.5, 100.);
                let eye = target + Vec3::Z * extent * 1.5;
                renderer.set_camera_with_basis(
                    Mat4::perspective_rh(45_f32.to_radians(), 640. / 480., 0.01, 1000.)
                        * Mat4::look_at_rh(eye, target, Vec3::Y),
                    Vec3::X,
                    Vec3::Y,
                );
                renderer.set_clear_colour([0.18, 0.20, 0.23, 1.]);
                let clear = renderer.capture_frame(1, 1, None)?.read_rgba()?;
                let mut report = Vec::new();
                let mut total_visible = 0;
                for time in [0.15, 0.5, 1.0, 2.5] {
                    let mut particles = Vec::new();
                    for (index, emitter) in effect["emitters"]
                        .as_array()
                        .expect("emitters")
                        .iter()
                        .enumerate()
                    {
                        if emitter["kind"] == "mesh"
                            && emitter["particle_faces"]
                                .as_array()
                                .is_none_or(|v| v.is_empty())
                        {
                            continue;
                        }
                        let texture = textures
                            .get(emitter["texture"].as_str().unwrap_or(""))
                            .copied()
                            .unwrap_or(0);
                        particles.extend(crate::preview_effects::effect_emitter_billboards(
                            emitter,
                            index,
                            time,
                            extent * 0.006,
                            texture,
                            Mat4::IDENTITY,
                            Vec3::X,
                            Vec3::Y,
                            -Vec3::Z,
                        ));
                    }
                    for p in &mut particles {
                        p.depth = (Vec3::from_array(p.center) - eye).dot(-Vec3::Z);
                    }
                    renderer.set_effect_particles(&particles)?;
                    renderer
                        .capture_frame(640, 480, None)?
                        .write(&dir.join(format!("{label}-{time}.png")))?;
                    let pixels = renderer.capture_frame(640, 480, None)?.read_rgba()?;
                    let visible = pixels
                        .chunks_exact(4)
                        .filter(|p| {
                            p[..3]
                                .iter()
                                .zip(&clear[..3])
                                .any(|(a, b)| a.abs_diff(*b) > 3)
                        })
                        .count();
                    total_visible += visible;
                    report.push(serde_json::json!({"time":time,"instances":particles.len(),"visible_pixels":visible}));
                }
                anyhow::ensure!(
                    label == "before" || total_visible > 0,
                    "no visible particles in {}",
                    dir.display()
                );
                std::fs::write(
                    dir.join(format!("{label}-report.json")),
                    serde_json::to_vec_pretty(&report)?,
                )?;
            }
            Ok(())
        })());
        event_loop.exit();
    }
    fn window_event(&mut self, _: &ActiveEventLoop, _: WindowId, _: WindowEvent) {}
}

#[test]
#[ignore = "explicit local DDS corpus capture; requires CDMW_EFFECT_PROBE_DIR and CDMW_EFFECT_PROBE_LABEL"]
fn capture_effect_corpus() {
    let event_loop = EventLoop::builder()
        .with_any_thread(true)
        .build()
        .expect("event loop");
    let mut probe = EffectProbe::default();
    event_loop.run_app(&mut probe).expect("event loop");
    probe.result.expect("probe ran").expect("effect captures");
}
