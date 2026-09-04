//! One resident loader with a replaceable pending request and cancellation.
use crate::cdmw_session::LoadedCdmwSessionPackage;
use crate::preview_geometry::PreviewGeometry;
use cdmw_formats::MeshDocument;
use cdmw_mesh::{DrawSnapshot, WorkingMesh};
use crossbeam_channel::{Receiver, Sender, bounded};
use serde_json::Value;
use std::path::PathBuf;
use std::sync::{
    Arc, Mutex,
    atomic::{AtomicU64, Ordering},
};
use winit::event_loop::EventLoopProxy;

#[derive(Debug)]
pub struct LoadedPreview {
    pub package: LoadedCdmwSessionPackage,
    pub mesh: WorkingMesh,
    pub document: MeshDocument,
    pub roles: Option<Vec<u32>>,
    pub snapshot: DrawSnapshot,
    pub geometry: PreviewGeometry,
}
#[derive(Debug)]
pub struct LoadRequest {
    pub request_id: u64,
    pub generation: u64,
    pub path: PathBuf,
    pub reset_view: bool,
    pub presentation: Value,
    pub revision: u64,
}
#[derive(Debug)]
pub struct PackageResult {
    pub request: LoadRequest,
    pub result: Result<LoadedPreview, String>,
}
pub struct PreviewLoader {
    pending: Arc<Mutex<Option<(u64, LoadRequest)>>>,
    serial: Arc<AtomicU64>,
    wake: Sender<()>,
    pub results: Receiver<PackageResult>,
}
impl PreviewLoader {
    pub fn new(proxy: EventLoopProxy<()>) -> std::io::Result<Self> {
        let pending = Arc::new(Mutex::new(None::<(u64, LoadRequest)>));
        let serial = Arc::new(AtomicU64::new(0));
        let (wake, requests) = bounded(1);
        let (sender, results) = bounded(1);
        let worker_pending = Arc::clone(&pending);
        let worker_serial = Arc::clone(&serial);
        std::thread::Builder::new()
            .name("cdmw-preview-loader".into())
            .spawn(move || {
                while requests.recv().is_ok() {
                    let Some((version, request)) =
                        worker_pending.lock().expect("preview request lock").take()
                    else {
                        continue;
                    };
                    let cancelled = || worker_serial.load(Ordering::Acquire) != version;
                    let result = (|| {
                        let manifest = if request.path.is_dir() {
                            request.path.join("manifest.json")
                        } else {
                            request.path.clone()
                        };
                        let package = LoadedCdmwSessionPackage::load_preview_cancellable(
                            &manifest, &cancelled,
                        )
                        .map_err(|e| e.to_string())?;
                        if cancelled() {
                            return Err("Preview load cancelled".into());
                        }
                        let mesh = WorkingMesh::from_document_lod(
                            package.document(),
                            package.source_lod_index(),
                        )
                        .map_err(|e| e.to_string())?;
                        if cancelled() {
                            return Err("Preview load cancelled".into());
                        }
                        let geometry = PreviewGeometry::from_mesh(&mesh);
                        if cancelled() {
                            return Err("Preview load cancelled".into());
                        }
                        let scene = package
                            .manifest()
                            .state
                            .get("preview_scene")
                            .unwrap_or(&Value::Null);
                        let (snapshot, roles) = crate::preview_geometry::prepare_snapshot(
                            &mesh,
                            &geometry,
                            scene,
                            &request.presentation,
                            &package.manifest().interaction_profile,
                            request.revision,
                        );
                        let document = package.document().clone();
                        Ok(LoadedPreview {
                            package,
                            mesh,
                            snapshot,
                            geometry,
                            document,
                            roles,
                        })
                    })();
                    let _publication = worker_pending.lock().expect("preview request lock");
                    if !cancelled() {
                        let _ = sender.try_send(PackageResult { request, result });
                        let _ = proxy.send_event(());
                    }
                }
            })?;
        Ok(Self {
            pending,
            serial,
            wake,
            results,
        })
    }
    pub fn request(&self, request: LoadRequest) {
        let mut pending = self.pending.lock().expect("preview request lock");
        let serial = self.serial.fetch_add(1, Ordering::AcqRel) + 1;
        while self.results.try_recv().is_ok() {}
        *pending = Some((serial, request));
        let _ = self.wake.try_send(());
    }
}
impl Drop for PreviewLoader {
    fn drop(&mut self) {
        self.serial.fetch_add(1, Ordering::AcqRel);
    }
}
