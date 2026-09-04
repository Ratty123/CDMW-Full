//! Pure scene transforms and revision-owned spatial data for the preview.

use crate::cdmw_preview::{
    editable_indices, reference_indices, role_model_matrix, scene_role_indices,
};
use cdmw_mesh::{DrawSnapshot, Provenance, WorkingMesh};
use glam::{EulerRot, Mat3, Mat4, Quat, Vec3};
use serde_json::Value;
use std::collections::{BTreeMap, HashMap, HashSet};

pub fn vector(value: Option<&Value>, fallback: Vec3) -> Vec3 {
    value
        .and_then(Value::as_array)
        .filter(|v| v.len() == 3)
        .and_then(|v| {
            Some(Vec3::new(
                v[0].as_f64()? as f32,
                v[1].as_f64()? as f32,
                v[2].as_f64()? as f32,
            ))
        })
        .filter(|v| v.is_finite())
        .unwrap_or(fallback)
}

pub fn matrix(value: Option<&Value>) -> Mat4 {
    let Some(values) = value.and_then(Value::as_array).filter(|v| v.len() == 16) else {
        return Mat4::IDENTITY;
    };
    let mut columns = [0.0; 16];
    for (out, value) in columns.iter_mut().zip(values) {
        let Some(number) = value.as_f64() else {
            return Mat4::IDENTITY;
        };
        *out = number as f32;
    }
    let result = Mat4::from_cols_array(&columns);
    if result.is_finite() {
        result
    } else {
        Mat4::IDENTITY
    }
}

pub fn placement_matrix(value: &Value) -> Mat4 {
    let angles = vector(value.get("rotation_degrees"), Vec3::ZERO) * std::f32::consts::PI / 180.0;
    // Python's row-vector S * Rx * Ry * Rz * T, transposed for glam.
    let rotation = Quat::from_euler(EulerRot::ZYX, angles.z, angles.y, angles.x);
    Mat4::from_scale_rotation_translation(
        vector(
            value.get("scale").or_else(|| value.get("scale_xyz")),
            Vec3::ONE,
        ),
        rotation,
        vector(value.get("translation"), Vec3::ZERO),
    )
}

pub fn placed_scene(scene: &Value, placement: &Value) -> (Mat4, Vec3) {
    let alignment = &scene["automatic_alignment"];
    let anchor = vector(alignment.get("source_anchor"), Vec3::ZERO);
    let mut manual = placement_matrix(placement);
    if alignment
        .get("model_matrix")
        .and_then(Value::as_array)
        .is_some_and(|v| v.len() == 16)
    {
        let automatic = matrix(alignment.get("model_matrix"));
        let translation = vector(placement.get("translation"), Vec3::ZERO);
        let pivot = automatic.transform_point3(anchor) + translation;
        manual.w_axis = glam::Vec4::W;
        let mut result = manual * automatic;
        result.w_axis = (pivot - result.transform_vector3(anchor)).extend(1.0);
        (result, pivot)
    } else {
        (manual, manual.transform_point3(anchor))
    }
}

#[derive(Debug)]
struct Node {
    low: Vec3,
    high: Vec3,
    range: std::ops::Range<usize>,
    children: Option<(usize, usize)>,
}

#[derive(Debug)]
pub struct PartGeometry {
    pub submesh: u32,
    triangles: Vec<[Vec3; 3]>,
    nodes: Vec<Node>,
    pub edges: Vec<[Vec3; 2]>,
}

impl PartGeometry {
    fn new(submesh: u32, mut triangles: Vec<[Vec3; 3]>) -> Self {
        let mut edges = Vec::new();
        let mut seen = HashSet::new();
        for triangle in &triangles {
            for (a, b) in [(0, 1), (1, 2), (2, 0)] {
                let mut key = [
                    triangle[a].to_array().map(f32::to_bits),
                    triangle[b].to_array().map(f32::to_bits),
                ];
                key.sort_unstable();
                if edges.len() < 120_000 && seen.insert(key) {
                    edges.push([triangle[a], triangle[b]]);
                }
            }
        }
        let mut nodes = Vec::new();
        let count = triangles.len();
        Self::build(&mut triangles, &mut nodes, 0..count);
        Self {
            submesh,
            triangles,
            nodes,
            edges,
        }
    }

    fn build(
        triangles: &mut [[Vec3; 3]],
        nodes: &mut Vec<Node>,
        range: std::ops::Range<usize>,
    ) -> usize {
        let mut low = Vec3::splat(f32::INFINITY);
        let mut high = Vec3::splat(f32::NEG_INFINITY);
        for point in triangles[range.clone()].iter().flatten() {
            low = low.min(*point);
            high = high.max(*point);
        }
        let index = nodes.len();
        nodes.push(Node {
            low,
            high,
            range: range.clone(),
            children: None,
        });
        if range.len() > 8 {
            let extent = high - low;
            let axis = if extent.x >= extent.y && extent.x >= extent.z {
                0
            } else if extent.y >= extent.z {
                1
            } else {
                2
            };
            triangles[range.clone()].sort_unstable_by(|a, b| {
                let center = |t: &[Vec3; 3]| t[0][axis] + t[1][axis] + t[2][axis];
                center(a).total_cmp(&center(b))
            });
            let mid = range.start + range.len() / 2;
            let left = Self::build(triangles, nodes, range.start..mid);
            let right = Self::build(triangles, nodes, mid..range.end);
            nodes[index].children = Some((left, right));
        }
        index
    }

    fn hit(&self, origin: Vec3, direction: Vec3, maximum: f32) -> Option<f32> {
        let mut best = maximum;
        let mut hit = None;
        let mut stack = vec![0];
        while let Some(index) = stack.pop() {
            let node = &self.nodes[index];
            if !ray_box(origin, direction, node.low, node.high, best) {
                continue;
            }
            if let Some((left, right)) = node.children {
                stack.extend([left, right]);
                continue;
            }
            for triangle in &self.triangles[node.range.clone()] {
                if let Some(distance) =
                    ray_triangle(origin, direction, *triangle).filter(|d| *d < best)
                {
                    best = distance;
                    hit = Some(distance);
                }
            }
        }
        hit
    }

    pub fn bounds(&self, transform: Mat4) -> (Vec3, Vec3) {
        let root = &self.nodes[0];
        let mut low = Vec3::splat(f32::INFINITY);
        let mut high = Vec3::splat(f32::NEG_INFINITY);
        for x in [root.low.x, root.high.x] {
            for y in [root.low.y, root.high.y] {
                for z in [root.low.z, root.high.z] {
                    let point = transform.transform_point3(Vec3::new(x, y, z));
                    low = low.min(point);
                    high = high.max(point);
                }
            }
        }
        (low, high)
    }
}

#[derive(Debug, Default)]
pub struct PreviewGeometry {
    pub parts: Vec<PartGeometry>,
}

impl PreviewGeometry {
    pub fn from_mesh(mesh: &WorkingMesh) -> Self {
        let mut parts = BTreeMap::<u32, Vec<[Vec3; 3]>>::new();
        for (_, face) in mesh.faces() {
            let points = face
                .vertices
                .map(|h| mesh.vertex(h).map(|v| Vec3::from_array(v.position)));
            if let [Some(a), Some(b), Some(c)] = points {
                parts.entry(face.submesh).or_default().push([a, b, c]);
            }
        }
        Self {
            parts: parts
                .into_iter()
                .map(|(id, t)| PartGeometry::new(id, t))
                .collect(),
        }
    }

    pub fn pick(
        &self,
        origin: Vec3,
        direction: Vec3,
        maximum: f32,
        visible: &HashSet<u32>,
        transform: impl Fn(u32) -> Mat4,
    ) -> Option<u32> {
        let mut best = maximum;
        let mut result = None;
        for part in &self.parts {
            if !visible.contains(&part.submesh) {
                continue;
            }
            let inverse = transform(part.submesh).inverse();
            if !inverse.is_finite() {
                continue;
            }
            // Keep direction unnormalized after inverse transform: t remains a
            // world-space ray distance even for non-uniformly scaled parts.
            if let Some(distance) = part.hit(
                inverse.transform_point3(origin),
                inverse.transform_vector3(direction),
                best,
            ) {
                best = distance;
                result = Some(part.submesh);
            }
        }
        result
    }
}

fn ray_box(origin: Vec3, direction: Vec3, low: Vec3, high: Vec3, maximum: f32) -> bool {
    let mut near: f32 = 0.0;
    let mut far = maximum;
    for axis in 0..3 {
        if direction[axis].abs() < 1.0e-12 {
            if origin[axis] < low[axis] || origin[axis] > high[axis] {
                return false;
            }
        } else {
            let a = (low[axis] - origin[axis]) / direction[axis];
            let b = (high[axis] - origin[axis]) / direction[axis];
            near = near.max(a.min(b));
            far = far.min(a.max(b));
            if near > far {
                return false;
            }
        }
    }
    true
}

fn ray_triangle(origin: Vec3, direction: Vec3, triangle: [Vec3; 3]) -> Option<f32> {
    let a = triangle[1] - triangle[0];
    let b = triangle[2] - triangle[0];
    let cross = direction.cross(b);
    let determinant = a.dot(cross);
    if determinant.abs() < 1.0e-10 {
        return None;
    }
    let delta = origin - triangle[0];
    let u = delta.dot(cross) / determinant;
    let q = delta.cross(a);
    let v = direction.dot(q) / determinant;
    let distance = b.dot(q) / determinant;
    (u >= -1.0e-6 && v >= -1.0e-6 && u + v <= 1.0 + 1.0e-6 && distance >= 0.0).then_some(distance)
}

pub struct SceneView<'a> {
    pub scene: &'a Value,
    pub presentation: &'a Value,
    pub geometry: &'a PreviewGeometry,
}
impl SceneView<'_> {
    pub fn submesh_model_matrix(&self, source_submesh: u32) -> Mat4 {
        let editable = editable_indices(self.scene);
        let reference = reference_indices(self.scene);
        let mut matrix = if reference.contains(&source_submesh) {
            role_model_matrix(self.scene, "reference")
        } else if editable.contains(&source_submesh) {
            role_model_matrix(self.scene, "editable")
        } else {
            Mat4::IDENTITY
        };
        let source_part = self.source_part_index(source_submesh);
        if let Some(part) = self
            .presentation
            .get("part_transforms")
            .and_then(Value::as_object)
            .and_then(|items| items.get(source_part.to_string().as_str()))
        {
            matrix *= placement_matrix(part);
        }
        let comparison_mode = self
            .presentation
            .get("comparison_mode")
            .and_then(Value::as_str)
            .or_else(|| self.scene.get("comparison_mode").and_then(Value::as_str))
            .unwrap_or("replacement_only");
        if comparison_mode == "side_by_side" {
            let extent = self
                .scene
                .get("framing")
                .and_then(|value| value.get("extent"))
                .and_then(Value::as_f64)
                .unwrap_or(1.0) as f32;
            let split = self
                .presentation
                .get("side_by_side_split_ratio")
                .and_then(Value::as_f64)
                .unwrap_or(0.5)
                .clamp(0.18, 0.82) as f32;
            let side_offset = (extent.max(0.01) * 0.65).max(0.05);
            let translation = if reference.contains(&source_submesh) {
                Vec3::new(-side_offset * split.recip().min(4.0), 0.0, 0.0)
            } else {
                Vec3::new(side_offset * (1.0 - split).recip().min(4.0), 0.0, 0.0)
            };
            matrix = Mat4::from_translation(translation) * matrix;
        }
        matrix
    }

    pub fn visible_submeshes(&self) -> HashSet<u32> {
        let mut visible = scene_role_indices(self.scene);
        if visible.is_empty() {
            visible.extend(self.geometry.parts.iter().map(|part| part.submesh));
        }
        let active = self
            .presentation
            .get("active_view")
            .and_then(Value::as_str)
            .unwrap_or_else(|| {
                match self
                    .presentation
                    .get("comparison_mode")
                    .or_else(|| self.scene.get("comparison_mode"))
                    .and_then(Value::as_str)
                {
                    Some("original_only") => "reference",
                    Some("overlay" | "side_by_side") => "comparison",
                    _ => "editable",
                }
            });
        if !scene_role_indices(self.scene).is_empty() && active == "editable" {
            visible = editable_indices(self.scene);
        } else if !scene_role_indices(self.scene).is_empty() && active == "reference" {
            visible = reference_indices(self.scene);
        }
        if let Some(hidden) = self
            .presentation
            .get("visibility")
            .and_then(|value| value.get("hidden_submesh_indices"))
            .and_then(Value::as_array)
        {
            let hidden = hidden
                .iter()
                .filter_map(Value::as_u64)
                .filter_map(|value| u32::try_from(value).ok())
                .collect::<HashSet<_>>();
            visible.retain(|index| !hidden.contains(&self.source_part_index(*index)));
        }
        visible
    }

    pub fn source_part_index(&self, scene_submesh: u32) -> u32 {
        self.scene
            .get("part_identities")
            .and_then(Value::as_array)
            .and_then(|identities| {
                identities.iter().find_map(|identity| {
                    (identity.get("scene_submesh_index").and_then(Value::as_u64)
                        == Some(u64::from(scene_submesh)))
                    .then(|| {
                        identity
                            .get("source_submesh_index")
                            .and_then(Value::as_u64)
                            .and_then(|value| u32::try_from(value).ok())
                            .unwrap_or(scene_submesh)
                    })
                })
            })
            .unwrap_or(scene_submesh)
    }
}

pub fn snapshot_presentation(presentation: &Value) -> Value {
    let mut result = serde_json::Map::new();
    for key in [
        "active_view",
        "comparison_mode",
        "visibility",
        "uv",
        "part_transforms",
        "side_by_side_split_ratio",
    ] {
        if let Some(value) = presentation.get(key) {
            result.insert(key.into(), value.clone());
        }
    }
    Value::Object(result)
}

pub fn prepare_snapshot(
    mesh: &WorkingMesh,
    geometry: &PreviewGeometry,
    scene: &Value,
    presentation: &Value,
    profile: &str,
    revision: u64,
) -> (DrawSnapshot, Option<Vec<u32>>) {
    let view = SceneView {
        scene,
        presentation,
        geometry,
    };
    let mut visible = view.visible_submeshes();
    let comparison = presentation
        .get("comparison_mode")
        .or_else(|| scene.get("comparison_mode"))
        .and_then(Value::as_str);
    if comparison == Some("overlay")
        && scene
            .get("reference_draw")
            .and_then(Value::as_str)
            .unwrap_or("wire")
            == "wire"
    {
        for index in reference_indices(scene) {
            visible.remove(&index);
        }
    }
    let mut snapshot = mesh.draw_snapshot_for_submeshes(&visible);
    if presentation["uv"]["flip_v"].as_bool().unwrap_or(false) {
        for uv in &mut snapshot.uvs {
            uv[1] = 1.0 - uv[1];
        }
    }

    let editable = editable_indices(scene);
    let gpu_scene_transform = profile == "static_replacement"
        && !editable.is_empty()
        && presentation
            .get("part_transforms")
            .and_then(Value::as_object)
            .is_none_or(serde_json::Map::is_empty)
        && presentation
            .get("comparison_mode")
            .and_then(Value::as_str)
            .or_else(|| scene.get("comparison_mode").and_then(Value::as_str))
            != Some("side_by_side");
    let mut scene_roles = gpu_scene_transform.then(|| Vec::with_capacity(snapshot.positions.len()));
    let matrices: HashMap<_, _> = geometry
        .parts
        .iter()
        .map(|part| {
            let model = view.submesh_model_matrix(part.submesh);
            (
                part.submesh,
                (model, Mat3::from_mat4(model).inverse().transpose()),
            )
        })
        .collect();
    let mut snapshot_index = 0usize;
    for (_handle, vertex) in mesh.vertices() {
        let source_submesh = match vertex.provenance {
            Provenance::Source { submesh, .. } => submesh,
            Provenance::Generated { .. } => 0,
        };
        if !visible.contains(&source_submesh) {
            continue;
        }
        let editable_role = gpu_scene_transform && editable.contains(&source_submesh);
        if let Some(roles) = &mut scene_roles {
            roles.push(u32::from(editable_role));
        }
        if !editable_role {
            let (matrix, normal_matrix) = matrices
                .get(&source_submesh)
                .copied()
                .unwrap_or((Mat4::IDENTITY, Mat3::IDENTITY));
            if let Some(position) = snapshot.positions.get_mut(snapshot_index) {
                *position = matrix
                    .transform_point3(Vec3::from_array(*position))
                    .to_array();
            }
            if let Some(normal) = snapshot.normals.get_mut(snapshot_index) {
                *normal = (normal_matrix * Vec3::from_array(*normal))
                    .normalize_or(Vec3::Y)
                    .to_array();
            }
        }
        snapshot_index = snapshot_index.saturating_add(1);
    }
    {
        snapshot.draw_revision = snapshot
            .draw_revision
            .wrapping_mul(1_099_511_628_211)
            .wrapping_add(revision);
        snapshot.fingerprint = format!("{}:scene:{}", snapshot.fingerprint, revision);
    }
    (snapshot, scene_roles)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn placement_matches_python_euler_and_scale_order() {
        let value = json!({"rotation_degrees":[30,0,90],"scale":[2,1,1]});
        let (matrix, _) = placed_scene(&json!({}), &value);
        assert!(
            matrix
                .transform_point3(Vec3::X)
                .abs_diff_eq(Vec3::new(0., 2., 0.), 1.0e-5)
        );
        let expected = Mat4::from_rotation_z(90_f32.to_radians())
            * Mat4::from_rotation_x(30_f32.to_radians())
            * Mat4::from_scale(Vec3::new(2., 1., 1.));
        assert!(matrix.abs_diff_eq(expected, 1.0e-5));
    }

    #[test]
    fn automatic_anchor_remains_fixed_under_manual_rotation() {
        let automatic = Mat4::from_translation(Vec3::new(10., 20., 30.));
        let scene = json!({"automatic_alignment":{"model_matrix":automatic.to_cols_array(),"source_anchor":[1,2,3]}});
        let (matrix, pivot) = placed_scene(
            &scene,
            &json!({"rotation_degrees":[45,30,90],"scale":[2,3,4],"translation":[4,5,6]}),
        );
        assert!(pivot.abs_diff_eq(Vec3::new(15., 27., 39.), 1.0e-5));
        assert!(
            matrix
                .transform_point3(Vec3::new(1., 2., 3.))
                .abs_diff_eq(pivot, 1.0e-5)
        );
    }

    #[test]
    fn picking_uses_intersection_depth_and_respects_empty_visibility() {
        let triangle = |z| {
            [
                Vec3::new(-10., -10., z),
                Vec3::new(10., -10., z),
                Vec3::new(0., 10., z),
            ]
        };
        let geometry = PreviewGeometry {
            parts: vec![
                PartGeometry::new(0, vec![triangle(2.)]),
                PartGeometry::new(1, vec![triangle(4.)]),
            ],
        };
        assert_eq!(
            geometry.pick(Vec3::ZERO, Vec3::Z, 100., &HashSet::new(), |_| {
                Mat4::IDENTITY
            }),
            None
        );
        assert_eq!(
            geometry.pick(Vec3::ZERO, Vec3::Z, 100., &HashSet::from([0, 1]), |_| {
                Mat4::IDENTITY
            }),
            Some(0)
        );
        assert_eq!(
            geometry.pick(Vec3::ZERO, Vec3::Z, 100., &HashSet::from([0, 1]), |part| {
                if part == 0 {
                    Mat4::from_scale(Vec3::splat(3.))
                } else {
                    Mat4::IDENTITY
                }
            }),
            Some(1)
        );
    }

    #[test]
    fn visible_snapshot_and_bounds_use_current_transforms_and_hide_all() {
        let document = cdmw_formats::decode_mesh(
            &cdmw_formats::synthetic::triangle_pam("test.dds"),
            cdmw_formats::MeshFormat::Pam,
        )
        .unwrap();
        let mesh = WorkingMesh::from_document(&document).unwrap();
        let geometry = PreviewGeometry::from_mesh(&mesh);
        let scene = serde_json::json!({});
        let hidden = serde_json::json!({"visibility":{"hidden_submesh_indices":[0]}});
        let (snapshot, _) = prepare_snapshot(&mesh, &geometry, &scene, &hidden, "read_only", 1);
        assert!(snapshot.positions.is_empty());
        let presentation =
            serde_json::json!({"part_transforms":{"0":{"translation":[10,20,30],"scale":[2,3,4]}}});
        let view = SceneView {
            scene: &scene,
            presentation: &presentation,
            geometry: &geometry,
        };
        let matrix = view.submesh_model_matrix(0);
        let (low, high) = geometry.parts[0].bounds(matrix);
        let (snapshot, _) =
            prepare_snapshot(&mesh, &geometry, &scene, &presentation, "read_only", 2);
        for point in snapshot.positions {
            let point = Vec3::from_array(point);
            assert!(point.cmpge(low).all() && point.cmple(high).all());
        }
        // triangle_pam spans [-1,1] in X/Y and lies at Z=-1.
        assert!(low.abs_diff_eq(Vec3::new(8., 17., 26.), 1.0e-5));
        assert!(high.abs_diff_eq(Vec3::new(12., 23., 26.), 1.0e-5));
    }

    #[test]
    fn ray_pick_handles_a_triangle_crossing_the_viewport_and_local_depth_order() {
        // At the pointer, the tilted triangle is nearer, even though its
        // average vertex depth is farther than the flat triangle's depth.
        let tilted = [
            Vec3::new(-1., -1., 2.),
            Vec3::new(20., -1., 30.),
            Vec3::new(-1., 20., 30.),
        ];
        let flat = [
            Vec3::new(-10., -10., 8.),
            Vec3::new(10., -10., 8.),
            Vec3::new(0., 10., 8.),
        ];
        let geometry = PreviewGeometry {
            parts: vec![
                PartGeometry::new(0, vec![tilted]),
                PartGeometry::new(1, vec![flat]),
            ],
        };
        assert_eq!(
            geometry.pick(Vec3::ZERO, Vec3::Z, 100., &HashSet::from([0, 1]), |_| {
                Mat4::IDENTITY
            }),
            Some(0)
        );
        assert_eq!(
            geometry.pick(Vec3::ZERO, Vec3::Z, 1., &HashSet::from([0, 1]), |_| {
                Mat4::IDENTITY
            }),
            None
        );
    }
}
