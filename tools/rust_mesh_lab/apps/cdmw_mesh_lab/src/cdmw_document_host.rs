//! The document's History list and Reference pieces used by name from CDMW
//! (`editor_control` "document"): jump the history to an entry, as the History list's
//! Undo from here and Restore through here do, and show or hide a set's reference pieces,
//! as their View boxes do. The LOD shown is the one CDMW opened the session with; the
//! editor offers no LOD switch for a CDMW session, so neither does this control.
use super::*;
use crate::cdmw_host_controls::{ControlOutcome, control_action, control_bool};

/// The document's actions CDMW may name.
pub(super) const DOCUMENT_HOST_ACTIONS: [&str; 3] = ["state", "history_cursor", "reference_piece"];

impl LabApplication {
    pub(crate) fn document_host_control(&mut self, arguments: &Value) -> ControlOutcome {
        let action = control_action(arguments).to_owned();
        let result = if action == "state" { Ok(()) } else { self.document_host_action(&action, arguments) };
        let state = self.document_host_state();
        match result {
            Ok(()) => ControlOutcome::done(state),
            Err(message) => ControlOutcome::refused(message, state),
        }
    }

    fn document_host_action(&mut self, action: &str, a: &Value) -> Result<(), String> {
        match action {
            "history_cursor" => {
                let target = a
                    .get("cursor")
                    .and_then(Value::as_u64)
                    .ok_or("history_cursor needs cursor: how many History entries stay applied.")?
                    as usize;
                // As the History list's right-click actions: offered only when it is ready.
                if !self.cdmw_history_ready() || self.cdmw_history.pending.is_some() {
                    return Err("The History list is not ready: wait for the current edit, and use the Edit \
                                comparison view."
                        .into());
                }
                let current = cursor(&self.cdmw_state).ok_or("The History list is still being updated.")?;
                let entries = entry_keys(&self.cdmw_state).len();
                if target > entries {
                    return Err(format!("The History has {entries} entries; cursor is 0 to {entries}."));
                }
                if target != current {
                    let revision = state_u64(&self.cdmw_state, "base_revision");
                    self.handle_actions(vec![UiAction::CdmwHistoryCursor { cursor: target, revision }]);
                }
                Ok(())
            }
            "reference_piece" => {
                let index = a.get("piece").and_then(Value::as_u64).ok_or("reference_piece needs piece.")? as usize;
                let visible = control_bool(a, "visible")?.ok_or("reference_piece needs visible (true or false).")?;
                let piece = self
                    .cdmw_reference_pieces
                    .iter_mut()
                    .find(|piece| piece.index == index)
                    .ok_or_else(|| format!("This document has no reference piece {index}; the state lists them."))?;
                if piece.visible != visible {
                    piece.visible = visible;
                    self.refresh_cdmw_mesh_display();
                }
                Ok(())
            }
            _ => Err(format!("The document has no action {action}; its actions are {}.",
                             DOCUMENT_HOST_ACTIONS.join(", "))),
        }
    }

    pub(crate) fn document_host_state(&self) -> Value {
        let pieces: Vec<Value> = self
            .cdmw_reference_pieces
            .iter()
            .map(|piece| json!({"piece": piece.index, "name": piece.name, "visible": piece.visible,
                                "parts": piece.part_count}))
            .collect();
        let set_files = self.cdmw_bridge.as_ref().map(|bridge| bridge.manifest().item_set_files.clone());
        json!({
            "history": {
                "entries": entry_keys(&self.cdmw_state).len(),
                "cursor": cursor(&self.cdmw_state),
                "ready": self.cdmw_history_ready() && self.cdmw_history.pending.is_none(),
                "traversing": self.cdmw_history.pending.is_some(),
            },
            "reference_pieces": pieces,
            "set_files": set_files.unwrap_or_default(),
            "lod": self.active_lod_index,
        })
    }
}
