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
//! An edit can also have a window of its own (P4 V5): `open_session` with
//! `viewport: "own"` and a `parent_hwnd` makes a child window under that parent
//! (the Mesh Editor tab) with a renderer on the Preview's device, so the tab's
//! editor is not a process of its own. Browse's view keeps drawing meanwhile;
//! window events go to the window they name, and leaving closes the edit's
//! window instead of giving a view back.
//!
//! Other previews can be windows of this process too (P4 V5): a
//! `viewport_open {viewport_id, manifest, parent_hwnd}` line on the preview
//! protocol opens another preview state with a child window under that parent,
//! drawn on the same device. Every line it writes names its `viewport_id`, and a
//! line naming it is routed to it (sessions follow the packages they load, so
//! they are not unique). Closing it (`close_request` naming it) drops its window
//! and says `viewport_closed`; the process keeps running.
//!
//! Create New Item and Mod Management pages can be windows of it as well: a
//! `page_open {page_id, manifest, parent_hwnd}` line on the New Item UI protocol
//! opens the page under that parent on the same device; its lines name its
//! `page_id` both ways, and `page_close` naming it drops it (`page_closed`).
//!
//! One stdin reader serves every state: each line names its protocol and is
//! routed by it, a preview line also by its session. Both states write whole lines to stdout through their own
//! writers, each locking the stream per line.

use crate::LabApplication;
use crate::cdmw_preview::{PreviewApplication, PreviewRoute};
use crate::cdmw_session::{EditorRoute, PROTOCOL, PendingSessionInput};
use cdmw_render_wgpu::WindowRenderer;
use crossbeam_channel::{Receiver, Sender, TryRecvError, bounded};
use serde_json::{Value, json};
use std::collections::HashMap;
use std::io::{BufRead, BufReader, Write};
use std::sync::{Arc, Mutex};
use std::thread;
use tracing::error;
use winit::application::ApplicationHandler;
use winit::event::WindowEvent;
use winit::event_loop::{ActiveEventLoop, ControlFlow, EventLoopProxy};
use winit::window::{WindowAttributes, WindowId};

/// A line on either protocol may carry a large state; the editor's bound is the larger.
const MAX_ENGINE_LINE_BYTES: usize = 256 * 1024;
const EDITOR_QUEUE_BOUND: usize = 256;

#[derive(Debug)]
enum EditorLine {
    Message(Value),
    /// `viewport_open`: the engine opens another preview state.
    Viewport(Value),
    /// `page_open` or `page_close` on the New Item UI protocol.
    Page(Value),
    Closed,
}

/// Preview routes by viewport id, shared with the stdin reader.
type PreviewRoutes = Arc<Mutex<HashMap<String, PreviewRoute>>>;
/// Page inputs by page id, shared with the stdin reader.
type PageRoutes = Arc<Mutex<HashMap<String, std::sync::mpsc::SyncSender<Result<Value, String>>>>>;
const PAGE_PROTOCOL: &str = crate::new_item_ui::PROTOCOL;

pub struct EngineApplication {
    preview: PreviewApplication,
    /// Other previews' windows in this process (P4 V5).
    viewports: Vec<PreviewApplication>,
    routes: PreviewRoutes,
    /// Create New Item and Mod Management pages in this process (P4 V5).
    pages: Vec<crate::new_item_ui::Application>,
    page_routes: PageRoutes,
    proxy: EventLoopProxy<()>,
    edit: Option<LabApplication>,
    edit_route: Option<EditorRoute>,
    editor_lines: Receiver<EditorLine>,
    parent_hwnd: u64,
    /// GPU texture uploads before the edit was entered, until it reports them.
    uploads_before_edit: Option<u64>,
    /// The edit's own window, when it has one instead of Browse's.
    edit_window: Option<WindowId>,
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
        let routes = PreviewRoutes::default();
        let page_routes = PageRoutes::default();
        spawn_engine_input(
            preview_route,
            Arc::clone(&routes),
            Arc::clone(&page_routes),
            editor_tx,
            proxy.clone(),
        );
        Self {
            preview,
            viewports: Vec::new(),
            routes,
            pages: Vec::new(),
            page_routes,
            proxy,
            edit: None,
            edit_route: None,
            editor_lines,
            parent_hwnd,
            uploads_before_edit: None,
            edit_window: None,
            lent_camera_report: None,
        }
    }

    fn poll_editor_lines(&mut self, event_loop: &ActiveEventLoop) {
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
                EditorLine::Message(value) => self.route_editor_message(value, event_loop),
                EditorLine::Viewport(value) => self.open_viewport(&value, event_loop),
                EditorLine::Page(value) => self.page_line(&value, event_loop),
            }
        }
    }

    fn route_editor_message(&mut self, value: Value, event_loop: &ActiveEventLoop) {
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
        if event == "promote_edit" {
            self.promote_edit(&value, event_loop);
            return;
        }
        if self.edit.is_none() {
            match event.as_str() {
                "open_session" if own_viewport_parent(&value).is_some() => {
                    self.enter_edit_own_window(value, event_loop);
                }
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

    /// `viewport_open {viewport_id, manifest, parent_hwnd}`: another preview's
    /// window in this process, on the main preview's device.
    fn open_viewport(&mut self, value: &Value, event_loop: &ActiveEventLoop) {
        let viewport_id = value
            .get("viewport_id")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned();
        let refuse = |reason: String| {
            write_preview_line(&json!({
                "event": "viewport_refused",
                "viewport_id": viewport_id,
                "reason": reason,
            }));
        };
        let manifest = value
            .get("manifest")
            .and_then(Value::as_str)
            .unwrap_or_default();
        let parent_hwnd = value
            .get("parent_hwnd")
            .and_then(Value::as_u64)
            .unwrap_or(0);
        if viewport_id.is_empty() || manifest.is_empty() || parent_hwnd == 0 {
            return refuse(
                "viewport_open needs a viewport id, a manifest and a parent window".to_owned(),
            );
        }
        if self
            .viewports
            .iter()
            .any(|view| view.viewport_id() == Some(viewport_id.as_str()))
        {
            return refuse("that viewport is already open here".to_owned());
        }
        let Some(gpu) = self.preview.shared_gpu() else {
            return refuse("the preview's renderer is not ready".to_owned());
        };
        let (mut viewport, route) = match PreviewApplication::open_routed(
            std::path::Path::new(manifest),
            parent_hwnd,
            self.proxy.clone(),
        ) {
            Ok(opened) => opened,
            Err(error) => return refuse(format!("{error:#}")),
        };
        viewport.make_secondary(gpu, viewport_id.clone());
        if let Ok(mut routes) = self.routes.lock() {
            routes.insert(viewport_id, route);
        }
        // Its window, renderer and `protocol_ready`/`ready`, as a launch does.
        viewport.resume(event_loop);
        self.viewports.push(viewport);
    }

    /// `page_open {page_id, manifest, parent_hwnd}` or `page_close {page_id}`.
    fn page_line(&mut self, value: &Value, event_loop: &ActiveEventLoop) {
        let page_id = value
            .get("page_id")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned();
        if value.get("type").and_then(Value::as_str) == Some("page_close") {
            for page in &mut self.pages {
                if page.page_id() == Some(page_id.as_str()) {
                    page.close_in_engine();
                }
            }
            return;
        }
        let refuse = |reason: String| {
            write_page_line(&json!({"type": "page_refused", "page_id": page_id, "reason": reason}));
        };
        let manifest = value
            .get("manifest")
            .and_then(Value::as_str)
            .unwrap_or_default();
        let parent_hwnd = value
            .get("parent_hwnd")
            .and_then(Value::as_u64)
            .unwrap_or(0);
        if page_id.is_empty() || manifest.is_empty() || parent_hwnd == 0 {
            return refuse("page_open needs a page id, a manifest and a parent window".to_owned());
        }
        if self
            .pages
            .iter()
            .any(|page| page.page_id() == Some(page_id.as_str()))
        {
            return refuse("that page is already open here".to_owned());
        }
        let Some(gpu) = self.preview.shared_gpu() else {
            return refuse("the preview's renderer is not ready".to_owned());
        };
        let (mut page, input) = match crate::new_item_ui::open_in_engine(
            std::path::Path::new(manifest),
            parent_hwnd,
            page_id.clone(),
            gpu,
        ) {
            Ok(opened) => opened,
            Err(error) => return refuse(format!("{error:#}")),
        };
        if let Ok(mut routes) = self.page_routes.lock() {
            routes.insert(page_id, input);
        }
        ApplicationHandler::resumed(&mut page, event_loop);
        self.pages.push(page);
    }

    /// Poll every page's input, let each set its wait, and drop the closed ones.
    fn wait_pages(&mut self, event_loop: &ActiveEventLoop, mut flow: ControlFlow) -> ControlFlow {
        for page in &mut self.pages {
            ApplicationHandler::user_event(page, event_loop, ());
            ApplicationHandler::about_to_wait(page, event_loop);
            flow = earliest(flow, event_loop.control_flow());
        }
        let (closed, open): (Vec<_>, Vec<_>) = std::mem::take(&mut self.pages)
            .into_iter()
            .partition(crate::new_item_ui::Application::is_closed);
        self.pages = open;
        for page in closed {
            let page_id = page.page_id().unwrap_or_default().to_owned();
            if let Ok(mut routes) = self.page_routes.lock() {
                routes.remove(&page_id);
            }
            drop(page);
            write_page_line(&json!({"type": "page_closed", "page_id": page_id}));
        }
        flow
    }

    /// Other viewports showing the edited file follow the edit read-only (P4 V5).
    /// Browse's own view does not while it is the edit's view.
    fn follow_edit(&mut self) {
        let Some(edit) = self.edit.as_mut() else {
            return;
        };
        let Some((path, revision, mesh)) = edit.mesh_for_followers(std::time::Instant::now())
        else {
            return;
        };
        let parts = mesh.submesh_indices().len();
        for preview in std::iter::once(&mut self.preview).chain(self.viewports.iter_mut()) {
            if preview.can_follow(&path, parts) {
                preview.follow(revision, mesh);
            }
        }
    }

    /// Drop the viewports that closed; CDMW hears `viewport_closed` for each.
    fn drop_closed_viewports(&mut self) {
        let (closed, open): (Vec<_>, Vec<_>) = std::mem::take(&mut self.viewports)
            .into_iter()
            .partition(PreviewApplication::wants_close);
        self.viewports = open;
        for viewport in closed {
            let viewport_id = viewport.viewport_id().unwrap_or_default().to_owned();
            if let Ok(mut routes) = self.routes.lock() {
                routes.remove(&viewport_id);
            }
            drop(viewport);
            write_preview_line(&json!({"event": "viewport_closed", "viewport_id": viewport_id}));
        }
    }

    /// `open_session {manifest, viewport: "own", parent_hwnd}`: the edit gets a
    /// child window of its own under `parent_hwnd`, drawn on the Preview's device.
    fn enter_edit_own_window(&mut self, open_session: Value, event_loop: &ActiveEventLoop) {
        let Some(parent_hwnd) = own_viewport_parent(&open_session) else {
            return;
        };
        let refuse = |reason: String| {
            write_editor_line(&json!({"event": "edit_refused", "reason": reason}));
        };
        let (window, renderer) = match self.editor_window_under(parent_hwnd, event_loop) {
            Ok(made) => made,
            Err(reason) => return refuse(reason),
        };
        let (input, route) = PendingSessionInput::routed();
        let _ = route.message(open_session);
        self.uploads_before_edit = Some(renderer.texture_upload_count());
        self.edit_window = Some(window.id());
        self.edit = Some(LabApplication::new_engine_edit(
            input,
            parent_hwnd,
            window,
            renderer,
            None,
        ));
        self.edit_route = Some(route);
    }

    /// A child window under `parent_hwnd` with a renderer on the Preview's device.
    fn editor_window_under(
        &self,
        parent_hwnd: u64,
        event_loop: &ActiveEventLoop,
    ) -> Result<(Arc<winit::window::Window>, WindowRenderer), String> {
        let gpu = self
            .preview
            .shared_gpu()
            .ok_or("the preview's renderer is not ready")?;
        let attributes = cdmw_win32_embed::with_parent_window(
            WindowAttributes::default()
                .with_title("CDMW — Mesh Editor")
                .with_decorations(false)
                .with_visible(false),
            parent_hwnd,
        )
        .map_err(|error| format!("the editor's parent window is invalid: {error}"))?;
        let window = event_loop
            .create_window(attributes)
            .map(Arc::new)
            .map_err(|error| format!("the editor's window could not be created: {error}"))?;
        let renderer = WindowRenderer::new_on(&gpu, window.clone())
            .map_err(|error| format!("the editor's renderer could not start: {error}"))?;
        Ok((window, renderer))
    }

    /// `promote_edit {parent_hwnd}` (Promote to tab): the edit in Browse's view
    /// moves into a window of its own under `parent_hwnd`, without reopening, and
    /// Browse gets its view back. Answers `edit_promoted {child_hwnd}`.
    fn promote_edit(&mut self, value: &Value, event_loop: &ActiveEventLoop) {
        let refuse = |reason: String| {
            write_editor_line(&json!({"event": "promote_refused", "reason": reason}));
        };
        if self.edit.is_none() || self.edit_window.is_some() {
            return refuse("no edit in Browse's view to move".to_owned());
        }
        let Some(parent_hwnd) = value
            .get("parent_hwnd")
            .and_then(Value::as_u64)
            .filter(|hwnd| *hwnd != 0)
        else {
            return refuse("promote_edit needs a parent window".to_owned());
        };
        let (window, renderer) = match self.editor_window_under(parent_hwnd, event_loop) {
            Ok(made) => made,
            Err(reason) => return refuse(reason),
        };
        let Some(edit) = self.edit.as_mut() else {
            return;
        };
        match edit.move_to_window(window.clone(), renderer, parent_hwnd) {
            Ok((lent, camera)) => {
                self.preview.return_view(lent, Some(camera));
                self.edit_window = Some(window.id());
                let child_hwnd = cdmw_win32_embed::window_hwnd(window.as_ref()).unwrap_or(0);
                write_editor_line(&json!({
                    "event": "edit_promoted",
                    "child_hwnd": child_hwnd,
                    "embedded_parent_hwnd": parent_hwnd,
                }));
            }
            Err(reason) => refuse(reason),
        }
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
        if self.edit_window.take().is_some() {
            // Its own window and renderer close with it; Browse's view was never lent.
            drop(edit);
            write_editor_line(&json!({"event": "edit_left"}));
            return;
        }
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
        // An edit in Browse's view gets that window's events; one in its own
        // window gets only those of its window.
        let to_edit = self
            .edit
            .as_ref()
            .is_some_and(|_| self.edit_window.is_none_or(|own| own == window_id));
        if to_edit && let Some(edit) = &mut self.edit {
            edit.window_event(event_loop, window_id, event);
            self.leave_if_requested();
        } else if let Some(viewport) = self
            .viewports
            .iter_mut()
            .find(|view| view.window_id() == Some(window_id))
        {
            viewport.route_window_event(event_loop, window_id, event);
        } else if let Some(page) = self
            .pages
            .iter_mut()
            .find(|page| page.window_id() == Some(window_id))
        {
            ApplicationHandler::window_event(page, event_loop, window_id, event);
        } else {
            self.preview.window_event(event_loop, window_id, event);
        }
    }

    fn about_to_wait(&mut self, event_loop: &ActiveEventLoop) {
        self.poll_editor_lines(event_loop);
        // While editing, the Preview only reads its messages and loads; the edit
        // state draws and sets the wait.
        self.preview.about_to_wait(event_loop);
        let mut preview_flow = event_loop.control_flow();
        for viewport in &mut self.viewports {
            viewport.wait(event_loop);
            preview_flow = earliest(preview_flow, event_loop.control_flow());
        }
        let preview_flow = self.wait_pages(event_loop, preview_flow);
        self.follow_edit();
        event_loop.set_control_flow(preview_flow);
        self.drop_closed_viewports();
        if let Some(edit) = &mut self.edit {
            edit.about_to_wait(event_loop);
            // Both views may be live (an edit in a window of its own): each set the
            // wait for its own deadlines, so keep the earlier of the two.
            event_loop.set_control_flow(earliest(preview_flow, event_loop.control_flow()));
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

/// Which edit mesh a following viewport shows (P4 V5).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct FollowedRevision {
    pub(crate) mesh: u64,
    pub(crate) geometry: u64,
    pub(crate) topology: u64,
}

/// Whether two source paths name the same archive file (case and separators aside).
pub(crate) fn same_source(first: &str, second: &str) -> bool {
    let normalize = |path: &str| path.replace('\\', "/").trim_matches('/').to_lowercase();
    !first.trim().is_empty() && normalize(first) == normalize(second)
}

/// The wait that wakes for both: polling beats any deadline, the earlier deadline
/// beats the later, and any deadline beats waiting for events.
fn earliest(first: ControlFlow, second: ControlFlow) -> ControlFlow {
    match (first, second) {
        (ControlFlow::Poll, _) | (_, ControlFlow::Poll) => ControlFlow::Poll,
        (ControlFlow::WaitUntil(a), ControlFlow::WaitUntil(b)) => ControlFlow::WaitUntil(a.min(b)),
        (ControlFlow::WaitUntil(at), ControlFlow::Wait)
        | (ControlFlow::Wait, ControlFlow::WaitUntil(at)) => ControlFlow::WaitUntil(at),
        (ControlFlow::Wait, ControlFlow::Wait) => ControlFlow::Wait,
    }
}

/// The parent window an `open_session` asks its own viewport under, if any.
fn own_viewport_parent(open_session: &Value) -> Option<u64> {
    (open_session.get("viewport").and_then(Value::as_str) == Some("own"))
        .then(|| open_session.get("parent_hwnd").and_then(Value::as_u64))
        .flatten()
        .filter(|hwnd| *hwnd != 0)
}

/// The one stdin reader of an engine process: each line goes to the state its
/// protocol names.
fn spawn_engine_input(
    preview: PreviewRoute,
    routes: PreviewRoutes,
    page_routes: PageRoutes,
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
                                } else if value.get("event").and_then(Value::as_str)
                                    == Some("viewport_open")
                                {
                                    if editor.try_send(EditorLine::Viewport(value)).is_err() {
                                        preview.error("CDMW control queue overflowed".to_owned());
                                    }
                                } else if value.get("protocol").and_then(Value::as_str)
                                    == Some(PAGE_PROTOCOL)
                                {
                                    route_page_line(&page_routes, &editor, value);
                                } else if let Some(route) = viewport_route(&routes, &value) {
                                    route.message(value);
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
            if let Ok(routes) = routes.lock() {
                for route in routes.values() {
                    route.closed();
                }
            }
            if let Ok(pages) = page_routes.lock() {
                for input in pages.values() {
                    let _ = input.try_send(Err("CDMW closed the control input".to_owned()));
                }
            }
            let _ = editor.send(EditorLine::Closed);
            let _ = proxy.send_event(());
        });
    if let Err(spawn_error) = spawned {
        error!("engine input thread could not start: {spawn_error}");
    }
}

/// A New Item UI line: opening and closing go to the engine, the rest to the
/// page it names (a full or closed page's line is dropped; its host times out).
fn route_page_line(page_routes: &PageRoutes, editor: &Sender<EditorLine>, value: Value) {
    let kind = value
        .get("type")
        .and_then(Value::as_str)
        .unwrap_or_default();
    if matches!(kind, "page_open" | "page_close") {
        let _ = editor.try_send(EditorLine::Page(value));
        return;
    }
    let Some(page_id) = value
        .get("page_id")
        .and_then(Value::as_str)
        .map(str::to_owned)
    else {
        return;
    };
    if let Ok(routes) = page_routes.lock()
        && let Some(input) = routes.get(&page_id)
    {
        let _ = input.try_send(Ok(value));
    }
}

/// A line the engine itself says on the New Item UI protocol.
fn write_page_line(value: &Value) {
    let mut value = value.clone();
    if let Some(object) = value.as_object_mut() {
        object.insert("protocol".to_owned(), json!(PAGE_PROTOCOL));
    }
    let Ok(mut line) = serde_json::to_vec(&value) else {
        return;
    };
    line.push(b'\n');
    let stdout = std::io::stdout();
    let mut output = stdout.lock();
    let _ = output.write_all(&line).and_then(|()| output.flush());
}

/// The route of the other viewport this preview line names, if any.
fn viewport_route(routes: &PreviewRoutes, value: &Value) -> Option<PreviewRoute> {
    let viewport_id = value.get("viewport_id").and_then(Value::as_str)?;
    routes.lock().ok()?.get(viewport_id).cloned()
}

/// A line the engine itself says on the preview protocol (`viewport_closed`).
fn write_preview_line(value: &Value) {
    let mut value = value.clone();
    if let Some(object) = value.as_object_mut() {
        object.insert(
            "protocol".to_owned(),
            json!(crate::cdmw_session::PREVIEW_PROTOCOL),
        );
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
    fn a_preview_line_goes_to_the_viewport_it_names() {
        let routes = PreviewRoutes::default();
        let (route, incoming) = crate::cdmw_preview::PreviewRoute::for_test();
        routes
            .lock()
            .unwrap_or_else(|_| panic!("routes"))
            .insert("dialog".to_owned(), route);
        let line = json!({"event": "package_load_request", "session_id": "shared", "viewport_id": "dialog"});
        let found = viewport_route(&routes, &line).unwrap_or_else(|| panic!("no route"));
        found.message(line);
        assert_eq!(incoming(), 1);
        // A session id alone (Browse's, or one a dialog shares with it) names no viewport.
        assert!(viewport_route(&routes, &json!({"session_id": "dialog"})).is_none());
        assert!(viewport_route(&routes, &json!({"viewport_id": "browse"})).is_none());
        assert!(viewport_route(&routes, &json!({"event": "cancel"})).is_none());
    }

    #[test]
    fn a_page_line_goes_to_the_page_it_names_and_opening_goes_to_the_engine() {
        let pages = PageRoutes::default();
        let (input, received) = std::sync::mpsc::sync_channel(4);
        pages
            .lock()
            .unwrap_or_else(|_| panic!("pages"))
            .insert("studio".to_owned(), input);
        let (editor, lines) = bounded(4);
        route_page_line(
            &pages,
            &editor,
            json!({"protocol": PAGE_PROTOCOL, "type": "state", "page_id": "studio"}),
        );
        assert!(received.try_recv().is_ok());
        route_page_line(
            &pages,
            &editor,
            json!({"protocol": PAGE_PROTOCOL, "type": "page_open", "page_id": "mods"}),
        );
        assert!(matches!(lines.try_recv(), Ok(EditorLine::Page(_))));
        // No page id, or a page not open here: dropped.
        route_page_line(
            &pages,
            &editor,
            json!({"protocol": PAGE_PROTOCOL, "type": "state"}),
        );
        route_page_line(
            &pages,
            &editor,
            json!({"protocol": PAGE_PROTOCOL, "type": "state", "page_id": "gone"}),
        );
        assert!(received.try_recv().is_err() && lines.try_recv().is_err());
    }

    #[test]
    fn a_follower_shows_only_the_same_archive_file() {
        assert!(same_source(
            "character/cd_phm_00_ub_00_0374.pac",
            "Character\\CD_PHM_00_UB_00_0374.PAC"
        ));
        assert!(same_source("/character/a.pac", "character/a.pac/"));
        assert!(!same_source("character/a.pac", "character/b.pac"));
        assert!(!same_source("", ""));
    }

    #[test]
    fn the_engine_waits_for_the_earlier_of_both_views() {
        let now = std::time::Instant::now();
        let soon = now + std::time::Duration::from_millis(16);
        let later = now + std::time::Duration::from_secs(5);
        assert_eq!(
            earliest(ControlFlow::Wait, ControlFlow::Wait),
            ControlFlow::Wait
        );
        assert_eq!(
            earliest(ControlFlow::WaitUntil(soon), ControlFlow::Wait),
            ControlFlow::WaitUntil(soon)
        );
        assert_eq!(
            earliest(ControlFlow::Wait, ControlFlow::WaitUntil(later)),
            ControlFlow::WaitUntil(later)
        );
        assert_eq!(
            earliest(ControlFlow::WaitUntil(later), ControlFlow::WaitUntil(soon)),
            ControlFlow::WaitUntil(soon)
        );
        assert_eq!(
            earliest(ControlFlow::WaitUntil(soon), ControlFlow::Poll),
            ControlFlow::Poll
        );
    }

    #[test]
    fn an_edit_asks_for_its_own_viewport_with_a_parent_window() {
        let own = json!({"event": "open_session", "viewport": "own", "parent_hwnd": 4242});
        assert_eq!(own_viewport_parent(&own), Some(4242));
        // Browse's view (the default) and a missing or null parent are not one.
        assert_eq!(
            own_viewport_parent(&json!({"event": "open_session", "keep_view": true})),
            None
        );
        assert_eq!(own_viewport_parent(&json!({"viewport": "own"})), None);
        assert_eq!(
            own_viewport_parent(&json!({"viewport": "own", "parent_hwnd": 0})),
            None
        );
        assert_eq!(
            own_viewport_parent(&json!({"viewport": "browse", "parent_hwnd": 9})),
            None
        );
    }

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
