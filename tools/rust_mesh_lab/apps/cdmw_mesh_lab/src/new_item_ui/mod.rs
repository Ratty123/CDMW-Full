//! Optional embedded New Item UI. The ordinary Mesh Editor route is unchanged.

mod capture;
mod fonts;
mod model;
mod view;

use anyhow::{Context, Result, bail};
use model::{Input, MAX_MESSAGE_BYTES, PROTOCOL, State};
use serde_json::{Value, json};
use std::collections::VecDeque;
use std::io::{BufRead, Read, Write};
use std::path::{Path, PathBuf};
use std::sync::{Arc, mpsc};
use std::time::{Duration, Instant};
use view::{PresentationView, apply_theme};
use winit::application::ApplicationHandler;
use winit::event::WindowEvent;
use winit::event_loop::{ActiveEventLoop, ControlFlow, EventLoop};
use winit::window::{Window, WindowId};

pub fn control_contract() -> Value {
    json!({"protocol":PROTOCOL,"entry_point":"--cdmw-new-item-session",
           "headless_entry_point":"--new-item-ui-document","native_controls":true})
}

pub fn try_run() -> Result<bool> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    let Some(mode) = args.first().map(String::as_str) else {
        return Ok(false);
    };
    if mode != "--cdmw-new-item-session" && mode != "--new-item-ui-document" {
        return Ok(false);
    }
    let path = args
        .get(1)
        .context("New Item UI requires its session/document path")?;
    let mut parent = None;
    let mut report = None;
    let mut capture = None;
    let mut size = [1440u32, 960u32];
    let mut index = 2;
    while index < args.len() {
        let value = args
            .get(index + 1)
            .context("Missing New Item UI option value")?;
        match args[index].as_str() {
            "--embedded-parent-hwnd" => parent = Some(value.parse::<u64>()?),
            "--new-item-ui-report" => report = Some(PathBuf::from(value)),
            "--capture-new-item-ui" => capture = Some(PathBuf::from(value)),
            "--width" => size[0] = value.parse()?,
            "--height" => size[1] = value.parse()?,
            other => bail!("Unknown New Item UI option: {other}"),
        }
        index += 2;
    }
    if !(320..=8192).contains(&size[0]) || !(240..=8192).contains(&size[1]) {
        bail!("Invalid New Item UI size");
    }
    let data = read_bounded(Path::new(path))?;
    if mode == "--new-item-ui-document" {
        let state: State = serde_json::from_slice(&data)?;
        state.validate(&state.session)?;
        let report = report.context("Headless New Item UI requires --new-item-ui-report")?;
        headless_report(&state, &report, capture.as_deref(), size)?;
        return Ok(true);
    }
    let manifest: Value = serde_json::from_slice(&data)?;
    let session = manifest["session"]
        .as_str()
        .context("Missing New Item UI session")?
        .to_owned();
    if manifest["protocol"] != PROTOCOL || session.len() > 64 {
        bail!("Invalid New Item UI manifest");
    }
    let parent = parent
        .filter(|parent| *parent != 0)
        .context("New Item UI requires an embedded parent HWND")?;
    let event_loop = EventLoop::<()>::with_user_event().build()?;
    let proxy = event_loop.create_proxy();
    let (sender, receiver) = mpsc::sync_channel(8);
    std::thread::Builder::new()
        .name("new-item-ui-input".into())
        .spawn(move || {
            let stdin = std::io::stdin();
            let mut reader = stdin.lock();
            loop {
                let mut line = Vec::new();
                let read = reader
                    .by_ref()
                    .take((MAX_MESSAGE_BYTES + 1) as u64)
                    .read_until(b'\n', &mut line);
                let result = match read {
                    Ok(0) => Err("The New Item host closed its input stream.".to_owned()),
                    Ok(_) if line.len() > MAX_MESSAGE_BYTES => {
                        Err("New Item message exceeds its limit.".to_owned())
                    }
                    Ok(_) => serde_json::from_slice(&line).map_err(|error| error.to_string()),
                    Err(error) => Err(error.to_string()),
                };
                let terminal = result.is_err();
                if sender.send(result).is_err() {
                    break;
                }
                let _ = proxy.send_event(());
                if terminal {
                    break;
                }
            }
        })?;
    let mut app = Application {
        session,
        parent,
        receiver,
        context: egui::Context::default(),
        window: None,
        input: None,
        renderer: None,
        state: None,
        view: PresentationView::default(),
        textures: egui::TexturesDelta::default(),
        requests: VecDeque::new(),
        next_request: 0,
        in_flight: None,
        last_layout: String::new(),
        error: None,
        next_repaint: None,
    };
    event_loop.run_app(&mut app)?;
    if let Some(error) = app.error {
        bail!("{error}");
    }
    Ok(true)
}

fn read_bounded(path: &Path) -> Result<Vec<u8>> {
    let file = std::fs::File::open(path)?;
    if file.metadata()?.len() > MAX_MESSAGE_BYTES as u64 {
        bail!("New Item document exceeds its limit");
    }
    let mut data = Vec::new();
    file.take((MAX_MESSAGE_BYTES + 1) as u64)
        .read_to_end(&mut data)?;
    if data.len() > MAX_MESSAGE_BYTES {
        bail!("New Item document changed beyond its limit");
    }
    Ok(data)
}

fn emit(message: &Value) -> Result<()> {
    let mut output = std::io::stdout().lock();
    serde_json::to_writer(&mut output, message)?;
    output.write_all(b"\n")?;
    output.flush()?;
    Ok(())
}

fn headless_report(
    state: &State,
    report: &Path,
    capture: Option<&Path>,
    size: [u32; 2],
) -> Result<()> {
    let context = egui::Context::default();
    apply_theme(&context, &state.theme);
    let mut view = PresentationView::default();
    load_images(&context, &mut view, state)?;
    let mut textures = egui::TexturesDelta::default();
    let mut last_output = None;
    for frame in 0..3 {
        let input = egui::RawInput {
            screen_rect: Some(egui::Rect::from_min_size(
                egui::Pos2::ZERO,
                egui::vec2(size[0] as f32, size[1] as f32),
            )),
            // Capture settled windows, after their opening fade and sizing pass.
            time: Some(frame as f64 * 0.25),
            ..Default::default()
        };
        let mut output = context.run_ui(input, |ui| view.draw(ui, state));
        textures.append(std::mem::take(&mut output.textures_delta));
        last_output = Some(output);
    }
    let adapter = if let (Some(path), Some(output)) = (capture, last_output) {
        let jobs = context.tessellate(output.shapes, output.pixels_per_point);
        Some(pollster::block_on(capture::write_png(
            path,
            size,
            output.pixels_per_point,
            &jobs,
            &textures,
        ))?)
    } else {
        None
    };
    textures.clear();
    std::fs::write(
        report,
        serde_json::to_vec_pretty(&json!({
            "schema": "cdmw_new_item_headless_layout_v1", "size": size,
            "controls": view.rects, "portals": view.portals, "errors": view.errors,
            "unsupported": state.unsupported, "generation": state.generation,
            "gpu_adapter": adapter, "capture": capture,
        }))?,
    )?;
    Ok(())
}

fn load_images(context: &egui::Context, view: &mut PresentationView, state: &State) -> Result<()> {
    view.textures
        .retain(|key, _| state.assets.contains_key(key));
    for (id, image) in &state.assets {
        if view.textures.contains_key(id) {
            continue;
        }
        if image.png_hex.len() % 2 != 0 {
            bail!("Invalid New Item image encoding");
        }
        let bytes: Result<Vec<_>, _> = image
            .png_hex
            .as_bytes()
            .chunks_exact(2)
            .map(|pair| {
                std::str::from_utf8(pair)
                    .ok()
                    .and_then(|text| u8::from_str_radix(text, 16).ok())
                    .ok_or(())
            })
            .collect();
        let bytes = bytes.map_err(|_| anyhow::anyhow!("Invalid New Item image encoding"))?;
        let mut decoder = png::Decoder::new(std::io::Cursor::new(bytes));
        decoder.set_transformations(png::Transformations::EXPAND | png::Transformations::STRIP_16);
        let mut reader = decoder.read_info()?;
        if reader.info().width != image.width || reader.info().height != image.height {
            bail!("New Item image dimensions differ");
        }
        let mut buffer = vec![
            0;
            reader
                .output_buffer_size()
                .context("Invalid image buffer size")?
        ];
        let info = reader.next_frame(&mut buffer)?;
        let data = &buffer[..info.buffer_size()];
        let color = match info.color_type {
            png::ColorType::Rgba => egui::ColorImage::from_rgba_unmultiplied(
                [info.width as usize, info.height as usize],
                data,
            ),
            png::ColorType::Rgb => {
                egui::ColorImage::from_rgb([info.width as usize, info.height as usize], data)
            }
            png::ColorType::Grayscale => {
                let rgb: Vec<u8> = data.iter().flat_map(|value| [*value; 3]).collect();
                egui::ColorImage::from_rgb([info.width as usize, info.height as usize], &rgb)
            }
            png::ColorType::GrayscaleAlpha => {
                let rgba: Vec<u8> = data
                    .chunks_exact(2)
                    .flat_map(|pair| [pair[0], pair[0], pair[0], pair[1]])
                    .collect();
                egui::ColorImage::from_rgba_unmultiplied(
                    [info.width as usize, info.height as usize],
                    &rgba,
                )
            }
            _ => bail!("Unsupported New Item image colour format"),
        };
        view.textures.insert(
            id.clone(),
            context.load_texture(id, color, egui::TextureOptions::LINEAR),
        );
    }
    Ok(())
}

struct Application {
    session: String,
    parent: u64,
    receiver: mpsc::Receiver<Result<Value, String>>,
    context: egui::Context,
    window: Option<Arc<Window>>,
    input: Option<egui_winit::State>,
    renderer: Option<cdmw_render_wgpu::WindowRenderer>,
    state: Option<State>,
    view: PresentationView,
    textures: egui::TexturesDelta,
    requests: VecDeque<Input>,
    next_request: u64,
    in_flight: Option<(u64, Input)>,
    last_layout: String,
    error: Option<String>,
    next_repaint: Option<Instant>,
}

impl Application {
    fn poll(&mut self, event_loop: &ActiveEventLoop) -> Result<()> {
        while let Ok(message) = self.receiver.try_recv() {
            let message = message.map_err(|error| anyhow::anyhow!(error))?;
            if message["protocol"] != PROTOCOL || message["session"] != self.session {
                bail!("New Item session message mismatch");
            }
            match message["type"].as_str() {
                Some("state") => {
                    let state: State = serde_json::from_value(message)?;
                    state.validate(&self.session)?;
                    if self
                        .state
                        .as_ref()
                        .is_some_and(|current| state.generation <= current.generation)
                    {
                        continue;
                    }
                    if let Some((request, previous)) = &self.in_flight {
                        if state.last_request >= *request {
                            self.view.acknowledge(previous);
                            for pending in &mut self.requests {
                                if pending.control == previous.control
                                    && matches!(
                                        pending.action,
                                        "text" | "number" | "cell" | "finish_edit"
                                    )
                                {
                                    if let Some(revision) =
                                        state.root.find_revision(&pending.control).or_else(|| {
                                            state.dialogs.iter().find_map(|dialog| {
                                                dialog.find_revision(&pending.control)
                                            })
                                        })
                                    {
                                        pending.revision = revision;
                                    }
                                }
                            }
                            self.in_flight = None;
                        }
                    }
                    apply_theme(&self.context, &state.theme);
                    load_images(&self.context, &mut self.view, &state)?;
                    emit(
                        &json!({"protocol":PROTOCOL,"type":"state_received","session":self.session,"generation":state.generation}),
                    )?;
                    self.state = Some(state);
                }
                Some("rejected") => {
                    self.view.reject_edits();
                    self.in_flight = None;
                    self.requests.clear();
                }
                Some("shutdown") => {
                    event_loop.exit();
                }
                Some("ack") => {}
                _ => bail!("Unknown New Item host message"),
            }
        }
        self.send_next()?;
        if let Some(window) = &self.window {
            window.request_redraw();
        }
        Ok(())
    }

    fn send_next(&mut self) -> Result<()> {
        if self.in_flight.is_none() {
            while let Some(input) = self.requests.pop_front() {
                // A final blur can also arrive from the old layout while a
                // navigation request is awaiting its state. Once the host has
                // removed that field, this lifecycle notification has no target.
                // Keep substantive stale edits subject to the host's rejection.
                if input.action == "finish_edit"
                    && self.state.as_ref().is_some_and(|state| {
                        state.root.find_revision(&input.control).is_none()
                            && state
                                .dialogs
                                .iter()
                                .all(|dialog| dialog.find_revision(&input.control).is_none())
                    })
                {
                    continue;
                }
                self.next_request += 1;
                emit(
                    &json!({"protocol":PROTOCOL,"type":"input","session":self.session,
                    "request":self.next_request,"control":input.control,"revision":input.revision,
                    "action":input.action,"value":input.value}),
                )?;
                self.in_flight = Some((self.next_request, input));
                break;
            }
        }
        Ok(())
    }

    fn redraw(&mut self, event_loop: &ActiveEventLoop) -> Result<()> {
        let Some(window) = self.window.clone() else {
            return Ok(());
        };
        let mut input = self
            .input
            .as_mut()
            .context("Missing New Item input")?
            .take_egui_input(&window);
        let focused = cdmw_win32_embed::has_keyboard_focus(&window)?;
        input.focused = focused;
        if let Some(viewport) = input.viewports.get_mut(&egui::ViewportId::ROOT) {
            viewport.focused = Some(focused);
        }
        input
            .events
            .retain(|event| !matches!(event, egui::Event::WindowFocused(_)));
        let output = self.context.run_ui(input, |ui| {
            if let Some(state) = &self.state {
                self.view.draw(ui, state);
            } else {
                ui.centered_and_justified(|ui| {
                    ui.spinner();
                });
            }
        });
        self.next_repaint = output
            .viewport_output
            .get(&egui::ViewportId::ROOT)
            .and_then(|viewport| {
                Instant::now().checked_add(viewport.repaint_delay.max(Duration::from_millis(8)))
            });
        self.input
            .as_mut()
            .unwrap()
            .handle_platform_output_with_event_loop(&window, event_loop, output.platform_output);
        self.textures.append(output.textures_delta);
        let jobs = self
            .context
            .tessellate(output.shapes, output.pixels_per_point);
        if let Some(renderer) = &mut self.renderer {
            crate::render_pending_egui_textures(&mut self.textures, |textures| {
                renderer.render_egui(&jobs, textures, output.pixels_per_point)
            })?;
        }
        for input in self.view.inputs.drain(..) {
            if matches!(input.action, "text" | "number" | "cell" | "range") {
                self.requests.retain(|queued| {
                    queued.edit_key() != input.edit_key() || queued.action != input.action
                });
            }
            if self.requests.len() < 128 {
                self.requests.push_back(input);
            }
        }
        if let Some(state) = &self.state {
            let portals = self.view.portals.clone();
            let layout = json!({"protocol":PROTOCOL,"type":"layout","session":self.session,
                "generation":state.generation,"pixels_per_point":output.pixels_per_point,"portals":portals});
            let encoded = layout.to_string();
            if encoded != self.last_layout {
                emit(&layout)?;
                self.last_layout = encoded;
            }
        }
        self.send_next()?;
        Ok(())
    }

    fn failed(&mut self, event_loop: &ActiveEventLoop, error: anyhow::Error) {
        let message = error.to_string();
        let _ = emit(
            &json!({"protocol":PROTOCOL,"type":"failed","session":self.session,"message":message}),
        );
        self.error = Some(message);
        event_loop.exit();
    }
}

impl ApplicationHandler for Application {
    fn resumed(&mut self, event_loop: &ActiveEventLoop) {
        if self.window.is_some() {
            return;
        }
        let result = (|| -> Result<()> {
            let attributes = cdmw_win32_embed::with_parent_window(
                Window::default_attributes()
                    .with_title("Create New Item")
                    .with_decorations(false)
                    .with_inner_size(winit::dpi::LogicalSize::new(1280, 900)),
                self.parent,
            )?;
            let window = Arc::new(event_loop.create_window(attributes)?);
            self.renderer = Some(pollster::block_on(cdmw_render_wgpu::WindowRenderer::new(
                window.clone(),
            ))?);
            self.input = Some(egui_winit::State::new(
                self.context.clone(),
                egui::ViewportId::ROOT,
                window.as_ref(),
                Some(window.scale_factor() as f32),
                window.theme(),
                None,
            ));
            emit(
                &json!({"protocol":PROTOCOL,"type":"ready","session":self.session,
                "child_hwnd":cdmw_win32_embed::window_hwnd(&window)?,"embedded_parent_hwnd":self.parent}),
            )?;
            window.request_redraw();
            self.window = Some(window);
            Ok(())
        })();
        if let Err(error) = result {
            self.failed(event_loop, error);
        }
    }

    fn user_event(&mut self, event_loop: &ActiveEventLoop, _event: ()) {
        if let Err(error) = self.poll(event_loop) {
            self.failed(event_loop, error);
        }
    }

    fn window_event(&mut self, event_loop: &ActiveEventLoop, _id: WindowId, event: WindowEvent) {
        let mut repaint = false;
        if matches!(
            event,
            WindowEvent::MouseInput {
                state: winit::event::ElementState::Pressed,
                ..
            }
        ) {
            if let Some(window) = &self.window {
                let _ = cdmw_win32_embed::focus_child_window(window);
            }
        }
        if let (Some(input), Some(window)) = (&mut self.input, &self.window) {
            repaint = input.on_window_event(window, &event).repaint;
        }
        match event {
            WindowEvent::CloseRequested => event_loop.exit(),
            WindowEvent::Resized(size) => {
                if let Some(renderer) = &mut self.renderer {
                    renderer.resize(size);
                }
            }
            WindowEvent::RedrawRequested => {
                repaint = false;
                if let Err(error) = self.redraw(event_loop) {
                    self.failed(event_loop, error);
                }
            }
            _ => {}
        }
        if repaint {
            if let Some(window) = &self.window {
                window.request_redraw();
            }
        }
    }

    fn about_to_wait(&mut self, event_loop: &ActiveEventLoop) {
        if self
            .next_repaint
            .is_some_and(|deadline| deadline <= Instant::now())
        {
            self.next_repaint = None;
            if let Some(window) = &self.window {
                window.request_redraw();
            }
        }
        event_loop.set_control_flow(
            self.next_repaint
                .map(ControlFlow::WaitUntil)
                .unwrap_or(ControlFlow::Wait),
        );
    }
}
