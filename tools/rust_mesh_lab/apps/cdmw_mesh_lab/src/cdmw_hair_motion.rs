use super::*;

impl LabApplication {
    pub(crate) fn render_hair(&mut self) {
        if !self.hair.active()
            || self.cdmw_state["replacement"]["comparison"]
                .as_str()
                .is_some_and(|v| v != "edit")
        {
            return;
        }
        if self.hair.playing
            && self.hair.motion_validated_revision != self.hair.state.as_ref().map(|s| s.revision)
        {
            match self.hair_motion_reason() {
                Ok(()) => {
                    self.hair.motion_validated_revision =
                        self.hair.state.as_ref().map(|s| s.revision)
                }
                Err(error) => {
                    self.hair.playing = false;
                    self.hair.feedback = error;
                }
            }
        }
        let visible = self.cdmw_visible_submeshes();
        let Some(state) = self.hair.state.as_ref() else {
            return;
        };
        let Some(document) = self.hair.preview.as_ref().or(self.document.as_ref()) else {
            return;
        };
        if self
            .hair
            .scene
            .as_ref()
            .is_none_or(|s| s.show_reference != self.hair.show_reference)
        {
            self.hair.scene = Some(build_scene(
                document,
                state,
                self.hair.show_reference,
                visible.as_ref(),
                self.hair.draw_revision + 1,
            ));
        }
        let (min, max) = hair_bounds(state);
        let height = (max.y - min.y).max(0.01);
        let pivot = self.hair.simulation.as_ref().map_or(
            Vec3::new((min.x + max.x) * 0.5, min.y, (min.z + max.z) * 0.5),
            |s| s.pivot,
        );
        let now = Instant::now();
        let dt = now.duration_since(self.hair.last_tick).as_secs_f64();
        self.hair.last_tick = now;
        if self.hair.playing && !self.hair.topology_busy && self.hair.stroke.is_none() {
            if self.hair.simulation.is_none() {
                self.hair.simulation = Simulation::new(state).ok();
            }
            if let Some(sim) = &mut self.hair.simulation {
                match sim.advance_test(
                    dt,
                    self.hair.motion,
                    &state.collisions,
                    self.hair.head_test,
                    height,
                ) {
                    Ok(pose) => self.hair.rotation = pose.head,
                    Err(error) => {
                        self.hair.feedback = error.to_string();
                        self.hair.playing = false;
                    }
                }
            }
        }
        let elapsed = self
            .hair
            .simulation
            .as_ref()
            .map_or(0.0, |s| s.elapsed as f32);
        let pose = hair::PreviewPose::at(pivot, height, elapsed, self.hair.head_test);
        let scene = self.hair.scene.as_mut().unwrap();
        if scene.applied && !self.hair.playing {
            return;
        }
        let snapshot = &mut scene.frame;
        snapshot.positions.clone_from(&scene.rest.positions);
        snapshot.normals.clone_from(&scene.rest.normals);
        snapshot.uvs.clone_from(&scene.rest.uvs);
        snapshot.indices.clone_from(&scene.rest.indices);
        snapshot
            .triangle_materials
            .clone_from(&scene.rest.triangle_materials);
        scene.vertex_locks.truncate(scene.rest.positions.len());
        let editing = self
            .hair
            .stroke
            .as_ref()
            .or_else(|| self.hair.job.as_ref().map(|_| state));
        let stroke_points = editing.map(|s| {
            s.guides
                .iter()
                .map(|g| {
                    g.points
                        .iter()
                        .map(|p| pose.head_point(Vec3::from(*p)).to_array())
                        .collect()
                })
                .collect::<Vec<Vec<_>>>()
        });
        let current_points;
        let points = if let Some(points) = stroke_points.as_ref() {
            points
        } else if let Some(sim) = self.hair.simulation.as_ref().filter(|s| s.elapsed > 0.0) {
            &sim.points
        } else {
            current_points = state
                .guides
                .iter()
                .map(|g| g.points.clone())
                .collect::<Vec<_>>();
            &current_points
        };
        let bindings = self
            .hair
            .stroke
            .as_ref()
            .map_or(state.bindings.as_slice(), |s| s.bindings.as_slice());
        for (part, first, count, _) in &scene.parts {
            if let Err(error) = hair::deform(
                bindings,
                points,
                *part,
                &mut snapshot.positions[*first..first + count],
            ) {
                self.hair.feedback = format!("Motion stopped: {error}");
                self.hair.playing = false;
                return;
            }
            locks::deform_normals(
                bindings,
                points,
                *part,
                &mut snapshot.normals[*first..first + count],
            );
            for lock in state
                .locks
                .iter()
                .filter(|l| l.part == *part && l.kind == LockKind::Rigid)
            {
                for &v in &lock.vertices {
                    let index = first + v as usize;
                    if index < first + count {
                        snapshot.positions[index] = pose
                            .head_point(Vec3::from(scene.rest.positions[index]))
                            .to_array();
                        snapshot.normals[index] =
                            (pose.head * Vec3::from(scene.rest.normals[index])).to_array();
                    }
                }
            }
        }
        for i in scene.reference_start..snapshot.positions.len() {
            let rest = Vec3::from(scene.rest.positions[i]);
            let weight = if scene
                .head_reference_ranges
                .iter()
                .any(|range| range.contains(&i))
            {
                1.0
            } else {
                ((rest.y - pivot.y + height * 0.22) / (height * 0.34)).clamp(0.0, 1.0)
            };
            let weight = weight * weight * (3.0 - 2.0 * weight);
            snapshot.positions[i] = pose
                .body_point(rest)
                .lerp(pose.head_point(rest), weight)
                .to_array();
            snapshot.normals[i] =
                (pose.body.slerp(pose.head, weight) * Vec3::from(scene.rest.normals[i])).to_array();
        }
        if self.hair.stroke.is_some() && self.hair.tool == Some(HairTool::Erase) {
            let mut indices = vec![];
            let mut materials = vec![];
            for (i, face) in snapshot.indices.chunks_exact(3).enumerate() {
                if !face.iter().any(|v| {
                    scene.vertex_locks[*v as usize]
                        .is_some_and(|id| self.hair.selected.contains(&(id as usize)))
                }) {
                    indices.extend_from_slice(face);
                    materials.push(snapshot.triangle_materials[i]);
                }
            }
            snapshot.indices = indices;
            snapshot.triangle_materials = materials;
        }
        // A drawn lock has its own tiny generated buffer until release. Existing
        // hair, reference geometry and DDS resources remain resident.
        if let Some(stroke) = self
            .hair
            .stroke
            .as_ref()
            .filter(|_| !self.hair.drawing.is_empty())
        {
            if let Ok(generated) = hair::generate_cached(stroke, &AtomicBool::new(false),
                &scene.scalp_picking, &scene.scalp_indices, Some(&self.hair.drawing)) {
                for geometry in generated {
                    let first = snapshot.positions.len() as u32;
                    snapshot.positions.extend(
                        geometry
                            .positions
                            .iter()
                            .map(|p| pose.head_point(Vec3::from(*p)).to_array()),
                    );
                    snapshot.normals.extend(
                        geometry
                            .normals
                            .iter()
                            .map(|n| (pose.head * Vec3::from(*n)).to_array()),
                    );
                    snapshot.uvs.extend(geometry.uvs);
                    snapshot
                        .indices
                        .extend(geometry.indices.iter().map(|i| first + i));
                    snapshot.triangle_materials.extend(std::iter::repeat_n(
                        geometry.part,
                        geometry.indices.len() / 3,
                    ));
                    let mut owners = vec![None; geometry.positions.len()];
                    for b in geometry.bindings {
                        owners[b.vertex as usize] = stroke
                            .locks
                            .iter()
                            .find(|l| l.guide == Some(b.guide))
                            .map(|l| l.id);
                    }
                    scene.vertex_locks.extend(owners);
                }
            }
        }
        if snapshot.indices != scene.picking_indices {
            scene.picking =
                hair::surface::SurfaceIndex::new(&snapshot.positions, &snapshot.indices);
            scene.picking_indices.clone_from(&snapshot.indices);
            snapshot.topology_generation = self.hair.draw_revision + 1;
            snapshot.fingerprint = format!("hair-stroke-{}", self.hair.draw_revision + 1);
        } else {
            scene.picking.refit(&snapshot.positions, &snapshot.indices);
        }
        self.hair.draw_revision += 1;
        snapshot.draw_revision = self.hair.draw_revision;
        if let Some(renderer) = &mut self.renderer {
            if let Err(error) = renderer.set_snapshot_with_deformation_interactive(snapshot, None) {
                self.hair.feedback = format!("Hair display stopped: {error}");
                self.hair.playing = false;
            }
        }
        scene.applied = true;
    }
}
