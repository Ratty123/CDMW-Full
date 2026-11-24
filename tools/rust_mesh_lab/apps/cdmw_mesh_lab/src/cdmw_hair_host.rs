//! Hair Tools' panel used by name from CDMW (`editor_control` "hair"): the panel's
//! local edits, its motion preview and its display options, each with the checks its
//! button has. Edits are prepared in the background as after a click; the answer says
//! whether one is still being prepared or saved (`preparing`, `saving`).
use super::*;
use crate::cdmw_host_controls::{ControlOutcome, control_action, control_bool, control_ids, control_number};

/// The Motion panel's movement tests, in its menu's order.
pub(super) const MOVEMENT_TESTS: [&str; 6] = ["still", "turn", "nod", "head_and_shoulders", "body_sway", "wind"];

/// The most locks one answer lists: a protocol line holds at most 256 KiB
/// (DOTNET_PROTOCOL_LINE_LIMIT on CDMW's side). `state` pages through the rest.
pub(super) const LISTED_LOCKS: usize = 400;

/// Hair's actions CDMW may name, besides `state`.
pub(super) const HAIR_HOST_ACTIONS: [&str; 16] = [
    "select_locks", "prepare", "empty", "fill", "lock_uv", "rigid", "rebind", "convert", "settings",
    "settle", "reset", "name", "delete", "motion", "display", "state",
];

fn preset_named(name: &str) -> Option<Preset> {
    match name {
        "cropped" => Some(Preset::Cropped),
        "bob" => Some(Preset::Bob),
        "long" => Some(Preset::Long),
        "ponytail" => Some(Preset::Ponytail),
        _ => None,
    }
}

impl LabApplication {
    pub(crate) fn hair_host_control(&mut self, arguments: &Value) -> ControlOutcome {
        let action = control_action(arguments).to_owned();
        let result = if action == "state" { Ok(()) } else { self.hair_host_action(&action, arguments) };
        // Only a read lists the locks; an edit's answer says how many there are.
        let listed = (action == "state").then(|| {
            arguments.get("lock_offset").and_then(Value::as_u64).unwrap_or(0) as usize
        });
        let state = self.hair_host_state(listed);
        match result {
            Ok(()) => ControlOutcome::done(state),
            Err(message) => ControlOutcome::refused(message, state),
        }
    }

    fn hair_host_action(&mut self, action: &str, a: &Value) -> Result<(), String> {
        if !HAIR_HOST_ACTIONS.contains(&action) {
            return Err(format!("Hair has no action {action}; its actions are {}.", HAIR_HOST_ACTIONS.join(", ")));
        }
        let Some(state) = self.hair.state.as_ref() else {
            return Err("Open a hairstyle with Hair Tools first.".into());
        };
        if state.converted && !matches!(action, "display") {
            return Err("Converted to ordinary mesh. Undo restores Hair editing.".into());
        }
        let has_generated = state.groups.iter().any(|g| g.mode == GroupMode::Generated);
        let has_existing = state.groups.iter().any(|g| g.mode == GroupMode::Existing);
        let unrebound = state.bound_reference != state.scalp.identity;
        if let Some(ids) = control_ids(a, "lock_ids")? {
            let known: HashSet<u64> = state.locks.iter().map(|lock| lock.id).collect();
            if let Some(missing) = ids.iter().find(|id| !known.contains(id)) {
                return Err(format!("This hairstyle has no lock {missing}; the hair state lists its locks."));
            }
            self.hair.selected = ids.iter().map(|id| *id as usize).collect();
        }
        let hair_action = match action {
            "select_locks" => {
                if a.get("lock_ids").is_none() {
                    return Err("select_locks needs lock_ids (an empty list clears the selection).".into());
                }
                return Ok(());
            }
            "display" => {
                for (key, slot) in [
                    ("show_reference", &mut self.hair.show_reference),
                    ("show_guides", &mut self.hair.show_guides),
                    ("show_collisions", &mut self.hair.show_collisions),
                ] {
                    if let Some(value) = control_bool(a, key)? {
                        *slot = value;
                    }
                }
                self.hair.invalidate_scene();
                return Ok(());
            }
            "motion" => return self.hair_host_motion(a),
            "prepare" if !has_existing => {
                return Err("Prepare existing hair sections is offered for a hairstyle with original sections.".into());
            }
            "empty" | "fill" if !has_generated => {
                return Err("Starter shapes create new hair in Create hairstyle.".into());
            }
            "rebind" if !unrebound => {
                return Err("Rebind to changed head is offered after the head reference changed.".into());
            }
            "prepare" => HairAction::Prepare,
            "empty" => HairAction::Empty,
            "rebind" => HairAction::Rebind,
            "convert" => HairAction::Convert,
            "settle" => HairAction::Settle,
            "reset" => HairAction::Reset,
            "rigid" => HairAction::Rigid,
            "delete" => HairAction::DeleteGuides,
            "fill" => {
                let name = a.get("preset").and_then(Value::as_str).unwrap_or("");
                let preset = preset_named(name).ok_or("fill needs preset: cropped, bob, long or ponytail")?;
                if let Some(length) = control_number(a, "length", 0.08, 0.60)? {
                    self.hair.preset_length = length;
                }
                HairAction::Fill(preset)
            }
            "settings" => {
                let width = control_number(a, "width", 0.0001, 10.0)?;
                let density = control_number(a, "density", 1.0, 32.0)?;
                if width.is_none() && density.is_none() {
                    return Err("settings needs width or density.".into());
                }
                if let Some(width) = width {
                    self.hair.width = width;
                }
                if let Some(density) = density {
                    self.hair.density = density.round() as u32;
                }
                HairAction::Settings
            }
            "lock_uv" => {
                let rect = match a.get("uv_rect") {
                    None => return Err("lock_uv needs uv_rect: [u, v, width, height] from 0 to 1, or null for the donor strip.".into()),
                    Some(Value::Null) => None,
                    Some(Value::Array(items)) if items.len() == 4 => {
                        let mut rect = [0.0_f32; 4];
                        for (slot, item) in rect.iter_mut().zip(items) {
                            *slot = item
                                .as_f64()
                                .map(|value| value as f32)
                                .filter(|value| value.is_finite() && (0.0..=1.0).contains(value))
                                .ok_or("uv_rect takes four numbers from 0 to 1")?;
                        }
                        Some(rect)
                    }
                    Some(_) => return Err("uv_rect takes four numbers from 0 to 1".into()),
                };
                HairAction::LockUv(rect)
            }
            "name" => {
                let name = a.get("style_name").and_then(Value::as_str).map(str::trim).unwrap_or("");
                if name.is_empty() || name.chars().count() > 64 {
                    return Err("name needs style_name, 1 to 64 characters.".into());
                }
                self.hair.style_name = name.to_owned();
                HairAction::Registration
            }
            _ => return Err(format!("Hair has no action {action}.")),
        };
        self.run_hair_host_action(hair_action)
    }

    /// Run one of the panel's actions as its button does, and say whether it was taken:
    /// a refusal leaves the panel's reason in its feedback line.
    fn run_hair_host_action(&mut self, action: HairAction) -> Result<(), String> {
        let resets = matches!(action, HairAction::Reset);
        let revision = self.hair.state.as_ref().map(|state| state.revision);
        let was_saving = self.hair.saving();
        self.hair.feedback.clear();
        self.run_hair_action(action);
        let taken = resets
            || self.hair.state.as_ref().map(|state| state.revision) != revision
            || (!was_saving && self.hair.saving());
        if taken {
            Ok(())
        } else if self.hair.feedback.is_empty() {
            Err("Hair Tools did not take it.".into())
        } else {
            Err(self.hair.feedback.clone())
        }
    }

    fn hair_host_motion(&mut self, a: &Value) -> Result<(), String> {
        if let Some(test) = a.get("test").filter(|test| !test.is_null()) {
            let name = test.as_str().unwrap_or("");
            let index = MOVEMENT_TESTS
                .iter()
                .position(|known| *known == name)
                .ok_or_else(|| format!("test is one of {}", MOVEMENT_TESTS.join(", ")))?;
            self.hair.head_test = index as u32;
        }
        if let Some(damping) = control_number(a, "damping", 0.0, 20.0)? {
            self.hair.motion.damping = damping;
        }
        if let Some(softness) = control_number(a, "shape_softness", 0.0, 0.005)? {
            self.hair.motion.bend_compliance = softness;
        }
        if let Some(gravity) = control_number(a, "gravity", -20.0, 0.0)? {
            self.hair.motion.gravity[1] = gravity;
        }
        if let Some(wind) = a.get("wind").filter(|wind| !wind.is_null()) {
            let values = wind
                .as_array()
                .filter(|values| values.len() == 3)
                .and_then(|values| {
                    values
                        .iter()
                        .map(|value| value.as_f64().map(|v| v as f32).filter(|v| v.is_finite() && (-30.0..=30.0).contains(v)))
                        .collect::<Option<Vec<_>>>()
                })
                .ok_or("wind takes three numbers from -30 to 30")?;
            self.hair.motion.wind.copy_from_slice(&values);
        }
        if let Some(play) = control_bool(a, "play")? {
            if play && !self.hair.playing {
                // As the Play button: offered only once the preview can run.
                self.hair_motion_reason()?;
            }
            if play != self.hair.playing {
                self.hair.playing = play;
                self.hair.last_tick = Instant::now();
            }
        }
        Ok(())
    }

    /// The panel as CDMW reads it: the locks and sections, the selection, the values
    /// the actions use, the motion preview and whether an edit is still on its way.
    pub(crate) fn hair_host_state(&mut self, listed: Option<usize>) -> Value {
        let motion_unavailable = if self.hair.state.is_some() { self.hair_motion_reason().err() } else { None };
        let Some(state) = self.hair.state.as_ref() else {
            return json!({"active": false});
        };
        let mut selected: Vec<u64> = self.hair.selected.iter().map(|id| *id as u64).collect();
        selected.sort_unstable();
        let selected_total = selected.len();
        selected.truncate(LISTED_LOCKS);
        let offset = listed.unwrap_or(0).min(state.locks.len());
        let locks: Vec<Value> = state
            .locks
            .iter()
            .skip(offset)
            .take(if listed.is_some() { LISTED_LOCKS } else { 0 })
            .map(|lock| {
                json!({"id": lock.id, "kind": lock.kind, "part": lock.part, "guide": lock.guide,
                       "mirrored": lock.mirrored, "cards": lock.cards, "width_scale": lock.width_scale,
                       "uv_rect": lock.uv_rect, "vertices": lock.vertices.len()})
            })
            .collect();
        let groups: Vec<Value> = state
            .groups
            .iter()
            .map(|group| {
                json!({"id": group.id, "name": group.name, "part": group.part, "mode": group.mode,
                       "width": group.width, "cards_per_guide": group.cards_per_guide, "uv_rect": group.uv_rect})
            })
            .collect();
        json!({
            "active": true,
            "converted": state.converted,
            "revision": state.revision,
            "style_name": state.style_name,
            "target_stem": state.template.target_stem,
            "rebind_offered": state.bound_reference != state.scalp.identity,
            "locks_total": state.locks.len(),
            "locks_offset": offset,
            "locks": locks,
            "groups": groups,
            "selected_locks": selected,
            "selected_total": selected_total,
            "panel": {
                "style_name": self.hair.style_name, "width": self.hair.width, "density": self.hair.density,
                "starter_length": self.hair.preset_length, "symmetry": self.hair.symmetry,
            },
            "display": {
                "show_reference": self.hair.show_reference, "show_guides": self.hair.show_guides,
                "show_collisions": self.hair.show_collisions,
            },
            "motion": {
                "playing": self.hair.playing,
                "test": MOVEMENT_TESTS[(self.hair.head_test as usize).min(MOVEMENT_TESTS.len() - 1)],
                "damping": self.hair.motion.damping, "shape_softness": self.hair.motion.bend_compliance,
                "gravity": self.hair.motion.gravity[1], "wind": self.hair.motion.wind,
                "elapsed": self.hair.simulation.as_ref().map_or(0.0, |simulation| simulation.elapsed),
                "unavailable": motion_unavailable,
            },
            "preparing": self.hair.preparing(),
            "saving": self.hair.saving(),
            "busy": self.cdmw_busy(),
            "feedback": self.hair.feedback,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::super::tests::ready_hair_app;
    use super::*;

    fn settle(app: &mut LabApplication) {
        let deadline = Instant::now() + std::time::Duration::from_secs(10);
        while app.hair.job.is_some() || !app.hair.queued.is_empty() {
            assert!(Instant::now() < deadline, "Hair preparation timed out");
            std::thread::sleep(std::time::Duration::from_millis(1));
            app.poll_hair();
        }
    }

    #[test]
    fn hair_control_reads_without_a_hairstyle_and_refuses_edits() {
        let mut app = LabApplication::new(None, None);
        let read = app.apply_editor_control("hair", &json!({"action": "state"}));
        assert!(read.ok);
        assert_eq!(read.state["active"], false);
        let edit = app.apply_editor_control("hair", &json!({"action": "empty"}));
        assert!(!edit.ok);
        assert!(edit.message.contains("Hair Tools"), "{}", edit.message);
        let unknown = app.apply_editor_control("hair", &json!({"action": "comb"}));
        assert!(!unknown.ok && unknown.message.contains("no action comb"), "{}", unknown.message);
        let other = app.apply_editor_control("session", &json!({}));
        assert!(!other.ok);
    }

    #[test]
    fn hair_control_selects_locks_and_changes_their_width_as_the_panel_does() {
        let (mut app, _rect) = ready_hair_app();
        let state = app.apply_editor_control("hair", &json!({"action": "state"})).state;
        let id = state["locks"][0]["id"].as_u64().expect("a lock");
        // A lock this hairstyle does not have is refused and selects nothing.
        let missing = app.apply_editor_control("hair", &json!({"action": "select_locks", "lock_ids": [u64::MAX]}));
        assert!(!missing.ok && missing.message.contains("no lock"), "{}", missing.message);
        let selected = app.apply_editor_control("hair", &json!({"action": "select_locks", "lock_ids": [id]}));
        assert!(selected.ok, "{}", selected.message);
        assert_eq!(selected.state["selected_locks"], json!([id]));
        // Settings needs a value; then it is one prepared edit, as Apply to selected locks.
        let empty = app.apply_editor_control("hair", &json!({"action": "settings"}));
        assert!(!empty.ok);
        let group_width = app.hair.state.as_ref().unwrap().groups[0].width;
        let changed = app.apply_editor_control(
            "hair",
            &json!({"action": "settings", "width": group_width * 1.5, "density": 4}),
        );
        assert!(changed.ok, "{}", changed.message);
        assert_eq!(changed.state["preparing"], true);
        assert_eq!(changed.state["panel"]["density"], 4);
        settle(&mut app);
        let lock = app.hair.state.as_ref().unwrap().locks.iter().find(|lock| lock.id == id).unwrap().clone();
        assert!((lock.width_scale - 1.5).abs() < 0.001);
        assert_eq!(lock.cards, 4);
    }

    #[test]
    fn hair_answers_list_locks_only_when_read_and_page_through_them() {
        let (mut app, _rect) = ready_hair_app();
        let total = app.hair.state.as_ref().unwrap().locks.len();
        assert!(total > 0);
        let read = app.apply_editor_control("hair", &json!({"action": "state"}));
        assert_eq!(read.state["locks_total"], total);
        assert_eq!(read.state["locks"].as_array().unwrap().len(), total.min(LISTED_LOCKS));
        let past = app.apply_editor_control("hair", &json!({"action": "state", "lock_offset": total + 5}));
        assert_eq!(past.state["locks"], json!([]));
        assert_eq!(past.state["locks_offset"], total);
        // An edit's answer carries the counts only, so a large hairstyle never fills a line.
        let display = app.apply_editor_control("hair", &json!({"action": "display", "show_guides": true}));
        assert!(display.ok);
        assert_eq!(display.state["locks"], json!([]));
        assert_eq!(display.state["locks_total"], total);
        assert!(serde_json::to_vec(&read.state).unwrap().len() < 256 * 1024);
    }

    #[test]
    fn hair_control_checks_ranges_and_reports_the_panel_refusal() {
        let (mut app, _rect) = ready_hair_app();
        for bad in [
            json!({"action": "settings", "width": -1}),
            json!({"action": "fill", "preset": "afro"}),
            json!({"action": "fill", "preset": "bob", "length": 2}),
            json!({"action": "lock_uv", "uv_rect": [0, 0, 2, 1]}),
            json!({"action": "motion", "test": "spin"}),
            json!({"action": "motion", "wind": [1, 2]}),
            json!({"action": "name", "style_name": "  "}),
            json!({"action": "display", "show_guides": "yes"}),
        ] {
            let outcome = app.apply_editor_control("hair", &bad);
            assert!(!outcome.ok, "{bad} was taken");
        }
        // Rigid with nothing selected: the panel's own reason comes back.
        app.hair.selected.clear();
        let rigid = app.apply_editor_control("hair", &json!({"action": "rigid"}));
        assert!(!rigid.ok);
        assert!(rigid.message.contains("Select the scalp sections"), "{}", rigid.message);
        // Settle before any motion: refused as its disabled button is.
        let settle_first = app.apply_editor_control("hair", &json!({"action": "settle"}));
        assert!(!settle_first.ok);
    }

    #[test]
    fn hair_control_sets_display_motion_and_name() {
        let (mut app, _rect) = ready_hair_app();
        let shown = app.apply_editor_control(
            "hair",
            &json!({"action": "display", "show_guides": true, "show_collisions": true, "show_reference": false}),
        );
        assert!(shown.ok, "{}", shown.message);
        assert_eq!(shown.state["display"], json!({"show_reference": false, "show_guides": true, "show_collisions": true}));
        let motion = app.apply_editor_control(
            "hair",
            &json!({"action": "motion", "test": "nod", "damping": 4.0, "gravity": -5.0, "wind": [1.0, 0.0, -2.0]}),
        );
        assert!(motion.ok, "{}", motion.message);
        assert_eq!(motion.state["motion"]["test"], "nod");
        assert_eq!(app.hair.head_test, 2);
        assert_eq!(app.hair.motion.wind, [1.0, 0.0, -2.0]);
        let played = app.apply_editor_control("hair", &json!({"action": "motion", "play": true}));
        assert_eq!(played.ok, app.hair.playing, "{}", played.message);
        let paused = app.apply_editor_control("hair", &json!({"action": "motion", "play": false}));
        assert!(paused.ok && !app.hair.playing);
        let reset = app.apply_editor_control("hair", &json!({"action": "reset"}));
        assert!(reset.ok, "{}", reset.message);
        let named = app.apply_editor_control("hair", &json!({"action": "name", "style_name": "Wind swept"}));
        assert!(named.ok, "{}", named.message);
        settle(&mut app);
        assert_eq!(app.hair.state.as_ref().unwrap().style_name, "Wind swept");
    }
}
