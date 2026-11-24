//! The Sculpt brushes used by name from CDMW (`editor_control` "sculpt"): one stroke of
//! Grab, Smooth, Inflate or Pinch along points given in model space, drawn through the
//! 3D view as the pointer draws it. The stroke goes through the same gesture as a drag,
//! so its falloff, symmetry, selection clipping, Undo step and CDMW commit are the
//! brush's own. The brush settings the panel shows are put back afterwards.
use super::*;
use crate::cdmw_host_controls::{control_number, ControlOutcome};

/// At most this many points in one stroke, and dabs at each.
pub(crate) const SCULPT_MAX_POINTS: usize = 256;
pub(crate) const SCULPT_MAX_DABS: usize = 32;

fn sculpt_tool(name: &str) -> Option<ViewportTool> {
    match name {
        "grab" => Some(ViewportTool::Grab),
        "smooth" => Some(ViewportTool::Smooth),
        "inflate" => Some(ViewportTool::Inflate),
        "pinch" => Some(ViewportTool::Pinch),
        _ => None,
    }
}

fn sculpt_points(arguments: &Value) -> Result<Vec<Vec3>, String> {
    let items = arguments
        .get("points")
        .and_then(Value::as_array)
        .ok_or("points must list [x, y, z] positions in model space")?;
    if items.is_empty() || items.len() > SCULPT_MAX_POINTS {
        return Err(format!("points must list 1 to {SCULPT_MAX_POINTS} positions"));
    }
    items
        .iter()
        .map(|item| {
            let values = item
                .as_array()
                .filter(|values| values.len() == 3)
                .and_then(|values| values.iter().map(Value::as_f64).collect::<Option<Vec<_>>>())
                .ok_or("each point must be [x, y, z]")?;
            let point = Vec3::new(values[0] as f32, values[1] as f32, values[2] as f32);
            if point.is_finite() {
                Ok(point)
            } else {
                Err("each point must be [x, y, z] with finite numbers".to_owned())
            }
        })
        .collect()
}

impl LabApplication {
    pub(crate) fn sculpt_host_control(&mut self, arguments: &Value) -> ControlOutcome {
        match self.sculpt_stroke(arguments) {
            Ok(state) => ControlOutcome::done(state),
            Err(message) => ControlOutcome::refused(message, Value::Null),
        }
    }

    fn sculpt_stroke(&mut self, arguments: &Value) -> Result<Value, String> {
        let tool_name = arguments.get("tool").and_then(Value::as_str).unwrap_or_default();
        let tool = sculpt_tool(tool_name).ok_or("tool must be grab, smooth, inflate or pinch")?;
        let points = sculpt_points(arguments)?;
        if tool == ViewportTool::Grab && points.len() < 2 {
            return Err("Grab moves the surface from the first point to the last: give at least two points".into());
        }
        let radius = control_number(arguments, "radius", 1.0e-5, 1.0e4)?.ok_or("radius (model units) is required")?;
        let strength_range = if tool == ViewportTool::Inflate { -1.0 } else { 0.01 };
        let strength = control_number(arguments, "strength", strength_range, 1.0)?;
        let dabs = control_number(arguments, "dabs", 1.0, SCULPT_MAX_DABS as f32)?.map_or(1, |dabs| dabs as usize);
        let falloff = match arguments.get("falloff").and_then(Value::as_str) {
            None => None,
            Some("smooth") => Some(BrushFalloff::Smooth),
            Some("linear") => Some(BrushFalloff::Linear),
            Some("constant") => Some(BrushFalloff::Constant),
            Some(_) => return Err("falloff must be smooth, linear or constant".into()),
        };
        let symmetry = match arguments.get("symmetry").and_then(Value::as_str) {
            None => None,
            Some("off") => Some(SculptSymmetry::Off),
            Some("x") => Some(SculptSymmetry::X),
            Some("y") => Some(SculptSymmetry::Y),
            Some("z") => Some(SculptSymmetry::Z),
            Some(_) => return Err("symmetry must be off, x, y or z".into()),
        };
        if self.mesh.is_none() {
            return Err("No mesh is open.".into());
        }
        if self.edit_gesture.is_some() || self.selection_gesture.is_some() {
            return Err("A drag is in progress in the 3D view; try again when it ends.".into());
        }
        let rectangle = self.viewport_rect.ok_or("The 3D view has not been laid out yet.")?;
        let pixels_per_unit = 1.0 / self.camera.world_units_per_pixel(rectangle).max(1.0e-9);
        let brush_pixels = radius * pixels_per_unit;
        if !(2.0..=4096.0).contains(&brush_pixels) {
            return Err(format!(
                "At this camera distance the radius is {brush_pixels:.1} pixels; move the camera (mesh_camera distance) so it is 2 to 4096 pixels."
            ));
        }
        let mut screen = Vec::with_capacity(points.len());
        for (index, point) in points.iter().enumerate() {
            let projected = self
                .camera
                .project(*point, rectangle)
                .map(|projected| projected.screen)
                .filter(|position| rectangle.contains(egui::pos2(position.x, position.y)))
                .ok_or_else(|| {
                    format!("Point {index} is not in the 3D view; turn the camera to it (mesh_camera) first.")
                })?;
            screen.push(projected);
        }

        let saved = (self.viewport_tool, self.brush_radius, self.brush_strength, self.brush_falloff, self.sculpt_symmetry);
        self.viewport_tool = tool;
        self.brush_radius = brush_pixels;
        if let Some(strength) = strength {
            self.brush_strength = strength;
        }
        if let Some(falloff) = falloff {
            self.brush_falloff = falloff;
        }
        if let Some(symmetry) = symmetry {
            self.sculpt_symmetry = symmetry;
        }
        let used_strength = self.brush_strength;
        let used_symmetry = self.sculpt_symmetry.label();
        let result = self.drive_sculpt_stroke(rectangle, &screen, dabs);
        (self.viewport_tool, self.brush_radius, self.brush_strength, self.brush_falloff, self.sculpt_symmetry) = saved;
        let status = result?;
        Ok(json!({
            "tool": tool_name,
            "points": points.len(),
            "dabs": dabs,
            "radius_pixels": brush_pixels,
            "strength": used_strength,
            "symmetry": used_symmetry,
            "status": status,
        }))
    }

    fn drive_sculpt_stroke(&mut self, rectangle: egui::Rect, screen: &[Vec2], dabs: usize) -> Result<String, String> {
        let first = screen[0];
        self.begin_primary_gesture(rectangle, first);
        if self.edit_gesture.is_none() {
            return Err(self.status.clone());
        }
        let grab = self.viewport_tool == ViewportTool::Grab;
        for (index, point) in screen.iter().enumerate() {
            let repeats = if grab { 1 } else { dabs };
            for dab in 0..repeats {
                if index == 0 && dab == 0 && !grab {
                    continue; // begin_primary_gesture applied the first dab
                }
                if self.edit_gesture.is_none() {
                    return Err(self.status.clone());
                }
                self.update_edit_gesture(rectangle, *point, true);
            }
        }
        if self.edit_gesture.is_none() {
            return Err(self.status.clone());
        }
        self.finish_primary_gesture();
        Ok(self.status.clone())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sculpt_refuses_what_the_brush_cannot_take_and_leaves_the_panel_as_it_was() {
        let mut app = LabApplication::new(None, None);
        let tool_before = app.viewport_tool;
        let wrong_tool = app.apply_editor_control("sculpt", &json!({"tool": "carve", "points": [[0, 0, 0]], "radius": 0.1}));
        assert!(!wrong_tool.ok && wrong_tool.message.contains("grab, smooth, inflate or pinch"), "{}", wrong_tool.message);
        let no_points = app.apply_editor_control("sculpt", &json!({"tool": "inflate", "points": [], "radius": 0.1}));
        assert!(!no_points.ok && no_points.message.contains("points"), "{}", no_points.message);
        let one_grab = app.apply_editor_control("sculpt", &json!({"tool": "grab", "points": [[0, 0, 0]], "radius": 0.1}));
        assert!(!one_grab.ok && one_grab.message.contains("at least two"), "{}", one_grab.message);
        let no_radius = app.apply_editor_control("sculpt", &json!({"tool": "smooth", "points": [[0, 0, 0]]}));
        assert!(!no_radius.ok && no_radius.message.contains("radius"), "{}", no_radius.message);
        let deflate_pinch =
            app.apply_editor_control("sculpt", &json!({"tool": "pinch", "points": [[0, 0, 0]], "radius": 0.1, "strength": -0.5}));
        assert!(!deflate_pinch.ok && deflate_pinch.message.contains("strength"), "{}", deflate_pinch.message);
        let no_mesh = app.apply_editor_control("sculpt", &json!({"tool": "inflate", "points": [[0, 0, 0]], "radius": 0.1, "strength": -0.5}));
        assert!(!no_mesh.ok && no_mesh.message.contains("No mesh"), "{}", no_mesh.message);
        assert_eq!(app.viewport_tool, tool_before);
    }
}
