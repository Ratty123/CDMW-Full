//! Versioned rest-shape authoring and transient guide simulation.
//! This module owns no files, UI, renderer or game archive mutation.

use glam::{Quat, Vec3};
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;
use std::sync::atomic::{AtomicBool, Ordering};
use thiserror::Error;

pub const HAIR_VERSION: u32 = 2;
#[path = "hair_locks.rs"]
pub mod locks;
#[path = "hair_surface.rs"]
pub mod surface;
pub const MAX_GUIDES: usize = 4096;
pub const MAX_POINTS: usize = 64;
pub const MAX_HAIR_VERTICES: usize = 500_000;

#[derive(Debug, Error)]
pub enum HairError {
    #[error("Invalid hair authoring state: {0}")]
    Invalid(String),
    #[error("Hair preparation cancelled")]
    Cancelled,
}
type Result<T> = std::result::Result<T, HairError>;

fn require(ok: bool, reason: &str) -> Result<()> {
    if ok {
        Ok(())
    } else {
        Err(HairError::Invalid(reason.to_owned()))
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Scalp {
    pub identity: String,
    pub positions: Vec<[f32; 3]>,
    pub triangles: Vec<[u32; 3]>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Attachment {
    pub triangle: u32,
    pub barycentric: [f32; 3],
}

impl Scalp {
    pub fn validate(&self) -> Result<()> {
        require(
            !self.identity.is_empty() && self.identity.len() <= 256,
            "reference identity is missing",
        )?;
        require(
            !self.positions.is_empty() && self.positions.len() <= MAX_HAIR_VERTICES,
            "reference vertex count is unsupported",
        )?;
        require(
            !self.triangles.is_empty() && self.triangles.len() <= 1_000_000,
            "reference triangle count is unsupported",
        )?;
        require(
            self.positions.iter().flatten().all(|v| v.is_finite()),
            "reference contains non-finite positions",
        )?;
        require(
            self.triangles
                .iter()
                .flatten()
                .all(|i| (*i as usize) < self.positions.len()),
            "reference index is out of range",
        )
    }

    pub fn point(&self, root: &Attachment) -> Result<Vec3> {
        let face = self
            .triangles
            .get(root.triangle as usize)
            .ok_or_else(|| HairError::Invalid("root triangle no longer exists".into()))?;
        require(
            root.barycentric
                .iter()
                .all(|v| v.is_finite() && *v >= -1e-5 && *v <= 1.00001)
                && (root.barycentric.iter().sum::<f32>() - 1.0).abs() < 1e-4,
            "invalid root barycentric coordinates",
        )?;
        let mut point = Vec3::ZERO;
        for (i, weight) in face.iter().zip(root.barycentric) {
            point += Vec3::from(self.positions[*i as usize]) * weight;
        }
        Ok(point)
    }

    pub fn normal(&self, root: &Attachment) -> Vec3 {
        let [a, b, c] =
            self.triangles[root.triangle as usize].map(|i| Vec3::from(self.positions[i as usize]));
        (b - a).cross(c - a).try_normalize().unwrap_or(Vec3::Y)
    }

    /// Nearest surface attachment is used only by an explicit bind/rebind action.
    pub fn nearest(&self, point: Vec3) -> Attachment {
        self.nearest_cancellable(point, &AtomicBool::new(false))
            .expect("uncancelled scalp query")
    }

    fn nearest_cancellable(&self, point: Vec3, cancelled: &AtomicBool) -> Result<Attachment> {
        let mut best = (
            f32::INFINITY,
            Attachment {
                triangle: 0,
                barycentric: [1.0, 0.0, 0.0],
            },
        );
        for (index, face) in self.triangles.iter().enumerate() {
            if index % 256 == 0 && cancelled.load(Ordering::Relaxed) {
                return Err(HairError::Cancelled);
            }
            let [a, b, c] = face.map(|i| Vec3::from(self.positions[i as usize]));
            let barycentric = closest_barycentric(point, a, b, c);
            let on_face = a * barycentric[0] + b * barycentric[1] + c * barycentric[2];
            let distance = point.distance_squared(on_face);
            if distance < best.0 {
                best = (
                    distance,
                    Attachment {
                        triangle: index as u32,
                        barycentric,
                    },
                );
            }
        }
        Ok(best.1)
    }
}

fn closest_barycentric(p: Vec3, a: Vec3, b: Vec3, c: Vec3) -> [f32; 3] {
    let ab = b - a;
    let ac = c - a;
    let ap = p - a;
    let d1 = ab.dot(ap);
    let d2 = ac.dot(ap);
    if d1 <= 0.0 && d2 <= 0.0 {
        return [1.0, 0.0, 0.0];
    }
    let bp = p - b;
    let d3 = ab.dot(bp);
    let d4 = ac.dot(bp);
    if d3 >= 0.0 && d4 <= d3 {
        return [0.0, 1.0, 0.0];
    }
    let vc = d1 * d4 - d3 * d2;
    if vc <= 0.0 && d1 >= 0.0 && d3 <= 0.0 {
        let v = d1 / (d1 - d3).max(1e-12);
        return [1.0 - v, v, 0.0];
    }
    let cp = p - c;
    let d5 = ab.dot(cp);
    let d6 = ac.dot(cp);
    if d6 >= 0.0 && d5 <= d6 {
        return [0.0, 0.0, 1.0];
    }
    let vb = d5 * d2 - d1 * d6;
    if vb <= 0.0 && d2 >= 0.0 && d6 <= 0.0 {
        let w = d2 / (d2 - d6).max(1e-12);
        return [1.0 - w, 0.0, w];
    }
    let va = d3 * d6 - d5 * d4;
    if va <= 0.0 && d4 - d3 >= 0.0 && d5 - d6 >= 0.0 {
        let w = (d4 - d3) / ((d4 - d3) + (d5 - d6)).max(1e-12);
        return [0.0, 1.0 - w, w];
    }
    let denominator = va + vb + vc;
    // The denominator is proportional to squared triangle area. Real scalp
    // triangles can be below one square millimetre without being degenerate.
    if denominator <= f32::MIN_POSITIVE {
        return [1.0, 0.0, 0.0];
    }
    [va / denominator, vb / denominator, vc / denominator]
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Guide {
    pub root: Attachment,
    pub group: u32,
    pub points: Vec<[f32; 3]>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum GroupMode {
    Generated,
    Existing,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct HairGroup {
    pub id: u32,
    pub name: String,
    pub part: u32,
    pub mode: GroupMode,
    pub width: f32,
    pub cards_per_guide: u32,
    pub uv_rect: [f32; 4],
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct VertexBinding {
    pub part: u32,
    pub vertex: u32,
    pub guide: u32,
    pub segment: u32,
    pub t: f32,
    /// Offset expressed in the rest segment's stable orthonormal frame.
    pub offset: [f32; 3],
    #[serde(default)]
    pub normal: [f32; 3],
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Capsule {
    pub a: [f32; 3],
    pub b: [f32; 3],
    pub radius: f32,
    #[serde(default = "head_collision_default")]
    pub follows_head: bool,
}
fn head_collision_default() -> bool {
    true
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Template {
    pub path: String,
    pub sha256: String,
    pub target_stem: String,
    pub character: String,
    pub physics_profile: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct HairState {
    pub version: u32,
    pub revision: u64,
    pub scalp: Scalp,
    #[serde(default)]
    pub references: Vec<Scalp>,
    pub bound_reference: String,
    pub reference_parts: Vec<u32>,
    pub template: Template,
    pub groups: Vec<HairGroup>,
    pub guides: Vec<Guide>,
    pub bindings: Vec<VertexBinding>,
    pub collisions: Vec<Capsule>,
    pub converted: bool,
    #[serde(default)]
    pub locks: Vec<locks::HairLock>,
    #[serde(default = "locks::first_id")]
    pub next_lock_id: u64,
    #[serde(default = "locks::default_name")]
    pub style_name: String,
    #[serde(default)]
    pub startup_preset: String,
    #[serde(default)]
    pub prepared_parts: Vec<u32>,
    #[serde(default)]
    pub vertex_sources: std::collections::BTreeMap<u32, Vec<i32>>,
}

impl HairState {
    pub fn validate(&self) -> Result<()> {
        require(
            self.version == HAIR_VERSION,
            "unsupported hair state version",
        )?;
        self.scalp.validate()?;
        require(self.references.len() <= 4, "too many fitting references")?;
        for reference in &self.references {
            reference.validate()?;
        }
        require(
            self.bound_reference == self.scalp.identity,
            "reference head changed; explicitly rebind the guides",
        )?;
        require(
            self.groups.len() <= 128 && self.guides.len() <= MAX_GUIDES,
            "hair resource limit exceeded",
        )?;
        require(
            self.bindings.len() <= MAX_HAIR_VERTICES,
            "too many deformation bindings",
        )?;
        let group_ids = self.groups.iter().map(|g| g.id).collect::<BTreeSet<_>>();
        let parts = self.groups.iter().map(|g| g.part).collect::<BTreeSet<_>>();
        require(
            group_ids.len() == self.groups.len() && parts.len() == self.groups.len(),
            "ambiguous hair groups",
        )?;
        for group in &self.groups {
            require(
                !self.reference_parts.contains(&group.part),
                "reference geometry cannot be hairstyle output",
            )?;
            require(
                group.width.is_finite() && group.width > 0.0 && group.width <= 10.0,
                "invalid card width",
            )?;
            require(
                (1..=32).contains(&group.cards_per_guide),
                "density must be 1 through 32 cards per guide",
            )?;
            require(
                group.uv_rect.iter().all(|v| v.is_finite())
                    && group.uv_rect[2] > group.uv_rect[0]
                    && group.uv_rect[3] > group.uv_rect[1],
                "invalid texture atlas region",
            )?;
        }
        for guide in &self.guides {
            require(
                group_ids.contains(&guide.group),
                "guide refers to a missing group",
            )?;
            require(
                (2..=MAX_POINTS).contains(&guide.points.len()),
                "guide point count must be 2 through 64",
            )?;
            require(
                guide.points.iter().flatten().all(|p| p.is_finite()),
                "non-finite guide position",
            )?;
            require(
                Vec3::from(guide.points[0]).distance(self.scalp.point(&guide.root)?) < 1e-4,
                "guide root moved off its attachment",
            )?;
            require(
                guide
                    .points
                    .windows(2)
                    .all(|s| Vec3::from(s[0]).distance_squared(Vec3::from(s[1])) > 1e-14),
                "guide has a zero-length segment",
            )?;
        }
        for binding in &self.bindings {
            let guide = self
                .guides
                .get(binding.guide as usize)
                .ok_or_else(|| HairError::Invalid("vertex has a missing guide".into()))?;
            require(
                (binding.segment as usize + 1) < guide.points.len(),
                "binding segment does not exist",
            )?;
            require(
                binding.t.is_finite()
                    && (0.0..=1.0).contains(&binding.t)
                    && binding
                        .offset
                        .iter()
                        .chain(&binding.normal)
                        .all(|v| v.is_finite()),
                "invalid vertex binding",
            )?;
            require(
                self.groups
                    .iter()
                    .any(|g| g.id == guide.group && g.part == binding.part),
                "binding crosses hair groups",
            )?;
        }
        locks::validate(self)?;
        require(
            self.collisions.len() <= 64
                && self.collisions.iter().all(|c| {
                    c.a.iter().chain(c.b.iter()).all(|v| v.is_finite())
                        && c.radius.is_finite()
                        && c.radius > 0.0
                }),
            "invalid collision capsule",
        )
    }

    pub fn rebind(&mut self, scalp: Scalp) -> Result<()> {
        self.rebind_cancellable(scalp, &AtomicBool::new(false))
    }

    pub fn rebind_cancellable(&mut self, scalp: Scalp, cancelled: &AtomicBool) -> Result<()> {
        scalp.validate()?;
        let mut next = self.clone();
        for guide in &mut next.guides {
            let old = Vec3::from(guide.points[0]);
            guide.root = scalp.nearest_cancellable(old, cancelled)?;
            let shift = scalp.point(&guide.root)? - old;
            for point in &mut guide.points {
                *point = (Vec3::from(*point) + shift).to_array();
            }
        }
        next.bound_reference = scalp.identity.clone();
        next.scalp = scalp;
        next.revision += 1;
        next.validate()?;
        *self = next;
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Preset {
    Cropped,
    Bob,
    Long,
    Ponytail,
}

pub fn plant_guide(
    state: &mut HairState,
    root: Attachment,
    group: u32,
    preset: Preset,
    length: f32,
    point_count: usize,
) -> Result<usize> {
    state.validate()?;
    require(
        !state.converted,
        "convert back through Undo before editing guides",
    )?;
    require(
        length.is_finite() && length > 0.0001 && length <= 100.0,
        "invalid guide length",
    )?;
    require(
        (2..=MAX_POINTS).contains(&point_count) && state.guides.len() < MAX_GUIDES,
        "guide limit exceeded",
    )?;
    require(
        state.groups.iter().any(|g| g.id == group),
        "select a hair group first",
    )?;
    let start = state.scalp.point(&root)?;
    let mut normal = state.scalp.normal(&root);
    let (min, max) = state.scalp.positions.iter().fold(
        (Vec3::splat(f32::INFINITY), Vec3::splat(f32::NEG_INFINITY)),
        |(min, max), p| (min.min(Vec3::from(*p)), max.max(Vec3::from(*p))),
    );
    if normal.dot(start - (min + max) * 0.5) < 0.0 {
        normal = -normal;
    }
    let radial = Vec3::new(
        start.x - (min.x + max.x) * 0.5,
        0.0,
        start.z - (min.z + max.z) * 0.5,
    )
    .try_normalize()
    .unwrap_or(Vec3::Z);
    let tie = Vec3::new(
        (min.x + max.x) * 0.5,
        max.y - (max.y - min.y) * 0.35,
        max.z + length * 0.12,
    );
    let mut points: Vec<[f32; 3]> = (0..point_count)
        .map(|i| {
            let t = i as f32 / (point_count - 1) as f32;
            if preset == Preset::Ponytail {
                return if t <= 0.5 {
                    let s = t * 2.0;
                    (start.lerp(tie, s * s * (3.0 - 2.0 * s))
                        + normal * length * 0.18 * (s * std::f32::consts::PI).sin())
                    .to_array()
                } else {
                    (tie + Vec3::new(0.0, -length * 0.7, length * 0.2) * ((t - 0.5) * 2.0))
                        .to_array()
                };
            }
            let (outward, down, back) = match preset {
                Preset::Cropped => (t * 0.8, t * t * 0.2, t * t * 0.2),
                Preset::Bob => (t * (1.0 - t * 0.75) * 0.65, t * t, 0.0),
                Preset::Long => (t * (1.0 - t * 0.85) * 0.6, t * t, t * t * 0.12),
                Preset::Ponytail => (t * (1.0 - t) * 0.3, t * t * 0.6, t * 0.8),
            };
            let surface_flow = if matches!(preset, Preset::Bob | Preset::Long) {
                let center = (min + max) * 0.5;
                let front =
                    ((center.z - start.z) / (max.z - min.z).max(0.001) * 2.0).clamp(0.0, 1.0);
                let parted =
                    Vec3::new(if start.x < center.x { -1.0 } else { 1.0 }, 0.0, 0.15).normalize();
                radial.lerp(parted, front * 0.85).normalize_or_zero() * t * 0.6
            } else {
                Vec3::ZERO
            };
            (start + length * (normal * outward + surface_flow - Vec3::Y * down + Vec3::Z * back))
                .to_array()
        })
        .collect();
    // Presets wrap the head instead of beginning with an intersecting rest pose.
    // The root remains the exact scalp attachment; only free points move.
    for (index, point) in points.iter_mut().enumerate().skip(1) {
        let mut p = Vec3::from(*point);
        for capsule in state.collisions.iter().filter(|c| c.follows_head) {
            let a = Vec3::from(capsule.a);
            let b = Vec3::from(capsule.b);
            let ab = b - a;
            let q = a + ab * ((p - a).dot(ab) / ab.length_squared().max(1e-12)).clamp(0.0, 1.0);
            if p.distance(q) < capsule.radius + 0.001 {
                p = q
                    + (p - q).try_normalize().unwrap_or(radial)
                        * (capsule.radius + 0.001 + index as f32 * 0.00001);
            }
        }
        *point = p.to_array();
    }
    let index = state.guides.len();
    state.guides.push(Guide {
        root,
        group,
        points,
    });
    state.revision += 1;
    Ok(index)
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Groom {
    Comb,
    Smooth,
    Cut,
    Lengthen,
    Curl,
    Clump,
}

pub fn groom(
    state: &mut HairState,
    guides: &[usize],
    operation: Groom,
    strength: f32,
    direction: [f32; 3],
    symmetry: bool,
) -> Result<()> {
    require(
        !state.converted && strength.is_finite() && (0.0..=1.0).contains(&strength),
        "invalid grooming stroke",
    )?;
    require(
        direction.iter().all(|v| v.is_finite()),
        "non-finite comb direction",
    )?;
    require(
        !guides.is_empty() && guides.iter().all(|i| *i < state.guides.len()),
        "select guides to groom",
    )?;
    let mut selected = guides.iter().copied().collect::<BTreeSet<_>>();
    if symmetry {
        locks::extend_mirrored_guides(state, &mut selected);
    }
    let before = state.guides.clone();
    let primary_left = before[guides[0]].points[0][0] < 0.0;
    for index in selected.iter().copied() {
        let paired = state
            .locks
            .iter()
            .any(|l| l.guide == Some(index as u32) && l.mirrored.is_some());
        let guide = &mut state.guides[index];
        let old = &before[index].points;
        if operation == Groom::Cut {
            let last = ((old.len() - 1) as f32 * (1.0 - strength * 0.8)).max(1.0);
            let segment = last.floor() as usize;
            guide.points.truncate(segment + 1);
            if last.fract() > 0.001 && segment + 1 < old.len() {
                guide.points.push(
                    Vec3::from(old[segment])
                        .lerp(Vec3::from(old[segment + 1]), last.fract())
                        .to_array(),
                );
            }
            continue;
        }
        let root = Vec3::from(old[0]);
        let length: f32 = old
            .windows(2)
            .map(|s| Vec3::from(s[0]).distance(Vec3::from(s[1])))
            .sum();
        let sign = if symmetry && paired && (root.x < 0.0) != primary_left {
            -1.0
        } else {
            1.0
        };
        let delta = Vec3::from(direction) * Vec3::new(sign, 1.0, 1.0);
        let tip_mean = selected
            .iter()
            .map(|i| &before[*i])
            .fold((Vec3::ZERO, 0usize), |(sum, n), g| {
                (sum + Vec3::from(*g.points.last().unwrap()), n + 1)
            });
        for i in 1..old.len() {
            let p = Vec3::from(old[i]);
            let t = i as f32 / (old.len() - 1) as f32;
            let next = match operation {
                Groom::Comb => p + delta * strength * t,
                Groom::Smooth => {
                    let previous = Vec3::from(old[i - 1]);
                    let next = Vec3::from(old[(i + 1).min(old.len() - 1)]);
                    p.lerp((previous + next) * 0.5, strength * 0.6)
                }
                Groom::Cut => p,
                Groom::Lengthen => {
                    if i + 1 == old.len() {
                        p + (p - Vec3::from(old[i - 1])).normalize_or_zero()
                            * Vec3::from(direction).length()
                            * strength
                    } else {
                        p
                    }
                }
                Groom::Curl => {
                    let angle = t * std::f32::consts::TAU * 2.0;
                    p + Vec3::new(angle.sin(), 0.0, angle.cos() - 1.0)
                        * length
                        * strength
                        * 0.15
                        * t
                }
                Groom::Clump => p.lerp(
                    root.lerp(tip_mean.0 / tip_mean.1.max(1) as f32, t),
                    strength * t * 0.6,
                ),
            };
            guide.points[i] = next.to_array();
        }
    }
    // A stroke is validated/published once on release. Never walk the scalp or
    // create history entries for individual pointer samples.
    Ok(())
}

fn segment_frame(a: Vec3, b: Vec3) -> (Vec3, Vec3, Vec3) {
    let tangent = (b - a).try_normalize().unwrap_or(Vec3::Y);
    let axis = if tangent.dot(Vec3::X).abs() < 0.9 {
        Vec3::X
    } else {
        Vec3::Z
    };
    let side = (axis - tangent * axis.dot(tangent)).normalize();
    (side, tangent.cross(side).normalize(), tangent)
}

/// Bind only an explicitly chosen part to its explicitly authored guide group.
pub fn bind_existing(
    state: &mut HairState,
    part: u32,
    positions: &[[f32; 3]],
    cancelled: &AtomicBool,
) -> Result<()> {
    state.validate()?;
    require(
        positions.len() <= MAX_HAIR_VERTICES && positions.iter().flatten().all(|v| v.is_finite()),
        "invalid existing hair geometry",
    )?;
    let group = state
        .groups
        .iter()
        .find(|g| g.part == part && g.mode == GroupMode::Existing)
        .ok_or_else(|| HairError::Invalid("choose an explicit existing-hair group".into()))?;
    let guide_ids: Vec<_> = state
        .guides
        .iter()
        .enumerate()
        .filter(|(_, g)| g.group == group.id)
        .collect();
    require(
        !guide_ids.is_empty(),
        "place and correct the group's root guides before binding",
    )?;
    let mut bindings = Vec::with_capacity(positions.len());
    let all_frames: Vec<_> = state
        .guides
        .iter()
        .map(|g| locks::frames(&g.points))
        .collect();
    for (vertex, p) in positions.iter().enumerate() {
        if cancelled.load(Ordering::Relaxed) {
            return Err(HairError::Cancelled);
        }
        let p = Vec3::from(*p);
        let mut best = (f32::INFINITY, None);
        for (guide_index, guide) in &guide_ids {
            for (segment, pair) in guide.points.windows(2).enumerate() {
                let a = Vec3::from(pair[0]);
                let b = Vec3::from(pair[1]);
                let t = ((p - a).dot(b - a) / a.distance_squared(b).max(1e-12)).clamp(0.0, 1.0);
                let offset = p - a.lerp(b, t);
                if offset.length_squared() < best.0 {
                    let (side, up, tangent) = all_frames[*guide_index][segment];
                    best = (
                        offset.length_squared(),
                        Some(VertexBinding {
                            part,
                            vertex: vertex as u32,
                            guide: *guide_index as u32,
                            segment: segment as u32,
                            t,
                            offset: [offset.dot(side), offset.dot(up), offset.dot(tangent)],
                            normal: [0.0; 3],
                        }),
                    );
                }
            }
        }
        bindings.push(
            best.1
                .ok_or_else(|| HairError::Invalid("no nonempty deformation guide".into()))?,
        );
    }
    state.bindings.retain(|b| b.part != part);
    state.bindings.extend(bindings);
    state.revision += 1;
    Ok(())
}

#[derive(Debug, Clone)]
pub struct HairGeometry {
    pub part: u32,
    pub positions: Vec<[f32; 3]>,
    pub normals: Vec<[f32; 3]>,
    pub uvs: Vec<[f32; 2]>,
    pub indices: Vec<u32>,
    pub bindings: Vec<VertexBinding>,
}

pub fn generate(state: &HairState, cancelled: &AtomicBool) -> Result<Vec<HairGeometry>> {
    state.validate()?;
    let count: usize = state
        .groups
        .iter()
        .filter(|g| g.mode == GroupMode::Generated)
        .map(|g| {
            state
                .guides
                .iter()
                .enumerate()
                .filter(|(_, guide)| guide.group == g.id)
                .map(|(i, guide)| {
                    guide.points.len()
                        * 2
                        * state
                            .locks
                            .iter()
                            .find(|l| l.guide == Some(i as u32) && l.cards > 0)
                            .map_or(g.cards_per_guide, |l| l.cards)
                            as usize
                })
                .sum::<usize>()
        })
        .sum();
    require(
        count <= MAX_HAIR_VERTICES,
        "generated hair exceeds the vertex budget",
    )?;
    let mut result = Vec::new();
    let scalp_indices: Vec<_> = state.scalp.triangles.iter().flatten().copied().collect();
    let scalp = surface::SurfaceIndex::new(&state.scalp.positions, &scalp_indices);
    for group in state
        .groups
        .iter()
        .filter(|g| g.mode == GroupMode::Generated)
    {
        let mut mesh = HairGeometry {
            part: group.part,
            positions: vec![],
            normals: vec![],
            uvs: vec![],
            indices: vec![],
            bindings: vec![],
        };
        for (gi, guide) in state
            .guides
            .iter()
            .enumerate()
            .filter(|(_, g)| g.group == group.id)
        {
            let frames = locks::frames(&guide.points);
            let mut lengths = vec![0.0];
            for pair in guide.points.windows(2) {
                lengths.push(lengths.last().unwrap() + Vec3::from(pair[0]).distance(Vec3::from(pair[1])));
            }
            let length = *lengths.last().unwrap();
            let lock = state.locks.iter().find(|l| l.guide == Some(gi as u32));
            let width_scale = lock.map_or(1.0, |l| l.width_scale);
            let density = lock
                .filter(|l| l.cards > 0)
                .map_or(group.cards_per_guide, |l| l.cards);
            for card in 0..density {
                if cancelled.load(Ordering::Relaxed) {
                    return Err(HairError::Cancelled);
                }
                let first = mesh.positions.len() as u32;
                let roll = card as f32 * std::f32::consts::PI / density as f32;
                let spread = ((card as f32 + 0.5) / density as f32 - 0.5) * group.width;
                for (i, point) in guide.points.iter().enumerate() {
                    let segment = i.min(guide.points.len() - 2);
                    let (side, up, tangent) = frames[segment];
                    let across = side * roll.cos() + up * roll.sin();
                    let normal = across.cross(tangent).normalize();
                    let t = lengths[i] / length;
                    for edge in [-1.0_f32, 1.0] {
                        let offset = across
                            * (edge * group.width * width_scale * 0.5 * (1.0 - t * 0.94)
                                + spread * t);
                        let vertex = mesh.positions.len() as u32;
                        let p = scalp.contact_with_reach(
                            &state.scalp.positions,
                            &scalp_indices,
                            Vec3::from(*point) + offset,
                            0.0002,
                            group.width * width_scale + 0.0002,
                        );
                        let offset = p - Vec3::from(*point);
                        mesh.positions.push(p.to_array());
                        mesh.normals.push(normal.to_array());
                        mesh.uvs.push([
                            if edge < 0.0 {
                                group.uv_rect[0]
                            } else {
                                group.uv_rect[2]
                            },
                            group.uv_rect[1] + (group.uv_rect[3] - group.uv_rect[1]) * t,
                        ]);
                        mesh.bindings.push(VertexBinding {
                            part: group.part,
                            vertex,
                            guide: gi as u32,
                            segment: segment as u32,
                            t: if i == segment { 0.0 } else { 1.0 },
                            offset: [offset.dot(side), offset.dot(up), offset.dot(tangent)],
                            normal: [normal.dot(side), normal.dot(up), normal.dot(tangent)],
                        });
                    }
                    if i > 0 {
                        let a = first + (i as u32 - 1) * 2;
                        mesh.indices
                            .extend_from_slice(&[a, a + 1, a + 2, a + 1, a + 3, a + 2]);
                    }
                }
            }
        }
        if !mesh.positions.is_empty() {
            result.push(mesh);
        }
    }
    Ok(result)
}

pub fn deform(
    bindings: &[VertexBinding],
    points: &[Vec<[f32; 3]>],
    part: u32,
    positions: &mut [[f32; 3]],
) -> Result<()> {
    let frames: Vec<_> = points.iter().map(|g| locks::frames(g)).collect();
    for binding in bindings.iter().filter(|b| b.part == part) {
        let guide = points
            .get(binding.guide as usize)
            .ok_or_else(|| HairError::Invalid("missing simulated guide".into()))?;
        let pair = guide
            .get(binding.segment as usize..binding.segment as usize + 2)
            .ok_or_else(|| HairError::Invalid("missing simulated segment".into()))?;
        let a = Vec3::from(pair[0]);
        let b = Vec3::from(pair[1]);
        let (side, up, tangent) = frames[binding.guide as usize][binding.segment as usize];
        let position = positions
            .get_mut(binding.vertex as usize)
            .ok_or_else(|| HairError::Invalid("deformation vertex no longer exists".into()))?;
        *position = (a.lerp(b, binding.t)
            + side * binding.offset[0]
            + up * binding.offset[1]
            + tangent * binding.offset[2])
            .to_array();
    }
    Ok(())
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub struct MotionSettings {
    pub gravity: [f32; 3],
    pub wind: [f32; 3],
    pub damping: f32,
    pub length_compliance: f32,
    pub bend_compliance: f32,
    pub iterations: u32,
    pub collision_margin: f32,
}
impl Default for MotionSettings {
    fn default() -> Self {
        Self {
            gravity: [0.0, -9.81, 0.0],
            wind: [0.0; 3],
            damping: 3.0,
            length_compliance: 0.0,
            bend_compliance: 0.00002,
            iterations: 12,
            collision_margin: 0.002,
        }
    }
}

#[derive(Debug, Clone)]
pub struct Simulation {
    pub points: Vec<Vec<[f32; 3]>>,
    velocities: Vec<Vec<Vec3>>,
    rest: Vec<Vec<[f32; 3]>>,
    accumulator: f64,
    pub elapsed: f64,
    pub pivot: Vec3,
    pub translation: Vec3,
    surface: surface::SurfaceIndex,
    scalp_positions: Vec<[f32; 3]>,
    scalp_indices: Vec<u32>,
    widths: Vec<f32>,
}

#[derive(Debug, Clone, Copy)]
pub struct PreviewPose {
    pub pivot: Vec3,
    pub body_pivot: Vec3,
    pub head: Quat,
    pub body: Quat,
    pub translation: Vec3,
}
impl PreviewPose {
    pub fn at(pivot: Vec3, height: f32, seconds: f32, test: u32) -> Self {
        let angle = (seconds * 1.5).sin() * 0.35;
        let body = if matches!(test, 3 | 4) {
            Quat::from_rotation_z((seconds * 1.2).sin() * 0.10)
                * Quat::from_rotation_y((seconds * 0.8).sin() * 0.12)
        } else {
            Quat::IDENTITY
        };
        let local = match test {
            1 => Quat::from_rotation_y(angle),
            2 => Quat::from_rotation_x(angle),
            3 => Quat::from_rotation_y(angle) * Quat::from_rotation_x((seconds * 1.9).sin() * 0.14),
            _ => Quat::IDENTITY,
        };
        let body_pivot = pivot - Vec3::Y * height;
        let translation = body_pivot + body * (pivot - body_pivot) - pivot;
        Self {
            pivot,
            body_pivot,
            head: body * local,
            body,
            translation,
        }
    }
    pub fn head_point(self, p: Vec3) -> Vec3 {
        self.pivot + self.translation + self.head * (p - self.pivot)
    }
    pub fn body_point(self, p: Vec3) -> Vec3 {
        self.body_pivot + self.body * (p - self.body_pivot)
    }
}

fn validate_motion(settings: MotionSettings, head_rotation: Quat) -> Result<()> {
    require(
        settings
            .gravity
            .iter()
            .chain(settings.wind.iter())
            .all(|v| v.is_finite())
            && settings.damping.is_finite()
            && settings.damping >= 0.0
            && settings.length_compliance.is_finite()
            && settings.length_compliance >= 0.0
            && settings.bend_compliance.is_finite()
            && settings.bend_compliance >= 0.0
            && settings.collision_margin.is_finite()
            && settings.collision_margin >= 0.0
            && (1..=64).contains(&settings.iterations)
            && head_rotation.is_finite(),
        "invalid simulation settings",
    )?;
    Ok(())
}

impl Simulation {
    /// Restart from edited rest geometry without jumping the preview rig back
    /// to time zero. Simulation velocities remain transient and start at rest.
    pub fn at_pose(state: &HairState, elapsed: f64, test: u32, height: f32) -> Result<Self> {
        require(
            elapsed.is_finite() && elapsed >= 0.0,
            "invalid preview time",
        )?;
        let mut simulation = Self::new(state)?;
        let pose = PreviewPose::at(simulation.pivot, height, elapsed as f32, test);
        simulation.elapsed = elapsed;
        simulation.translation = pose.translation;
        for guide in &mut simulation.points {
            for point in guide {
                *point = pose.head_point(Vec3::from(*point)).to_array();
            }
        }
        Ok(simulation)
    }
    /// Evaluate the procedural rig at solver steps, rather than display frames.
    /// Equal elapsed time produces equal motion at 30, 60 or 144 Hz presentation.
    pub fn advance_test(
        &mut self,
        seconds: f64,
        mut settings: MotionSettings,
        capsules: &[Capsule],
        test: u32,
        height: f32,
    ) -> Result<PreviewPose> {
        require(seconds.is_finite() && seconds >= 0.0, "invalid frame time")?;
        require(
            height.is_finite() && height > 0.0 && test <= 5,
            "invalid preview movement test",
        )?;
        validate_motion(settings, Quat::IDENTITY)?;
        const STEP: f64 = 1.0 / 120.0;
        self.accumulator = (self.accumulator + seconds).min(STEP * 8.0);
        let mut pose = PreviewPose::at(self.pivot, height, self.elapsed as f32, test);
        let mut colliders = capsules.to_vec();
        while self.accumulator + 1e-12 >= STEP {
            pose = PreviewPose::at(self.pivot, height, (self.elapsed + STEP) as f32, test);
            self.translation = pose.translation;
            for (target, source) in colliders.iter_mut().zip(capsules) {
                if !source.follows_head {
                    target.a = pose.body_point(Vec3::from(source.a)).to_array();
                    target.b = pose.body_point(Vec3::from(source.b)).to_array();
                }
            }
            if test == 5 {
                settings.wind = [4.0 + (self.elapsed as f32 * 1.7).sin() * 2.0, 0.0, 0.5];
            }
            self.step(STEP as f32, settings, &colliders, pose.head);
            self.accumulator -= STEP;
            self.elapsed += STEP;
        }
        require(
            self.points
                .iter()
                .flatten()
                .flatten()
                .all(|v| v.is_finite()),
            "hair simulation produced non-finite geometry",
        )?;
        Ok(pose)
    }
    pub fn new(state: &HairState) -> Result<Self> {
        state.validate()?;
        let rest: Vec<_> = state.guides.iter().map(|g| g.points.clone()).collect();
        let (minimum, maximum) = state.scalp.positions.iter().fold(
            (Vec3::splat(f32::INFINITY), Vec3::splat(f32::NEG_INFINITY)),
            |(a, b), p| (a.min(Vec3::from(*p)), b.max(Vec3::from(*p))),
        );
        let mut widths = vec![0.0_f32; state.guides.len()];
        for binding in &state.bindings {
            widths[binding.guide as usize] =
                widths[binding.guide as usize].max(Vec3::from(binding.offset).length());
        }
        Ok(Self {
            surface: surface::SurfaceIndex::new(
                &state.scalp.positions,
                &state
                    .scalp
                    .triangles
                    .iter()
                    .flatten()
                    .copied()
                    .collect::<Vec<_>>(),
            ),
            scalp_positions: state.scalp.positions.clone(),
            scalp_indices: state.scalp.triangles.iter().flatten().copied().collect(),
            widths,
            translation: Vec3::ZERO,
            velocities: rest.iter().map(|g| vec![Vec3::ZERO; g.len()]).collect(),
            points: rest.clone(),
            rest,
            accumulator: 0.0,
            elapsed: 0.0,
            pivot: Vec3::new(
                (minimum.x + maximum.x) * 0.5,
                minimum.y,
                (minimum.z + maximum.z) * 0.5,
            ),
        })
    }

    /// Fixed 120 Hz integration, with bounded catch-up. No authored state is changed.
    pub fn advance(
        &mut self,
        frame_seconds: f64,
        settings: MotionSettings,
        collisions: &[Capsule],
        head_rotation: Quat,
    ) -> Result<()> {
        require(
            frame_seconds.is_finite() && frame_seconds >= 0.0,
            "invalid simulation frame time",
        )?;
        validate_motion(settings, head_rotation)?;
        const STEP: f64 = 1.0 / 120.0;
        self.accumulator = (self.accumulator + frame_seconds).min(STEP * 8.0);
        while self.accumulator + 1e-12 >= STEP {
            self.step(STEP as f32, settings, collisions, head_rotation);
            self.accumulator -= STEP;
            self.elapsed += STEP;
        }
        Ok(())
    }

    fn step(&mut self, dt: f32, settings: MotionSettings, capsules: &[Capsule], rotation: Quat) {
        let force = Vec3::from(settings.gravity) + Vec3::from(settings.wind);
        let mut previous = Vec::new();
        let mut contact_correction = Vec::new();
        let mut length_lambda = Vec::new();
        let mut bend_lambda = Vec::new();
        for (guide_index, ((points, velocity), rest)) in self
            .points
            .iter_mut()
            .zip(&mut self.velocities)
            .zip(&self.rest)
            .enumerate()
        {
            previous.clone_from(points);
            contact_correction.clear();
            contact_correction.resize(points.len(), Vec3::ZERO);
            for i in 1..points.len() {
                // Length and bend constraints alone allow the entire strand to
                // rotate around its root and collapse under gravity. Retain the
                // authored shape in head space, with softer, mobile tips.
                let t = i as f32 / (points.len() - 1) as f32;
                let stiffness =
                    1000.0 / (1.0 + settings.bend_compliance * 50_000.0) * (1.0 - 0.5 * t * t);
                let target =
                    self.pivot + self.translation + rotation * (Vec3::from(rest[i]) - self.pivot);
                velocity[i] += (force + (target - Vec3::from(points[i])) * stiffness) * dt;
                velocity[i] /= 1.0 + stiffness * dt * dt + stiffness.sqrt() * 0.5 * dt;
                points[i] = (Vec3::from(points[i]) + velocity[i] * dt).to_array();
            }
            length_lambda.clear();
            length_lambda.resize(points.len() - 1, 0.0);
            bend_lambda.clear();
            bend_lambda.resize(points.len().saturating_sub(2), 0.0);
            let root =
                self.pivot + self.translation + rotation * (Vec3::from(rest[0]) - self.pivot);
            points[0] = root.to_array();
            for iteration in 0..settings.iterations {
                for i in 0..points.len() - 2 {
                    distance_constraint(
                        points,
                        i,
                        i + 2,
                        Vec3::from(rest[i]).distance(Vec3::from(rest[i + 2])),
                        settings.bend_compliance / (dt * dt),
                        &mut bend_lambda[i],
                    );
                }
                for i in 0..points.len() - 1 {
                    distance_constraint(
                        points,
                        i,
                        i + 1,
                        Vec3::from(rest[i]).distance(Vec3::from(rest[i + 1])),
                        settings.length_compliance / (dt * dt),
                        &mut length_lambda[i],
                    );
                }
                for point in points.iter_mut().skip(1) {
                    let mut world = Vec3::from(*point);
                    for capsule in capsules {
                        let mut p = if capsule.follows_head {
                            self.pivot
                                + rotation.inverse() * (world - self.pivot - self.translation)
                        } else {
                            world
                        };
                        let a = Vec3::from(capsule.a);
                        let ab = Vec3::from(capsule.b) - a;
                        let t = ((p - a).dot(ab) / ab.length_squared().max(1e-12)).clamp(0.0, 1.0);
                        let center = a + ab * t;
                        let offset = p - center;
                        let radius = capsule.radius + settings.collision_margin;
                        if offset.length_squared() < radius * radius {
                            p = center + offset.try_normalize().unwrap_or(Vec3::X) * radius;
                        }
                        world = if capsule.follows_head {
                            self.pivot + self.translation + rotation * (p - self.pivot)
                        } else {
                            p
                        };
                    }
                    *point = world.to_array();
                }
                // Solve in the same local scalp coordinates used for rendering.
                // Probe the whole segment, with the follower-card extent, while
                // pinning the first point exactly to its authored attachment.
                if iteration + 1 != settings.iterations {
                    continue;
                }
                let radius = settings.collision_margin + self.widths[guide_index];
                for i in 1..points.len() {
                    let local = |p: [f32; 3]| {
                        self.pivot
                            + rotation.inverse() * (Vec3::from(p) - self.pivot - self.translation)
                    };
                    let a = local(points[i - 1]);
                    let b = local(points[i]);
                    let samples =
                        ((a.distance(b) / radius.max(0.002)).ceil() as usize).clamp(2, 16);
                    let mut correction = Vec3::ZERO;
                    for sample in 1..samples {
                        let t = sample as f32 / samples as f32;
                        let p = a.lerp(b, t);
                        let margin = if i == 1 { radius * t } else { radius };
                        let delta = self.surface.contact(
                            &self.scalp_positions,
                            &self.scalp_indices,
                            p,
                            margin,
                        ) - p;
                        if delta.length_squared() > correction.length_squared() {
                            correction = delta;
                        }
                    }
                    if correction.length_squared() > 0.0 {
                        let world = rotation * correction;
                        if i > 1 {
                            points[i - 1] = (Vec3::from(points[i - 1]) + world).to_array();
                            contact_correction[i - 1] += world;
                        }
                        let delta = world * if i == 1 { 2.0 } else { 1.0 };
                        points[i] = (Vec3::from(points[i]) + delta).to_array();
                        contact_correction[i] += delta;
                    }
                }
                // A segment correction also moves its predecessor. Resolve
                // every free point last so the next segment cannot push a
                // previously resolved card row back into the scalp.
                for i in 1..points.len() {
                    let p = self.pivot
                        + rotation.inverse()
                            * (Vec3::from(points[i]) - self.pivot - self.translation);
                    let corrected =
                        self.surface
                            .contact(&self.scalp_positions, &self.scalp_indices, p, radius);
                    let delta = rotation * (corrected - p);
                    points[i] = (Vec3::from(points[i]) + delta).to_array();
                    contact_correction[i] += delta;
                }
            }
            // Cut tips can approach float32 precision, and contacts can bring
            // adjacent points together. Keep them distinct before deformation
            // and settled-state validation without changing pinned roots.
            for i in 1..points.len() {
                let a = Vec3::from(points[i - 1]);
                let delta = Vec3::from(points[i]) - a;
                if delta.length_squared() < 1e-10 {
                    let direction = delta.try_normalize().unwrap_or_else(|| {
                        rotation * (Vec3::from(rest[i]) - Vec3::from(rest[i - 1])).normalize()
                    });
                    let corrected = a + direction * 1e-5;
                    contact_correction[i] += corrected - Vec3::from(points[i]);
                    points[i] = corrected.to_array();
                }
            }
            let damping = (-settings.damping * dt).exp();
            for i in 1..points.len() {
                velocity[i] =
                    (Vec3::from(points[i]) - Vec3::from(previous[i]) - contact_correction[i]) / dt
                        * damping;
            }
            velocity[0] = Vec3::ZERO;
        }
    }

    pub fn settled_state(&self, state: &HairState, head_rotation: Quat) -> Result<HairState> {
        require(
            state.guides.len() == self.points.len(),
            "simulation belongs to another hairstyle",
        )?;
        let mut next = state.clone();
        for (guide, points) in next.guides.iter_mut().zip(&self.points) {
            require(
                guide.points.len() == points.len(),
                "simulation topology is stale",
            )?;
            guide.points = points
                .iter()
                .map(|p| {
                    (self.pivot
                        + head_rotation.inverse()
                            * (Vec3::from(*p) - self.pivot - self.translation))
                        .to_array()
                })
                .collect();
            guide.points[0] = next.scalp.point(&guide.root)?.to_array();
        }
        next.revision += 1;
        next.validate()?;
        Ok(next)
    }
}

fn distance_constraint(
    points: &mut [[f32; 3]],
    a: usize,
    b: usize,
    rest: f32,
    alpha: f32,
    lambda: &mut f32,
) {
    let pa = Vec3::from(points[a]);
    let pb = Vec3::from(points[b]);
    let delta = pb - pa;
    let distance = delta.length();
    if distance < 1e-10 {
        return;
    }
    let wa = if a == 0 { 0.0 } else { 1.0 };
    let dl = (-(distance - rest) - alpha * *lambda) / (wa + 1.0 + alpha);
    *lambda += dl;
    points[a] = (pa - wa * dl * delta / distance).to_array();
    points[b] = (pb + dl * delta / distance).to_array();
}

#[cfg(test)]
mod tests {
    use super::*;

    fn state() -> HairState {
        HairState {
            vertex_sources: Default::default(),
            prepared_parts: vec![],
            locks: vec![],
            next_lock_id: 1,
            style_name: locks::default_name(),
            startup_preset: "bob".into(),
            version: HAIR_VERSION,
            revision: 0,
            scalp: Scalp {
                identity: "head-a".into(),
                positions: vec![[-1.0, 1.0, -1.0], [0.0, 1.0, 1.0], [1.0, 1.0, -1.0]],
                triangles: vec![[0, 1, 2]],
            },
            bound_reference: "head-a".into(),
            reference_parts: vec![1],
            references: vec![],
            template: Template {
                path: "hair.pac".into(),
                sha256: "a".repeat(64),
                target_stem: "new_hair".into(),
                character: "Damiane".into(),
                physics_profile: "Hair".into(),
            },
            groups: vec![HairGroup {
                id: 0,
                name: "Hair".into(),
                part: 0,
                mode: GroupMode::Generated,
                width: 0.02,
                cards_per_guide: 6,
                uv_rect: [0.0, 0.0, 1.0, 1.0],
            }],
            guides: vec![],
            bindings: vec![],
            collisions: vec![],
            converted: false,
        }
    }
    fn planted() -> HairState {
        let mut s = state();
        plant_guide(
            &mut s,
            Attachment {
                triangle: 0,
                barycentric: [0.3, 0.4, 0.3],
            },
            0,
            Preset::Long,
            0.3,
            16,
        )
        .unwrap();
        s
    }

    #[test]
    fn hair_groom_preserves_roots_and_changes_rest_shape() {
        for operation in [
            Groom::Comb,
            Groom::Smooth,
            Groom::Cut,
            Groom::Lengthen,
            Groom::Curl,
            Groom::Clump,
        ] {
            let mut s = planted();
            let before = s.clone();
            groom(&mut s, &[0], operation, 0.4, [0.05, 0.01, 0.02], true).unwrap();
            assert_eq!(s.guides[0].points[0], before.guides[0].points[0]);
            assert_ne!(s.guides[0].points, before.guides[0].points);
            s.validate().unwrap();
        }
    }
    #[test]
    fn hair_generated_cards_bind_and_deform_without_changing_uvs() {
        let s = planted();
        let mesh = generate(&s, &AtomicBool::new(false)).unwrap().remove(0);
        assert_eq!(mesh.positions.len(), 6 * 16 * 2);
        let mut moved = s
            .guides
            .iter()
            .map(|g| g.points.clone())
            .collect::<Vec<_>>();
        for p in moved[0].iter_mut().skip(1) {
            p[0] += 0.1;
        }
        let mut positions = mesh.positions.clone();
        deform(&mesh.bindings, &moved, 0, &mut positions).unwrap();
        assert_ne!(positions, mesh.positions);
        assert_eq!(mesh.uvs.len(), positions.len());
        let cancelled = AtomicBool::new(true);
        assert!(matches!(
            generate(&s, &cancelled),
            Err(HairError::Cancelled)
        ));
    }
    #[test]
    fn hair_card_taper_and_texture_follow_distance_not_sample_count() {
        let mut s = planted();
        let root = s.scalp.point(&s.guides[0].root).unwrap();
        let distances = [0.0, 0.01, 0.1, 1.0];
        s.guides[0].points = distances.map(|d| (root + Vec3::Y * d).to_array()).to_vec();
        s.groups[0].cards_per_guide = 1;
        let mesh = generate(&s, &AtomicBool::new(false)).unwrap().remove(0);
        for (i, distance) in distances.iter().enumerate() {
            assert!((mesh.uvs[i * 2][1] - distance).abs() < 1e-5);
            let width = Vec3::from(mesh.positions[i * 2]).distance(Vec3::from(mesh.positions[i * 2 + 1]));
            assert!((width - s.groups[0].width * (1.0 - distance * 0.94)).abs() < 1e-5);
        }
    }

    #[test]
    fn hair_existing_binding_roundtrips_and_requires_explicit_group() {
        let mut s = planted();
        let positions = vec![[0.02, 1.0, 0.0], [0.03, 0.9, 0.0], [0.04, 0.8, 0.0]];
        assert!(bind_existing(&mut s, 0, &positions, &AtomicBool::new(false)).is_err());
        s.groups[0].mode = GroupMode::Existing;
        bind_existing(&mut s, 0, &positions, &AtomicBool::new(false)).unwrap();
        let mut result = positions.clone();
        let points = s
            .guides
            .iter()
            .map(|g| g.points.clone())
            .collect::<Vec<_>>();
        deform(&s.bindings, &points, 0, &mut result).unwrap();
        for (a, b) in result.iter().zip(&positions) {
            assert!(Vec3::from(*a).distance(Vec3::from(*b)) < 1e-5);
        }
    }
    #[test]
    fn hair_reference_change_requires_explicit_rebind() {
        let mut s = planted();
        let mut scalp = s.scalp.clone();
        scalp.identity = "head-b".into();
        for p in &mut scalp.positions {
            p[1] += 0.1;
        }
        s.scalp = scalp.clone();
        assert!(s.validate().is_err());
        s.rebind(scalp).unwrap();
        s.validate().unwrap();
        assert!((s.guides[0].points[0][1] - 1.1).abs() < 1e-5);
    }
    #[test]
    fn hair_simulation_is_deterministic_pinned_and_transient_across_frame_rates() {
        let s = planted();
        let original = s.clone();
        let mut a = Simulation::new(&s).unwrap();
        let mut b = a.clone();
        let settings = MotionSettings {
            gravity: [0.0, -1.0, 0.0],
            ..Default::default()
        };
        for _ in 0..60 {
            a.advance(1.0 / 60.0, settings, &[], Quat::IDENTITY)
                .unwrap();
        }
        for _ in 0..30 {
            b.advance(1.0 / 30.0, settings, &[], Quat::IDENTITY)
                .unwrap();
        }
        assert_eq!(a.points, b.points);
        assert_eq!(a.points[0][0], s.guides[0].points[0]);
        assert_ne!(a.points[0], s.guides[0].points);
        assert_eq!(s, original);
        for (pair, rest) in a.points[0].windows(2).zip(s.guides[0].points.windows(2)) {
            let length = Vec3::from(pair[0]).distance(Vec3::from(pair[1]));
            let base = Vec3::from(rest[0]).distance(Vec3::from(rest[1]));
            assert!(length < base * 1.15, "{length} > {base}");
        }
        let settled = a.settled_state(&s, Quat::IDENTITY).unwrap();
        assert_ne!(settled.guides, s.guides);
        assert_eq!(
            Simulation::new(&s).unwrap().points,
            s.guides
                .iter()
                .map(|g| g.points.clone())
                .collect::<Vec<_>>()
        );
    }
    #[test]
    fn hair_short_cut_tip_survives_motion_and_settling() {
        let mut state = planted();
        let points = &mut state.guides[0].points;
        let last = points.len() - 1;
        points[last] = (Vec3::from(points[last - 1]) + Vec3::Y * 1.2e-7).to_array();
        state.validate().unwrap();
        for movement in 0..6 {
            let mut simulation = Simulation::new(&state).unwrap();
            for _ in 0..60 {
                let pose = simulation
                    .advance_test(
                        1.0 / 60.0,
                        MotionSettings::default(),
                        &state.collisions,
                        movement,
                        0.2,
                    )
                    .unwrap();
                simulation.settled_state(&state, pose.head).unwrap();
            }
        }
    }

    #[test]
    fn hair_motion_retains_authored_shape_instead_of_falling_from_the_root() {
        let mut state = planted();
        let root = Vec3::from(state.guides[0].points[0]);
        for (i, point) in state.guides[0].points.iter_mut().enumerate() {
            let t = i as f32 / 15.0;
            *point = (root + Vec3::new(t * 0.3, t * 0.12, 0.0)).to_array();
        }
        let mut simulation = Simulation::new(&state).unwrap();
        for _ in 0..300 {
            simulation
                .advance(1.0 / 60.0, MotionSettings::default(), &[], Quat::IDENTITY)
                .unwrap();
        }
        let tip = Vec3::from(*simulation.points[0].last().unwrap());
        let original = Vec3::from(*state.guides[0].points.last().unwrap());
        assert!(
            tip.distance(original) < 0.06,
            "authored shape collapsed: {tip:?}"
        );
        assert!(tip.distance(original) > 0.0001, "preview is rigid");
        assert_eq!(simulation.points[0][0], state.guides[0].points[0]);
    }

    #[test]
    fn hair_generated_card_contacts_roundtrip_through_bindings() {
        let mut state = planted();
        let root = Vec3::from(state.guides[0].points[0]);
        for (i, point) in state.guides[0].points.iter_mut().enumerate() {
            *point = (root + Vec3::X * (i as f32 * 0.001)).to_array();
        }
        let mesh = generate(&state, &AtomicBool::new(false)).unwrap().remove(0);
        let mut positions = mesh.positions.clone();
        deform(
            &mesh.bindings,
            &[state.guides[0].points.clone()],
            0,
            &mut positions,
        )
        .unwrap();
        for (a, b) in mesh.positions.iter().zip(&positions) {
            assert!(Vec3::from(*a).distance(Vec3::from(*b)) < 1e-6);
            assert!(a[1] >= root.y, "follower card entered scalp");
        }
    }

    #[test]
    fn hair_settled_shape_remains_valid_after_flat_contacts() {
        let mut state = planted();
        let root = Vec3::from(state.guides[0].points[0]);
        for (i, point) in state.guides[0].points.iter_mut().enumerate() {
            *point = (root - Vec3::Y * (i as f32 * 0.00005)).to_array();
        }
        state.validate().unwrap();
        let mut simulation = Simulation::new(&state).unwrap();
        for _ in 0..30 {
            simulation
                .advance(
                    1.0 / 60.0,
                    MotionSettings {
                        gravity: [0.0; 3],
                        ..Default::default()
                    },
                    &[],
                    Quat::IDENTITY,
                )
                .unwrap();
            simulation.settled_state(&state, Quat::IDENTITY).unwrap();
        }
    }

    #[test]
    fn hair_small_scalp_triangles_keep_interior_attachments() {
        let bary = closest_barycentric(
            Vec3::new(0.000125, 0.000125, 0.0002),
            Vec3::ZERO,
            Vec3::new(0.0005, 0.0, 0.0),
            Vec3::new(0.0, 0.0005, 0.0),
        );
        assert!(Vec3::from(bary).distance(Vec3::new(0.5, 0.25, 0.25)) < 1e-6);
    }

    #[test]
    fn hair_collision_pushes_vertices_outside_capsule() {
        let s = planted();
        let mut sim = Simulation::new(&s).unwrap();
        let capsule = Capsule {
            a: [0.0, 0.77, -0.2],
            b: [0.0, 0.9, -0.2],
            radius: 0.08,
            follows_head: true,
        };
        sim.advance(
            1.0 / 60.0,
            MotionSettings::default(),
            &[capsule.clone()],
            Quat::IDENTITY,
        )
        .unwrap();
        for p in sim.points[0].iter().skip(1) {
            let center = Vec3::new(0.0, p[1].clamp(0.77, 0.9), -0.2);
            assert!(Vec3::from(*p).distance(center) >= 0.0819);
        }
    }
    #[test]
    fn hair_budget_and_invalid_bindings_are_rejected() {
        let mut s = planted();
        s.groups[0].cards_per_guide = 33;
        assert!(generate(&s, &AtomicBool::new(false)).is_err());
        s.groups[0].cards_per_guide = 6;
        s.groups[0].part = 1;
        assert!(s.validate().is_err());
    }
}
