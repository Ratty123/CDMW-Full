//! Delete feedback and shortcuts share the existing guarded authoring routes.
use super::*;

fn guidance_id() -> egui::Id {
    egui::Id::new("cdmw-delete-guidance")
}

/// Set by CDMW when its test automation drives this editor. Nobody is there to close
/// a dialog then, so a refusal must never wait for a click.
pub(crate) const AUTOMATION_ENV: &str = "CDMW_MESH_EDITOR_AUTOMATION";

pub(crate) fn driven_by_automation() -> bool {
    std::env::var_os(AUTOMATION_ENV).is_some_and(|value| value == "1")
}

impl LabApplication {
    /// Explain why Delete did nothing. The Free Edit advice belongs only to refusals
    /// the output mode causes; a busy, read-only or empty-selection refusal has its own fix.
    pub(crate) fn show_cdmw_delete_guidance(&mut self, message: &str) {
        self.show_cdmw_delete_guidance_with(message, false);
    }

    /// A refusal the output mode causes: the Free Edit advice and button may follow it.
    pub(crate) fn show_cdmw_output_delete_guidance(&mut self, message: &str) {
        self.show_cdmw_delete_guidance_with(message, true);
    }

    fn show_cdmw_delete_guidance_with(&mut self, message: &str, about_output: bool) {
        let shown = crate::localization::tr(message);
        if let Some(bridge) = &self.cdmw_bridge {
            let _ = bridge.publish_notice("delete_unavailable", &shown);
        }
        if self.cdmw_driven_by_automation {
            // The reason reaches CDMW (above) and the status line; no dialog waits.
            self.status = shown;
            return;
        }
        self.egui_context.data_mut(|data| {
            data.insert_temp(guidance_id(), (message.to_owned(), about_output))
        });
        self.egui_context.request_repaint();
    }

    pub(super) fn draw_cdmw_delete_guidance(
        &mut self,
        context: &egui::Context,
        actions: &mut Vec<UiAction>,
    ) {
        let Some((message, about_output)) =
            context.data_mut(|data| data.get_temp::<(String, bool)>(guidance_id()))
        else {
            return;
        };
        let mut close = false;
        let modal = egui::Modal::new(guidance_id()).show(context, |ui| {
            ui.set_max_width((context.content_rect().width() - 40.0).clamp(180.0, 440.0));
            ui.heading(crate::localization::tr("Delete unavailable"));
            ui.add(egui::Label::new(crate::localization::tr(&message)).wrap());
            if about_output && state_str(&self.cdmw_state, "output_policy") != Some("free_edit_rebuild") {
                ui.add(egui::Label::new(crate::localization::tr(
                    "Free Edit creates an OBJ package without the game rig or physics. Supported vertex and face deletion can stay in Exact output.",
                )).wrap());
            }
            ui.horizontal_wrapped(|ui| {
                if about_output
                    && state_bool(&self.cdmw_state, "authoring_enabled")
                    && !self.cdmw_busy()
                    && !self.cdmw_has_archive_refit()
                    && !self.cdmw_has_item_set()
                    && state_str(&self.cdmw_state, "output_policy") == Some("exact_game_asset")
                    && ui.button(crate::localization::tr("Choose Free Edit...")).clicked()
                {
                    actions.push(UiAction::ChooseCdmwFreeEdit);
                    close = true;
                }
                close |= ui.button(crate::localization::tr("Close")).clicked();
            });
        });
        if close || modal.should_close() {
            context.data_mut(|data| data.remove::<(String, bool)>(guidance_id()));
        }
    }

    pub(super) fn cdmw_part_delete_action(&mut self) -> Option<UiAction> {
        // The refusals cdmw_part_action_reason gives in its output-policy branch, and
        // only those, are about the output mode.
        let about_output = !self.cdmw_busy()
            && !self.cdmw_morph_comparison_active()
            && state_bool(&self.cdmw_state, "authoring_enabled")
            && state_str(&self.cdmw_state, "output_policy") != Some("free_edit_rebuild")
            && self.cdmw_state["replacement"]["item_set"] != true;
        if let Some(reason) = self.cdmw_part_action_reason("delete") {
            if about_output {
                self.show_cdmw_output_delete_guidance(reason);
            } else {
                self.show_cdmw_delete_guidance(reason);
            }
            return None;
        }
        Some(UiAction::CdmwCommand {
            command: "topology",
            arguments: json!({
                "action": "delete",
                "selection": {"source_indices": self.selected_part_indices(),
                    "vertices_by_submesh": {}, "edges_by_submesh": {}, "faces_by_submesh": {}},
                "params": {"delete_parts": true},
                "label": "Delete part",
            }),
            label: "Delete part",
        })
    }

    pub(super) fn cdmw_delete_guidance_open(&self) -> bool {
        self.egui_context
            .data_mut(|data| data.get_temp::<(String, bool)>(guidance_id()).is_some())
    }

    /// The Delete shortcut; the keyboard dispatcher has already checked focus and popups.
    pub(super) fn cdmw_delete_selection(&mut self, actions: &mut Vec<UiAction>) {
        if let Some(pending) = self.cdmw_pending_request.as_ref() {
            // Name what is being waited for: a selection, an edit, a Finish...
            let operation = pending.label.trim().to_owned();
            if operation.is_empty() {
                self.show_cdmw_delete_guidance("Wait for the current operation before deleting.");
            } else {
                let operation = crate::localization::tr(&operation);
                let message = crate::localization::tr(format!(
                    "Still running: {operation}. Delete again when it has finished."
                ));
                self.show_cdmw_delete_guidance(&message);
            }
        } else if !state_bool(&self.cdmw_state, "authoring_enabled") {
            self.show_cdmw_delete_guidance("This session is read-only");
        } else if self.cdmw_morph_comparison_active()
            || self.cdmw_state["replacement"]["comparison"]
                .as_str()
                .is_some_and(|mode| mode != "edit")
        {
            self.show_cdmw_delete_guidance(
                "Return to Edit view with outfit corrections enabled before deleting.",
            );
        } else if !self.selected_part_indices().is_empty() {
            if let Some(action) = self.cdmw_part_delete_action() {
                actions.push(action);
            }
        } else if self.selected_counts().total() > 0 {
            actions.push(UiAction::CdmwTopology {
                action: "delete",
                label: "Delete selection",
                params: json!({}),
            });
        } else {
            self.show_cdmw_delete_guidance(
                "Select a part, vertex, edge or face before using Delete.",
            );
        }
    }
}
