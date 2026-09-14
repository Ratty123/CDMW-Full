use super::*;
use cdmw_mesh::hair::locks::{self, LockKind};
use std::collections::BTreeSet;

pub(super) fn prepare(
    mut state: HairState,
    mut document: MeshDocument,
    label: String,
    operation: Preparation,
    cancelled: &AtomicBool,
) -> Result<PreparedHair, String> {
    let start = Instant::now();
    let check = || {
        if cancelled.load(Ordering::Relaxed) {
            Err("Hair preparation cancelled".to_owned())
        } else {
            Ok(())
        }
    };
    check()?;
    if matches!(operation, Preparation::Rebind) {
        state
            .rebind_cancellable(state.scalp.clone(), cancelled)
            .map_err(|e| e.to_string())?;
    }
    if let Preparation::Fill(group, preset, length) = operation {
        let generated = state
            .groups
            .iter()
            .any(|g| g.id == group && g.mode == GroupMode::Generated);
        if !generated {
            return Err(
                "Presets create new hair. Use Create hairstyle to start from a preset.".into(),
            );
        }
        let removed = state
            .guides
            .iter()
            .enumerate()
            .filter(|(_, g)| g.group == group)
            .map(|(i, _)| i)
            .collect();
        locks::remove_guides(&mut state, &removed);
        let (min, max) = hair_bounds(&state);
        let top = min.y + (max.y - min.y) * 0.60;
        let mut faces = Vec::new();
        let mut area = 0.0;
        for (i, face) in state.scalp.triangles.iter().enumerate() {
            let [a, b, c] = face.map(|v| Vec3::from(state.scalp.positions[v as usize]));
            if a.y.min(b.y).min(c.y) < top {
                continue;
            }
            let size = (b - a).cross(c - a).length() * 0.5;
            if size > 1e-12 {
                area += size;
                faces.push((i as u32, area));
            }
        }
        if faces.is_empty() {
            return Err("The head has no upper scalp surface. Change the head reference.".into());
        }
        for i in 0..256 {
            check()?;
            let target = area * (i as f32 + 0.5) / 256.0;
            let index = faces
                .partition_point(|(_, sum)| *sum < target)
                .min(faces.len() - 1);
            let u = ((i as f32 * 0.618034 + 0.5).fract()).sqrt();
            let v = (i as f32 * 0.414214 + 0.25).fract();
            hair::plant_guide(
                &mut state,
                Attachment {
                    triangle: faces[index].0,
                    barycentric: [1.0 - u, u * (1.0 - v), u * v],
                },
                group,
                preset,
                length,
                16,
            )
            .map_err(|e| e.to_string())?;
        }
    }
    let lod = document.lods.first_mut().ok_or("Hair requires LOD0")?;
    if matches!(operation, Preparation::Analyze) {
        for group in state
            .groups
            .clone()
            .iter()
            .filter(|g| g.mode == GroupMode::Existing)
        {
            let part = lod
                .submeshes
                .get(group.part as usize)
                .ok_or("Missing hair material part")?;
            locks::prepare_existing(
                &mut state,
                group.part,
                &part.positions,
                &part.normals,
                &part.uvs,
                &part.indices,
                cancelled,
            )
            .map_err(|e| e.to_string())?;
            if !state.prepared_parts.contains(&group.part) {
                state.prepared_parts.push(group.part);
            }
        }
    }
    if let Preparation::Bind(group) = operation {
        let part_index = state
            .groups
            .iter()
            .find(|g| g.id == group)
            .ok_or("Choose a hair group")?
            .part;
        let part = &lod.submeshes[part_index as usize];
        hair::bind_existing(&mut state, part_index, &part.positions, cancelled)
            .map_err(|e| e.to_string())?;
        let guide_indices: Vec<_> = state
            .guides
            .iter()
            .enumerate()
            .filter(|(_, g)| g.group == group)
            .map(|(i, _)| i)
            .collect();
        state.locks.retain(|l| l.part != part_index);
        for gi in guide_indices {
            let vertices = state
                .bindings
                .iter()
                .filter(|b| b.part == part_index && b.guide == gi as u32)
                .map(|b| b.vertex)
                .collect();
            let id = state.next_lock_id;
            state.next_lock_id += 1;
            state.locks.push(locks::HairLock {
                id,
                part: part_index,
                guide: Some(gi as u32),
                vertices,
                kind: LockKind::Bound,
                mirrored: None,
                width_scale: 1.0,
                cards: 0,
            });
            let lock_index = state.locks.len() - 1;
            locks::bind_lock(&mut state, lock_index, &part.positions, &part.normals)
                .map_err(|e| e.to_string())?;
        }
        if !state.prepared_parts.contains(&part_index) {
            state.prepared_parts.push(part_index);
        }
    }
    if let Preparation::Delete(ref ids) = operation {
        delete_locks(&mut state, &mut document, ids)?;
    }
    if let Preparation::Cut(id, segment, t, symmetry) = operation {
        let lock = state
            .locks
            .iter()
            .find(|l| l.id == id)
            .ok_or("Point at a hair lock to cut")?;
        let pair = if symmetry { lock.mirrored } else { None };
        let source_points = lock
            .guide
            .map(|g| state.guides[g as usize].points.len())
            .unwrap_or(2);
        let fraction = (segment as f32 + t) / (source_points - 1) as f32;
        cut_lock(&mut state, &mut document, id, segment, t)?;
        if let Some(pair) = pair {
            if let Some(guide) = state
                .locks
                .iter()
                .find(|l| l.id == pair)
                .and_then(|l| l.guide)
            {
                let along = fraction * (state.guides[guide as usize].points.len() - 1) as f32;
                cut_lock(
                    &mut state,
                    &mut document,
                    pair,
                    along.floor() as u32,
                    along.fract(),
                )?;
            }
        }
    }
    if matches!(operation, Preparation::Empty) {
        let removed = state
            .guides
            .iter()
            .enumerate()
            .filter(|(_, g)| {
                state
                    .groups
                    .iter()
                    .any(|p| p.id == g.group && p.mode == GroupMode::Generated)
            })
            .map(|(i, _)| i)
            .collect();
        locks::remove_guides(&mut state, &removed);
    }
    let rebuild = !matches!(
        operation,
        Preparation::Deform | Preparation::Metadata | Preparation::Analyze | Preparation::Bind(_)
    );
    if rebuild {
        let generated: BTreeSet<_> = state
            .groups
            .iter()
            .filter(|g| g.mode == GroupMode::Generated)
            .map(|g| g.part)
            .collect();
        state.bindings.retain(|b| !generated.contains(&b.part));
        for geometry in hair::generate(&state, cancelled).map_err(|e| e.to_string())? {
            let part = &mut document.lods[0].submeshes[geometry.part as usize];
            part.positions = geometry.positions;
            part.normals = geometry.normals;
            part.uvs = geometry.uvs;
            part.indices = geometry.indices;
            part.source_vertex_indices = vec![-1; part.positions.len()];
            state.bindings.extend(geometry.bindings);
        }
        for group in &state.groups {
            if group.mode == GroupMode::Generated
                && !state.guides.iter().any(|g| g.group == group.id)
            {
                let part = &mut document.lods[0].submeshes[group.part as usize];
                part.positions.clear();
                part.normals.clear();
                part.uvs.clear();
                part.indices.clear();
                part.source_vertex_indices.clear();
            }
        }
        locks::synchronize_generated(&mut state);
    }
    if !matches!(
        operation,
        Preparation::Metadata | Preparation::Analyze | Preparation::Bind(_)
    ) {
        let points: Vec<_> = state.guides.iter().map(|g| g.points.clone()).collect();
        for group in &state.groups {
            let part = &mut document.lods[0].submeshes[group.part as usize];
            hair::deform(&state.bindings, &points, group.part, &mut part.positions)
                .map_err(|e| e.to_string())?;
            locks::deform_normals(&state.bindings, &points, group.part, &mut part.normals);
        }
    }
    state.validate().map_err(|e| e.to_string())?;
    check()?;
    for group in state
        .groups
        .iter()
        .filter(|g| g.mode == GroupMode::Existing)
    {
        state.vertex_sources.insert(
            group.part,
            document.lods[0].submeshes[group.part as usize]
                .source_vertex_indices
                .clone(),
        );
    }
    Ok(PreparedHair {
        state,
        document,
        label,
        milliseconds: start.elapsed().as_secs_f64() * 1000.0,
    })
}

fn compact_part(
    state: &mut HairState,
    document: &mut MeshDocument,
    part_id: u32,
    removed: &BTreeSet<u32>,
) {
    let part = &mut document.lods[0].submeshes[part_id as usize];
    let kept: Vec<_> = part
        .indices
        .chunks_exact(3)
        .filter(|f| f.iter().all(|v| !removed.contains(v)))
        .flat_map(|f| f.iter().copied())
        .collect();
    let used: BTreeSet<_> = kept.iter().copied().collect();
    let mut map = HashMap::new();
    for (next, old) in used.iter().enumerate() {
        map.insert(*old, next as u32);
    }
    part.positions = used.iter().map(|i| part.positions[*i as usize]).collect();
    part.normals = used.iter().map(|i| part.normals[*i as usize]).collect();
    part.uvs = used.iter().map(|i| part.uvs[*i as usize]).collect();
    part.source_vertex_indices = used
        .iter()
        .map(|i| {
            part.source_vertex_indices
                .get(*i as usize)
                .copied()
                .unwrap_or(-1)
        })
        .collect();
    part.indices = kept.iter().map(|i| map[i]).collect();
    state.bindings.retain_mut(|b| {
        b.part != part_id
            || if let Some(v) = map.get(&b.vertex) {
                b.vertex = *v;
                true
            } else {
                false
            }
    });
    for lock in state.locks.iter_mut().filter(|l| l.part == part_id) {
        lock.vertices = lock
            .vertices
            .iter()
            .filter_map(|v| map.get(v).copied())
            .collect();
    }
}

pub(super) fn delete_locks(
    state: &mut HairState,
    document: &mut MeshDocument,
    ids: &[u64],
) -> Result<(), String> {
    let mut parts: HashMap<u32, BTreeSet<u32>> = HashMap::new();
    let mut guides = BTreeSet::new();
    for lock in state.locks.iter().filter(|l| ids.contains(&l.id)) {
        parts
            .entry(lock.part)
            .or_default()
            .extend(lock.vertices.iter().copied());
        if let Some(g) = lock.guide {
            guides.insert(g as usize);
        }
    }
    for (part, vertices) in parts {
        compact_part(state, document, part, &vertices);
    }
    state.locks.retain(|l| !ids.contains(&l.id));
    locks::remove_guides(state, &guides);
    Ok(())
}

fn cut_lock(
    state: &mut HairState,
    document: &mut MeshDocument,
    id: u64,
    segment: u32,
    t: f32,
) -> Result<(), String> {
    let lock = state
        .locks
        .iter()
        .find(|l| l.id == id)
        .ok_or("Point at a hair lock to cut")?
        .clone();
    let gi = lock
        .guide
        .ok_or("Correct this lock's root before cutting")?;
    let guide = &state.guides[gi as usize];
    let segment = (segment as usize).min(guide.points.len() - 2);
    let t = t.clamp(0.01, 1.0);
    let tip = Vec3::from(guide.points[segment])
        .lerp(Vec3::from(guide.points[segment + 1]), t)
        .to_array();
    let remove: BTreeSet<_> = state
        .bindings
        .iter()
        .filter(|b| b.guide == gi && b.segment as f32 + b.t > segment as f32 + t + 1e-5)
        .map(|b| b.vertex)
        .collect();
    if lock.kind == LockKind::Bound {
        compact_part(state, document, lock.part, &remove);
    }
    let guide = &mut state.guides[gi as usize];
    guide.points.truncate(segment + 1);
    guide.points.push(tip);
    for b in state.bindings.iter_mut().filter(|b| b.guide == gi) {
        if b.segment as usize >= segment {
            b.segment = segment as u32;
            b.t = (b.t / t).min(1.0);
        }
    }
    Ok(())
}
