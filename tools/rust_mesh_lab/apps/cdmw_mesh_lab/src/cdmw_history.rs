//! Selectable history and acknowledged traversal of the existing Undo/Redo lane.

use super::*;
use crate::cdmw_ui::{state_bool, state_u64};

#[derive(Default)]
pub(super) struct HistoryView {
    pub selected: Option<usize>,
    entries: Vec<Value>,
    pending: Option<Traversal>,
}

struct Traversal {
    entries: Vec<Value>,
    target: usize,
    expected_cursor: usize,
    request_id: u64,
}

fn entry_keys(state: &Value) -> Vec<Value> {
    state["history_entries"].as_array().into_iter().flatten().map(|entry| {
        let mut entry = entry.clone();
        if let Some(object) = entry.as_object_mut() { object.remove("state"); }
        entry
    }).collect()
}

fn cursor(state: &Value) -> Option<usize> {
    let entries = state["history_entries"].as_array()?;
    let cursor = usize::try_from(state["history_cursor"].as_u64()?).ok()?;
    (cursor <= entries.len()
        && state["undo_count"].as_u64() == Some(cursor as u64)
        && state["redo_count"].as_u64() == Some((entries.len() - cursor) as u64)).then_some(cursor)
}

impl LabApplication {
    fn cdmw_history_ready(&self) -> bool {
        !self.cdmw_busy() && !self.hair.preparing()
            && self.edit_gesture.is_none() && self.selection_gesture.is_none()
            && !self.cdmw_exit_requested
            && state_bool(&self.cdmw_state, "authoring_enabled")
            && self.cdmw_state["replacement"]["comparison"].as_str().unwrap_or("edit") == "edit"
    }

    pub(super) fn draw_cdmw_history(&mut self, ui: &mut egui::Ui, actions: &mut Vec<UiAction>) {
        let entries = entry_keys(&self.cdmw_state);
        if entries != self.cdmw_history.entries {
            self.cdmw_history.selected = None;
            self.cdmw_history.entries.clone_from(&entries);
        }
        if entries.is_empty() {
            ui.label(RichText::new(crate::localization::tr("No confirmed Mesh Editor actions yet")).italics());
            return;
        }
        ui.small(crate::localization::tr("Select an action, then right-click to undo or restore."));
        let cursor = cursor(&self.cdmw_state);
        let ready = self.cdmw_history_ready() && cursor.is_some();
        let revision = state_u64(&self.cdmw_state, "base_revision");
        for (index, entry) in entries.iter().enumerate() {
            let label = entry.as_str().or_else(|| entry["label"].as_str()).unwrap_or("Mesh Edit");
            let applied = index < cursor.unwrap_or(0);
            let label = format!("{} {}. {}", if applied { "●" } else { "○" }, index + 1, crate::localization::tr(label));
            ui.push_id(index, |ui| {
                let row = ui.add(egui::Button::new(if applied { RichText::new(label) } else { RichText::new(label).weak() })
                    .selected(self.cdmw_history.selected == Some(index)).wrap());
                if row.clicked() || row.secondary_clicked() {
                    self.cdmw_history.selected = Some(index);
                }
                row.context_menu(|ui| {
                    let (caption, help, target) = if applied {
                        ("Undo from here", "Undo this action and all later actions. They remain available to restore.", index)
                    } else {
                        ("Restore through here", "Restore undone actions up to and including this action.", index + 1)
                    };
                    if ui.add_enabled(ready, egui::Button::new(crate::localization::tr(caption)))
                        .on_hover_text(crate::localization::tr(help)).clicked() {
                        actions.push(UiAction::CdmwHistoryCursor { cursor: target, revision });
                        ui.close();
                    }
                });
            });
        }
    }

    pub(super) fn start_cdmw_history(&mut self, target: usize, revision: u64) {
        if !self.cdmw_history_ready() || self.cdmw_history.pending.is_some() { return; }
        let Some(current) = cursor(&self.cdmw_state) else { return; };
        let entries = entry_keys(&self.cdmw_state);
        if revision != state_u64(&self.cdmw_state, "base_revision") || target > entries.len() {
            self.status = "History changed. Select the action again.".into();
            return;
        }
        if target == current { return; }
        self.cdmw_history.pending = Some(Traversal { entries, target, expected_cursor: current, request_id: 0 });
        self.queue_cdmw_history_step();
    }

    fn queue_cdmw_history_step(&mut self) {
        let Some(plan) = self.cdmw_history.pending.as_mut() else { return; };
        let undo = plan.target < plan.expected_cursor;
        plan.expected_cursor = if undo { plan.expected_cursor - 1 } else { plan.expected_cursor + 1 };
        self.submit_cdmw_command(if undo { "undo" } else { "redo" }, json!({}), if undo { "Undo" } else { "Redo" });
        if let Some(request) = &self.cdmw_pending_request {
            self.cdmw_history.pending.as_mut().unwrap().request_id = request.request_id;
        } else {
            self.cdmw_history.pending = None;
        }
    }

    pub(super) fn finish_cdmw_history_step(&mut self, request_id: u64, ok: bool) {
        let Some(plan) = self.cdmw_history.pending.as_ref() else { return; };
        if !ok || self.cdmw_exit_requested {
            // The ordinary result handler already installed the last confirmed
            // host state and reported the rejection. Never continue after it.
            self.cdmw_history.pending = None;
            return;
        }
        if request_id != plan.request_id || cursor(&self.cdmw_state) != Some(plan.expected_cursor)
            || entry_keys(&self.cdmw_state) != plan.entries {
            self.cdmw_history.pending = None;
            self.status = "History changed. Stopped at the last confirmed action.".into();
            return;
        }
        if plan.expected_cursor == plan.target {
            self.cdmw_history.pending = None;
            return;
        }
        // Each step waits for the existing validated host response, including
        // its geometry, selection, revision and reciprocal history snapshot.
        self.queue_cdmw_history_step();
    }
}
