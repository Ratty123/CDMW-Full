//! Prepare immutable particle geometry alongside the cancellable scene load.
use crate::preview_effect_lightning::LightningMaterial;
use cdmw_render_wgpu::{EffectMeshAsset, EffectMeshVertex};
use serde_json::Value;

#[derive(Debug, Default)]
pub(crate) struct EffectMeshes(pub Vec<Option<EffectMeshAsset>>);

impl EffectMeshes {
    pub fn read(scene: &Value, cancelled: &dyn Fn() -> bool) -> Result<Self, String> {
        let mut result = Self::default();
        if let Some(emitters) = scene["effects_overlay"]["emitters"].as_array() {
            for emitter in emitters.iter().take(2048) {
                if cancelled() {
                    return Err("Preview load cancelled".into());
                }
                result.0.push(read_asset(emitter, cancelled)?);
            }
        }
        Ok(result)
    }
}

fn vector<const N: usize>(value: &Value) -> Option<[f32; N]> {
    let values = value.as_array()?;
    if values.len() < N {
        return None;
    }
    let mut result = [0.; N];
    for (out, value) in result.iter_mut().zip(values) {
        *out = value.as_f64()? as f32;
        if !out.is_finite() {
            return None;
        }
    }
    Some(result)
}

fn read_asset(e: &Value, cancelled: &dyn Fn() -> bool) -> Result<Option<EffectMeshAsset>, String> {
    // This GPU shader owns the decoded, untextured additive lightning variant.
    // Other materials continue through their existing draw path.
    if e["kind"] != "mesh"
        || e["blend"] != "additive"
        || e["texture"].as_str().is_some_and(|v| !v.is_empty())
    {
        return Ok(None);
    }
    let Some(material) = LightningMaterial::read(e) else {
        return Ok(None);
    };
    let Some(positions) = e["particle_vertices"]
        .as_array()
        .filter(|v| !v.is_empty() && v.len() <= 8192)
    else {
        return Ok(None);
    };
    let Some(faces) = e["particle_faces"]
        .as_array()
        .filter(|v| !v.is_empty() && v.len() <= 8192)
    else {
        return Ok(None);
    };
    let mut vertices = Vec::with_capacity(positions.len());
    for (i, position) in positions.iter().enumerate() {
        if i % 256 == 0 && cancelled() {
            return Err("Preview load cancelled".into());
        }
        let (Some(position), Some(normal), Some(uv), Some(controls)) = (
            vector(position),
            vector(&e["particle_normals"][i]),
            vector(&e["particle_uvs"][i]),
            vector::<3>(&e["particle_colors"][i]),
        ) else {
            return Ok(None);
        };
        vertices.push(EffectMeshVertex {
            position,
            normal,
            uv,
            controls: [controls[0], controls[1], controls[2], 1.],
        });
    }
    let mut indices = Vec::with_capacity(faces.len() * 3);
    for (i, face) in faces.iter().enumerate() {
        if i % 256 == 0 && cancelled() {
            return Err("Preview load cancelled".into());
        }
        let Some(face) = face.as_array().filter(|v| v.len() == 3) else {
            return Ok(None);
        };
        for index in face {
            let Some(index) = index.as_u64().filter(|i| *i < vertices.len() as u64) else {
                return Ok(None);
            };
            indices.push(index as u32);
        }
    }
    Ok(Some(EffectMeshAsset {
        vertices,
        indices,
        lightning: material.gpu(),
    }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn only_complete_supported_meshes_enter_the_cached_gpu_path() {
        let mut e = json!({"kind":"mesh", "blend":"additive", "texture":"",
            "material":{"name":"EffectTest_Lightning","values":{"_materialFlags":16384}},
            "particle_vertices":[[0.,0.,0.],[1.,0.,0.],[0.,1.,0.]],
            "particle_normals":[]});
        e["particle_normals"] = json!([[0., 0., 1.], [0., 0., 1.], [0., 0., 1.]]);
        e["particle_colors"] = json!([[1., 1., 1.], [1., 1., 1.], [1., 1., 1.]]);
        e["particle_uvs"] = json!([[0., 0.], [1., 0.], [0., 1.]]);
        e["particle_faces"] = json!([[0, 1, 2]]);
        let asset = read_asset(&e, &|| false).unwrap().unwrap();
        assert_eq!(asset.indices, [0, 1, 2]);
        assert_eq!(asset.vertices.len(), 3);
        assert!(read_asset(&e, &|| true).is_err());
        e["particle_faces"] = json!([[0, 1, 3]]);
        assert!(read_asset(&e, &|| false).unwrap().is_none());
        e["particle_faces"] = json!([[0, 1, 2]]);
        e["texture"] = json!("textured-lightning.dds");
        assert!(read_asset(&e, &|| false).unwrap().is_none());
    }
}
