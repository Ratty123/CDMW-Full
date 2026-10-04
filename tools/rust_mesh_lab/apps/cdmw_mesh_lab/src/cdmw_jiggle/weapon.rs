//! Independent reference placement. Dragging never edits WorkingMesh or reloads a solver.
use super::*;
use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, Default, Deserialize, Serialize, PartialEq)]
pub(crate) struct Placement {
    pub offset: [f64; 3],
    pub rotation: [f64; 3],
}

impl Placement {
    pub fn valid(self) -> bool {
        self.offset
            .iter()
            .all(|v| v.is_finite() && v.abs() <= 100.0)
            && self
                .rotation
                .iter()
                .all(|v| v.is_finite() && v.abs() <= 360.0)
    }

    pub fn transform(self) -> glam::DMat4 {
        let [x, y, z] = self.rotation.map(f64::to_radians);
        let rotation = glam::DQuat::from_rotation_z(z)
            * glam::DQuat::from_rotation_y(y)
            * glam::DQuat::from_rotation_x(x);
        glam::DMat4::from_rotation_translation(rotation, glam::DVec3::from(self.offset))
    }
}

#[derive(Debug)]
pub(crate) struct Reference {
    pub draw: DrawSnapshot,
    pub placement: Placement,
    pub base_inverse: glam::DMat4,
}

#[derive(Clone, Copy)]
pub(super) struct Drag {
    start: Placement,
    last: Vec2,
    pivot: Vec3,
    axis: GizmoAxis,
    tool: ViewportTool,
}

pub(super) fn collision_key(state: &Value) -> Value {
    json!([
        state["jiggle"]["collision_inputs"],
        state["jiggle"]["weapon_placement"],
        state["jiggle"]["decoded"]["file"],
        state["base_revision"]
    ])
}

impl LabApplication {
    pub(crate) fn play_weapon_preview(&mut self) {
        let preview = &mut self.cdmw_jiggle.preview;
        if preview
            .scene
            .as_ref()
            .is_some_and(|s| s.weapon_reference.is_some())
        {
            if preview.weapon_tool.is_some() {
                preview.motion = jiggle::Motion::Freehand(Vec3::ZERO);
                if let Some(Scene {
                    simulation: Simulation::Cloth(simulation),
                    ..
                }) = &mut preview.scene
                {
                    simulation.hold_body = true;
                }
            }
            if !preview.playing {
                preview.last_tick = Instant::now();
            }
            preview.playing = true;
        }
    }

    pub(crate) fn weapon_placement(&self) -> Placement {
        self.cdmw_jiggle
            .preview
            .scene
            .as_ref()
            .and_then(|s| s.weapon_reference.as_ref())
            .map(|r| r.placement)
            .unwrap_or_else(|| {
                serde_json::from_value(self.cdmw_state["jiggle"]["weapon_placement"].clone())
                    .unwrap_or_default()
            })
    }

    pub(crate) fn place_weapon_preview(&mut self, placement: Placement) {
        if !placement.valid() {
            return;
        }
        let preview = &mut self.cdmw_jiggle.preview;
        let Some(scene) = &mut preview.scene else {
            return;
        };
        let Some(reference) = &mut scene.weapon_reference else {
            return;
        };
        if reference.placement == placement {
            return;
        }
        reference.placement = placement;
        if let Simulation::Cloth(simulation) = &mut scene.simulation {
            simulation.weapon_target = placement.transform() * reference.base_inverse;
            simulation.hold_body = true;
        }
        // Independent weapon tests keep the body stationary and let cloth settle.
        preview.motion = jiggle::Motion::Freehand(Vec3::ZERO);
        preview.weapon_tool.get_or_insert(ViewportTool::Move);
        if !preview.playing {
            preview.last_tick = Instant::now();
        }
        preview.playing = true;
        scene.refresh_display(preview.keep_centred);
        self.cdmw_jiggle.weapon_placement_dirty = true;
    }

    pub(super) fn weapon_placement_action(&mut self) -> Option<UiAction> {
        if !self.cdmw_jiggle.weapon_placement_dirty
            || self.cdmw_busy()
            || self.cdmw_jiggle.preview.weapon_drag.is_some()
        {
            return None;
        }
        let placement = self.weapon_placement();
        self.cdmw_jiggle.weapon_placement_dirty = false;
        self.cdmw_jiggle.weapon_placement_sent = Some(placement);
        Some(UiAction::CdmwCommand {
            command: "cloth_collision_input",
            arguments: json!({"weapon_placement": placement}),
            label: "Place weapon preview",
        })
    }

    pub(crate) fn accept_weapon_placement_state(&mut self, state: &Value) -> bool {
        let Some(sent) = self.cdmw_jiggle.weapon_placement_sent else {
            return false;
        };
        if state["jiggle"]["collision_inputs"] != self.cdmw_state["jiggle"]["collision_inputs"]
            || self.cdmw_jiggle.preview.scene.is_none()
        {
            return false;
        }
        let placement =
            serde_json::from_value::<Placement>(state["jiggle"]["weapon_placement"].clone()).ok();
        if placement != Some(sent) {
            // Failed commands return the last accepted state. Preserve the scene
            // until result handling restores that placement and reports the error.
            return state["jiggle"]["weapon_placement"]
                == self.cdmw_state["jiggle"]["weapon_placement"];
        }
        self.cdmw_jiggle.weapon_placement_sent = None;
        // This is the acknowledgement of our live placement, not a new source.
        self.cdmw_jiggle.collision_preview_key = collision_key(state);
        true
    }

    pub(super) fn draw_weapon_placement(
        &mut self,
        ui: &mut egui::Ui,
        available: bool,
        actions: &mut Vec<UiAction>,
    ) {
        let ready = available
            && self.cdmw_jiggle.preview.pending.is_none()
            && self
                .cdmw_jiggle
                .preview
                .scene
                .as_ref()
                .is_some_and(|s| s.weapon_reference.is_some());
        let mut placement = self.weapon_placement();
        let mut changed = false;
        ui.add_enabled_ui(ready, |ui| {
            ui.horizontal_wrapped(|ui| {
                for (tool, label) in [(ViewportTool::Move, "Move weapon"), (ViewportTool::Rotate, "Rotate weapon")] {
                    if ui.add(egui::Button::new(label).selected(self.cdmw_jiggle.preview.weapon_tool == Some(tool)))
                        .on_hover_text("Drag the weapon gizmo to test cloth contact. Weapon collisions must be enabled; preview placement is not exported.").clicked() {
                        self.cdmw_jiggle.preview.weapon_tool = Some(tool);
                        self.play_weapon_preview();
                    }
                }
            });
            for (label, values, step, limit, suffix) in [
                ("Weapon preview position", &mut placement.offset, 0.01, 100.0, ""),
                ("Weapon preview rotation", &mut placement.rotation, 1.0, 360.0, "°"),
            ] {
                ui.label(label).on_hover_text("Place the weapon in model space. In-game sockets and weapon animation are not loaded.");
                ui.push_id(label, |ui| ui.horizontal_top(|ui| {
                    ui.spacing_mut().item_spacing.x = 3.0;
                    ui.spacing_mut().button_padding.x = 2.0;
                    let text_width = |text: &str| ui.painter().layout_no_wrap(text.into(),
                        egui::TextStyle::Body.resolve(ui.style()), ui.visuals().text_color()).size().x;
                    let visible_width = ui.available_rect_before_wrap().intersect(ui.clip_rect()).width();
                    let width = (visible_width / 3.0 - text_width("X") - text_width("⋮")
                        - 2.0 * ui.spacing().button_padding.x - 12.0).max(30.0);
                    for (i, axis) in ["X", "Y", "Z"].iter().enumerate() {
                        ui.label(*axis);
                        changed |= ui.add(crate::cdmw_ui::numeric::value(&mut values[i])
                            .speed(step).range(-limit..=limit).suffix(suffix).compact_width(width)).changed();
                    }
                }));
            }
        });
        if changed {
            self.place_weapon_preview(placement);
        }
        // Numeric dragging remains local until release, just like the gizmo.
        if !ui.input(|i| i.pointer.any_down())
            && let Some(action) = self.weapon_placement_action()
        {
            actions.push(action);
        }
    }

    pub(crate) fn weapon_gizmo(&self) -> Option<(ViewportTool, Vec3)> {
        let preview = &self.cdmw_jiggle.preview;
        let scene = preview.scene.as_ref()?;
        let reference = scene.weapon_reference.as_ref()?;
        let mut pivot = Vec3::from(reference.placement.offset.map(|v| v as f32));
        if !preview.keep_centred {
            pivot = scene.simulation.motion_transform().transform_point3(pivot);
        }
        Some((preview.weapon_tool?, pivot))
    }

    pub(crate) fn reset_weapon_placement_request(&mut self) {
        self.cdmw_jiggle.weapon_placement_sent = None;
        self.cdmw_jiggle.weapon_placement_dirty = false;
    }

    pub(crate) fn reject_weapon_placement(&mut self) {
        if let Ok(placement) =
            serde_json::from_value(self.cdmw_state["jiggle"]["weapon_placement"].clone())
        {
            self.place_weapon_preview(placement);
        }
        self.reset_weapon_placement_request();
    }

    pub(crate) fn cancel_weapon_drag(&mut self) {
        if let Some(drag) = self.cdmw_jiggle.preview.weapon_drag.take() {
            self.place_weapon_preview(drag.start);
            self.cdmw_jiggle.weapon_placement_dirty = false;
        }
    }

    pub(crate) fn handle_weapon_pointer(
        &mut self,
        event: &ViewportPointerEvent,
        rectangle: egui::Rect,
    ) -> bool {
        let Some((tool, pivot)) = self.weapon_gizmo() else {
            return false;
        };
        match *event {
            ViewportPointerEvent::PrimaryPressed(point) => {
                if !self.cdmw_busy()
                    && self.cdmw_jiggle.preview.pending.is_none()
                    && let Some(axis) = self.hit_test_gizmo(tool, point, pivot, rectangle)
                {
                    self.cdmw_jiggle.preview.weapon_drag = Some(Drag {
                        start: self.weapon_placement(),
                        last: point,
                        pivot,
                        axis,
                        tool,
                    });
                }
            }
            ViewportPointerEvent::PrimaryMoved(point)
            | ViewportPointerEvent::PrimaryReleased(point) => {
                if let Some(mut drag) = self.cdmw_jiggle.preview.weapon_drag
                    && point.is_finite()
                {
                    let mut placement = self.weapon_placement();
                    let screen_delta = point - drag.last;
                    let display_inverse = self
                        .cdmw_jiggle
                        .preview
                        .scene
                        .as_ref()
                        .map(|s| {
                            if self.cdmw_jiggle.preview.keep_centred {
                                glam::Mat4::IDENTITY
                            } else {
                                s.simulation.motion_transform().inverse()
                            }
                        })
                        .unwrap_or(glam::Mat4::IDENTITY);
                    if drag.tool == ViewportTool::Move {
                        let delta = if drag.axis == GizmoAxis::Free {
                            self.camera.screen_delta_to_world(screen_delta, rectangle)
                        } else {
                            self.camera.axis_drag_delta(
                                drag.axis.vector(&self.camera),
                                drag.pivot,
                                screen_delta,
                                rectangle,
                            )
                        };
                        let delta = display_inverse.transform_vector3(delta);
                        for i in 0..3 {
                            placement.offset[i] =
                                (placement.offset[i] + f64::from(delta[i])).clamp(-100.0, 100.0);
                        }
                    } else {
                        let axis = display_inverse
                            .transform_vector3(drag.axis.vector(&self.camera))
                            .as_dvec3();
                        let angle = self
                            .camera
                            .project(drag.pivot, rectangle)
                            .map(|c| signed_screen_angle(drag.last - c.screen, point - c.screen))
                            .unwrap_or(0.0);
                        let current = glam::DQuat::from_mat4(&placement.transform());
                        let next = glam::DQuat::from_axis_angle(axis.normalize(), f64::from(angle))
                            * current;
                        let (z, y, x) = next.to_euler(glam::EulerRot::ZYX);
                        placement.rotation = [x, y, z].map(f64::to_degrees);
                    }
                    self.place_weapon_preview(placement);
                    drag.last = point;
                    self.cdmw_jiggle.preview.weapon_drag = Some(drag);
                }
                if matches!(event, ViewportPointerEvent::PrimaryReleased(_)) {
                    self.cdmw_jiggle.preview.weapon_drag = None;
                    if let Some(UiAction::CdmwCommand {
                        command,
                        arguments,
                        label,
                    }) = self.weapon_placement_action()
                    {
                        self.submit_cdmw_command(command, arguments, label);
                    }
                }
            }
            _ => {
                self.cancel_weapon_drag();
                return false;
            }
        }
        // A visible weapon gizmo owns primary drags; authored cloak tools never see them.
        true
    }
}
