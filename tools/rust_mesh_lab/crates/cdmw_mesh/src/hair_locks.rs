//! Visible lock ownership and card preparation, independent of material Parts.
use super::*;
use std::collections::{BTreeMap, HashMap};

pub fn first_id() -> u64 {
    1
}
pub fn default_name() -> String {
    "My hairstyle".into()
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum LockKind {
    Generated,
    Bound,
    Rigid,
    Unresolved,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct HairLock {
    pub id: u64,
    pub part: u32,
    pub guide: Option<u32>,
    pub vertices: Vec<u32>,
    pub kind: LockKind,
    pub mirrored: Option<u64>,
    pub width_scale: f32,
    #[serde(default)]
    pub cards: u32,
}

pub fn validate(state: &HairState) -> Result<()> {
    require(
        ["", "cropped", "bob", "long", "ponytail", "empty"]
            .contains(&state.startup_preset.as_str()),
        "unknown hair preset",
    )?;
    require(state.locks.len() <= 16_384, "too many hair locks")?;
    require(
        !state.style_name.trim().is_empty() && state.style_name.len() <= 160,
        "name the hairstyle using at most 160 bytes",
    )?;
    let mut ids = BTreeSet::new();
    let mut vertices = BTreeSet::new();
    for lock in &state.locks {
        require(
            lock.id > 0 && lock.id < state.next_lock_id && ids.insert(lock.id),
            "duplicate or invalid lock identity",
        )?;
        require(lock.cards <= 32, "too many follower cards")?;
        require(
            lock.width_scale.is_finite() && (0.02..=20.0).contains(&lock.width_scale),
            "invalid lock width",
        )?;
        require(
            state.groups.iter().any(|g| g.part == lock.part),
            "lock has no material part",
        )?;
        if let Some(index) = lock.guide {
            let guide = state
                .guides
                .get(index as usize)
                .ok_or_else(|| HairError::Invalid("lock guide is missing".into()))?;
            require(
                state
                    .groups
                    .iter()
                    .any(|g| g.part == lock.part && g.id == guide.group),
                "lock guide crosses parts",
            )?;
        }
        require(
            lock.vertices
                .iter()
                .all(|v| (*v as usize) < MAX_HAIR_VERTICES && vertices.insert((lock.part, *v))),
            "ambiguous lock geometry ownership",
        )?;
    }
    for lock in &state.locks {
        if let Some(pair) = lock.mirrored {
            require(
                pair != lock.id
                    && state
                        .locks
                        .iter()
                        .any(|p| p.id == pair && p.mirrored == Some(lock.id)),
                "asymmetric mirror pairing",
            )?;
        }
    }
    Ok(())
}

pub fn extend_mirrored_guides(state: &HairState, guides: &mut BTreeSet<usize>) {
    let pairs: Vec<_> = state
        .locks
        .iter()
        .filter(|l| l.guide.is_some_and(|g| guides.contains(&(g as usize))))
        .filter_map(|l| l.mirrored)
        .collect();
    for lock in &state.locks {
        if pairs.contains(&lock.id) {
            if let Some(guide) = lock.guide {
                guides.insert(guide as usize);
            }
        }
    }
}

/// Parallel transport prevents side-axis flips along curved cards. All writers,
/// bindings and deformation use this same frame convention.
pub fn frames(points: &[[f32; 3]]) -> Vec<(Vec3, Vec3, Vec3)> {
    let mut result = Vec::with_capacity(points.len().saturating_sub(1));
    let mut previous: Option<(Vec3, Vec3)> = None;
    for pair in points.windows(2) {
        let tangent = (Vec3::from(pair[1]) - Vec3::from(pair[0])).normalize_or_zero();
        let side = match previous {
            Some((side, old)) => {
                let rotated = Quat::from_rotation_arc(old, tangent) * side;
                (rotated - tangent * rotated.dot(tangent)).normalize_or_zero()
            }
            None => super::segment_frame(Vec3::from(pair[0]), Vec3::from(pair[1])).0,
        };
        result.push((side, tangent.cross(side).normalize_or_zero(), tangent));
        previous = Some((side, tangent));
    }
    result
}

pub fn deform_normals(
    bindings: &[VertexBinding],
    points: &[Vec<[f32; 3]>],
    part: u32,
    normals: &mut [[f32; 3]],
) {
    let frames: Vec<_> = points.iter().map(|g| frames(g)).collect();
    for b in bindings.iter().filter(|b| b.part == part) {
        if let Some(normal) = normals.get_mut(b.vertex as usize) {
            if let Some(&(x, y, z)) = frames
                .get(b.guide as usize)
                .and_then(|f| f.get(b.segment as usize))
            {
                let local = Vec3::from(b.normal);
                if local.length_squared() > 0.1 {
                    *normal = (x * local.x + y * local.y + z * local.z)
                        .normalize_or_zero()
                        .to_array();
                }
            }
        }
    }
}

pub fn synchronize_generated(state: &mut HairState) {
    let generated: BTreeSet<_> = state
        .groups
        .iter()
        .filter(|g| g.mode == GroupMode::Generated)
        .map(|g| g.part)
        .collect();
    let mut ownership: BTreeMap<(u32, u32), Vec<u32>> = BTreeMap::new();
    for binding in &state.bindings {
        if generated.contains(&binding.part) {
            ownership
                .entry((binding.part, binding.guide))
                .or_default()
                .push(binding.vertex);
        }
    }
    state.locks.retain(|l| {
        !generated.contains(&l.part)
            || l.guide
                .is_some_and(|g| ownership.contains_key(&(l.part, g)))
    });
    for ((part, guide), vertices) in ownership {
        if let Some(lock) = state
            .locks
            .iter_mut()
            .find(|l| l.part == part && l.guide == Some(guide))
        {
            lock.vertices = vertices;
        } else {
            let id = state.next_lock_id;
            state.next_lock_id += 1;
            state.locks.push(HairLock {
                id,
                part,
                guide: Some(guide),
                vertices,
                kind: LockKind::Generated,
                mirrored: None,
                width_scale: 1.0,
                cards: 0,
            });
        }
    }
    repair_pairs(state);
}

fn repair_pairs(state: &mut HairState) {
    let ids: BTreeSet<_> = state.locks.iter().map(|l| l.id).collect();
    for lock in &mut state.locks {
        if lock.mirrored.is_some_and(|id| !ids.contains(&id)) {
            lock.mirrored = None;
        }
    }
}

pub fn remove_guides(state: &mut HairState, removed: &BTreeSet<usize>) {
    let mut map = HashMap::new();
    let mut next = 0;
    state.guides = std::mem::take(&mut state.guides)
        .into_iter()
        .enumerate()
        .filter_map(|(index, guide)| {
            if removed.contains(&index) {
                None
            } else {
                map.insert(index as u32, next);
                next += 1;
                Some(guide)
            }
        })
        .collect();
    state.bindings.retain_mut(|b| {
        if let Some(guide) = map.get(&b.guide) {
            b.guide = *guide;
            true
        } else {
            false
        }
    });
    state.locks.retain_mut(|l| match l.guide {
        Some(guide) => {
            if let Some(index) = map.get(&guide) {
                l.guide = Some(*index);
                true
            } else {
                false
            }
        }
        None => true,
    });
    repair_pairs(state);
}

pub fn readiness(state: &HairState, parts: &[(u32, usize)]) -> Result<()> {
    state.validate()?;
    require(
        !state.locks.iter().any(|l| l.kind == LockKind::Unresolved),
        "Motion preview needs grooming guides or rigid attachments for every section. Unchanged original hair can still be exported.",
    )?;
    require(
        !state.guides.is_empty(),
        if state.groups.iter().any(|g| g.mode == GroupMode::Existing) {
            "Prepare existing hair sections to preview motion. Unchanged original hair can still be exported."
        } else {
            "Draw a lock or apply a preset before playing motion"
        },
    )?;
    require(
        !state.bindings.is_empty(),
        "Prepare the hair sections before playing motion",
    )?;
    require(
        !state.locks.is_empty(),
        "Prepare this older hair draft to enable lock editing and motion",
    )?;
    let bound: BTreeSet<_> = state.bindings.iter().map(|b| (b.part, b.vertex)).collect();
    let rigid: BTreeSet<_> = state
        .locks
        .iter()
        .filter(|l| l.kind == LockKind::Rigid)
        .flat_map(|l| l.vertices.iter().map(|v| (l.part, *v)))
        .collect();
    for &(part, count) in parts {
        require(
            (0..count as u32).all(|v| bound.contains(&(part, v)) || rigid.contains(&(part, v))),
            "Some visible hair has no motion binding. Prepare or correct the highlighted sections",
        )?;
    }
    Ok(())
}

/// Bind one explicit card/lock, O(vertices * points). No nearest-guide search.
pub fn bind_lock(
    state: &mut HairState,
    lock_index: usize,
    positions: &[[f32; 3]],
    normals: &[[f32; 3]],
) -> Result<()> {
    let lock = &state.locks[lock_index];
    let gi = lock
        .guide
        .ok_or_else(|| HairError::Invalid("correct the lock's root first".into()))?;
    let guide = &state.guides[gi as usize];
    let frames = frames(&guide.points);
    let owned: BTreeSet<_> = lock.vertices.iter().copied().collect();
    state
        .bindings
        .retain(|b| b.part != lock.part || !owned.contains(&b.vertex));
    for &vertex in &lock.vertices {
        let p = Vec3::from(positions[vertex as usize]);
        let mut best = (f32::INFINITY, 0, 0.0, Vec3::ZERO);
        for (segment, pair) in guide.points.windows(2).enumerate() {
            let a = Vec3::from(pair[0]);
            let b = Vec3::from(pair[1]);
            let t = ((p - a).dot(b - a) / a.distance_squared(b).max(1e-12)).clamp(0.0, 1.0);
            let offset = p - a.lerp(b, t);
            if offset.length_squared() < best.0 {
                best = (offset.length_squared(), segment, t, offset);
            }
        }
        let (x, y, z) = frames[best.1];
        let n = normals
            .get(vertex as usize)
            .copied()
            .map(Vec3::from)
            .unwrap_or(y);
        state.bindings.push(VertexBinding {
            part: lock.part,
            vertex,
            guide: gi,
            segment: best.1 as u32,
            t: best.2,
            offset: [best.3.dot(x), best.3.dot(y), best.3.dot(z)],
            normal: [n.dot(x), n.dot(y), n.dot(z)],
        });
    }
    Ok(())
}

pub fn prepare_existing(
    state: &mut HairState,
    part: u32,
    positions: &[[f32; 3]],
    normals: &[[f32; 3]],
    uvs: &[[f32; 2]],
    indices: &[u32],
    cancelled: &AtomicBool,
) -> Result<()> {
    let group = state
        .groups
        .iter()
        .find(|g| g.part == part && g.mode == GroupMode::Existing)
        .ok_or_else(|| HairError::Invalid("Choose an existing hair part".into()))?
        .id;
    let removed = state
        .guides
        .iter()
        .enumerate()
        .filter(|(_, g)| g.group == group)
        .map(|(i, _)| i)
        .collect();
    remove_guides(state, &removed);
    state.locks.retain(|l| l.part != part);
    let mut parent: Vec<usize> = (0..positions.len()).collect();
    fn root(parent: &mut [usize], mut i: usize) -> usize {
        while parent[i] != i {
            parent[i] = parent[parent[i]];
            i = parent[i];
        }
        i
    }
    for face in indices.chunks_exact(3) {
        require(
            face.iter().all(|i| (*i as usize) < parent.len()),
            "card index out of range",
        )?;
        let a = root(&mut parent, face[0] as usize);
        for &i in &face[1..] {
            let b = root(&mut parent, i as usize);
            parent[b] = a;
        }
    }
    // PAC cards may duplicate both ends of a seam. Join only an exact,
    // uniquely paired geometric boundary edge, retaining every original UV and
    // vertex record. A single touching vertex or a branching edge is ambiguous.
    let mut edge_counts: BTreeMap<(u32, u32), u32> = BTreeMap::new();
    for f in indices.chunks_exact(3) {
        for (a, b) in [(f[0], f[1]), (f[1], f[2]), (f[2], f[0])] {
            *edge_counts.entry((a.min(b), a.max(b))).or_default() += 1;
        }
    }
    let mut seams: BTreeMap<([u32; 3], [u32; 3]), Vec<(u32, u32)>> = BTreeMap::new();
    for ((a, b), count) in edge_counts {
        if count == 1 {
            let x = positions[a as usize].map(f32::to_bits);
            let y = positions[b as usize].map(f32::to_bits);
            if x != y {
                seams.entry((x.min(y), x.max(y))).or_default().push((a, b));
            }
        }
    }
    for edges in seams.into_values().filter(|edges| edges.len() == 2) {
        let a = root(&mut parent, edges[0].0 as usize);
        let b = root(&mut parent, edges[1].0 as usize);
        if a != b {
            parent[b] = a;
        }
    }
    let mut cards: BTreeMap<usize, Vec<u32>> = BTreeMap::new();
    for i in 0..positions.len() {
        let r = root(&mut parent, i);
        cards.entry(r).or_default().push(i as u32);
    }
    let min = state
        .scalp
        .positions
        .iter()
        .map(|p| Vec3::from(*p))
        .fold(Vec3::splat(f32::INFINITY), Vec3::min);
    let max = state
        .scalp
        .positions
        .iter()
        .map(|p| Vec3::from(*p))
        .fold(Vec3::splat(f32::NEG_INFINITY), Vec3::max);
    let tolerance = (max - min).max_element() * 0.035;
    for vertices in cards.into_values() {
        if cancelled.load(Ordering::Relaxed) {
            return Err(HairError::Cancelled);
        }
        let id = state.next_lock_id;
        state.next_lock_id += 1;
        let mut lock = HairLock {
            id,
            part,
            guide: None,
            vertices,
            kind: LockKind::Unresolved,
            mirrored: None,
            width_scale: 1.0,
            cards: 0,
        };
        // UV seams split source cards already. Trace their longest geometric
        // endpoint direction; require a distinctly scalp-facing endpoint.
        let center = lock
            .vertices
            .iter()
            .map(|v| Vec3::from(positions[*v as usize]))
            .sum::<Vec3>()
            / lock.vertices.len() as f32;
        let far = *lock
            .vertices
            .iter()
            .max_by(|a, b| {
                Vec3::from(positions[**a as usize])
                    .distance_squared(center)
                    .total_cmp(&Vec3::from(positions[**b as usize]).distance_squared(center))
            })
            .unwrap();
        let end = Vec3::from(positions[far as usize]);
        let other = lock
            .vertices
            .iter()
            .map(|v| Vec3::from(positions[*v as usize]))
            .max_by(|a, b| a.distance_squared(end).total_cmp(&b.distance_squared(end)))
            .unwrap();
        let axis = (other - end).normalize_or_zero();
        let span = end.distance(other);
        if span < 1e-6 {
            state.locks.push(lock);
            continue;
        }
        let sample = |t: f32| {
            let mut sum = Vec3::ZERO;
            let mut weight = 0.0;
            for &v in &lock.vertices {
                let p = Vec3::from(positions[v as usize]);
                let s = ((p - end).dot(axis) / span).clamp(0.0, 1.0);
                let w = (1.0 - (s - t).abs() * 12.0).max(0.0);
                sum += p * w;
                weight += w;
            }
            if weight > 0.0 {
                sum / weight
            } else {
                end.lerp(other, t)
            }
        };
        let a = sample(0.0);
        let b = sample(1.0);
        let ra = state.scalp.nearest_cancellable(a, cancelled)?;
        let rb = state.scalp.nearest_cancellable(b, cancelled)?;
        let da = state.scalp.point(&ra)?.distance(a);
        let db = state.scalp.point(&rb)?.distance(b);
        let valid_uv = lock.vertices.iter().all(|v| {
            uvs.get(*v as usize)
                .is_some_and(|uv| uv.iter().all(|v| v.is_finite()))
        });
        let close_to_scalp = da.max(db) < tolerance * 2.0
            && center.y > min.y + (max.y - min.y) * 0.45
            && span < (max - min).max_element() * 1.3
            && lock.vertices.iter().all(|v| {
                state.scalp.positions.iter().any(|p| {
                    Vec3::from(*p).distance_squared(Vec3::from(positions[*v as usize]))
                        < (tolerance * 2.0).powi(2)
                })
            });
        if close_to_scalp {
            lock.kind = LockKind::Rigid;
        } else if valid_uv
            && (da - db).abs() > tolerance
            && da.min(db) < tolerance * 3.0
            && state.guides.len() < MAX_GUIDES
        {
            let reversed = db < da;
            let root = if reversed { rb } else { ra };
            let mut points: Vec<_> = (0..16)
                .map(|i| {
                    sample(if reversed {
                        1.0 - i as f32 / 15.0
                    } else {
                        i as f32 / 15.0
                    })
                    .to_array()
                })
                .collect();
            points[0] = state.scalp.point(&root)?.to_array();
            if points
                .windows(2)
                .all(|s| Vec3::from(s[0]).distance_squared(Vec3::from(s[1])) > 1e-14)
            {
                lock.guide = Some(state.guides.len() as u32);
                lock.kind = LockKind::Bound;
                state.guides.push(Guide {
                    root,
                    group,
                    points,
                });
            }
        }
        state.locks.push(lock);
        if state.locks.last().unwrap().guide.is_some() {
            bind_lock(state, state.locks.len() - 1, positions, normals)?;
        }
    }
    repair_pairs(state);
    Ok(())
}
