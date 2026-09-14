//! Cached triangle picking shared by scalp placement and visible hair selection.
use glam::Vec3;

#[derive(Clone)]
struct Node {
    min: Vec3,
    max: Vec3,
    start: usize,
    end: usize,
    children: Option<(usize, usize)>,
}
#[derive(Clone, Default)]
pub struct SurfaceIndex {
    nodes: Vec<Node>,
    faces: Vec<usize>,
}
#[derive(Debug, Clone, Copy)]
pub struct SurfaceHit {
    pub triangle: usize,
    pub distance: f32,
    pub barycentric: [f32; 3],
}

impl SurfaceIndex {
    pub fn new(positions: &[[f32; 3]], indices: &[u32]) -> Self {
        let mut index = Self {
            nodes: vec![],
            faces: (0..indices.len() / 3).collect(),
        };
        if !index.faces.is_empty() {
            index.build(positions, indices, 0, index.faces.len());
        }
        index
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
