//! One process, two modes (P4 V3).
//!
//! Browse's helper (`--cdmw-preview-session`) runs this handler. It owns the
//! Preview state for the whole process and, while the user edits in place, an
//! edit state too. `open_session` on the editor protocol enters edit mode: the
//! Preview lends its window, its renderer (with every texture it uploaded) and
//! its camera, and the edit state installs the session into them, so nothing is
//! launched and no texture whose digest matches is uploaded again. When the
//! edit ends (Finish, Discard, Cancel or `leave_edit`), the edit state gives the
//! renderer and the camera back and the Preview shows its resident scene again.
//!
//! One stdin reader serves both states: each line names its protocol and is
//! routed by it. Both states write whole lines to stdout through their own
//! writers, each locking the stream per line.

use crate::LabApplication;
use crate::cdmw_preview::{PreviewApplication, PreviewRoute};
use crate::cdmw_session::{EditorRoute, PROTOCOL, PendingSessionInput};
use crossbeam_channel::{Receiver, Sender, TryRecvError, bounded};
use serde_json::{Value, json};
use std::io::{BufRead, BufReader, Write};
use std::thread;
use tracing::error;
use winit::application::ApplicationHandler;
use winit::event::WindowEvent;
use winit::event_loop::{ActiveEventLoop, EventLoopProxy};
use winit::window::WindowId;

/// A line on either protocol may carry a large state; the editor's bound is the larger.
const MAX_ENGINE_LINE_BYTES: usize = 256 * 1024;
const EDITOR_QUEUE_BOUND: usize = 256;

#[derive(Debug)]
enum EditorLine {
    Message(Value),
    Closed,
}

pub struct EngineApplication {
    preview: PreviewApplication,
    edit: Option<LabApplication>,
    edit_route: Option<EditorRoute>,
    editor_lines: Receiver<EditorLine>,
    parent_hwnd: u64,
    /// GPU texture uploads before the edit was entered, until it reports them.
    uploads_before_edit: Option<u64>,
    lent_camera_report: Option<Value>,
}

impl EngineApplication {
    #[must_use]
    pub fn new(
        preview: PreviewApplication,
        preview_route: PreviewRoute,
        parent_hwnd: u64,
        proxy: EventLoopProxy<()>,
    ) -> Self {
        let (editor_tx, editor_lines) = bounded(EDITOR_QUEUE_BOUND);
        spawn_engine_input(preview_route, editor_tx, proxy);
        Self {
            preview,
            edit: None,
            edit_route: None,
            editor_lines,
            parent_hwnd,
            uploads_before_edit: None,
            lent_camera_report: None,
        }
    }

    fn poll_editor_lines(&mut self) {
        loop {
            let line = match self.editor_lines.try_recv() {
                Ok(line) => line,
                Err(TryRecvError::Empty | TryRecvError::Disconnected) => return,
            };
            match line {
                EditorLine::Closed => {
                    if let Some(route) = &self.edit_route {
                        route.error("CDMW closed the control input".to_owned());
                    }
                }
                EditorLine::Message(value) => self.route_editor_message(value),
            }
        }
    }

    fn route_editor_message(&mut self, value: Value) {
        let event = value
            .get("event")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned();
        if event == "leave_edit" {
            // The host ends the edit whatever the edit state is doing.
            if self.edit.is_some() {
                self.leave_edit();
            }
            return;
        }
        if self.edit.is_none() {
            match event.as_str() {
                "open_session" => self.enter_edit(value),
                "enter_edit" => self.enter_edit_view(&value),
                // A cancel for an edit that already ended needs no answer.
                "cancel" | "close_request" => {}
                other => write_editor_line(&json!({
                    "event": "edit_refused",
                    "reason": format!("no edit is open for {other}"),
                })),
            }
            return;
        }
        if event == "open_session" && !self.edit.as_ref().is_some_and(LabApplication::showing_view)
        {
            write_editor_line(&json!({
                "event": "edit_refused",
                "reason": "an edit is already open in this viewport",
            }));
            return;
        }
        if let Some(route) = &self.edit_route
            && !route.message(value)
        {
            route.error("CDMW control queue overflowed".to_owned());
        }
    }

    /// `open_session {manifest, keep_view}` on the editor protocol.
    fn enter_edit(&mut self, open_session: Value) {
        let keep_view = open_session
            .get("keep_view")
            .and_then(Value::as_bool)
            .unwrap_or(true);
        let lent = match self.preview.lend_view() {
            Ok(lent) => lent,
            Err(reason) => {
                write_editor_line(&json!({"event": "edit_refused", "reason": reason}));
                return;
            }
        };
        self.uploads_before_edit = Some(lent.renderer.texture_upload_count());
        self.lent_camera_report = Some(crate::camera_report(&lent.camera));
        let (input, route) = PendingSessionInput::routed();
        // The edit state reads its `open_session` as a pre-started helper does.
        let _ = route.message(open_session);
        self.edit = Some(LabApplication::new_engine_edit(
            input,
            self.parent_hwnd,
            lent.window,
            lent.renderer,
            keep_view.then_some(lent.camera),
        ));
        self.edit_route = Some(route);
    }

    /// `enter_edit {keep_view}`: show the editor at once on Browse's resident
    /// model; the session follows as `open_session` (P4 V4).
    fn enter_edit_view(&mut self, value: &Value) {
        let keep_view = value
            .get("keep_view")
            .and_then(Value::as_bool)
            .unwrap_or(true);
        let parts = self.preview.view_parts();
        let lent = match self.preview.lend_view() {
            Ok(lent) => lent,
            Err(reason) => {
                write_editor_line(&json!({"event": "edit_refused", "reason": reason}));
                return;
            }
        };
        self.uploads_before_edit = Some(lent.renderer.texture_upload_count());
        self.lent_camera_report = Some(crate::camera_report(&lent.camera));
        let (input, route) = PendingSessionInput::routed();
        let (root, manifest, lod, document, textures, layers) = parts;
        let bridge = crate::cdmw_session::CdmwBridge::view_only(
            root, manifest, lod, textures, layers, input,
        );
        let mut edit = LabApplication::new_view_edit(
            self.parent_hwnd,
            lent.window,
            lent.renderer,
            keep_view.then_some(lent.camera),
        );
        let started = std::time::Instant::now();
        let shown = edit.install_view(bridge, document);
        let install_ms = started.elapsed().as_secs_f64() * 1000.0;
        self.edit = Some(edit);
        self.edit_route = Some(route);
        match shown {
            Ok(()) => {
                write_editor_line(&json!({
                    "event": "edit_viewing",
                    "install_ms": install_ms,
                    // When the view was up, by the helper's clock (CDMW may read it later).
                    "at_unix_ms": std::time::SystemTime::now()
                        .duration_since(std::time::UNIX_EPOCH)
                        .map_or(0, |since| since.as_millis() as u64),
                }));
            }
            Err(error) => {
                write_editor_line(&json!({"event": "edit_refused", "reason": error.to_string()}));
                self.leave_edit();
            }
        }
    }

    fn leave_edit(&mut self) {
        let Some(mut edit) = self.edit.take() else {
            return;
        };
        self.edit_route = None;
        self.uploads_before_edit = None;
        let (renderer, camera) = edit.give_back_view();
        drop(edit);
        self.preview.return_view(renderer, Some(camera));
        write_editor_line(&json!({"event": "edit_left"}));
    }

    fn leave_if_requested(&mut self) {
        if self
            .edit
            .as_ref()
            .is_some_and(LabApplication::engine_leave_requested)
        {
            self.leave_edit();
        }
    }
}

impl ApplicationHandler for EngineApplication {
    fn resumed(&mut self, event_loop: &ActiveEventLoop) {
        // The window and renderer are the Preview's; an edit borrows them.
        self.preview.resumed(event_loop);
    }

    fn window_event(
        &mut self,
        event_loop: &ActiveEventLoop,
        window_id: WindowId,
        event: WindowEvent,
    ) {
        if let Some(edit) = &mut self.edit {
            edit.window_event(event_loop, window_id, event);
            self.leave_if_requested();
        } else {
            self.preview.window_event(event_loop, window_id, event);
        }
    }

    fn about_to_wait(&mut self, event_loop: &ActiveEventLoop) {
        self.poll_editor_lines();
        // While editing, the Preview only reads its messages and loads; the edit
        // state draws and sets the wait.
        self.preview.about_to_wait(event_loop);
        if let Some(edit) = &mut self.edit {
            edit.about_to_wait(event_loop);
            // Once the session is installed: how many textures entering uploaded.
            if let Some(before) = self.uploads_before_edit
                && let Some((after, retained)) = edit.engine_installed_uploads()
            {
                self.uploads_before_edit = None;
                let mut report = json!({
                    "event": "edit_entered",
                    "texture_uploads_before": before,
                    "texture_uploads_after": after,
                    "retained_entries": retained.entries,
                    "retained_unpinned_bytes": retained.unpinned_bytes,

                });
                // The camera before and after, flat for the runtime record.
                if let (Some(object), Value::Object(browse), Value::Object(edit_camera)) = (
                    report.as_object_mut(),
                    self.lent_camera_report.take().unwrap_or(Value::Null),
                    edit.engine_camera_report(),
                ) {
                    for (key, value) in browse {
                        object.insert(format!("browse_camera_{key}"), value);
                    }
                    for (key, value) in edit_camera {
                        object.insert(format!("edit_camera_{key}"), value);
                    }
                }
                write_editor_line(&report);
            }
        }
        self.leave_if_requested();
    }
}

/// The one stdin reader of an engine process: each line goes to the state its
/// protocol names.
fn spawn_engine_input(
    preview: PreviewRoute,
    editor: Sender<EditorLine>,
    proxy: EventLoopProxy<()>,
) {
    let spawned = thread::Builder::new()
        .name("cdmw-engine-input".to_owned())
        .spawn(move || {
            let stdin = std::io::stdin();
            let mut reader = BufReader::new(stdin.lock());
            loop {
                let mut line = Vec::new();
                match reader.read_until(b'\n', &mut line) {
                    Ok(0) => break,
                    Ok(_) if line.len() > MAX_ENGINE_LINE_BYTES => {
                        preview.error("Preview protocol line exceeded its safety limit".to_owned());
                        break;
                    }
                    Ok(_) => {
                        while matches!(line.last(), Some(b'\n' | b'\r')) {
                            line.pop();
                        }
                        if line.is_empty() {
                            continue;
                        }
                        match serde_json::from_slice::<Value>(&line) {
                            Ok(value) => {
                                if is_editor_line(&value) {
                                    if editor.try_send(EditorLine::Message(value)).is_err() {
                                        preview.error("CDMW control queue overflowed".to_owned());
                                    }
                                } else {
                                    preview.message(value);
                                }
                            }
                            Err(error) => {
                                preview.error(format!("Preview received invalid JSON: {error}"));
                            }
                        }
                        let _ = proxy.send_event(());
                    }
                    Err(error) => {
                        preview.error(format!("Preview input failed: {error}"));
                        break;
                    }
                }
            }
            preview.closed();
            let _ = editor.send(EditorLine::Closed);
            let _ = proxy.send_event(());
        });
    if let Err(spawn_error) = spawned {
        error!("engine input thread could not start: {spawn_error}");
    }
}

/// Lines on the editor protocol go to the edit state; everything else is the Preview's.
fn is_editor_line(value: &Value) -> bool {
    value.get("protocol").and_then(Value::as_str) == Some(PROTOCOL)
}

/// A line the engine itself says on the editor protocol (`edit_left`, `edit_refused`).
fn write_editor_line(value: &Value) {
    let mut value = value.clone();
    if let Some(object) = value.as_object_mut() {
        object.insert("protocol".to_owned(), json!(PROTOCOL));
        object.insert("process_id".to_owned(), json!(std::process::id()));
    }
    let Ok(mut line) = serde_json::to_vec(&value) else {
        return;
    };
    line.push(b'\n');
    let stdout = std::io::stdout();
    let mut output = stdout.lock();
    let _ = output.write_all(&line).and_then(|()| output.flush());
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn each_line_goes_to_the_state_its_protocol_names() {
        assert!(is_editor_line(
            &json!({"protocol": PROTOCOL, "event": "open_session"})
        ));
        assert!(!is_editor_line(&json!({
            "protocol": crate::cdmw_session::PREVIEW_PROTOCOL,
            "event": "package_load_request",
        })));
        // A line without a protocol is the Preview's, which refuses it as it always has.
        assert!(!is_editor_line(&json!({"event": "cancel"})));
    }
}
