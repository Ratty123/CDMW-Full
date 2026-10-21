//! Delete feedback and shortcuts share the existing guarded authoring routes.
use super::*;

fn guidance_id() -> egui::Id {
    egui::Id::new("cdmw-delete-guidance")
}

impl LabApplication {
    pub(crate) fn show_cdmw_delete_guidance(&mut self, message: &str) {
        self.egui_context
            .data_mut(|data| data.insert_temp(guidance_id(), message.to_owned()));
        self.egui_context.request_repaint();
    }

    pub(super) fn draw_cdmw_delete_guidance(
        &mut self,
        context: &egui::Context,
        actions: &mut Vec<UiAction>,
    ) {
        let Some(message) = context.data_mut(|data| data.get_temp::<String>(guidance_id())) else {
            return;
        };
        let mut close = false;
        let modal = egui::Modal::new(guidance_id()).show(context, |ui| {
            ui.set_max_width((context.content_rect().width() - 40.0).clamp(180.0, 440.0));
            ui.heading(crate::localization::tr("Delete unavailable"));
            ui.add(egui::Label::new(crate::localization::tr(&message)).wrap());
            if state_str(&self.cdmw_state, "output_policy") != Some("free_edit_rebuild") {
                ui.add(egui::Label::new(crate::localization::tr(
                    "Free Edit creates an OBJ package without the game rig or physics. Supported vertex and face deletion can stay in Exact output.",
                )).wrap());
            }
            ui.horizontal_wrapped(|ui| {
                if state_bool(&self.cdmw_state, "authoring_enabled")
                    && !self.cdmw_busy()
                    && !self.cdmw_has_archive_refit()
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
            context.data_mut(|data| data.remove::<String>(guidance_id()));
        }
    }

    pub(super) fn cdmw_part_delete_action(&mut self) -> Option<UiAction> {
        if let Some(reason) = self.cdmw_part_action_reason("delete") {
            self.show_cdmw_delete_guidance(reason);
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

    pub(super) fn cdmw_delete_shortcut(&mut self, actions: &mut Vec<UiAction>) {
        let context = &self.egui_context;
        if self.hair.active()
            || context.egui_wants_keyboard_input()
            || egui::Popup::is_any_open(context)
            || context.data_mut(|data| data.get_temp::<String>(guidance_id()).is_some())
            || !context
                .input_mut(|input| input.consume_key(egui::Modifiers::NONE, egui::Key::Delete))
        {
            return;
        }
        if self.cdmw_busy() {
            self.show_cdmw_delete_guidance("Wait for the current operation before deleting.");
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
