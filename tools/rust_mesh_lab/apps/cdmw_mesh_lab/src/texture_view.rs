//! Dedicated, read-only embedded texture mode; no mesh document or edit bridge.
use anyhow::{Context, Result, bail};
use cdmw_render_wgpu::texture_view::{TextureViewState, TextureViewer};
use crossbeam_channel::{Receiver, bounded};
use serde::Deserialize;
use serde_json::json;
use std::io::{BufRead, Read, Write};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Instant;
use winit::application::ApplicationHandler;
use winit::event::{ElementState, MouseButton, MouseScrollDelta, WindowEvent};
use winit::event_loop::{ActiveEventLoop, ControlFlow, EventLoop};
use winit::window::{Window, WindowId};

const MAX_LINE: usize = 64 * 1024;

fn stepped_zoom(zoom: f32, delta: f32) -> f32 {
    const STEPS: [f32; 13] = [
        0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0, 16.0,
    ];
    let index = STEPS
        .iter()
        .enumerate()
        .min_by(|(_, a), (_, b)| (**a - zoom).abs().total_cmp(&(**b - zoom).abs()))
        .map_or(0, |(index, _)| index);
    STEPS[if delta > 0.0 {
        (index + 1).min(STEPS.len() - 1)
    } else if delta < 0.0 {
        index.saturating_sub(1)
    } else {
        index
    }]
}

#[derive(Debug, Deserialize)]
#[serde(tag = "command", rename_all = "snake_case", deny_unknown_fields)]
enum Command {
    Load {
        generation: u64,
        path: PathBuf,
    },
    View {
        generation: u64,
        state: TextureViewState,
    },
    Resize {
        width: u32,
        height: u32,
    },
    Close,
}

fn read_dds(path: &Path) -> Result<Vec<u8>> {
    if !path.is_absolute() {
        bail!("DDS path must be absolute");
    }
    let file = std::fs::File::open(path)?;
    let limit = cdmw_texture::DDS_MAX_PAYLOAD_BYTES;
    if file.metadata()?.len() > limit as u64 {
        bail!("DDS exceeds 512 MiB");
    }
    let mut bytes = Vec::new();
    file.take(limit as u64 + 1).read_to_end(&mut bytes)?;
    if bytes.len() > limit {
        bail!("DDS exceeds 512 MiB");
    }
    Ok(bytes)
}

fn emit(value: serde_json::Value) {
    let mut out = std::io::stdout().lock();
    let _ = writeln!(out, "{value}");
    let _ = out.flush();
}

pub fn try_run() -> Result<bool> {
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    if args.first().is_some_and(|a| a == "--capture-dds-texture") {
        if args.len() != 3 {
            bail!("--capture-dds-texture <dds> <png> requires exactly two paths");
        }
        let output = Path::new(&args[2]);
        if !output
            .extension()
            .is_some_and(|value| value.eq_ignore_ascii_case("png"))
            || output.exists()
        {
            bail!("DDS capture requires a new PNG output path");
        }
        let started = Instant::now();
        let bytes = read_dds(Path::new(&args[1]))?;
        let mut viewer = pollster::block_on(TextureViewer::new(None))?;
        let metadata = viewer.load(&bytes)?;
        let size = [metadata.width.min(4096), metadata.height.min(4096)];
        let pixels = viewer.capture(size, TextureViewState::default())?;
        let elapsed = started.elapsed().as_secs_f64() * 1000.0;
        emit(json!({"event":"frame_ready", "milliseconds":elapsed, "metadata":metadata}));
        let file = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(output)?;
        let mut encoder = png::Encoder::new(file, size[0], size[1]);
        encoder.set_color(png::ColorType::Rgba);
        encoder.set_depth(png::BitDepth::Eight);
        encoder.write_header()?.write_image_data(&pixels)?;
        emit(json!({"event":"captured", "milliseconds":elapsed, "metadata":metadata}));
        return Ok(true);
    }
    if !args.first().is_some_and(|a| a == "--cdmw-texture-view") {
        return Ok(false);
    }
    if args.len() != 3 || args[1] != "--embedded-parent-hwnd" {
        bail!("--cdmw-texture-view requires --embedded-parent-hwnd <decimal>");
    }
    let parent: u64 = args[2].to_str().context("invalid parent HWND")?.parse()?;
    if parent == 0 {
        bail!("invalid parent HWND");
    }
    let event_loop = EventLoop::<()>::with_user_event().build()?;
    event_loop.set_control_flow(ControlFlow::Wait);
    let proxy = event_loop.create_proxy();
    let (sender, commands) = bounded(32);
    std::thread::spawn(move || {
        let mut input = std::io::BufReader::new(std::io::stdin());
        loop {
            let mut line = Vec::new();
            let count = input
                .by_ref()
                .take(MAX_LINE as u64 + 1)
                .read_until(b'\n', &mut line);
            let command = match count {
                Ok(0) | Err(_) => Command::Close,
                Ok(_) if line.len() > MAX_LINE => Command::Close,
                Ok(_) => match serde_json::from_slice(&line) {
                    Ok(command) => command,
                    Err(error) => {
                        emit(json!({"event":"error", "generation":0, "message":error.to_string()}));
                        continue;
                    }
                },
            };
            let close = matches!(command, Command::Close);
            if sender.send(command).is_err() {
                break;
            }
            if proxy.send_event(()).is_err() || close {
                break;
            }
        }
    });
    let mut app = TextureApplication {
        parent,
        commands,
        window: None,
        viewer: None,
        state: TextureViewState::default(),
        generation: 0,
        mips: 1,
        image_size: [1; 2],
        cursor: [0.0; 2],
        dragging: false,
        pending_loaded: None,
    };
    event_loop.run_app(&mut app)?;
    Ok(true)
}

struct TextureApplication {
    parent: u64,
    commands: Receiver<Command>,
    window: Option<Arc<Window>>,
    viewer: Option<TextureViewer>,
    state: TextureViewState,
    generation: u64,
    mips: u32,
    image_size: [u32; 2],
    cursor: [f32; 2],
    dragging: bool,
    pending_loaded: Option<(Instant, serde_json::Value)>,
}

impl TextureApplication {
    fn fail(&self, error: impl std::fmt::Display) {
        emit(json!({"event":"error", "generation":self.generation, "message":error.to_string()}));
    }
    fn view_changed(&self) {
        emit(json!({"event":"view", "generation":self.generation, "state":self.state}));
        if let Some(window) = &self.window {
            window.request_redraw();
        }
    }
    fn unfit(&mut self) {
        if self.state.fit {
            if let Some(window) = &self.window {
                let size = window.inner_size();
                self.state.zoom = ((size.width as f32
                    / (self.image_size[0] >> self.state.mip).max(1) as f32)
                    .min(
                        size.height as f32 / (self.image_size[1] >> self.state.mip).max(1) as f32,
                    )
                    / self.state.pixel_ratio)
                    .clamp(0.1, 16.0);
            }
            self.state.fit = false;
        }
    }
    fn command(&mut self, command: Command, event_loop: &ActiveEventLoop) -> Result<()> {
        match command {
            Command::Close => event_loop.exit(),
            Command::Resize { width, height } => {
                if width == 0 || height == 0 || width > 16384 || height > 16384 {
                    bail!("invalid viewport size");
                }
                if let Some(window) = &self.window {
                    let _ = window.request_inner_size(winit::dpi::PhysicalSize::new(width, height));
                }
            }
            Command::Load { generation, path } => {
                if generation <= self.generation {
                    return Ok(());
                }
                self.generation = generation;
                let started = Instant::now();
                let bytes = read_dds(&path)?;
                let metadata = self
                    .viewer
                    .as_mut()
                    .context("texture renderer is not ready")?
                    .load(&bytes)?;
                self.state = TextureViewState::default();
                self.mips = metadata.mip_count;
                self.image_size = [metadata.width, metadata.height];
                emit(
                    json!({"event":"uploaded", "generation":self.generation, "metadata":metadata,
                    "milliseconds":started.elapsed().as_secs_f64()*1000.0}),
                );
                self.pending_loaded = Some((started, serde_json::to_value(metadata)?));
                if let Some(window) = &self.window {
                    window.set_visible(true);
                    window.request_redraw();
                }
            }
            Command::View { generation, state } => {
                if generation != self.generation {
                    return Ok(());
                }
                state.validate(self.mips)?;
                self.state = state;
                self.view_changed();
            }
        }
        Ok(())
    }
}

impl ApplicationHandler<()> for TextureApplication {
    fn resumed(&mut self, event_loop: &ActiveEventLoop) {
        let result = (|| -> Result<()> {
            let attributes = cdmw_win32_embed::with_parent_window(
                Window::default_attributes()
                    .with_title("CDMW Texture Preview")
                    .with_decorations(false)
                    .with_visible(false)
                    .with_position(winit::dpi::PhysicalPosition::new(0, 0))
                    .with_inner_size(winit::dpi::PhysicalSize::new(640, 480)),
                self.parent,
            )?;
            let window = Arc::new(event_loop.create_window(attributes)?);
            self.viewer = Some(pollster::block_on(TextureViewer::new(Some(
                window.clone(),
            )))?);
            let hwnd = cdmw_win32_embed::window_hwnd(&window)?;
            self.window = Some(window);
            emit(json!({"event":"ready", "protocol":"cdmw_texture_view_v1", "hwnd":hwnd}));
            Ok(())
        })();
        if let Err(error) = result {
            self.fail(error);
            event_loop.exit();
        }
    }
    fn user_event(&mut self, event_loop: &ActiveEventLoop, (): ()) {
        while let Ok(command) = self.commands.try_recv() {
            if let Err(error) = self.command(command, event_loop) {
                self.fail(error);
            }
        }
    }
    fn window_event(&mut self, event_loop: &ActiveEventLoop, _id: WindowId, event: WindowEvent) {
        match event {
            WindowEvent::CloseRequested => event_loop.exit(),
            WindowEvent::Resized(size) => {
                if let Some(viewer) = &mut self.viewer {
                    viewer.resize(size.width, size.height);
                }
                if let Some(window) = &self.window {
                    window.request_redraw();
                }
            }
            WindowEvent::RedrawRequested => {
                if self.generation == 0 {
                    return;
                }
                if let Some(viewer) = &mut self.viewer {
                    match viewer.render(self.state) {
                        Err(error) => {
                            self.fail(error);
                            event_loop.exit();
                            return;
                        }
                        Ok(false) => {
                            event_loop.set_control_flow(ControlFlow::WaitUntil(
                                Instant::now() + std::time::Duration::from_millis(100),
                            ));
                            return;
                        }
                        Ok(true) => event_loop.set_control_flow(ControlFlow::Wait),
                    }
                    if let Some((started, metadata)) = self.pending_loaded.take() {
                        if let Some(window) = &self.window {
                            window.set_visible(true);
                        }
                        emit(
                            json!({"event":"loaded", "generation":self.generation, "metadata":metadata,
                            "milliseconds":started.elapsed().as_secs_f64()*1000.0}),
                        );
                    }
                }
            }
            WindowEvent::MouseInput {
                state,
                button: MouseButton::Left | MouseButton::Middle,
                ..
            } => {
                self.dragging = state == ElementState::Pressed;
            }
            WindowEvent::CursorMoved { position, .. } => {
                let cursor = [position.x as f32, position.y as f32];
                if self.dragging {
                    self.unfit();
                    for (i, value) in cursor.iter().enumerate() {
                        self.state.pan[i] = (self.state.pan[i] + value - self.cursor[i])
                            .clamp(-1_000_000.0, 1_000_000.0);
                    }
                    self.view_changed();
                }
                self.cursor = cursor;
            }
            WindowEvent::MouseWheel { delta, .. } => {
                let delta = match delta {
                    MouseScrollDelta::LineDelta(_, y) => y,
                    MouseScrollDelta::PixelDelta(p) => p.y as f32 / 120.0,
                };
                self.unfit();
                self.state.zoom = stepped_zoom(self.state.zoom, delta);
                self.view_changed();
            }
            _ => {}
        }
    }
    fn new_events(&mut self, _event_loop: &ActiveEventLoop, cause: winit::event::StartCause) {
        if matches!(cause, winit::event::StartCause::ResumeTimeReached { .. }) {
            if let Some(window) = &self.window {
                window.request_redraw();
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn texture_protocol_rejects_unknown_commands_fields_and_invalid_views() {
        assert_eq!(stepped_zoom(1.0, 1.0), 1.5);
        assert_eq!(stepped_zoom(1.0, -1.0), 0.75);
        assert_eq!(stepped_zoom(16.0, 1.0), 16.0);
        assert!(
            serde_json::from_str::<Command>(
                r#"{"command":"load","generation":1,"path":"a.dds","write":true}"#
            )
            .is_err()
        );
        assert!(serde_json::from_str::<Command>(r#"{"command":"save"}"#).is_err());
        let mut state = TextureViewState::default();
        assert!(state.validate(1).is_ok());
        state.mip = 1;
        assert!(state.validate(1).is_err());
        state.mip = 0;
        state.channel = 5;
        assert!(state.validate(1).is_err());
        state.channel = 0;
        state.zoom = f32::NAN;
        assert!(state.validate(1).is_err());
        state.zoom = 1.0;
        state.pan[0] = f32::INFINITY;
        assert!(state.validate(1).is_err());
        state.pan[0] = 0.0;
        state.pixel_ratio = 0.0;
        assert!(state.validate(1).is_err());
        assert!(read_dds(Path::new("relative.dds")).is_err());
    }

    fn block_dds(dxgi: u32, block: &[u8]) -> Vec<u8> {
        let mut bytes = vec![0; 148];
        bytes[..4].copy_from_slice(b"DDS ");
        for (offset, value) in [
            (4, 124_u32),
            (12, 4),
            (16, 4),
            (28, 1),
            (76, 32),
            (80, 4),
            (128, dxgi),
            (132, 3),
            (140, 1),
        ] {
            bytes[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
        }
        bytes[84..88].copy_from_slice(b"DX10");
        bytes.extend_from_slice(block);
        bytes
    }

    fn bc7_solid() -> [u8; 16] {
        let mut block = [0_u8; 16];
        let mut offset = 0;
        let mut put = |value: u32, count: usize| {
            for i in 0..count {
                block[(offset + i) / 8] |= (((value >> i) & 1) as u8) << ((offset + i) % 8);
            }
            offset += count;
        };
        put(64, 7); // Mode 6; endpoints share one p-bit each.
        for value in [64, 64, 32, 32, 16, 16, 127, 127] {
            put(value, 7);
        }
        put(1, 1);
        put(1, 1);
        block // Constant (129,65,33,255), every selector zero.
    }

    #[test]
    #[ignore = "requires a BC-capable D3D12 GPU"]
    fn texture_view_gpu_known_bc1_bc5_bc7_channels_mips_and_pan() -> Result<()> {
        let mut viewer = pollster::block_on(TextureViewer::new(None))?;
        let state = TextureViewState::default();
        let bc1 = block_dds(71, &[0, 248, 0, 0, 0, 0, 0, 0]);
        let bc5 = block_dds(83, &[128, 128, 0, 0, 0, 0, 0, 0, 64, 64, 0, 0, 0, 0, 0, 0]);
        let bc7 = block_dds(99, &bc7_solid()); // sRGB-tagged: channels must still be raw.
        for (dds, expected) in [
            (&bc1, [255, 0, 0]),
            (&bc5, [128, 64, 0]),
            (&bc7, [129, 65, 33]),
        ] {
            viewer.load(dds)?;
            let pixels = viewer.capture([4, 4], state)?;
            for pixel in pixels.chunks_exact(4) {
                for i in 0..3 {
                    assert!(
                        (i32::from(pixel[i]) - expected[i]).abs() <= 1,
                        "{pixel:?} != {expected:?}"
                    );
                }
            }
        }
        for channel in 1..=4 {
            let pixels = viewer.capture([4, 4], TextureViewState { channel, ..state })?;
            let expected = [129, 65, 33, 255][channel as usize - 1];
            assert!(
                pixels
                    .chunks_exact(4)
                    .all(|p| p[..3].iter().all(|c| (i32::from(*c) - expected).abs() <= 1))
            );
        }
        viewer.load(&bc5)?;
        let pixels = viewer.capture(
            [4, 4],
            TextureViewState {
                reconstruct_z: true,
                ..state
            },
        )?;
        assert!(
            (237..=239).contains(&pixels[2]),
            "normal Z: {:?}",
            &pixels[..4]
        );
        viewer.load(&block_dds(
            84,
            &[129, 129, 0, 0, 0, 0, 0, 0, 127, 127, 0, 0, 0, 0, 0, 0],
        ))?;
        for (channel, expected) in [(1, 0), (2, 255)] {
            assert_eq!(
                viewer.capture([4, 4], TextureViewState { channel, ..state })?[0],
                expected
            );
        }
        let mut mips = bc1.clone();
        mips[28..32].copy_from_slice(&2_u32.to_le_bytes());
        mips.extend_from_slice(&[224, 7, 0, 0, 0, 0, 0, 0]); // Green second mip.
        viewer.load(&mips)?;
        assert_eq!(
            &viewer.capture([2, 2], TextureViewState { mip: 1, ..state })?[..3],
            &[0, 255, 0]
        );
        let panned = viewer.capture(
            [8, 4],
            TextureViewState {
                fit: false,
                pan: [2.0, 0.0],
                ..state
            },
        )?;
        assert_eq!(&panned[4 * 6..4 * 7], &[255, 0, 0, 255]);
        assert_ne!(&panned[..3], &[255, 0, 0]);
        let hidpi = viewer.capture(
            [8, 8],
            TextureViewState {
                fit: false,
                pixel_ratio: 2.0,
                ..state
            },
        )?;
        assert!(hidpi.chunks_exact(4).all(|p| p == [255, 0, 0, 255]));
        viewer.load(&block_dds(61, &[128; 16]))?; // R8 is grayscale in RGB, but absent G stays zero.
        assert_eq!(&viewer.capture([4, 4], state)?[..3], &[128, 128, 128]);
        assert_eq!(
            &viewer.capture(
                [4, 4],
                TextureViewState {
                    channel: 2,
                    ..state
                }
            )?[..3],
            &[0, 0, 0]
        );
        Ok(())
    }
}
