//! The UI scale of the screen CDMW's Qt host shows an embedded editor on.
//!
//! winit reads a window's DPI when it creates it and updates it only on
//! `WM_DPICHANGED`, which Windows sends to top-level windows, not to the child
//! window CDMW embeds. The child keeps the scale of the monitor it was created
//! on, so once CDMW is on a monitor with another scale, egui would draw text
//! larger or smaller than the Qt controls beside it. CDMW sends the scale of the
//! screen the editor is on (`scale` in the Mesh Editor's theme, `pixels_per_point`
//! in Create New Item's) and egui's zoom makes up the difference.

use serde_json::Value;

/// A usable host scale from a theme value.
pub(crate) fn host_scale(value: Option<&Value>) -> Option<f32> {
    value
        .and_then(Value::as_f64)
        .filter(|scale| scale.is_finite() && *scale > 0.0 && *scale <= 8.0)
        .map(|scale| scale as f32)
}

/// Draw at `host_scale` in a window winit holds at `window_scale`.
pub(crate) fn apply(context: &egui::Context, host_scale: f32, window_scale: f32) {
    let window_scale = if window_scale.is_finite() && window_scale > 0.0 {
        window_scale
    } else {
        1.0
    };
    // Compensate before egui-winit maps input as well as before drawing, so text,
    // hit boxes, IME placement and the viewport all use the host's physical scale.
    // Apply immediately: set_zoom_factor defers until after input conversion.
    context.options_mut(|options| {
        options.zoom_factor = host_scale / window_scale;
        options.zoom_with_keyboard = false; // CDMW Appearance owns the UI size.
    });
}

impl crate::LabApplication {
    /// Keep the scale a CDMW theme names. A theme without one keeps the last.
    pub(crate) fn remember_cdmw_host_scale(&self, theme: &Value) {
        if let Some(scale) = host_scale(theme.get("scale")) {
            self.cdmw_host_scale.set(Some(scale));
        }
    }

    /// Run before every frame and every window event, as Create New Item does: the
    /// window can change under the editor (Promote to tab, a monitor change).
    pub(crate) fn sync_cdmw_host_scale(&self, window_scale: f32) {
        if let Some(scale) = self.cdmw_host_scale.get() {
            apply(&self.egui_context, scale, window_scale);
        }
    }

    /// Physical pixels per egui point: the scale egui-winit maps input with.
    pub(crate) fn egui_pixels_per_point(&self, window_scale: f64) -> f64 {
        window_scale * f64::from(self.egui_context.zoom_factor())
    }
}
