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
            let moved = capture(&mut renderer, "moved.png")?;
            if moved == baseline {
                return Err("Capture ignored live placement".into());
            }
            let failure = renderer.replace_preview_scene(|candidate| {
                candidate.set_snapshot(&snapshot)?;
                candidate.set_scene_transform(Mat4::IDENTITY)?;
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
