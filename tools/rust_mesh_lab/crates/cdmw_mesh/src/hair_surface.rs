//! Cached triangle picking shared by scalp placement and visible hair selection.
use glam::Vec3;

#[derive(Debug, Clone)]
struct Node {
    min: Vec3,
    max: Vec3,
    start: usize,
    end: usize,
    children: Option<(usize, usize)>,
}
#[derive(Debug, Clone, Default)]
pub struct SurfaceIndex {
    nodes: Vec<Node>,
    faces: Vec<usize>,
    normals: Vec<Vec3>,
    components: Vec<usize>,
}
#[derive(Debug, Clone, Copy)]
pub struct SurfaceHit {
    pub triangle: usize,
    pub distance: f32,
    pub barycentric: [f32; 3],
}

impl SurfaceIndex {
    /// Closest point with BVH pruning, reused by the transient contact solver.
    pub fn nearest(
        &self,
        positions: &[[f32; 3]],
        indices: &[u32],
        point: Vec3,
    ) -> Option<(Vec3, Vec3)> {
        if self.nodes.is_empty() {
            return None;
        }
        // Median splits bound the traversal depth by the number of bits in
        // usize. Contact queries run thousands of times per solver step.
        let mut stack = [0_usize; usize::BITS as usize + 1];
        let mut pending = 1;
        let mut best = f32::INFINITY;
        let mut result = None;
        while pending > 0 {
            pending -= 1;
            let index = stack[pending];
            let node = &self.nodes[index];
            if point.distance_squared(point.clamp(node.min, node.max)) > best {
                continue;
            }
            if let Some((a, b)) = node.children {
                let distance = |i: usize| {
                    point.distance_squared(point.clamp(self.nodes[i].min, self.nodes[i].max))
                };
                let children = if distance(a) < distance(b) {
                    [b, a]
                } else {
                    [a, b]
                };
                stack[pending..pending + 2].copy_from_slice(&children);
                pending += 2;
                continue;
            }
            for &face in &self.faces[node.start..node.end] {
                let [a, b, c] =
                    [0, 1, 2].map(|i| Vec3::from(positions[indices[face * 3 + i] as usize]));
                let bary = super::closest_barycentric(point, a, b, c);
                let closest = a * bary[0] + b * bary[1] + c * bary[2];
                let distance = point.distance_squared(closest);
                if distance < best {
                    let normal = self.normals[face];
                    if normal == Vec3::ZERO {
                        continue;
                    }
                    best = distance;
                    result = Some((closest, normal));
                }
            }
        }
        result
    }

    pub fn contact(
        &self,
        positions: &[[f32; 3]],
        indices: &[u32],
        point: Vec3,
        radius: f32,
    ) -> Vec3 {
        self.contact_with_reach(positions, indices, point, radius, radius)
    }

    /// Include the card's full width when checking an open fitting surface.
    /// Clearance and search reach differ for vertices offset from a guide.
    pub fn contact_with_reach(
        &self,
        positions: &[[f32; 3]],
        indices: &[u32],
        point: Vec3,
        radius: f32,
        reach: f32,
    ) -> Vec3 {
        let Some(bounds) = self.nodes.first() else {
            return point;
        };
        if point.distance_squared(point.clamp(bounds.min, bounds.max)) > reach.max(radius).powi(2) {
            return point;
        }
        let mut corrected = point;
        // A correction beside an ear or a joined face seam can make an adjacent
        // triangle the nearest surface. Resolve that new contact too, otherwise
        // an apparently clear guide can still carry its card into the crease.
        for _ in 0..4 {
            let Some((surface, normal)) = self.nearest(positions, indices, corrected) else {
                break;
            };
            let offset = corrected - surface;
            let signed = offset.dot(normal);
            // Keep open boundaries finite rather than extending an infinite wall.
            let tangent = offset - normal * signed;
            if signed >= radius - 1e-7 || tangent.length_squared() > radius.max(0.0001).powi(2) {
                break;
            }
            corrected += normal * (radius - signed);
        }
        corrected
    }

    pub fn new(positions: &[[f32; 3]], indices: &[u32]) -> Self {
        let mut index = Self {
            nodes: vec![],
            faces: (0..indices.len() / 3).collect(),
            normals: vec![],
            components: vec![],
        };
        if !index.faces.is_empty() {
            index.build(positions, indices, 0, index.faces.len());
        }
        index.components = Self::connected_components(positions, indices);
        index.cache_normals(positions, indices);
        index
    }

    fn cache_normals(&mut self, positions: &[[f32; 3]], indices: &[u32]) {
        let center = self
            .nodes
            .first()
            .map_or(Vec3::ZERO, |n| (n.min + n.max) * 0.5);
        let mut volumes = vec![0.0_f64; positions.len()];
        self.normals.clear();
        for (i, face) in indices.chunks_exact(3).enumerate() {
            let [a, b, c] = [0, 1, 2].map(|i| Vec3::from(positions[face[i] as usize]));
            let cross = (b - a).cross(c - a);
            volumes[self.components[i]] += (a - center).dot(cross) as f64;
            self.normals
                .push(cross.try_normalize().unwrap_or(Vec3::ZERO));
        }
        // Head and body-crown PAC components can have opposite winding. Orient
        // connected surfaces consistently without reversing concave ear faces.
        for (i, normal) in self.normals.iter_mut().enumerate() {
            if volumes[self.components[i]] < 0.0 {
                *normal = -*normal;
            }
        }
    }

    fn connected_components(positions: &[[f32; 3]], indices: &[u32]) -> Vec<usize> {
        fn root(parents: &mut [usize], mut value: usize) -> usize {
            while parents[value] != value {
                parents[value] = parents[parents[value]];
                value = parents[value];
            }
            value
        }
        let mut parents: Vec<_> = (0..positions.len()).collect();
        let mut shared = std::collections::HashMap::new();
        for (i, position) in positions.iter().enumerate() {
            let key = position.map(|v| if v == 0.0 { 0 } else { v.to_bits() });
            let original = *shared.entry(key).or_insert(i);
            parents[i] = original;
        }
        for face in indices.chunks_exact(3) {
            let [a, b, c] = [0, 1, 2].map(|i| root(&mut parents, face[i] as usize));
            parents[b] = a;
            parents[c] = a;
        }
        indices
            .chunks_exact(3)
            .map(|f| root(&mut parents, f[0] as usize))
            .collect()
    }
    fn bounds(
        &self,
        positions: &[[f32; 3]],
        indices: &[u32],
        start: usize,
        end: usize,
    ) -> (Vec3, Vec3) {
        let mut min = Vec3::splat(f32::INFINITY);
        let mut max = Vec3::splat(f32::NEG_INFINITY);
        for &face in &self.faces[start..end] {
            for &v in &indices[face * 3..face * 3 + 3] {
                let p = Vec3::from(positions[v as usize]);
                min = min.min(p);
                max = max.max(p);
            }
        }
        (min, max)
    }
    fn build(
        &mut self,
        positions: &[[f32; 3]],
        indices: &[u32],
        start: usize,
        end: usize,
    ) -> usize {
        let (min, max) = self.bounds(positions, indices, start, end);
        let node = self.nodes.len();
        self.nodes.push(Node {
            min,
            max,
            start,
            end,
            children: None,
        });
        if end - start > 8 {
            let extent = max - min;
            let axis = if extent.x >= extent.y && extent.x >= extent.z {
                0
            } else if extent.y >= extent.z {
                1
            } else {
                2
            };
            let mid = (start + end) / 2;
            let center = |face: usize| {
                indices[face * 3..face * 3 + 3]
                    .iter()
                    .map(|i| positions[*i as usize][axis])
                    .sum::<f32>()
            };
            self.faces[start..end]
                .select_nth_unstable_by(mid - start, |a, b| center(*a).total_cmp(&center(*b)));
            let a = self.build(positions, indices, start, mid);
            let b = self.build(positions, indices, mid, end);
            self.nodes[node].children = Some((a, b));
        }
        node
    }
    pub fn refit(&mut self, positions: &[[f32; 3]], indices: &[u32]) {
        for i in (0..self.nodes.len()).rev() {
            let n = &self.nodes[i];
            let (min, max) = if let Some((a, b)) = n.children {
                (
                    self.nodes[a].min.min(self.nodes[b].min),
                    self.nodes[a].max.max(self.nodes[b].max),
                )
            } else {
                self.bounds(positions, indices, n.start, n.end)
            };
            self.nodes[i].min = min;
            self.nodes[i].max = max;
        }
        self.cache_normals(positions, indices);
    }
    pub fn hit(
        &self,
        positions: &[[f32; 3]],
        indices: &[u32],
        origin: Vec3,
        direction: Vec3,
    ) -> Option<SurfaceHit> {
        if self.nodes.is_empty() {
            return None;
        }
        let mut stack = vec![0];
        let mut closest = None;
        let mut limit = f32::INFINITY;
        while let Some(index) = stack.pop() {
            let node = &self.nodes[index];
            let mut lo = 0.0_f32;
            let mut hi = limit;
            for axis in 0..3 {
                if direction[axis].abs() < 1e-9 {
                    if origin[axis] < node.min[axis] || origin[axis] > node.max[axis] {
                        hi = -1.0;
                    }
                } else {
                    let a = (node.min[axis] - origin[axis]) / direction[axis];
                    let b = (node.max[axis] - origin[axis]) / direction[axis];
                    lo = lo.max(a.min(b));
                    hi = hi.min(a.max(b));
                }
            }
            if hi < lo {
                continue;
            }
            if let Some((a, b)) = node.children {
                stack.push(a);
                stack.push(b);
                continue;
            }
            for &face in &self.faces[node.start..node.end] {
                let a = Vec3::from(positions[indices[face * 3] as usize]);
                let b = Vec3::from(positions[indices[face * 3 + 1] as usize]);
                let c = Vec3::from(positions[indices[face * 3 + 2] as usize]);
                let e = b - a;
                let f = c - a;
                let cross = direction.cross(f);
                let det = e.dot(cross);
                if det.abs() < 1e-10 {
                    continue;
                }
                let inv = 1.0 / det;
                let offset = origin - a;
                let u = offset.dot(cross) * inv;
                if !(0.0..=1.0).contains(&u) {
                    continue;
                }
                let q = offset.cross(e);
                let v = direction.dot(q) * inv;
                if v < 0.0 || u + v > 1.0 {
                    continue;
                }
                let distance = f.dot(q) * inv;
                if distance > 1e-7 && distance < limit {
                    limit = distance;
                    closest = Some(SurfaceHit {
                        triangle: face,
                        distance,
                        barycentric: [1.0 - u - v, u, v],
                    });
                }
            }
        }
        closest
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hair_concave_contacts_keep_surface_winding() {
        // An L-shaped closed prism: the inside wall faces away from the solid
        // despite pointing toward the overall bounding-box center.
        let polygon = [
            [0.0, 0.0],
            [2.0, 0.0],
            [2.0, 0.8],
            [0.8, 0.8],
            [0.8, 2.0],
            [0.0, 2.0],
        ];
        let positions: Vec<_> = [0.0, 1.0]
            .into_iter()
            .flat_map(|z| polygon.map(|[x, y]| [x, y, z]))
            .collect();
        let mut indices = vec![];
        for i in 1..5_u32 {
            indices.extend([0, i + 1, i, 6, i + 6, i + 7]);
        }
        for i in 0..6_u32 {
            let j = (i + 1) % 6;
            indices.extend([i, j, j + 6, i, j + 6, i + 6]);
        }
        for reverse in [false, true] {
            if reverse {
                for face in indices.chunks_exact_mut(3) {
                    face.swap(1, 2);
                }
            }
            let surface = SurfaceIndex::new(&positions, &indices);
            let outside = Vec3::new(0.81, 1.3, 0.5);
            assert_eq!(surface.contact(&positions, &indices, outside, 0.0), outside);
            let inside = Vec3::new(0.79, 1.3, 0.5);
            let corrected = surface.contact(&positions, &indices, inside, 0.002);
            assert!(corrected.distance(Vec3::new(0.802, 1.3, 0.5)) < 1e-5);
        }
        let mut combined = positions.clone();
        combined.extend(positions.iter().map(|p| [p[0] + 3.0, p[1], p[2]]));
        let mut mixed = indices.clone();
        for face in indices.chunks_exact(3) {
            mixed.extend([face[0] + 12, face[2] + 12, face[1] + 12]);
        }
        let surface = SurfaceIndex::new(&combined, &mixed);
        for x in [0.81, 3.81] {
            let outside = Vec3::new(x, 1.3, 0.5);
            assert_eq!(surface.contact(&combined, &mixed, outside, 0.0), outside);
            let inside = outside - Vec3::X * 0.02;
            assert!(
                surface
                    .contact(&combined, &mixed, inside, 0.002)
                    .distance(outside - Vec3::X * 0.008)
                    < 1e-5
            );
        }
    }
}
