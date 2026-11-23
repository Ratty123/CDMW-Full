//! The Mesh islands list used by name from CDMW (`editor_control` "islands"): select an
//! island or several, show or hide one in the view, isolate one within its part, show them
//! all again, and the Island colors option. Only the view and the selection change, as
//! with the list's own controls; output inclusion stays a host command (`replacement_islands`).
use super::*;
use crate::cdmw_host_controls::{ControlOutcome, control_action, control_bool};

/// The islands' actions CDMW may name.
pub(super) const ISLAND_HOST_ACTIONS: [&str; 7] =
    ["state", "select", "select_many", "visibility", "isolate", "show_all", "colours"];

impl LabApplication {
    pub(crate) fn islands_host_control(&mut self, arguments: &Value) -> ControlOutcome {
        let action = control_action(arguments).to_owned();
        let result = if action == "state" { Ok(()) } else { self.islands_host_action(&action, arguments) };
        let state = self.islands_host_state();
        match result {
            Ok(()) => ControlOutcome::done(state),
            Err(message) => ControlOutcome::refused(message, state),
        }
    }

    /// The faces of island `island` (its row number in the list) of part `part`.
    fn host_island_faces(&self, part: u64, island: u64) -> Result<(u32, Vec<u32>), String> {
        let parts = self.cdmw_state["mesh_islands"]["parts"].as_array().cloned().unwrap_or_default();
        let row = parts
            .iter()
            .find(|row| row["index"].as_u64() == Some(part))
            .ok_or_else(|| format!("The Mesh islands list has no part {part}; the islands state lists its parts."))?;
        let islands = row["islands"].as_array().cloned().unwrap_or_default();
        let faces = islands
            .get(island as usize)
            .map(island_faces)
            .ok_or_else(|| format!("Part {part} has islands 0 to {}.", islands.len().saturating_sub(1)))?;
        if faces.is_empty() {
            return Err(format!("Island {island} of part {part} has no faces."));
        }
        Ok((part as u32, faces))
    }

    fn host_island_of(&self, value: &Value) -> Result<(u32, Vec<u32>), String> {
        let part = value.get("part").and_then(Value::as_u64).ok_or("Name the island's part (a part number).")?;
        let island = value.get("island").and_then(Value::as_u64).ok_or("Name the island (its number in the part).")?;
        self.host_island_faces(part, island)
    }

    fn islands_host_action(&mut self, action: &str, a: &Value) -> Result<(), String> {
        if !ISLAND_HOST_ACTIONS.contains(&action) {
            return Err(format!("The islands have no action {action}; their actions are {}.",
                               ISLAND_HOST_ACTIONS.join(", ")));
        }
        if action == "colours" {
            let enabled = control_bool(a, "enabled")?.ok_or("colours needs enabled (true or false).")?;
            let available = self.cdmw_state["mesh_islands"]["color_faces"].is_array();
            let shown = self.view_mode == ViewMode::PartId && self.cdmw_island_colours;
            if enabled && !available && !shown {
                return Err("Island colors are offered once the mesh's islands are known.".into());
            }
            self.set_cdmw_island_colours(enabled);
            return Ok(());
        }
        // As the list: disabled while a request is pending and outside Edit comparison.
        if self.cdmw_busy() {
            return Err("The Mesh Editor is working on the last request; try again in a moment.".into());
        }
        let editing = self.cdmw_state["replacement"]["comparison"].as_str().is_none_or(|mode| mode == "edit");
        if !editing {
            return Err("Mesh islands are edited in the Edit comparison view only.".into());
        }
        let ui_action = match action {
            "select" => {
                let (part, faces) = self.host_island_of(a)?;
                UiAction::SelectIsland { part, faces }
            }
            "select_many" => {
                let rows = a.get("islands").and_then(Value::as_array).ok_or("select_many needs islands: [{part, island}].")?;
                let islands = rows.iter().map(|row| self.host_island_of(row)).collect::<Result<Vec<_>, _>>()?;
                UiAction::SelectIslands(islands)
            }
            "visibility" => {
                let (part, faces) = self.host_island_of(a)?;
                let visible = control_bool(a, "visible")?.ok_or("visibility needs visible (true or false).")?;
                UiAction::SetIslandVisibility { part, faces, visible }
            }
            "isolate" => {
                let (part, faces) = self.host_island_of(a)?;
                UiAction::IsolateIsland { part, faces }
            }
            "show_all" => UiAction::ShowAllIslands,
            _ => return Err(format!("The islands have no action {action}.")),
        };
        self.handle_actions(vec![ui_action]);
        Ok(())
    }

    /// The list as CDMW reads it: each part's islands with their face counts, which are hidden
    /// in the view and which are selected, and whether the list can be used now.
    pub(crate) fn islands_host_state(&self) -> Value {
        let selected: HashSet<(u32, u32)> = self
            .mesh
            .as_ref()
            .into_iter()
            .flat_map(|mesh| {
                mesh.selection.faces.iter().filter_map(|handle| match mesh.face(*handle)?.provenance {
                    Provenance::Source { submesh, element } => Some((submesh, element)),
                    _ => None,
                })
            })
            .collect();
        let parts: Vec<Value> = self.cdmw_state["mesh_islands"]["parts"]
            .as_array()
            .into_iter()
            .flatten()
            .map(|row| {
                let part = row["index"].as_u64().unwrap_or_default() as u32;
                let islands: Vec<Value> = row["islands"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .enumerate()
                    .map(|(index, island)| {
                        let faces = island_faces(island);
                        let hidden = self.cdmw_hidden_islands.iter().any(|h| h.part == part && h.faces == faces);
                        let chosen = !faces.is_empty() && faces.iter().all(|face| selected.contains(&(part, *face)));
                        json!({"island": index, "faces": faces.len(), "first_face": faces.first(),
                               "shown": !hidden, "selected": chosen,
                               "included": island["included"].as_bool().unwrap_or(true)})
                    })
                    .collect();
                json!({"part": part, "name": row["name"], "available": row["available"],
                       "reason": row["reason"], "islands": islands})
            })
            .collect();
        let editing = self.cdmw_state["replacement"]["comparison"].as_str().is_none_or(|mode| mode == "edit");
        json!({
            "parts": parts,
            "hidden": self.cdmw_hidden_islands.len(),
            "usable": editing && !self.cdmw_busy(),
            "island_colours": self.view_mode == ViewMode::PartId && self.cdmw_island_colours,
            "island_colours_offered": self.cdmw_state["mesh_islands"]["color_faces"].is_array(),
        })
    }
}
