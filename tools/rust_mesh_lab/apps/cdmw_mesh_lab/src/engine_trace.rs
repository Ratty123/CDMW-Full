//! An opt-in trace of the engine's event loop (section 8.7 B4).
//!
//! With `CDMW_ENGINE_LOOP_TRACE=<file>` set, the engine writes one JSON line a
//! second: how often the loop woke and why, which windows drew, how many
//! messages woke it, and the wait each part chose last. Without it nothing is
//! counted or written.

use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::fs::File;
use std::io::Write;
use std::time::{Duration, Instant};
use winit::event::StartCause;
use winit::event_loop::ControlFlow;

pub(crate) struct LoopTrace {
    file: Option<File>,
    started: Instant,
    counts: BTreeMap<String, u64>,
    waits: BTreeMap<String, String>,
}

impl LoopTrace {
    pub(crate) fn from_env() -> Self {
        let file =
            std::env::var_os("CDMW_ENGINE_LOOP_TRACE").and_then(|path| File::create(path).ok());
        Self {
            file,
            started: Instant::now(),
            counts: BTreeMap::new(),
            waits: BTreeMap::new(),
        }
    }

    pub(crate) fn enabled(&self) -> bool {
        self.file.is_some()
    }

    pub(crate) fn count(&mut self, name: &str) {
        if self.enabled() {
            *self.counts.entry(name.to_owned()).or_default() += 1;
        }
    }

    pub(crate) fn woke(&mut self, cause: StartCause) {
        self.count(match cause {
            StartCause::ResumeTimeReached { .. } => "wake_deadline",
            StartCause::WaitCancelled { .. } => "wake_event",
            StartCause::Poll => "wake_poll",
            StartCause::Init => "wake_init",
        });
    }

    pub(crate) fn wait(&mut self, part: &str, flow: ControlFlow) {
        if !self.enabled() {
            return;
        }
        let now = Instant::now();
        let text = match flow {
            ControlFlow::Wait => "wait".to_owned(),
            ControlFlow::Poll => "poll".to_owned(),
            ControlFlow::WaitUntil(at) if at <= now => {
                format!("until {} ms ago", now.duration_since(at).as_millis())
            }
            ControlFlow::WaitUntil(at) => {
                format!("until in {} ms", at.duration_since(now).as_millis())
            }
        };
        self.waits.insert(part.to_owned(), text);
    }

    /// Write the last second's counts once a second has passed.
    pub(crate) fn flush_if_due(&mut self) {
        let Some(file) = self.file.as_mut() else {
            return;
        };
        let elapsed = self.started.elapsed();
        if elapsed < Duration::from_secs(1) {
            return;
        }
        let counts: serde_json::Map<String, Value> = self
            .counts
            .iter()
            .map(|(name, count)| (name.clone(), json!(count)))
            .collect();
        let waits: serde_json::Map<String, Value> = self
            .waits
            .iter()
            .map(|(part, wait)| (part.clone(), json!(wait)))
            .collect();
        let line = json!({"seconds": elapsed.as_secs_f64(), "counts": counts, "waits": waits});
        let _ = writeln!(file, "{line}");
        let _ = file.flush();
        self.started = Instant::now();
        self.counts.clear();
        self.waits.clear();
    }
}
