//! The view's diagnostic overlays and inspection aids used by name from CDMW
//! (`editor_control` "overlays"): Persistent edit colours (the deformation heatmap), the
//! Rig page's Weight colours, Frame bone, Frame influence and Select influenced vertices,
//! the selection highlight, and the material inspector's preview light and veil screen.
//! None of them changes the mesh or its output, except Select influenced vertices, which
//! replaces the selection as its button does.
use super::*;
use crate::cdmw_host_controls::{ControlOutcome, control_action, control_bool, control_number};

/// The overlays' actions CDMW may name.
pub(super) const OVERLAY_HOST_ACTIONS: [&str; 6] =
    ["state", "set", "frame_bone", "frame_influence", "select_influence", "inspection"];

fn placement_named(name: &str) -> Option<LightPlacement> {
    match name {
        "camera" => Some(LightPlacement::Camera),
        "front" => Some(LightPlacement::Front),
        "side" => Some(LightPlacement::Side),
        "behind" => Some(LightPlacement::Behind),
        "above" => Some(LightPlacement::Above),
        _ => None,
    }
}

fn placement_name(placement: LightPlacement) -> &'static str {
    match placement {
        LightPlacement::Camera => "camera",
        LightPlacement::Front => "front",
        LightPlacement::Side => "side",
        LightPlacement::Behind => "behind",
        LightPlacement::Above => "above",
    }
}

fn screen_named(name: &str) -> Option<VeilScreen> {
    match name {
        "1920x1080" => Some(VeilScreen::Hd1080),
        "2560x1440" => Some(VeilScreen::Qhd1440),
        "3840x2160" => Some(VeilScreen::Uhd2160),
        _ => None,
    }
}

fn screen_name(screen: VeilScreen) -> &'static str {
    match screen {
        VeilScreen::Hd1080 => "1920x1080",
        VeilScreen::Qhd1440 => "2560x1440",
        VeilScreen::Uhd2160 => "3840x2160",
    }
}

impl LabApplication {
    pub(crate) fn overlays_host_control(&mut self, arguments: &Value) -> ControlOutcome {
        let action = control_action(arguments).to_owned();
        let result = if action == "state" { Ok(()) } else { self.overlays_host_action(&action, arguments) };
        let state = self.overlays_host_state();
        match result {
            Ok(()) => ControlOutcome::done(state),
            Err(message) => ControlOutcome::refused(message, state),
        }
    }

    fn overlays_host_action(&mut self, action: &str, a: &Value) -> Result<(), String> {
        match action {
            "set" => {
                if let Some(enabled) = control_bool(a, "deformation_heatmap")? {
                    self.deformation_heatmap_enabled = enabled;
                }
                if let Some(enabled) = control_bool(a, "weight_colours")? {
                    if enabled && !self.cdmw_rig.available {
                        return Err(if self.cdmw_rig.reason.is_empty() {
                            "Weight colours need a bone with resolved influence (Rig page).".to_owned()
                        } else {
                            self.cdmw_rig.reason.clone()
                        });
                    }
                    self.cdmw_rig.show_weights = enabled;
                }
                if let Some(hidden) = control_bool(a, "hide_selection_highlight")? {
                    self.handle_actions(vec![UiAction::SetSelectionHighlightHidden(hidden)]);
                }
                Ok(())
            }
            "frame_bone" => {
                if self.rig_active_bone().is_none() {
                    return Err("Frame bone needs a labelled bone (select one on the Rig page).".into());
                }
                self.handle_actions(vec![UiAction::FrameRigBone]);
                Ok(())
            }
            "frame_influence" | "select_influence" => {
                if self.rig_influenced_vertices().is_empty() {
                    return Err("This bone has no resolved influence on visible Parts.".into());
                }
                self.handle_actions(vec![if action == "frame_influence" {
                    UiAction::FrameRigInfluence
                } else {
                    UiAction::SelectRigInfluence
                }]);
                Ok(())
            }
            "inspection" => {
                let mut changes = Vec::new();
                if let Some(hide) = control_bool(a, "hide_selection")? {
                    changes.push(MaterialInspectionChange::HideSelection(hide));
                }
                if let Some(light) = a.get("light").filter(|value| !value.is_null()) {
                    let placement = light
                        .as_str()
                        .and_then(placement_named)
                        .ok_or("light is camera, front, side, behind or above")?;
                    changes.push(MaterialInspectionChange::Light(placement));
                }
                if let Some(strength) = control_number(a, "light_strength", 0.0, 2.0)? {
                    changes.push(MaterialInspectionChange::LightStrength(strength));
                }
                if let Some(screen) = a.get("veil_screen").filter(|value| !value.is_null()) {
                    let screen = screen
                        .as_str()
                        .and_then(screen_named)
                        .ok_or("veil_screen is 1920x1080, 2560x1440 or 3840x2160")?;
                    changes.push(MaterialInspectionChange::VeilScreen(screen));
                }
                if changes.is_empty() {
                    return Err("inspection needs hide_selection, light, light_strength or veil_screen.".into());
                }
                self.handle_actions(changes.into_iter().map(UiAction::MaterialInspection).collect());
                Ok(())
            }
            _ => Err(format!("The overlays have no action {action}; their actions are {}.",
                             OVERLAY_HOST_ACTIONS.join(", "))),
        }
    }

    pub(crate) fn overlays_host_state(&self) -> Value {
        let inspection = self.material_inspection;
        json!({
            "deformation_heatmap": self.deformation_heatmap_enabled,
            "weight_colours": self.cdmw_rig.show_weights,
            "weight_colours_available": self.cdmw_rig.available,
            "rig_reason": self.cdmw_rig.reason,
            "active_bone": self.rig_active_bone().is_some(),
            "influenced_vertices": self.rig_influenced_vertices().len(),
            "selection_highlight_hidden": self.selection_highlight_hidden,
            "inspection": {
                "hide_selection": inspection.hide_selection,
                "light": placement_name(inspection.placement),
                "light_placed": inspection.light.is_some(),
                "light_strength": inspection.light_strength,
                "veil_screen": screen_name(inspection.veil_screen),
            },
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn overlays_control_toggles_the_heatmap_and_inspection_light_as_their_controls_do() {
        let mut app = LabApplication::new(None, None);
        let set = app.apply_editor_control("overlays", &json!({"action": "set", "deformation_heatmap": true}));
        assert!(set.ok, "{}", set.message);
        assert!(app.deformation_heatmap_enabled && set.state["deformation_heatmap"] == true);
        let lit = app.apply_editor_control(
            "overlays", &json!({"action": "inspection", "light": "behind", "light_strength": 1.5,
                                "veil_screen": "3840x2160", "hide_selection": false}));
        assert!(lit.ok, "{}", lit.message);
        assert_eq!(lit.state["inspection"]["light"], "behind");
        assert_eq!(lit.state["inspection"]["veil_screen"], "3840x2160");
        assert_eq!(lit.state["inspection"]["hide_selection"], false);
        assert_eq!(app.material_inspection.light_strength, 1.5);
        let hidden = app.apply_editor_control("overlays", &json!({"action": "set", "hide_selection_highlight": true}));
        assert!(hidden.ok && app.selection_highlight_hidden);
    }

    #[test]
    fn overlays_control_refuses_what_the_rig_page_would_not_offer() {
        let mut app = LabApplication::new(None, None);
        for (arguments, reason) in [
            (json!({"action": "frame_bone"}), "labelled bone"),
            (json!({"action": "frame_influence"}), "no resolved influence"),
            (json!({"action": "select_influence"}), "no resolved influence"),
            (json!({"action": "set", "weight_colours": true}), ""),
            (json!({"action": "inspection"}), "needs hide_selection"),
            (json!({"action": "inspection", "light": "moon"}), "camera, front"),
            (json!({"action": "inspection", "veil_screen": "800x600"}), "1920x1080"),
            (json!({"action": "inspection", "light_strength": 3}), "0 to 2"),
            (json!({"action": "explode"}), "no action explode"),
        ] {
            let outcome = app.apply_editor_control("overlays", &arguments);
            assert!(!outcome.ok, "{arguments} was taken");
            assert!(outcome.message.contains(reason), "{arguments}: {}", outcome.message);
        }
        assert!(!app.cdmw_rig.show_weights || !app.cdmw_rig.available);
    }
}
