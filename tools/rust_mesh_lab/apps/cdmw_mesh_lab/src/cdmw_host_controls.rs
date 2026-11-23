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
            _ => ControlOutcome::refused(format!("The editor has no control {control}."), Value::Null),
        };
        self.egui_context.request_repaint();
        if let Some(window) = &self.window {
            window.request_redraw();
        }
        outcome
    }
}
