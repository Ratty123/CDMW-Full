//! The editor's own controls used by name from CDMW (`editor_control`,
//! `HOST_EDITOR_CONTROLS_CAPABILITY`). Each control acts as its button or checkbox does,
//! with the same checks, and every message is answered with the control's state, so a
//! refusal the panel would only show in its own text reaches CDMW too.
use super::*;

/// What one control did: whether it took the action, the editor's reason when it did
/// not, and the control's state afterwards.
pub(crate) struct ControlOutcome {
    pub ok: bool,
    pub message: String,
    pub state: Value,
}

impl ControlOutcome {
    pub(crate) fn done(state: Value) -> Self {
        Self { ok: true, message: String::new(), state }
    }

    pub(crate) fn refused(message: impl Into<String>, state: Value) -> Self {
        Self { ok: false, message: message.into(), state }
    }
}

/// The action an `editor_control` names in `arguments.action`.
pub(crate) fn control_action(arguments: &Value) -> &str {
    arguments.get("action").and_then(Value::as_str).unwrap_or("state")
}

/// An optional number from `low` to `high`; anything else is refused with its name.
pub(crate) fn control_number(arguments: &Value, key: &str, low: f32, high: f32) -> Result<Option<f32>, String> {
    match arguments.get(key) {
        None | Some(Value::Null) => Ok(None),
        Some(item) => item
            .as_f64()
            .map(|number| number as f32)
            .filter(|number| number.is_finite() && (low..=high).contains(number))
            .map(Some)
            .ok_or_else(|| format!("{key} must be a number from {low} to {high}")),
    }
}

/// An optional true or false.
pub(crate) fn control_bool(arguments: &Value, key: &str) -> Result<Option<bool>, String> {
    match arguments.get(key) {
        None | Some(Value::Null) => Ok(None),
        Some(item) => item.as_bool().map(Some).ok_or_else(|| format!("{key} must be true or false")),
    }
}

/// An optional list of whole numbers.
pub(crate) fn control_ids(arguments: &Value, key: &str) -> Result<Option<Vec<u64>>, String> {
    match arguments.get(key) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Array(items)) => items
            .iter()
            .map(|item| item.as_u64().ok_or_else(|| format!("{key} must list whole numbers")))
            .collect::<Result<Vec<_>, _>>()
            .map(Some),
        Some(_) => Err(format!("{key} must list whole numbers")),
    }
}

impl LabApplication {
    /// Use one control and say what it did (`editor_control`).
    pub(crate) fn apply_editor_control(&mut self, control: &str, arguments: &Value) -> ControlOutcome {
        let outcome = match control {
            "hair" => self.hair_host_control(arguments),
            "islands" => self.islands_host_control(arguments),
            "document" => self.document_host_control(arguments),
            "overlays" => self.overlays_host_control(arguments),
            "capture" => self.capture_host_control(arguments),
            "sculpt" => self.sculpt_host_control(arguments),
            _ => ControlOutcome::refused(format!("The editor has no control {control}."), Value::Null),
        };
        self.egui_context.request_repaint();
        if let Some(window) = &self.window {
            window.request_redraw();
        }
        outcome
    }
}

/// The largest side a capture draws, as the renderer's offscreen capture allows.
pub(crate) const CAPTURE_MAX_SIDE: u32 = 2048;
static CAPTURES: AtomicU64 = AtomicU64::new(0);

impl LabApplication {
    /// The 3D view as the editor's renderer draws it, at the viewport's size (at most
    /// `max_side` on its longer side), written as a PNG into the session folder. The
    /// panels are not in it. CDMW reads the file and removes it.
    pub(crate) fn capture_host_control(&mut self, arguments: &Value) -> ControlOutcome {
        match self.capture_view(arguments) {
            Ok(state) => ControlOutcome::done(state),
            Err(message) => ControlOutcome::refused(message, Value::Null),
        }
    }

    fn capture_view(&mut self, arguments: &Value) -> Result<Value, String> {
        let max_side = control_number(arguments, "max_side", 64.0, CAPTURE_MAX_SIDE as f32)?
            .map_or(CAPTURE_MAX_SIDE, |side| side as u32);
        let rect = self.viewport_rect.ok_or("The 3D view has not been laid out yet.")?;
        let scale = self.egui_context.pixels_per_point().max(0.25);
        let (width, height) = (rect.width() * scale, rect.height() * scale);
        if width < 1.0 || height < 1.0 {
            return Err("The 3D view has no size to draw.".into());
        }
        let fit = (max_side as f32 / width.max(height)).min(1.0);
        let size = |value: f32| ((value * fit).round() as u32).clamp(1, CAPTURE_MAX_SIDE);
        let (width, height) = (size(width), size(height));
        let root = self
            .cdmw_bridge
            .as_ref()
            .map(|bridge| bridge.session_root().to_path_buf())
            .ok_or("This editor has no CDMW session to write the picture into.")?;
        let renderer = self.renderer.as_mut().ok_or("The 3D view has no renderer (its GPU is not available).")?;
        let folder = root.join("captures");
        fs::create_dir_all(&folder).map_err(|error| format!("Could not make the capture folder: {error}"))?;
        let path = folder.join(format!("view-{}.png", CAPTURES.fetch_add(1, Ordering::Relaxed) + 1));
        renderer
            .capture_frame(width, height, None)
            .and_then(|capture| capture.write(&path))
            .map_err(|error| format!("The 3D view could not be drawn to a picture: {error}"))?;
        Ok(json!({"path": path.to_string_lossy(), "width": width, "height": height}))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn capture_says_why_it_cannot_draw_the_view() {
        let mut app = LabApplication::new(None, None);
        let unlaid = app.apply_editor_control("capture", &json!({}));
        assert!(!unlaid.ok && unlaid.message.contains("laid out"), "{}", unlaid.message);
        app.viewport_rect = Some(egui::Rect::from_min_size(egui::Pos2::ZERO, egui::vec2(640.0, 360.0)));
        let sessionless = app.apply_editor_control("capture", &json!({"max_side": 512}));
        assert!(!sessionless.ok && sessionless.message.contains("no CDMW session"), "{}", sessionless.message);
        let root = tempfile::tempdir().expect("root");
        app.cdmw_bridge = Some(CdmwBridge::for_test(root.path().to_path_buf(), "capture", 1, 0));
        let headless = app.apply_editor_control("capture", &json!({}));
        assert!(!headless.ok && headless.message.contains("no renderer"), "{}", headless.message);
        let too_big = app.apply_editor_control("capture", &json!({"max_side": 9000}));
        assert!(!too_big.ok && too_big.message.contains("max_side"), "{}", too_big.message);
        assert!(!root.path().join("captures").exists());
    }
}

#[cfg(all(test, windows))]
mod gpu_tests {
    use super::*;

    #[test]
    #[ignore = "explicit synthetic hidden-window D3D12 capture"]
    fn capture_writes_the_views_picture_into_the_session_folder() {
        use winit::application::ApplicationHandler;
        use winit::event::WindowEvent;
        use winit::event_loop::{ActiveEventLoop, EventLoop};
        use winit::platform::windows::EventLoopBuilderExtWindows;
        use winit::window::{Window, WindowId};

        #[derive(Default)]
        struct Probe(Option<anyhow::Result<()>>);

        impl ApplicationHandler for Probe {
            fn resumed(&mut self, event_loop: &ActiveEventLoop) {
                self.0 = Some(run(event_loop));
                event_loop.exit();
            }

            fn window_event(&mut self, _: &ActiveEventLoop, _: WindowId, _: WindowEvent) {}
        }

        fn run(event_loop: &ActiveEventLoop) -> anyhow::Result<()> {
            let window = Arc::new(event_loop.create_window(
                Window::default_attributes()
                    .with_visible(false)
                    .with_inner_size(winit::dpi::PhysicalSize::new(320, 180)),
            )?);
            let renderer = pollster::block_on(WindowRenderer::new(window))?;
            let root = tempfile::tempdir()?;
            let mut app = LabApplication::new(None, None);
            app.renderer = Some(renderer);
            app.cdmw_bridge = Some(CdmwBridge::for_test(root.path().to_path_buf(), "capture", 1, 0));
            app.viewport_rect = Some(egui::Rect::from_min_size(egui::Pos2::ZERO, egui::vec2(320.0, 180.0)));
            let outcome = app.apply_editor_control("capture", &json!({"max_side": 160}));
            anyhow::ensure!(outcome.ok, "{}", outcome.message);
            let path = PathBuf::from(outcome.state["path"].as_str().unwrap_or_default());
            let session = fs::canonicalize(root.path())?;
            anyhow::ensure!(path.starts_with(&session), "{} is outside the session", path.display());
            anyhow::ensure!(outcome.state["width"] == 160 && outcome.state["height"] == 90, "{}", outcome.state);
            let bytes = fs::read(&path)?;
            anyhow::ensure!(bytes.starts_with(b"\x89PNG"), "not a PNG");
            Ok(())
        }

        let mut event_loop = EventLoop::builder();
        event_loop.with_any_thread(true);
        let event_loop = event_loop.build().expect("event loop");
        let mut probe = Probe::default();
        event_loop.run_app(&mut probe).expect("run");
        probe.0.expect("resumed").expect("capture");
    }
}
