//! Opt-in captures of a caller-owned authoring package through the editor renderer.
//! No alternate normals, smoothing, material colours, or geometry are generated here.
use super::*;

#[test]
#[ignore = "requires caller-authorized packages, CDMW_AUTHORING_CAPTURE_REQUEST and D3D12"]
fn capture_authoring_viewport_from_all_angles() -> TestResult {
    use winit::application::ApplicationHandler;
    use winit::event_loop::{ActiveEventLoop, EventLoop};
    use winit::platform::windows::EventLoopBuilderExtWindows;
    use winit::window::{Window, WindowId};

    #[derive(Default)]
    struct Probe(Option<TestResult>);
    impl ApplicationHandler for Probe {
        fn resumed(&mut self, event_loop: &ActiveEventLoop) {
            self.0 = Some(capture(event_loop));
            event_loop.exit();
        }
        fn window_event(&mut self, _: &ActiveEventLoop, _: WindowId, _: WindowEvent) {}
    }

    fn capture(event_loop: &ActiveEventLoop) -> TestResult {
        let request: Value = serde_json::from_slice(&std::fs::read(std::env::var(
            "CDMW_AUTHORING_CAPTURE_REQUEST",
        )?)?)?;
        let jobs = request["jobs"]
            .as_array()
            .ok_or("capture request needs jobs")?;
        let target: [f32; 3] = serde_json::from_value(request["target"].clone())?;
        let zoom = request["relative_zoom"]
            .as_f64()
            .ok_or("capture request needs zoom")? as f32;
        let views: Vec<(String, f32, f32)> = serde_json::from_value(request["views"].clone())?;
        let size = 1536;
        let rectangle = egui::Rect::from_min_size(egui::Pos2::ZERO, egui::Vec2::splat(size as f32));
        for job in jobs {
            let manifest = PathBuf::from(job["manifest"].as_str().ok_or("missing manifest")?);
            let output = PathBuf::from(job["output"].as_str().ok_or("missing output")?);
            std::fs::create_dir(&output)?;
            let (bridge, document) = CdmwBridge::open(&manifest)?;
            let mut app = LabApplication::new_cdmw(bridge, document, None)?;
            let before = app.mesh.as_ref().ok_or("missing mesh")?.draw_snapshot();
            let window = Arc::new(
                event_loop.create_window(
                    Window::default_attributes()
                        .with_visible(false)
                        .with_inner_size(winit::dpi::PhysicalSize::new(size, size)),
                )?,
            );
            app.view_mode = ViewMode::PartId;
            app.renderer = Some(app.create_renderer(window)?);
            // The actual editor method applies Part colours and all visibility state.
            app.refresh_cdmw_mesh_display();
            app.camera
                .frame_all_in_viewport(app.mesh.as_ref().unwrap(), rectangle);
            let mut captures = Vec::new();
            for (name, yaw, pitch) in &views {
                assert!(name.bytes().all(|c| c.is_ascii_alphanumeric() || c == b'-'));
                app.camera.set_orbit_state_with_roll(
                    yaw.to_radians(),
                    pitch.to_radians(),
                    0.,
                    Some(Vec3::from(target)),
                    Some(zoom),
                );
                let renderer = app.renderer.as_mut().unwrap();
                renderer.set_view_mode(app.view_mode);
                renderer.set_overlays(false, false);
                renderer.set_bone_overlay(false);
                renderer.set_clear_colour([0.006, 0.008, 0.012, 1.]);
                renderer.set_camera(app.camera.view_projection(rectangle));
                let path = output.join(format!("{name}.png"));
                renderer.capture_frame(size, size, None)?.write(&path)?;
                captures.push(json!({"path": path, "yaw_degrees": yaw, "pitch_degrees": pitch}));
            }
            assert_eq!(
                app.mesh.as_ref().unwrap().draw_snapshot(),
                before,
                "rendering must not change positions, normals, topology or materials"
            );
            let renderer = app.renderer.as_ref().unwrap();
            std::fs::write(
                output.join("capture-report.json"),
                serde_json::to_vec_pretty(&json!({
                    "renderer": "wgpu_d3d12_rust", "path": "LabApplication::create_renderer / refresh_cdmw_mesh_display / WindowRenderer::capture_frame",
                    "view": "Part colors", "manifest": manifest, "manifest_sha256": format!("{:x}", Sha256::digest(std::fs::read(&manifest)?)),
                    "adapter": renderer.adapter_report().name, "sample_count": renderer.quality_report().sample_count,
                    "target": target, "relative_zoom": zoom, "dimensions": [size, size], "captures": captures,
                    "geometry_unchanged": true, "proof": "production renderer capture; hidden window, not normal-window interaction or game proof"
                }))?,
            )?;
        }
        Ok(())
    }
    let event_loop = EventLoop::builder().with_any_thread(true).build()?;
    let mut probe = Probe::default();
    event_loop.run_app(&mut probe)?;
    probe.0.ok_or("authoring capture did not run")?
}
