//! Off-screen captures of other packages in the engine process (P4 V5).
//!
//! Character Finder's thumbnails used to start a `--capture-cdmw-preview-session`
//! renderer process each. Browse's engine process now takes them as
//! `package_capture_request` lines: one capture thread renders them, one at a
//! time, on the renderer's own device (a clone of its handles), so no second
//! device and no process is created. The capture is the same code the command
//! line runs; only the device differs.
//!
//! The thread records and submits its own command buffers on the shared queue;
//! the event loop's frames are untouched. It never runs during a click's work:
//! CDMW pauses the Finder warm-up that sends these while foreground work runs.

use cdmw_render_wgpu::SharedGpu;
use crossbeam_channel::{Sender, TrySendError, bounded};
use serde_json::{Value, json};
use std::path::PathBuf;
use std::thread;

/// Requests queued behind the one being rendered; CDMW sends at most two at once.
const QUEUED_CAPTURES: usize = 4;
const MIN_CAPTURE_SIZE: u32 = 16;
const MAX_CAPTURE_SIZE: u32 = 1_024;

#[derive(Debug, PartialEq)]
pub(crate) struct PackageCaptureJob {
    pub(crate) request_id: Value,
    pub(crate) manifest: PathBuf,
    pub(crate) output: PathBuf,
    pub(crate) report: Option<PathBuf>,
    pub(crate) size: u32,
}

/// Read a `package_capture_request`; the paths are checked again by the capture.
pub(crate) fn parse_package_capture(value: &Value) -> Result<PackageCaptureJob, String> {
    let path = |key: &str| {
        value
            .get(key)
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|text| !text.is_empty())
            .map(PathBuf::from)
    };
    let manifest = path("manifest").ok_or("package_capture_request needs a manifest")?;
    let output = path("output").ok_or("package_capture_request needs an output")?;
    let size = value
        .get("size")
        .and_then(Value::as_u64)
        .unwrap_or(256)
        .clamp(u64::from(MIN_CAPTURE_SIZE), u64::from(MAX_CAPTURE_SIZE));
    Ok(PackageCaptureJob {
        request_id: value.get("request_id").cloned().unwrap_or(Value::Null),
        manifest,
        output,
        report: path("report"),
        size: u32::try_from(size).unwrap_or(256),
    })
}

/// The capture thread of one device.
pub(crate) struct PackageCaptures {
    jobs: Sender<PackageCaptureJob>,
}

impl PackageCaptures {
    /// `send` writes a whole outbound line (the Preview fills in its identity).
    pub(crate) fn start(
        gpu: SharedGpu,
        send: impl Fn(Value) + Send + 'static,
    ) -> Result<Self, String> {
        let (jobs, incoming) = bounded::<PackageCaptureJob>(QUEUED_CAPTURES);
        thread::Builder::new()
            .name("cdmw-package-capture".to_owned())
            .spawn(move || {
                for job in incoming {
                    let result = crate::capture_cdmw_session(
                        &job.manifest,
                        &job.output,
                        job.report.as_deref(),
                        true,
                        None,
                        None,
                        job.size,
                        Some(&gpu),
                    );
                    send(match result {
                        Ok(()) => json!({
                            "event": "package_capture_result",
                            "request_id": job.request_id,
                            "status": "captured",
                        }),
                        Err(error) => json!({
                            "event": "package_capture_result",
                            "request_id": job.request_id,
                            "status": "error",
                            "message": format!("{error:#}"),
                        }),
                    });
                }
            })
            .map_err(|error| format!("the capture thread could not start: {error}"))?;
        Ok(Self { jobs })
    }

    /// Queue a capture, or say why not (the caller answers the request).
    pub(crate) fn submit(&self, job: PackageCaptureJob) -> Result<(), String> {
        match self.jobs.try_send(job) {
            Ok(()) => Ok(()),
            Err(TrySendError::Full(_)) => Err("the capture queue is full".to_owned()),
            Err(TrySendError::Disconnected(_)) => Err("the capture thread stopped".to_owned()),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_capture_on_a_shared_device_matches_a_capture_on_its_own_device() {
        let root = tempfile::tempdir().unwrap_or_else(|error| panic!("tempdir: {error}"));
        let manifest = crate::cdmw_session::tests::write_preview_core_package_fixture(root.path());
        let out = tempfile::tempdir().unwrap_or_else(|error| panic!("tempdir: {error}"));
        let own = out.path().join("own.bmp");
        let shared = out.path().join("shared.bmp");
        if let Err(error) =
            crate::capture_cdmw_session(&manifest, &own, None, true, None, None, 64, None)
        {
            // No adapter on this machine: nothing to compare.
            eprintln!("skipped: {error:#}");
            return;
        }
        let gpu = pollster::block_on(SharedGpu::headless())
            .unwrap_or_else(|error| panic!("shared device: {error}"));
        // On another thread, as the engine's capture thread runs it.
        let (manifest_copy, shared_copy, gpu_copy) =
            (manifest.clone(), shared.clone(), gpu.clone());
        thread::spawn(move || {
            crate::capture_cdmw_session(
                &manifest_copy,
                &shared_copy,
                None,
                true,
                None,
                None,
                64,
                Some(&gpu_copy),
            )
        })
        .join()
        .unwrap_or_else(|_| panic!("capture thread panicked"))
        .unwrap_or_else(|error| panic!("shared capture: {error:#}"));
        let read = |path: &std::path::Path| {
            std::fs::read(path).unwrap_or_else(|error| panic!("{}: {error}", path.display()))
        };
        assert_eq!(read(&own), read(&shared));
    }

    #[test]
    fn a_capture_request_names_its_package_output_and_size() {
        let job = parse_package_capture(&json!({
            "request_id": 7,
            "manifest": "C:/cache/package/manifest.json",
            "output": "C:/cache/finder/preview.bmp",
            "report": "C:/cache/finder/report.json",
            "size": 256,
        }))
        .unwrap_or_else(|error| panic!("{error}"));
        assert_eq!(job.request_id, json!(7));
        assert_eq!(
            job.manifest,
            PathBuf::from("C:/cache/package/manifest.json")
        );
        assert_eq!(
            job.report,
            Some(PathBuf::from("C:/cache/finder/report.json"))
        );
        assert_eq!(job.size, 256);
    }

    #[test]
    fn a_capture_request_without_paths_is_refused_and_sizes_are_bounded() {
        assert!(parse_package_capture(&json!({"output": "a.bmp"})).is_err());
        assert!(parse_package_capture(&json!({"manifest": "m.json", "output": " "})).is_err());
        let tiny =
            parse_package_capture(&json!({"manifest": "m.json", "output": "a.bmp", "size": 1}))
                .unwrap_or_else(|error| panic!("{error}"));
        assert_eq!(tiny.size, MIN_CAPTURE_SIZE);
        let huge = parse_package_capture(
            &json!({"manifest": "m.json", "output": "a.bmp", "size": 1 << 20}),
        )
        .unwrap_or_else(|error| panic!("{error}"));
        assert_eq!(huge.size, MAX_CAPTURE_SIZE);
        assert_eq!(huge.report, None);
    }
}
