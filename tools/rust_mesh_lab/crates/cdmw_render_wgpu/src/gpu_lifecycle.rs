use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use crate::RenderError;

/// One delayed recovery per helper lifetime. Repeated driver faults require an
/// explicit Retry, rather than automatically replaying a GPU-reset workload.
#[derive(Default)]
pub struct GpuRecovery {
    attempted: bool,
    deadline: Option<Instant>,
}

impl GpuRecovery {
    pub fn schedule(&mut self, now: Instant) -> bool {
        if self.attempted {
            return false;
        }
        self.attempted = true;
        self.deadline = Some(now + Duration::from_millis(500));
        true
    }

    pub fn deadline(&self) -> Option<Instant> {
        self.deadline
    }

    pub fn cancel_pending(&mut self) {
        self.deadline = None;
    }

    /// A user-requested retry keeps the CPU session and permits one new device.
    pub fn retry(&mut self, now: Instant) {
        if self.deadline.is_none() {
            self.attempted = true;
            self.deadline = Some(now + Duration::from_millis(500));
        }
    }

    pub fn take_due(&mut self, now: Instant) -> bool {
        if self.deadline.is_some_and(|deadline| now >= deadline) {
            self.deadline = None;
            return true;
        }
        false
    }
}

#[derive(Clone, Default)]
pub(crate) struct GpuFaults(Arc<Mutex<Option<String>>>);

impl GpuFaults {
    pub(crate) fn record(&self, message: String) {
        if let Ok(mut fault) = self.0.lock() {
            // Preserve the initiating error instead of the subsequent invalid
            // resources reported after an OOM or driver reset.
            fault.get_or_insert(message);
        }
    }

    pub(crate) fn check(&self) -> Result<(), RenderError> {
        let fault = self
            .0
            .lock()
            .map_err(|_| RenderError::GpuFault("GPU error state unavailable".into()))?;
        match fault.as_ref() {
            Some(message) => Err(RenderError::GpuFault(message.clone())),
            None => Ok(()),
        }
    }
}

pub(crate) fn interactive_instance_descriptor() -> wgpu::InstanceDescriptor {
    let mut descriptor = wgpu::InstanceDescriptor::new_without_display_handle();
    descriptor.backends = wgpu::Backends::DX12;
    // wgpu's DX12 allocator checks the current DXGI process budget, which
    // changes as other applications allocate memory. Leave headroom and reject
    // new resources without deliberately losing an otherwise usable device.
    descriptor.memory_budget_thresholds.for_resource_creation = Some(85);
    descriptor
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn gpu_recovery_waits_and_cannot_loop_after_another_fault() {
        let mut recovery = GpuRecovery::default();
        let now = Instant::now();
        assert!(recovery.schedule(now));
        assert!(!recovery.take_due(now));
        assert!(recovery.take_due(now + Duration::from_millis(500)));
        assert!(!recovery.take_due(now + Duration::from_secs(1)));
        assert!(!recovery.schedule(now + Duration::from_secs(60)));
        recovery.retry(now);
        recovery.cancel_pending();
        assert!(!recovery.take_due(now + Duration::from_secs(1)));
        assert!(!recovery.schedule(now + Duration::from_secs(60)));
        assert!(recovery.deadline().is_none());
        recovery.retry(now);
        assert!(!recovery.take_due(now));
        assert!(recovery.take_due(now + Duration::from_millis(500)));
        assert!(!recovery.schedule(now + Duration::from_secs(60)));
    }

    #[test]
    fn gpu_fault_keeps_the_original_cause_until_device_replacement() {
        let fault = GpuFaults::default();
        assert!(fault.check().is_ok());
        let callback = fault.clone();
        callback.record("device removed".into());
        callback.record("invalid texture after removal".into());
        assert!(
            matches!(fault.check(), Err(RenderError::GpuFault(message)) if message == "device removed")
        );
        assert!(GpuFaults::default().check().is_ok());
    }
}
