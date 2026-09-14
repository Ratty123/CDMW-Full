//! Production pointer dispatch for direct lock editing.
use super::*;

impl LabApplication {
    pub(super) fn lock_at(&self, point: Vec2, rect: egui::Rect) -> Option<(u64, u32, f32)> {
        let scene = self.hair.scene.as_ref()?;
        let (origin, direction, _) = self.camera.screen_ray(point, rect)?;
        let hit = scene.picking.hit(
            &scene.frame.positions,
            &scene.frame.indices,
            origin,
            direction,
        )?;
        let face = &scene.frame.indices[hit.triangle * 3..hit.triangle * 3 + 3];
        let id = scene
            .vertex_locks
            .get(face[0] as usize)
            .copied()
            .flatten()?;
        let along: f32 = face
            .iter()
            .zip(hit.barycentric)
            .map(|(v, w)| scene.vertex_along.get(*v as usize).copied().unwrap_or(0.0) * w)
            .sum();
        Some((id, along.floor() as u32, along.fract()))
    }

    fn pick_hair_scalp(&self, origin: Vec3, direction: Vec3) -> Option<Attachment> {
        let scene = self.hair.scene.as_ref()?;
        let state = self.hair.state.as_ref()?;
        let (min, max) = hair_bounds(state);
        let pivot = self.hair.simulation.as_ref().map_or(
            Vec3::new((min.x + max.x) * 0.5, min.y, (min.z + max.z) * 0.5),
            |s| s.pivot,
        );
        let pose = hair::PreviewPose::at(
            pivot,
            (max.y - min.y).max(0.01),
            self.hair
                .simulation
                .as_ref()
                .map_or(0.0, |s| s.elapsed as f32),
            self.hair.head_test,
        );
        let origin = pivot + pose.head.inverse() * (origin - pivot - pose.translation);
        let hit = scene.scalp_picking.hit(
            &state.scalp.positions,
            &scene.scalp_indices,
            origin,
            pose.head.inverse() * direction,
        )?;
        Some(Attachment {
            triangle: hit.triangle as u32,
            barycentric: hit.barycentric,
        })
    }

    fn brush_locks(&self, point: Vec2, rect: egui::Rect) -> Vec<u64> {
        let mut ids = BTreeSet::new();
        // Bounded surface samples respect occlusion; never select every guide
        // projected behind the face or the visible lock.
        for offset in [
            Vec2::ZERO,
            Vec2::X,
            -Vec2::X,
            Vec2::Y,
            -Vec2::Y,
            Vec2::new(0.7, 0.7),
            Vec2::new(-0.7, 0.7),
            Vec2::new(0.7, -0.7),
            Vec2::new(-0.7, -0.7),
        ] {
            if let Some((id, _, _)) = self.lock_at(point + offset * self.hair.radius, rect) {
                ids.insert(id);
            }
        }
        ids.into_iter().collect()
    }

    pub(crate) fn handle_hair_input(&mut self, ui: &egui::Ui, rect: egui::Rect) -> bool {
        if !self.hair.active()
            || self.cdmw_state["replacement"]["comparison"]
                .as_str()
                .is_some_and(|v| v != "edit")
        {
            return false;
        }
        let modifiers = ui.input(|i| i.modifiers);
        if ui.input(|i| i.key_pressed(egui::Key::Escape)) {
            self.hair.stroke = None;
            self.hair.stroke_changed = false;
            self.hair.drawing.clear();
            self.hair.stroke_start = None;
            self.hair.last_pointer = None;
            self.hair.scene = None;
            self.hair.playing = self.hair.restart_after_stroke;
            self.pointer_events.clear();
            return true;
        }
        if !ui.ctx().egui_wants_keyboard_input() && ui.input(|i| i.key_pressed(egui::Key::Delete)) {
            self.run_hair_action(HairAction::DeleteGuides);
        }
        let pointer = ui
            .input(|i| i.pointer.hover_pos())
            .map(|p| Vec2::new(p.x, p.y));
        let hit = pointer.and_then(|p| self.lock_at(p, rect));
        self.hair.hover = hit.map(|h| h.0);
        if self.hair.stroke_start.is_none() {
            self.hair.cut_preview = hit;
        }
        let events: Vec<_> = self.pointer_events.drain().collect();
        for event in events {
            self.dispatch_hair_pointer(event, rect, modifiers.ctrl, modifiers.alt, modifiers.shift);
        }
        if ui.rect_contains_pointer(rect) {
            let scroll = ui.input(|i| i.smooth_scroll_delta.y);
            if scroll.abs() > 0.0 {
                self.camera.zoom(scroll);
            }
        }
        true
    }

    pub(crate) fn dispatch_hair_pointer(
        &mut self,
        event: ViewportPointerEvent,
        rect: egui::Rect,
        ctrl: bool,
        alt: bool,
        shift: bool,
    ) {
        if alt || shift {
            if self.hair.stroke_start.take().is_some() {
                self.hair.stroke = None;
                self.hair.stroke_changed = false;
                self.hair.drawing.clear();
                self.hair.scene = None;
                self.hair.playing = self.hair.restart_after_stroke;
                self.hair.restart_after_stroke = false;
            }
            match event {
                ViewportPointerEvent::PrimaryPressed(p) => {
                    self.hair.last_pointer = Some(p);
                }
                ViewportPointerEvent::PrimaryMoved(p) => {
                    if let Some(old) = self.hair.last_pointer.replace(p) {
                        if shift {
                            self.camera.pan(p - old, rect);
                        } else {
                            self.camera.orbit(p - old);
                        }
                    }
                }
                ViewportPointerEvent::PrimaryReleased(_) => self.hair.last_pointer = None,
                ViewportPointerEvent::Orbit(d) => self.camera.orbit(d),
                ViewportPointerEvent::Pan(d) => self.camera.pan(d, rect),
            }
            return;
        }
        match event {
            ViewportPointerEvent::PrimaryPressed(point) if self.hair_input_ready() => {
                let hit = self.lock_at(point, rect);
                self.hair.stroke_primary = hit.map(|h| h.0);
                self.hair.stroke_distances.clear();
                self.hair.stroke_start = Some(point);
                self.hair.last_pointer = Some(point);
                self.hair.stroke_changed = false;
                self.hair.drawing.clear();
                if self.hair.tool == Some(HairTool::Select) {
                    if let Some((id, _, _)) = hit {
                        if ctrl {
                            if !self.hair.selected.remove(&(id as usize)) {
                                self.hair.selected.insert(id as usize);
                            }
                        } else {
                            self.hair.selected = HashSet::from([id as usize]);
                        }
                    } else if !ctrl {
                        self.hair.selected.clear();
                    }
                    return;
                }
                if matches!(self.hair.tool, Some(HairTool::Move | HairTool::Lengthen)) {
                    if let Some((id, _, _)) = hit {
                        if !self.hair.selected.contains(&(id as usize)) {
                            self.hair.selected = HashSet::from([id as usize]);
                        }
                    } else {
                        self.hair.feedback =
                            "Click a visible hair lock to select it, then drag.".into();
                        self.hair.stroke_start = None;
                        return;
                    }
                }
                if self.hair.tool == Some(HairTool::Cut) {
                    self.hair.cut_preview = hit;
                    self.hair.restart_after_stroke = self.hair.playing;
                    self.hair.playing = false;
                    return;
                }
                self.hair.restart_after_stroke = self.hair.playing;
                self.hair.playing = false;
                self.hair.stroke = self.hair.state.clone();
                self.hair.last_plant = None;
                if self.hair.tool == Some(HairTool::Erase) {
                    self.hair.selected.clear();
                }
                self.hair_stroke_point(rect, point);
            }
            ViewportPointerEvent::PrimaryMoved(point) => {
                if self.hair.stroke_start.is_some() {
                    self.hair_stroke_point(rect, point);
                }
            }
            ViewportPointerEvent::PrimaryReleased(point) => {
                if self.hair.stroke_start.is_none() {
                    return;
                }
                if self.hair.tool == Some(HairTool::Select) {
                    if let Some(start) = self.hair.stroke_start {
                        if start.distance(point) > 5.0 {
                            self.select_hair_marquee(start, point, rect, ctrl);
                        }
                    }
                } else if self.hair.tool == Some(HairTool::Cut) {
                    if let (Some((id, segment, t)), Some(mut state)) =
                        (self.hair.cut_preview, self.hair.state.clone())
                    {
                        state.revision += 1;
                        self.queue_hair(
                            state,
                            "Cut hair",
                            Preparation::Cut(id, segment, t, self.hair.symmetry),
                        );
                    }
                } else {
                    self.hair_stroke_point(rect, point);
                    if let Some(mut state) = self.hair.stroke.take() {
                        if matches!(self.hair.tool, Some(HairTool::Guide | HairTool::Paint))
                            && self
                                .hair
                                .stroke_start
                                .is_some_and(|start| start.distance(point) < 2.0)
                        {
                            self.hair.stroke_changed = false;
                            self.hair.selected.retain(|id| {
                                self.hair
                                    .state
                                    .as_ref()
                                    .is_some_and(|s| s.locks.iter().any(|l| l.id == *id as u64))
                            });
                        }
                        if self.hair.stroke_changed {
                            state.revision += 1;
                            let operation = match self.hair.tool {
                                Some(HairTool::Guide | HairTool::Paint) => Preparation::Generate,
                                Some(HairTool::Erase) => Preparation::Delete(
                                    self.hair.selected.iter().map(|i| *i as u64).collect(),
                                ),
                                _ => Preparation::Deform,
                            };
                            self.queue_hair(state, "Groom hair", operation);
                        }
                    }
                }
                self.hair.stroke_start = None;
                self.hair.last_pointer = None;
                self.hair.drawing.clear();
                // Keep the edited rest pose visible while its worker publishes.
                // Resume at the same procedural pose after preparation completes.
                self.hair.playing = self.hair.restart_after_stroke && self.hair.job.is_none();
                self.hair.last_tick = Instant::now();
                if self.hair.playing {
                    self.hair.restart_after_stroke = false;
                }
                if let Some(scene) = &mut self.hair.scene {
                    scene.applied = false;
                }
            }
            ViewportPointerEvent::Orbit(delta) => self.camera.orbit(delta),
            ViewportPointerEvent::Pan(delta) => self.camera.pan(delta, rect),
            _ => {}
        }
    }

    fn select_hair_marquee(&mut self, start: Vec2, end: Vec2, rect: egui::Rect, add: bool) {
        let box_rect =
            egui::Rect::from_two_pos(egui::pos2(start.x, start.y), egui::pos2(end.x, end.y));
        let Some(scene) = &self.hair.scene else {
            return;
        };
        let mut selected = HashSet::new();
        for (vertex, id) in scene.vertex_locks.iter().enumerate() {
            let Some(id) = id else {
                continue;
            };
            if selected.contains(&(*id as usize)) {
                continue;
            }
            let Some(p) = self
                .camera
                .project(Vec3::from(scene.frame.positions[vertex]), rect)
            else {
                continue;
            };
            if box_rect.contains(egui::pos2(p.screen.x, p.screen.y))
                && (self.hair.select_through
                    || self.lock_at(p.screen, rect).is_some_and(|hit| hit.0 == *id))
            {
                selected.insert(*id as usize);
            }
        }
        if !add {
            self.hair.selected.clear();
        }
        self.hair.selected.extend(selected);
    }

    fn hair_stroke_point(&mut self, rect: egui::Rect, pointer: Vec2) {
        let Some(mut state) = self.hair.stroke.take() else {
            return;
        };
        let previous = self.hair.last_pointer.replace(pointer).unwrap_or(pointer);
        let distance = pointer.distance(previous);
        let tool = self.hair.tool.unwrap_or(HairTool::Select);
        let hit = self.lock_at(pointer, rect);
        let result: Result<(), String> = (|| {
            if tool == HairTool::Erase {
                let mut ids = self.brush_locks(pointer, rect);
                if self.hair.symmetry {
                    let pairs: Vec<_> = state
                        .locks
                        .iter()
                        .filter(|l| ids.contains(&l.id))
                        .filter_map(|l| l.mirrored)
                        .collect();
                    ids.extend(pairs);
                }
                for id in ids {
                    self.hair.stroke_changed |= self.hair.selected.insert(id as usize);
                }
                return Ok(());
            }
            if tool == HairTool::Guide || tool == HairTool::Paint {
                if state.groups.iter().any(|g| g.mode == GroupMode::Existing) {
                    return Err("Draw is available in Create hairstyle. Existing hair can be reshaped, cut or deleted.".into());
                }
                if self.hair.drawing.is_empty() {
                    let ray = self
                        .camera
                        .screen_ray(pointer, rect)
                        .ok_or("Point at the scalp to draw")?;
                    let Some(root) = self.pick_hair_scalp(ray.0, ray.1) else {
                        return Ok(());
                    };
                    let position = state.scalp.point(&root).map_err(|e| e.to_string())?;
                    let normal = state.scalp.normal(&root).normalize_or_zero();
                    let group = self.hair.group;
                    let part = state
                        .groups
                        .iter()
                        .find(|g| g.id == group)
                        .ok_or("Missing hair material")?
                        .part;
                    let guide = state.guides.len() as u32;
                    if guide as usize + if self.hair.symmetry { 2 } else { 1 } > hair::MAX_GUIDES {
                        return Err("Hair guide limit reached".into());
                    }
                    state.guides.push(hair::Guide {
                        root,
                        group,
                        points: vec![position.to_array(), (position + normal * 0.002).to_array()],
                    });
                    let id = state.next_lock_id;
                    state.next_lock_id += 1;
                    state.locks.push(locks::HairLock {
                        id,
                        part,
                        guide: Some(guide),
                        vertices: vec![],
                        kind: LockKind::Generated,
                        mirrored: None,
                        width_scale: 1.0,
                        cards: 0,
                    });
                    self.hair.drawing.push(id);
                    self.hair.last_plant = Some(position);
                    if self.hair.symmetry && position.x.abs() > 0.001 {
                        let attachment = state.scalp.nearest(position * Vec3::new(-1.0, 1.0, 1.0));
                        let mirrored = state.scalp.point(&attachment).map_err(|e| e.to_string())?;
                        let gi = state.guides.len() as u32;
                        let pair = state.next_lock_id;
                        state.next_lock_id += 1;
                        state.guides.push(hair::Guide {
                            root: attachment,
                            group,
                            points: vec![
                                mirrored.to_array(),
                                (mirrored + normal * Vec3::new(-1.0, 1.0, 1.0) * 0.002).to_array(),
                            ],
                        });
                        state.locks.last_mut().unwrap().mirrored = Some(pair);
                        state.locks.push(locks::HairLock {
                            id: pair,
                            part,
                            guide: Some(gi),
                            vertices: vec![],
                            kind: LockKind::Generated,
                            mirrored: Some(id),
                            width_scale: 1.0,
                            cards: 0,
                        });
                        self.hair.drawing.push(pair);
                    }
                    self.hair.selected = self.hair.drawing.iter().map(|id| *id as usize).collect();
                } else if distance >= 0.5 {
                    let root = self.hair.last_plant.unwrap();
                    let start = self.hair.stroke_start.unwrap();
                    let delta = self.camera.plane_drag_delta(
                        self.camera.forward(),
                        root,
                        start,
                        pointer,
                        rect,
                    );
                    for (i, id) in self.hair.drawing.iter().enumerate() {
                        let lock = state.locks.iter().find(|l| l.id == *id).unwrap();
                        let guide = &mut state.guides[lock.guide.unwrap() as usize];
                        let tip = Vec3::from(guide.points[0])
                            + delta
                                * if i == 0 {
                                    Vec3::ONE
                                } else {
                                    Vec3::new(-1.0, 1.0, 1.0)
                                };
                        if tip.distance(Vec3::from(guide.points[0])) > 0.002 {
                            if guide.points.len() == 2 && !self.hair.stroke_changed {
                                guide.points[1] = tip.to_array();
                            } else if guide.points.len() < hair::MAX_POINTS
                                && tip.distance(Vec3::from(*guide.points.last().unwrap())) > 0.001
                            {
                                guide.points.push(tip.to_array());
                            }
                            self.hair.stroke_changed = true;
                        }
                    }
                }
                return Ok(());
            }
            if tool == HairTool::Root {
                if self.hair.selected.is_empty() {
                    return Err("Select hair sections, then click their shared scalp root".into());
                }
                let parts: BTreeSet<_> = state
                    .locks
                    .iter()
                    .filter(|l| self.hair.selected.contains(&(l.id as usize)))
                    .map(|l| l.part)
                    .collect();
                if parts.len() != 1 {
                    return Err(
                        "Group sections from one material at a time, then set their shared root"
                            .into(),
                    );
                }
                if self.hair.selected.len() > 1 {
                    let selected = self.hair.selected.clone();
                    let id = *selected.iter().min().unwrap() as u64;
                    let vertices: Vec<_> = state
                        .locks
                        .iter()
                        .filter(|l| selected.contains(&(l.id as usize)))
                        .flat_map(|l| l.vertices.clone())
                        .collect();
                    let removed = state
                        .locks
                        .iter()
                        .filter(|l| selected.contains(&(l.id as usize)))
                        .filter_map(|l| l.guide.map(|g| g as usize))
                        .collect();
                    let part = *parts.first().unwrap();
                    locks::remove_guides(&mut state, &removed);
                    state.locks.retain(|l| !selected.contains(&(l.id as usize)));
                    state.locks.push(locks::HairLock {
                        id,
                        part,
                        guide: None,
                        vertices,
                        kind: LockKind::Unresolved,
                        mirrored: None,
                        width_scale: 1.0,
                        cards: 0,
                    });
                    self.hair.selected = HashSet::from([id as usize]);
                }
                let ray = self
                    .camera
                    .screen_ray(pointer, rect)
                    .ok_or("Point at the scalp")?;
                let Some(root) = self.pick_hair_scalp(ray.0, ray.1) else {
                    return Ok(());
                };
                let position = state.scalp.point(&root).map_err(|e| e.to_string())?;
                let index = state
                    .locks
                    .iter()
                    .position(|l| self.hair.selected.contains(&(l.id as usize)))
                    .ok_or("Select a hair section")?;
                let lock = state.locks[index].clone();
                let doc = self
                    .hair
                    .preview
                    .as_ref()
                    .or(self.document.as_ref())
                    .ok_or("Loading hair")?;
                let part = &doc.lods[0].submeshes[lock.part as usize];
                let tip = lock
                    .vertices
                    .iter()
                    .map(|i| Vec3::from(part.positions[*i as usize]))
                    .max_by(|a, b| {
                        a.distance_squared(position)
                            .total_cmp(&b.distance_squared(position))
                    })
                    .ok_or("Empty hair section")?;
                let group = state
                    .groups
                    .iter()
                    .find(|g| g.part == lock.part)
                    .unwrap()
                    .id;
                let points = (0..16)
                    .map(|i| position.lerp(tip, i as f32 / 15.0).to_array())
                    .collect();
                let gi = if let Some(gi) = lock.guide {
                    state.guides[gi as usize] = hair::Guide {
                        root,
                        group,
                        points,
                    };
                    gi
                } else {
                    let gi = state.guides.len() as u32;
                    state.guides.push(hair::Guide {
                        root,
                        group,
                        points,
                    });
                    gi
                };
                state.locks[index].guide = Some(gi);
                state.locks[index].kind = LockKind::Bound;
                locks::bind_lock(&mut state, index, &part.positions, &part.normals)
                    .map_err(|e| e.to_string())?;
                self.hair.stroke_changed = true;
                return Ok(());
            }
            if distance < 0.001 {
                return Ok(());
            }
            let ids: Vec<_> = if tool == HairTool::Move || tool == HairTool::Lengthen {
                self.hair.selected.iter().map(|i| *i as u64).collect()
            } else {
                let brushed = self.brush_locks(pointer, rect);
                brushed
                    .into_iter()
                    .filter(|id| {
                        self.hair.selected.is_empty()
                            || self.hair.selected.contains(&(*id as usize))
                    })
                    .collect()
            };
            let mut guides: Vec<_> = state
                .locks
                .iter()
                .filter(|l| ids.contains(&l.id))
                .filter_map(|l| l.guide.map(|g| g as usize))
                .collect();
            if guides.is_empty() {
                if hit.is_some() {
                    self.hair.feedback =
                        "This is a rigid or unresolved section. Correct its root to groom it."
                            .into();
                }
                return Ok(());
            }
            if let Some(primary) = self
                .hair
                .stroke_primary
                .and_then(|id| state.locks.iter().find(|l| l.id == id))
                .and_then(|l| l.guide)
            {
                guides.sort_by_key(|g| if *g == primary as usize { 0 } else { 1 });
            }
            let pivot = Vec3::from(state.guides[guides[0]].points[0]);
            let delta = self.hair.rotation.inverse()
                * self.camera.plane_drag_delta(
                    self.camera.forward(),
                    pivot,
                    previous,
                    pointer,
                    rect,
                );
            let strength = if matches!(tool, HairTool::Move | HairTool::Comb | HairTool::Lengthen) {
                if tool == HairTool::Move {
                    1.0
                } else {
                    self.hair.strength
                }
            } else {
                1.0 - (-distance * self.hair.strength / 40.0).exp()
            };
            let groom = match tool {
                HairTool::Smooth => Groom::Smooth,
                HairTool::Lengthen => Groom::Lengthen,
                HairTool::Curl => Groom::Curl,
                HairTool::Clump => Groom::Clump,
                _ => Groom::Comb,
            };
            if matches!(tool, HairTool::Smooth | HairTool::Curl | HairTool::Clump) {
                // Evaluate the rest shape at cumulative stroke distance. Splitting
                // the same stroke into more mouse events cannot amplify the tool.
                let mut affected: BTreeSet<_> = guides.iter().copied().collect();
                if self.hair.symmetry {
                    locks::extend_mirrored_guides(&state, &mut affected);
                }
                if let Some(before) = &self.hair.state {
                    for &gi in &affected {
                        state.guides[gi] = before.guides[gi].clone();
                        *self.hair.stroke_distances.entry(gi).or_default() += distance;
                    }
                }
                let total = affected
                    .iter()
                    .map(|g| self.hair.stroke_distances[g])
                    .fold(f32::INFINITY, f32::min);
                let strength = 1.0 - (-total * self.hair.strength / 40.0).exp();
                hair::groom(
                    &mut state,
                    &guides,
                    groom,
                    strength,
                    delta.to_array(),
                    self.hair.symmetry,
                )
                .map_err(|e| e.to_string())?;
            } else {
                hair::groom(
                    &mut state,
                    &guides,
                    groom,
                    strength,
                    delta.to_array(),
                    self.hair.symmetry,
                )
                .map_err(|e| e.to_string())?;
            }
            self.hair.stroke_changed = true;
            Ok(())
        })();
        if let Err(error) = result {
            self.hair.feedback = error;
        }
        self.hair.stroke = Some(state);
        if let Some(scene) = &mut self.hair.scene {
            scene.applied = false;
        }
    }

    pub(crate) fn paint_hair_guides(&self, ui: &egui::Ui, rect: egui::Rect) {
        if !self.hair.active() {
            return;
        }
        let Some(state) = self.hair.stroke.as_ref().or(self.hair.state.as_ref()) else {
            return;
        };
        if let Some(scene) = &self.hair.scene {
            let mut samples = 0;
            for lock in &state.locks {
                let selected = self.hair.selected.contains(&(lock.id as usize));
                let hovered = self.hair.hover == Some(lock.id);
                let unresolved = lock.kind == LockKind::Unresolved;
                if !selected && !hovered && !unresolved {
                    continue;
                }
                let color = if unresolved {
                    Color32::from_rgb(240, 165, 60)
                } else if hovered {
                    Color32::from_rgb(100, 220, 255)
                } else {
                    Color32::from_rgb(70, 170, 245)
                };
                if let Some((_, first, count, _)) = scene
                    .parts
                    .iter()
                    .find(|(part, _, _, _)| *part == lock.part)
                {
                    for v in lock
                        .vertices
                        .iter()
                        .step_by((lock.vertices.len() / 24).max(1))
                    {
                        if samples >= 512 {
                            break;
                        }
                        samples += 1;
                        if (*v as usize) >= *count {
                            continue;
                        }
                        let Some(p) = self
                            .camera
                            .project(Vec3::from(scene.frame.positions[first + *v as usize]), rect)
                        else {
                            continue;
                        };
                        if self.lock_at(p.screen, rect).is_some_and(|h| h.0 == lock.id) {
                            ui.painter().circle_filled(
                                egui::pos2(p.screen.x, p.screen.y),
                                1.4,
                                color,
                            );
                        }
                    }
                }
            }
        }
        if self.hair.show_guides || self.hair.show_collisions {
            let (min, max) = hair_bounds(state);
            let height = (max.y - min.y).max(0.01);
            let pivot = self.hair.simulation.as_ref().map_or(
                Vec3::new((min.x + max.x) * 0.5, min.y, (min.z + max.z) * 0.5),
                |s| s.pivot,
            );
            let pose = hair::PreviewPose::at(
                pivot,
                height,
                self.hair
                    .simulation
                    .as_ref()
                    .map_or(0.0, |s| s.elapsed as f32),
                self.hair.head_test,
            );
            if self.hair.show_guides {
                for (index, guide) in state.guides.iter().enumerate() {
                    let points: Vec<_> = if self.hair.stroke.is_none() {
                        self.hair
                            .simulation
                            .as_ref()
                            .and_then(|s| s.points.get(index))
                            .cloned()
                            .unwrap_or_else(|| guide.points.clone())
                    } else {
                        guide
                            .points
                            .iter()
                            .map(|p| pose.head_point(Vec3::from(*p)).to_array())
                            .collect()
                    };
                    if let Some(root) = points
                        .first()
                        .and_then(|p| self.camera.project(Vec3::from(*p), rect))
                    {
                        ui.painter().circle_filled(
                            egui::pos2(root.screen.x, root.screen.y),
                            3.0,
                            Color32::LIGHT_GREEN,
                        );
                    }
                    for pair in points.windows(2) {
                        if let (Some(a), Some(b)) = (
                            self.camera.project(Vec3::from(pair[0]), rect),
                            self.camera.project(Vec3::from(pair[1]), rect),
                        ) {
                            ui.painter().line_segment(
                                [
                                    egui::pos2(a.screen.x, a.screen.y),
                                    egui::pos2(b.screen.x, b.screen.y),
                                ],
                                egui::Stroke::new(1.0, Color32::from_rgb(220, 170, 80)),
                            );
                        }
                    }
                }
            }
            if self.hair.show_collisions {
                for capsule in &state.collisions {
                    let transform = |p| {
                        if capsule.follows_head {
                            pose.head_point(p)
                        } else {
                            pose.body_point(p)
                        }
                    };
                    let a = transform(Vec3::from(capsule.a));
                    let b = transform(Vec3::from(capsule.b));
                    let stroke = egui::Stroke::new(1.0, Color32::LIGHT_GREEN);
                    for center in [a, b] {
                        for plane in [(Vec3::X, Vec3::Y), (Vec3::Y, Vec3::Z), (Vec3::X, Vec3::Z)] {
                            for segment in 0..24 {
                                let point = |i: f32| {
                                    center
                                        + (plane.0 * (i * std::f32::consts::TAU / 24.0).cos()
                                            + plane.1 * (i * std::f32::consts::TAU / 24.0).sin())
                                            * capsule.radius
                                };
                                if let (Some(p), Some(q)) = (
                                    self.camera.project(point(segment as f32), rect),
                                    self.camera.project(point((segment + 1) as f32), rect),
                                ) {
                                    ui.painter().line_segment(
                                        [
                                            egui::pos2(p.screen.x, p.screen.y),
                                            egui::pos2(q.screen.x, q.screen.y),
                                        ],
                                        stroke,
                                    );
                                }
                            }
                        }
                    }
                    if let (Some(p), Some(q)) =
                        (self.camera.project(a, rect), self.camera.project(b, rect))
                    {
                        ui.painter().line_segment(
                            [
                                egui::pos2(p.screen.x, p.screen.y),
                                egui::pos2(q.screen.x, q.screen.y),
                            ],
                            stroke,
                        );
                    }
                }
            }
        }
        if let Some(pointer) = ui
            .input(|i| i.pointer.hover_pos())
            .filter(|p| rect.contains(*p))
        {
            if self.hair.tool == Some(HairTool::Cut) && self.hair.cut_preview.is_some() {
                ui.painter().line_segment(
                    [
                        pointer - egui::vec2(8.0, 0.0),
                        pointer + egui::vec2(8.0, 0.0),
                    ],
                    egui::Stroke::new(2.0, Color32::RED),
                );
            } else if !matches!(
                self.hair.tool,
                Some(HairTool::Select | HairTool::Move | HairTool::Guide | HairTool::Root)
            ) {
                ui.painter().circle_stroke(
                    pointer,
                    self.hair.radius,
                    egui::Stroke::new(1.0, Color32::LIGHT_BLUE),
                );
            }
            if self.hair.tool == Some(HairTool::Select) {
                if let Some(start) = self.hair.stroke_start {
                    ui.painter().rect_stroke(
                        egui::Rect::from_two_pos(egui::pos2(start.x, start.y), pointer),
                        0.0,
                        egui::Stroke::new(1.0, Color32::LIGHT_BLUE),
                        egui::StrokeKind::Inside,
                    );
                }
            }
        }
    }
}
