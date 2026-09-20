//! Decoded ordinary bone-to-render path from game build 1.0.0.2944.
//!
//! Mirrors `cdmw/modding/pac_jiggle_skinning.py`: inverse-bind composition and
//! current-frame jiggle/wind blending before guide cloth. Callers resolve the
//! rig maps and active runtime buffers. Special cross-LOD correction, sample
//! generation, normal transforms and stream-out packing remain outside this core.

pub type Matrix = [[f64; 4]; 4];
type Result<T> = std::result::Result<T, &'static str>;

#[derive(Debug)]
pub struct BoneMatrices {
    pub skeletal_matrix: Matrix,
    pub jiggle_matrix: Option<Matrix>,
}

/// PAC slot -> original bone -> skinning index are distinct maps. All selected
/// slots must resolve, even when their weight is zero. A missing jiggle buffer
/// explicitly disables jiggle; vertex data alone does not establish activation.
pub struct RenderInput<'a> {
    pub record: &'a [u8; 40],
    pub render_flags: u32,
    pub bone_palette: &'a [u32],
    pub skinning_index_map: &'a [u32],
    pub skeletal_matrices: &'a [Matrix],
    pub jiggle_matrices: Option<&'a [Matrix]>,
    pub wind_weight: f64,
    pub wind_samples: Option<&'a [Matrix]>,
}

fn finite(matrix: &Matrix) -> Result<()> {
    if matrix.iter().flatten().all(|value| value.is_finite()) {
        Ok(())
    } else {
        Err("Jiggle skinning matrices must be finite.")
    }
}

fn entry<T>(buffer: &[T], index: u32) -> Result<&T> {
    buffer
        .get(index as usize)
        .ok_or("Jiggle skinning index refers outside its supplied runtime buffer.")
}

/// Compose the ordinary inverse-bind path, including LOD0. Character-space
/// scale multiplies pose basis rows only. Solver row0.w/row1.w move to the
/// ordinary matrix AFTER composition; they must not contaminate either basis.
pub fn prepare_bone(
    inverse_bind: &Matrix,
    animation: &Matrix,
    jiggle: Option<&Matrix>,
    character_space_scale: [f64; 3],
) -> Result<BoneMatrices> {
    finite(inverse_bind)?;
    finite(animation)?;
    if let Some(jiggle) = jiggle {
        finite(jiggle)?;
    }
    if character_space_scale.iter().any(|value| !value.is_finite()) {
        return Err("Character-space bone scale must contain three finite values.");
    }
    let compose = |pose: &Matrix| -> Result<Matrix> {
        let mut scaled = *pose;
        for i in 0..3 {
            for j in 0..3 {
                scaled[i][j] *= character_space_scale[i];
            }
            scaled[i][3] = 0.0;
        }
        let result = std::array::from_fn(|i| {
            std::array::from_fn(|j| (0..4).map(|k| inverse_bind[i][k] * scaled[k][j]).sum())
        });
        finite(&result)?;
        Ok(result)
    };
    let mut skeletal_matrix = compose(animation)?;
    skeletal_matrix[0][3] = if jiggle.is_some_and(|m| m[0][3] > 0.0) {
        1.0
    } else {
        0.0
    };
    skeletal_matrix[1][3] = jiggle.map_or(0.0, |m| m[1][3]);
    Ok(BoneMatrices {
        skeletal_matrix,
        jiggle_matrix: jiggle.map(compose).transpose()?,
    })
}

fn weighted(buffer: &[Matrix], indices: &[u32], weights: &[u8]) -> Result<Matrix> {
    let mut result = [[0.0; 4]; 4];
    for (&index, &weight) in indices.iter().zip(weights) {
        let matrix = entry(buffer, index)?;
        finite(matrix)?;
        for i in 0..4 {
            for j in 0..4 {
                result[i][j] += matrix[i][j] * f64::from(weight);
            }
        }
    }
    // Normalized raw byte weights. An all-zero total yields zero XYZ, not an
    // invented identity/fallback bone. Fetches above still validate every slot.
    let total = weights
        .iter()
        .map(|value| u32::from(*value))
        .sum::<u32>()
        .max(1);
    for row in &mut result {
        for value in row {
            *value /= f64::from(total);
        }
    }
    finite(&result)?;
    Ok(result)
}

/// Blend one retained 40-byte PAC record before guide-cloth processing.
/// Ordinary unbound vertices use six slots; guide-bound and special render
/// modes use four. Only the special modes bypass jiggle. Positive bone weights
/// above one extrapolate; nonpositive weights bypass simulation. Output metadata
/// is consumed, returning an affine fourth column (0, 0, 0, 1).
pub fn blend_vertex(input: RenderInput<'_>) -> Result<Matrix> {
    if !input.wind_weight.is_finite() {
        return Err("Jiggle wind weight must be finite.");
    }
    let ordinary_mode = input.render_flags & 0xe00 == 0;
    let count = if ordinary_mode && input.record[39] & 63 == 63 {
        6
    } else {
        4
    };
    let mut bones = [0; 6];
    let mut indices = [0; 6];
    for i in 0..count {
        let offset = 20 + (i / 3) * 4;
        let group = u32::from_le_bytes(
            input.record[offset..offset + 4]
                .try_into()
                .expect("fixed record"),
        );
        let slot = (group >> ((i % 3) * 10)) & 1023;
        bones[i] = *entry(input.bone_palette, slot)?;
        indices[i] = *entry(input.skinning_index_map, bones[i])?;
    }
    let weights = &input.record[28..28 + count];
    let skeletal = weighted(input.skeletal_matrices, &indices[..count], weights)?;
    let vertex_blend = if input.render_flags & 128 != 0 {
        1.0 - f64::from(input.record[38] & 15) / 15.0
    } else {
        1.0 - f64::from(input.record[38]) / 255.0
    };
    let blend = if skeletal[0][3] > 0.0 {
        skeletal[1][3]
    } else {
        vertex_blend
    };
    let mut result = skeletal;
    if ordinary_mode
        && blend > 0.0
        && let Some(matrices) = input.jiggle_matrices
    {
        let mut jiggle = weighted(matrices, &indices[..count], weights)?;
        if input.wind_weight > 0.0 {
            let samples = input
                .wind_samples
                .ok_or("Active jiggle wind blending requires the runtime sample buffer.")?;
            // Samples use the original bone's low byte BEFORE the skinning map.
            let samples_indices = bones.map(|bone| 1024 | (bone & 255));
            let sample = weighted(samples, &samples_indices[..count], weights)?;
            let translation: [f64; 3] = std::array::from_fn(|j| jiggle[3][j] + sample[3][j]);
            let wind: [[f64; 3]; 4] = std::array::from_fn(|i| {
                std::array::from_fn(|j| {
                    if i == 3 {
                        translation[j]
                    } else {
                        (0..3).map(|k| sample[i][k] * jiggle[k][j]).sum::<f64>()
                            + sample[i][3] * translation[j]
                    }
                })
            });
            for i in 0..4 {
                for j in 0..3 {
                    jiggle[i][j] += input.wind_weight * (wind[i][j] - jiggle[i][j]);
                }
            }
        }
        for i in 0..4 {
            for j in 0..3 {
                result[i][j] += blend * (jiggle[i][j] - result[i][j]);
            }
        }
    }
    for (i, row) in result.iter_mut().enumerate() {
        row[3] = f64::from(u8::from(i == 3));
    }
    finite(&result)?;
    Ok(result)
}

#[cfg(test)]
mod tests;
