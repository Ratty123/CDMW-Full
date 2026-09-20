//! Validated rig snapshot and preview-coordinate binding for decoded jiggle.
//!
//! The host resolves PAB/PABC ownership with `prepare_jiggle_rig`; this core
//! rechecks the snapshot and advances it without Python work per frame. Matrices
//! use row vectors. Source inverse binds remain unchanged by neutral appearance.
//! Runtime activation/profile selection and game animation sampling are caller
//! inputs, not facts inferred from the presence of PAC vertex contribution.

use crate::jiggle_bones;
use crate::jiggle_skinning::{self, Matrix};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, VecDeque};
use std::sync::atomic::{AtomicU64, Ordering};

type Result<T> = std::result::Result<T, &'static str>;
static NEXT_RIG_IDENTITY: AtomicU64 = AtomicU64::new(1);

/// One-time snapshot of the host's validated fixed-layout PAB and resolved PAC
/// palette. Neutral matrices include the existing PABC axis reconciliation.
/// Native validation cannot establish ownership of an arbitrary caller's data.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct RigSnapshot {
    pub bone_palette: Vec<u32>,
    pub parents: Vec<i32>,
    pub inverse_bind_matrices: Vec<Matrix>,
    pub neutral_global_matrices: Vec<Matrix>,
    pub neutral_local_matrices: Vec<Matrix>,
}

#[derive(Debug)]
pub struct Rig {
    identity: u64,
    snapshot: RigSnapshot,
    order: Vec<usize>,
    skinning_index_map: Vec<u32>,
}

pub struct FrameInput<'a> {
    pub shader_data: &'a [u8; 264],
    pub character_transform: &'a [u8; 272],
    pub view_position: [f64; 3],
    pub previous_view_position: [f64; 3],
    pub bone_scale: f64,
    pub character_space_scales: &'a [[f64; 3]],
    pub update_frame_index: u32,
    pub delta_time: f64,
    pub reset_requested: bool,
    /// Absolute local pose replacements keyed by original bone ordinal.
    pub local_pose_overrides: &'a BTreeMap<u32, Matrix>,
    /// A missing command lets an existing instance continue without reinjection.
    pub commands: &'a BTreeMap<u32, [u8; 116]>,
}

#[derive(Debug)]
pub struct FrameOutput {
    rig_identity: u64,
    pub bone_states: Vec<[u8; 116]>,
    pub skeletal_matrices: Vec<Matrix>,
    pub jiggle_matrices: Vec<Matrix>,
    pub reset_bones: Vec<u32>,
}

fn multiply(left: &Matrix, right: &Matrix) -> Matrix {
    std::array::from_fn(|i| std::array::from_fn(|j| (0..4).map(|k| left[i][k] * right[k][j]).sum()))
}

fn inverse_affine(m: &Matrix) -> Result<Matrix> {
    if m.iter().flatten().any(|value| !value.is_finite())
        || m.map(|row| row[3]) != [0.0, 0.0, 0.0, 1.0]
    {
        return Err("Jiggle rig matrices must be finite row-major affine transforms.");
    }
    let [[a, b, c, _], [d, e, f, _], [g, h, i, _], [tx, ty, tz, _]] = *m;
    let determinant = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g);
    if !determinant.is_finite() || determinant.abs() <= 1e-12 {
        return Err("Jiggle rig transform matrix is singular.");
    }
    let r = 1.0 / determinant;
    let mut inverse = [
        [
            (e * i - f * h) * r,
            (c * h - b * i) * r,
            (b * f - c * e) * r,
            0.0,
        ],
        [
            (f * g - d * i) * r,
            (a * i - c * g) * r,
            (c * d - a * f) * r,
            0.0,
        ],
        [
            (d * h - e * g) * r,
            (b * g - a * h) * r,
            (a * e - b * d) * r,
            0.0,
        ],
        [0.0, 0.0, 0.0, 1.0],
    ];
    for j in 0..3 {
        inverse[3][j] = -(tx * inverse[0][j] + ty * inverse[1][j] + tz * inverse[2][j]);
    }
    if inverse.iter().flatten().any(|value| !value.is_finite()) {
        return Err("Jiggle rig matrix inverse must be finite.");
    }
    Ok(inverse)
}

fn near(actual: &Matrix, expected: &Matrix) -> bool {
    actual
        .iter()
        .flatten()
        .zip(expected.iter().flatten())
        .all(|(a, b)| a.is_finite() && (a - b).abs() <= 2e-5 * (1.0 + a.abs() + b.abs()))
}

fn packed_pose(pose: &Matrix) -> Result<([u8; 64], Matrix)> {
    let mut bytes = [0; 64];
    let mut rounded = [[0.0; 4]; 4];
    for (i, value) in pose.iter().flatten().enumerate() {
        let value = *value as f32;
        if !value.is_finite() {
            return Err("Jiggle animation pose exceeds float32 storage.");
        }
        bytes[4 * i..4 * i + 4].copy_from_slice(&value.to_le_bytes());
        rounded[i / 4][i % 4] = f64::from(value);
    }
    Ok((bytes, rounded))
}

impl Rig {
    pub fn new(snapshot: RigSnapshot) -> Result<Self> {
        let count = snapshot.parents.len();
        if !(1..=4096).contains(&count)
            || snapshot.inverse_bind_matrices.len() != count
            || snapshot.neutral_global_matrices.len() != count
            || snapshot.neutral_local_matrices.len() != count
        {
            return Err("Jiggle rig needs complete matrix buffers within 4096 bones.");
        }
        if snapshot.bone_palette.is_empty()
            || snapshot
                .bone_palette
                .iter()
                .any(|bone| *bone as usize >= count)
        {
            return Err("Jiggle rig needs a resolved PAC bone palette.");
        }
        let mut children = vec![Vec::new(); count];
        let mut queue = VecDeque::new();
        for (index, &parent) in snapshot.parents.iter().enumerate() {
            if parent == -1 {
                queue.push_back(index);
            } else if parent < 0 || parent as usize >= count || parent as usize == index {
                return Err("Jiggle rig has an invalid parent index.");
            } else {
                children[parent as usize].push(index);
            }
            inverse_affine(&snapshot.inverse_bind_matrices[index])?;
            inverse_affine(&snapshot.neutral_global_matrices[index])?;
            inverse_affine(&snapshot.neutral_local_matrices[index])?;
        }
        let mut order = Vec::with_capacity(count);
        while let Some(index) = queue.pop_front() {
            order.push(index);
            queue.extend(&children[index]);
        }
        if order.len() != count {
            return Err("Jiggle rig hierarchy contains a cycle.");
        }
        for (index, &parent) in snapshot.parents.iter().enumerate() {
            let local = &snapshot.neutral_local_matrices[index];
            let expected = if parent == -1 {
                *local
            } else {
                multiply(local, &snapshot.neutral_global_matrices[parent as usize])
            };
            if !near(&expected, &snapshot.neutral_global_matrices[index]) {
                return Err("Jiggle rig has inconsistent local-to-parent pose matrices.");
            }
        }
        Ok(Self {
            identity: NEXT_RIG_IDENTITY.fetch_add(1, Ordering::Relaxed),
            snapshot,
            order,
            skinning_index_map: (0..count as u32).collect(),
        })
    }

    pub fn bone_count(&self) -> usize {
        self.snapshot.parents.len()
    }

    pub fn palette(&self) -> &[u32] {
        &self.snapshot.bone_palette
    }

    /// Original ordinals are retained. Only changed branches are recomposed;
    /// simulated parent motion never feeds back into a child's animation target.
    pub fn pose(&self, overrides: &BTreeMap<u32, Matrix>) -> Result<Vec<Matrix>> {
        for (index, matrix) in overrides {
            if *index as usize >= self.bone_count() {
                return Err("Jiggle pose refers to a missing original bone index.");
            }
            inverse_affine(matrix)?;
        }
        let mut poses = self.snapshot.neutral_global_matrices.clone();
        let mut changed = vec![false; self.bone_count()];
        for &index in &self.order {
            let parent = self.snapshot.parents[index];
            let original = &self.snapshot.neutral_local_matrices[index];
            let local = overrides.get(&(index as u32)).unwrap_or(original);
            changed[index] = local != original || (parent != -1 && changed[parent as usize]);
            if changed[index] {
                poses[index] = if parent == -1 {
                    *local
                } else {
                    multiply(local, &poses[parent as usize])
                };
                inverse_affine(&poses[index])?;
            }
        }
        Ok(poses)
    }

    /// Build original-ordinal-indexed buffers. This reference allocation does
    /// not claim that the game's actual LOD0 skinning map is identity.
    pub fn step(
        &self,
        previous: Option<&FrameOutput>,
        input: FrameInput<'_>,
    ) -> Result<FrameOutput> {
        let count = self.bone_count();
        if input.character_space_scales.len() != count
            || previous
                .is_some_and(|p| p.rig_identity != self.identity || p.bone_states.len() != count)
        {
            return Err("Jiggle rig state and character-space scales must cover every bone.");
        }
        if input.commands.keys().any(|index| *index as usize >= count) {
            return Err("Jiggle command refers to a missing original bone index.");
        }
        let poses = self.pose(input.local_pose_overrides)?;
        let mut output = FrameOutput {
            rig_identity: self.identity,
            bone_states: Vec::with_capacity(count),
            skeletal_matrices: Vec::with_capacity(count),
            jiggle_matrices: Vec::with_capacity(count),
            reset_bones: Vec::new(),
        };
        for (index, pose) in poses.iter().enumerate() {
            let (animation, rounded) = packed_pose(pose)?;
            let solved = jiggle_bones::step(jiggle_bones::StepInput {
                previous_bone: previous.map(|states| &states.bone_states[index]),
                command_bone: input.commands.get(&(index as u32)).unwrap_or(&[0; 116]),
                shader_data: input.shader_data,
                animation_matrix: &animation,
                character_transform: input.character_transform,
                view_position: input.view_position,
                previous_view_position: input.previous_view_position,
                bone_scale: input.bone_scale,
                original_bone_index: index as u32,
                update_frame_index: input.update_frame_index,
                delta_time: input.delta_time,
                reset_requested: input.reset_requested,
            })?;
            let prepared = jiggle_skinning::prepare_bone(
                &self.snapshot.inverse_bind_matrices[index],
                &rounded,
                Some(&solved.matrix),
                input.character_space_scales[index],
            )?;
            output.bone_states.push(solved.bone);
            output.skeletal_matrices.push(prepared.skeletal_matrix);
            output
                .jiggle_matrices
                .push(prepared.jiggle_matrix.expect("solver supplied"));
            if solved.reset {
                output.reset_bones.push(index as u32);
            }
        }
        Ok(output)
    }

    /// Bind currently displayed (possibly sculpted) positions to the neutral
    /// rig's source frame. Invert the BLENDED skin matrix, not the blend of bone
    /// inverses. Retain the original position and compose transforms at playback
    /// to avoid an unnecessary source/display round trip. This never edits PAC.
    pub fn bind_vertices(
        &self,
        positions: &[[f64; 3]],
        records: &[[u8; 40]],
        render_flags: u32,
    ) -> Result<VertexBinding> {
        self.bind_vertices_cancellable(positions, records, render_flags, &|| false)
    }

    pub fn bind_vertices_cancellable(
        &self,
        positions: &[[f64; 3]],
        records: &[[u8; 40]],
        render_flags: u32,
        cancelled: &dyn Fn() -> bool,
    ) -> Result<VertexBinding> {
        if cancelled() { return Err("Jiggle preview preparation was cancelled."); }
        if positions.is_empty() || positions.len() > 100_000 || positions.len() != records.len() {
            return Err(
                "Jiggle binding needs matching positions and PAC records within 100,000 vertices.",
            );
        }
        if positions.iter().flatten().any(|value| !value.is_finite()) {
            return Err("Jiggle binding positions must be finite.");
        }
        let mut matrices = Vec::with_capacity(self.bone_count());
        for (inverse, pose) in self
            .snapshot
            .inverse_bind_matrices
            .iter()
            .zip(&self.snapshot.neutral_global_matrices)
        {
            let (_, rounded) = packed_pose(pose)?;
            matrices.push(
                jiggle_skinning::prepare_bone(inverse, &rounded, None, [1.0; 3])?.skeletal_matrix,
            );
        }
        let mut to_source = Vec::with_capacity(records.len());
        for (index, record) in records.iter().enumerate() {
            if index.is_multiple_of(256) && cancelled() {
                return Err("Jiggle preview preparation was cancelled.");
            }
            let blend = jiggle_skinning::blend_vertex(jiggle_skinning::RenderInput {
                record,
                render_flags,
                bone_palette: self.palette(),
                skinning_index_map: &self.skinning_index_map,
                skeletal_matrices: &matrices,
                jiggle_matrices: None,
                wind_weight: 0.0,
                wind_samples: None,
            })?;
            to_source.push(inverse_affine(&blend)?);
        }
        Ok(VertexBinding {
            positions: positions.to_vec(),
            records: records.to_vec(),
            to_source,
            render_flags,
            rig_identity: self.identity,
        })
    }
}

/// Immutable ownership snapshot; rebuild when the rig, topology, weights or
/// displayed rest positions change. Byte38 contribution can vary at playback.
#[derive(Debug)]
pub struct VertexBinding {
    positions: Vec<[f64; 3]>,
    records: Vec<[u8; 40]>,
    to_source: Vec<Matrix>,
    render_flags: u32,
    rig_identity: u64,
}

impl VertexBinding {
    /// Produces PAC model-space positions. Character/world motion is applied by
    /// the preview after this stage. `contributions` contains full byte38 values
    /// for current/original comparisons; other record lanes are fixed. Explicit
    /// `jiggle_enabled=false` bypasses simulation for an all-disabled comparison,
    /// including positive bone overrides that would supersede byte38=255.
    pub fn positions(
        &self,
        rig: &Rig,
        frame: &FrameOutput,
        contributions: &[u8],
        jiggle_enabled: bool,
        wind_weight: f64,
        wind_samples: Option<&[Matrix]>,
    ) -> Result<Vec<[f64; 3]>> {
        // Equal lengths alone cannot prove that previous states or a binding
        // belong to the same rig. Reject a different neutral/source transform.
        if self.rig_identity != rig.identity
            || frame.rig_identity != rig.identity
            || contributions.len() != self.records.len()
            || frame.bone_states.len() != rig.bone_count()
            || frame.skeletal_matrices.len() != rig.bone_count()
            || frame.jiggle_matrices.len() != rig.bone_count()
        {
            return Err("Jiggle preview binding, rig and frame buffers do not match.");
        }
        let mut output = Vec::with_capacity(self.records.len());
        for (index, original) in self.records.iter().enumerate() {
            let mut record = *original;
            record[38] = contributions[index];
            let skin = jiggle_skinning::blend_vertex(jiggle_skinning::RenderInput {
                record: &record,
                render_flags: self.render_flags,
                bone_palette: rig.palette(),
                skinning_index_map: &rig.skinning_index_map,
                skeletal_matrices: &frame.skeletal_matrices,
                jiggle_matrices: jiggle_enabled.then_some(&frame.jiggle_matrices),
                wind_weight,
                wind_samples,
            })?;
            let change = multiply(&self.to_source[index], &skin);
            let position: [f64; 3] = std::array::from_fn(|j| {
                (0..3)
                    .map(|i| self.positions[index][i] * change[i][j])
                    .sum::<f64>()
                    + change[3][j]
            });
            if position.iter().any(|value| !value.is_finite()) {
                return Err("Jiggle preview produced non-finite positions.");
            }
            output.push(position);
        }
        Ok(output)
    }
}

#[cfg(test)]
mod tests;
