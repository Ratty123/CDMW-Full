//! A mesh opened by another CDMW workflow: the edit goes back there at Finish.
//!
//! Create New Item opens an imported model here to split parts and paint cloth. The
//! host marks such a session with `handoff_target`; this view then guides the few
//! steps that matter, names Finish after the way back and hides the Free Edit output
//! controls, which Create New Item owns.

use super::*;
use crate::cdmw_ui::state_str;

pub(super) const NEW_ITEM_HANDOFF: &str = "new_item";

impl LabApplication {
    /// True when Finish Edit Mesh hands the edit back to Create New Item.
    pub(super) fn cdmw_returns_to_new_item(&self) -> bool {
        state_str(&self.cdmw_state, "handoff_target") == Some(NEW_ITEM_HANDOFF)
    }

    pub(super) fn cdmw_finish_label(&self) -> &'static str {
        if self.cdmw_returns_to_new_item() {
            "Finish and return to Create New Item"
        } else {
            "Finish Edit Mesh"
        }
    }

    /// The three steps a Create New Item model usually needs, each one click away.
    pub(super) fn draw_cdmw_handoff_banner(&mut self, root_ui: &mut egui::Ui) {
        if !self.cdmw_returns_to_new_item() || self.hair.active() {
            return;
        }
        let mut open = None;
        egui::Panel::top("cdmw-new-item-handoff").show(root_ui, |ui| {
            ui.horizontal_wrapped(|ui| {
                ui.label(RichText::new(crate::localization::tr("Editing a model for Create New Item")).strong());
                ui.separator();
                if ui
                    .button(crate::localization::tr("1 Split into parts"))
                    .on_hover_text(crate::localization::tr(
                        "Optional. Select faces with Click, Brush, Rectangle or Lasso, then choose Create Part \
                         on the Select page. Each part can get its own material, glow or cloth. Hiding a part \
                         only hides it here; delete its faces to leave it out of the item.",
                    ))
                    .clicked()
                {
                    open = Some(CdmwRailPage::Select);
                }
                if ui
                    .button(crate::localization::tr("2 Paint cloth"))
                    .on_hover_text(crate::localization::tr(
                        "Optional. On the Cloth page, mark what should swing as cloth. \
                         Used when Template cloth / physics is on in Create New Item.",
                    ))
                    .clicked()
                {
                    open = Some(CdmwRailPage::Cloth);
                }
                ui.label(crate::localization::tr("3 Finish and return to Create New Item (top right)"));
            });
        });
        if let Some(page) = open {
            let context = root_ui.ctx().clone();
            self.open_cdmw_tool_settings(&context, page);
            context.request_repaint();
        }
    }

    /// Output for a handed-off session: nothing to choose here.
    pub(super) fn draw_cdmw_handoff_output(&self, ui: &mut egui::Ui, heading: bool) {
        if heading {
            ui.label(RichText::new(crate::localization::tr("Output")).strong());
        }
        ui.label(crate::localization::tr("Create New Item"));
        ui.small(crate::localization::tr(
            "Finish sends the edited model back to Create New Item, which builds the item and its package.",
        ));
    }
}
