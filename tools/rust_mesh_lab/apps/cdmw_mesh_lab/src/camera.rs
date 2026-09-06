#![forbid(unsafe_code)]

use cdmw_mesh::{VertexHandle, WorkingMesh};
use cdmw_render_wgpu::integrated_startup_view;
use egui::Rect;
use glam::{Mat4, Quat, Vec2, Vec3};
use std::collections::HashSet;

const FIELD_OF_VIEW_Y: f32 = 45.0_f32.to_radians();
const MIN_DISTANCE: f32 = 1.0e-4;
const FRAME_MARGIN: f32 = 1.12;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StandardView {
    Front,
    Back,
    Left,
    Right,
    Top,
    Bottom,
}

#[derive(Debug, Clone, Copy)]
pub struct ProjectedPoint {
    pub screen: Vec2,
    pub depth: f32,
    pub inside_view: bool,
}

#[derive(Debug, Clone)]
pub struct OrbitCamera {
    target: Vec3,
    yaw: f32,
    pitch: f32,
    roll: f32,
    distance: f32,
    fit_target: Vec3,
    fit_distance: f32,
    scene_radius: f32,
    revision: u64,
}

impl Default for OrbitCamera {
    fn default() -> Self {
        Self {
            target: Vec3::ZERO,
            yaw: std::f32::consts::PI,
            pitch: 0.0,
            roll: 0.0,
            distance: 5.0,
            fit_target: Vec3::ZERO,
            fit_distance: 5.0,
            scene_radius: 1.0,
            revision: 1,
        }
    }
}

impl OrbitCamera {
    #[must_use]
    pub fn revision(&self) -> u64 {
        self.revision
    }

    #[must_use]
    pub fn target(&self) -> Vec3 {
        self.target
    }

    #[must_use]
    pub fn eye(&self) -> Vec3 {
        self.target + self.orientation() * Vec3::Z * self.distance
    }

    #[must_use]
    pub fn forward(&self) -> Vec3 {
        (self.target - self.eye()).normalize_or_zero()
    }

    #[must_use]
    pub fn right(&self) -> Vec3 {
        (self.orientation() * Vec3::X).normalize_or_zero()
    }

    #[must_use]
    pub fn up(&self) -> Vec3 {
        (self.orientation() * Vec3::Y).normalize_or_zero()
    }

    #[must_use]
    pub fn view_projection(&self, rectangle: Rect) -> Mat4 {
        let aspect = (rectangle.width() / rectangle.height().max(1.0)).max(1.0e-4);
        let near = (self.distance * 0.001).max(MIN_DISTANCE);
        let far = (self.distance + self.scene_radius * 8.0).max(near + 1.0);
        Mat4::perspective_rh(FIELD_OF_VIEW_Y, aspect, near, far)
            * Mat4::look_at_rh(self.eye(), self.target, self.up())
    }

    pub fn plane_drag_delta(
        &self,
        normal: Vec3,
        pivot: Vec3,
        start: Vec2,
        end: Vec2,
        rectangle: Rect,
    ) -> Vec3 {
        let intersect = |point| {
            let (origin, direction, _) = self.screen_ray(point, rectangle)?;
            let denominator = direction.dot(normal);
            if denominator.abs() < 1.0e-5 {
                return None;
            }
            let distance = (pivot - origin).dot(normal) / denominator;
            let hit = origin + direction * distance;
            (distance >= 0.0 && hit.is_finite()).then_some(hit)
        };
        intersect(start)
            .zip(intersect(end))
            .map(|(a, b)| b - a)
            .unwrap_or(Vec3::ZERO)
    }

    /// Unproject the pointer through the actual near/far clip planes.
    pub fn screen_ray(&self, point: Vec2, rectangle: Rect) -> Option<(Vec3, Vec3, f32)> {
        if !point.is_finite() || rectangle.width() <= 0.0 || rectangle.height() <= 0.0 {
            return None;
        }
        let x = (point.x - rectangle.left()) / rectangle.width() * 2.0 - 1.0;
        let y = 1.0 - (point.y - rectangle.top()) / rectangle.height() * 2.0;
        // Form the ray in the orthonormal camera basis. Inverting the combined
        // perspective matrix loses precision at high far/near ratios.
        let tangent = (FIELD_OF_VIEW_Y * 0.5).tan();
        let aspect = (rectangle.width() / rectangle.height().max(1.0)).max(1.0e-4);
        let direction =
            (self.forward() + self.right() * x * tangent * aspect + self.up() * y * tangent)
                .normalize();
        let depth = direction.dot(self.forward());
        let near = (self.distance * 0.001).max(MIN_DISTANCE);
        let far = (self.distance + self.scene_radius * 8.0).max(near + 1.0);
        let origin = self.eye() + direction * (near / depth);
        if !origin.is_finite() || !direction.is_finite() || depth <= 0.0 {
            return None;
        }
        Some((origin, direction, (far - near) / depth))
    }

    #[must_use]
    pub fn project(&self, position: Vec3, rectangle: Rect) -> Option<ProjectedPoint> {
        if rectangle.width() <= 0.0 || rectangle.height() <= 0.0 || !position.is_finite() {
            return None;
        }
        let clip = self.view_projection(rectangle) * position.extend(1.0);
        if !clip.is_finite() || clip.w <= 1.0e-6 {
            return None;
        }
        let normalized = clip.truncate() / clip.w;
        let screen = Vec2::new(
            rectangle.left() + (normalized.x + 1.0) * 0.5 * rectangle.width(),
            rectangle.top() + (1.0 - normalized.y) * 0.5 * rectangle.height(),
        );
        Some(ProjectedPoint {
            screen,
            depth: normalized.z,
            inside_view: normalized.x >= -1.0
                && normalized.x <= 1.0
                && normalized.y >= -1.0
                && normalized.y <= 1.0
                && normalized.z >= 0.0
                && normalized.z <= 1.0,
        })
    }

    pub fn frame_all(&mut self, mesh: &WorkingMesh) {
        self.frame_positions(
            mesh.vertices()
                .map(|(_, vertex)| Vec3::from_array(vertex.position)),
        );
    }

    pub fn frame_all_in_viewport(&mut self, mesh: &WorkingMesh, rectangle: Rect) {
        self.frame_positions_in_viewport(
            mesh.vertices()
                .map(|(_, vertex)| Vec3::from_array(vertex.position)),
            rectangle,
        );
    }

    /// Frame a newly opened integrated CDMW mesh from a useful authored side.
    ///
    /// Character meshes and assets already broadside to the canonical Front view
    /// retain that view. Strongly Z-elongated assets (the common authored frame
    /// for swords and similar held items) start from a side three-quarter view so
    /// their length is visible instead of pointing toward the camera.
    pub fn frame_integrated_startup(&mut self, mesh: &WorkingMesh) {
        self.frame_integrated_positions(
            mesh.vertices()
                .map(|(_, vertex)| Vec3::from_array(vertex.position)),
        );
    }

    pub fn frame_integrated_positions(&mut self, positions: impl Iterator<Item = Vec3>) {
        let Some((minimum, maximum)) = finite_bounds(positions) else {
            return;
        };

        let extent = maximum - minimum;
        let startup_view = integrated_startup_view(extent);
        self.yaw = startup_view.yaw;
        self.pitch = startup_view.pitch;
        self.frame_bounds(minimum, maximum);
    }

    pub fn frame_selected(&mut self, mesh: &WorkingMesh) {
        let scope = mesh.selected_vertex_scope();
        if scope.is_empty() {
            self.frame_all(mesh);
            return;
        }
        self.frame_positions(
            scope
                .iter()
                .filter_map(|handle| mesh.vertex(*handle))
                .map(|vertex| Vec3::from_array(vertex.position)),
        );
    }

    pub fn frame_selected_in_viewport(&mut self, mesh: &WorkingMesh, rectangle: Rect) {
        let scope = mesh.selected_vertex_scope();
        if scope.is_empty() {
            self.frame_all_in_viewport(mesh, rectangle);
            return;
        }
        self.frame_positions_in_viewport(
            scope
                .iter()
                .filter_map(|handle| mesh.vertex(*handle))
                .map(|vertex| Vec3::from_array(vertex.position)),
            rectangle,
        );
    }

    pub fn set_standard_view(&mut self, view: StandardView) {
        (self.yaw, self.pitch) = match view {
            StandardView::Front => (std::f32::consts::PI, 0.0),
            StandardView::Back => (0.0, 0.0),
            StandardView::Left => (-std::f32::consts::FRAC_PI_2, 0.0),
            StandardView::Right => (std::f32::consts::FRAC_PI_2, 0.0),
            StandardView::Top => (0.0, -std::f32::consts::FRAC_PI_2 + 1.0e-3),
            StandardView::Bottom => (0.0, std::f32::consts::FRAC_PI_2 - 1.0e-3),
        };
        self.roll = 0.0;
        self.bump_revision();
    }

    /// Point the camera using package-authored semantic vectors.
    ///
    /// `view_direction` is the direction from the eye toward the subject and
    /// `screen_up` fixes roll, which is essential for long assets whose
    /// authored upright axis is not world Y.
    pub fn set_semantic_view(&mut self, view_direction: Vec3, screen_up: Vec3) -> bool {
        let forward = view_direction.normalize_or_zero();
        if forward == Vec3::ZERO {
            return false;
        }
        let desired_up = (screen_up - forward * screen_up.dot(forward)).normalize_or_zero();
        if desired_up == Vec3::ZERO {
            return false;
        }
        let eye_direction = -forward;
        self.yaw = eye_direction
            .x
            .atan2(eye_direction.z)
            .rem_euclid(std::f32::consts::TAU);
        self.pitch = (-eye_direction.y.asin()).clamp(
            -std::f32::consts::FRAC_PI_2 + 0.01,
            std::f32::consts::FRAC_PI_2 - 0.01,
        );
        let base = Quat::from_rotation_y(self.yaw) * Quat::from_rotation_x(self.pitch);
        let base_right = base * Vec3::X;
        let base_up = base * Vec3::Y;
        self.roll = (-desired_up.dot(base_right)).atan2(desired_up.dot(base_up));
        self.bump_revision();
        true
    }

    pub fn frame_explicit_bounds_in_viewport(
        &mut self,
        minimum: Vec3,
        maximum: Vec3,
        rectangle: Rect,
    ) {
        if minimum.is_finite() && maximum.is_finite() {
            self.frame_bounds_in_viewport(minimum.min(maximum), minimum.max(maximum), rectangle);
        }
    }

    pub fn orbit(&mut self, delta: Vec2) {
        if !delta.is_finite() || delta == Vec2::ZERO {
            return;
        }
        self.yaw = (self.yaw - delta.x * 0.008).rem_euclid(std::f32::consts::TAU);
        self.pitch = (self.pitch - delta.y * 0.008).clamp(
            -std::f32::consts::FRAC_PI_2 + 0.01,
            std::f32::consts::FRAC_PI_2 - 0.01,
        );
        self.bump_revision();
    }

    pub fn pan(&mut self, delta: Vec2, rectangle: Rect) {
        if !delta.is_finite() || delta == Vec2::ZERO {
            return;
        }
        let units = self.world_units_per_pixel(rectangle);
        self.target += -self.right() * delta.x * units + self.up() * delta.y * units;
        self.bump_revision();
    }

    pub fn zoom(&mut self, wheel_delta: f32) {
        if !wheel_delta.is_finite() || wheel_delta.abs() <= f32::EPSILON {
            return;
        }
        let minimum = (self.scene_radius * 0.01).max(MIN_DISTANCE);
        let maximum = (self.scene_radius * 10_000.0).max(10.0);
        self.distance = (self.distance * (-wheel_delta * 0.002).exp()).clamp(minimum, maximum);
        self.bump_revision();
    }

    pub fn set_orbit_state_with_roll(
        &mut self,
        yaw: f32,
        pitch: f32,
        roll: f32,
        target: Option<Vec3>,
        relative_zoom: Option<f32>,
    ) {
        if yaw.is_finite() {
            self.yaw = yaw.rem_euclid(std::f32::consts::TAU);
        }
        if pitch.is_finite() {
            self.pitch = pitch.clamp(
                -std::f32::consts::FRAC_PI_2 + 0.01,
                std::f32::consts::FRAC_PI_2 - 0.01,
            );
        }
        if roll.is_finite() {
            self.roll = roll.rem_euclid(std::f32::consts::TAU);
        }
        if let Some(target) = target.filter(|value| value.is_finite()) {
            self.target = target;
        }
        if let Some(relative_zoom) = relative_zoom.filter(|value| value.is_finite()) {
            let minimum = (self.scene_radius * 0.01).max(MIN_DISTANCE);
            let maximum = (self.scene_radius * 10_000.0).max(10.0);
            self.distance =
                (self.fit_distance / relative_zoom.clamp(0.1, 64.0)).clamp(minimum, maximum);
        }
        self.bump_revision();
    }

    #[must_use]
    pub fn orbit_state(&self) -> (f32, f32, Vec3, f32) {
        (self.yaw, self.pitch, self.target, self.distance)
    }

    #[must_use]
    pub fn roll(&self) -> f32 {
        self.roll
    }

    #[must_use]
    pub fn fit_target(&self) -> Vec3 {
        self.fit_target
    }

    #[must_use]
    pub fn relative_zoom(&self) -> f32 {
        (self.fit_distance / self.distance.max(MIN_DISTANCE)).clamp(0.1, 64.0)
    }

    #[must_use]
    pub fn world_units_per_pixel(&self, rectangle: Rect) -> f32 {
        let visible_height = 2.0 * self.distance * (FIELD_OF_VIEW_Y * 0.5).tan();
        visible_height / rectangle.height().max(1.0)
    }

    #[must_use]
    pub fn screen_delta_to_world(&self, delta: Vec2, rectangle: Rect) -> Vec3 {
        let units = self.world_units_per_pixel(rectangle);
        self.right() * delta.x * units - self.up() * delta.y * units
    }

    /// Intersect a screen point with the camera-facing plane through `plane_point`.
    #[must_use]
    pub fn point_on_view_plane(
        &self,
        point: Vec2,
        plane_point: Vec3,
        rectangle: Rect,
    ) -> Option<Vec3> {
        if !point.is_finite() {
            return None;
        }
        let projected = self.project(plane_point, rectangle)?;
        let depth = (plane_point - self.eye()).dot(self.forward());
        let units = 2.0 * depth * (FIELD_OF_VIEW_Y * 0.5).tan() / rectangle.height();
        let delta = point - projected.screen;
        let result = plane_point + self.right() * delta.x * units - self.up() * delta.y * units;
        result.is_finite().then_some(result)
    }

    #[must_use]
    pub fn axis_drag_delta(
        &self,
        axis: Vec3,
        pivot: Vec3,
        screen_delta: Vec2,
        rectangle: Rect,
    ) -> Vec3 {
        let axis = axis.normalize_or_zero();
        if axis == Vec3::ZERO || !screen_delta.is_finite() {
            return Vec3::ZERO;
        }
        let sample_length = self.world_units_per_pixel(rectangle) * 100.0;
        let Some(start) = self.project(pivot, rectangle) else {
            return Vec3::ZERO;
        };
        let Some(end) = self.project(pivot + axis * sample_length, rectangle) else {
            return Vec3::ZERO;
        };
        let projected = end.screen - start.screen;
        if projected.length_squared() <= 1.0e-4 {
            return axis * -screen_delta.y * self.world_units_per_pixel(rectangle);
        }
        let amount = screen_delta.dot(projected.normalize()) * sample_length / projected.length();
        axis * amount
    }

    #[must_use]
    pub fn selected_center(mesh: &WorkingMesh) -> Option<Vec3> {
        let scope = mesh.selected_vertex_scope();
        center_of_handles(mesh, &scope)
    }

    fn orientation(&self) -> Quat {
        Quat::from_rotation_y(self.yaw)
            * Quat::from_rotation_x(self.pitch)
            * Quat::from_rotation_z(self.roll)
    }

    fn frame_positions(&mut self, positions: impl Iterator<Item = Vec3>) {
        let Some((minimum, maximum)) = finite_bounds(positions) else {
            return;
        };
        self.frame_bounds(minimum, maximum);
    }

    pub(super) fn frame_positions_in_viewport(
        &mut self,
        positions: impl Iterator<Item = Vec3>,
        rectangle: Rect,
    ) {
        let Some((minimum, maximum)) = finite_bounds(positions) else {
            return;
        };
        self.frame_bounds_in_viewport(minimum, maximum, rectangle);
    }

    fn frame_bounds(&mut self, minimum: Vec3, maximum: Vec3) {
        debug_assert!(minimum.is_finite() && maximum.is_finite());
        self.target = (minimum + maximum) * 0.5;
        self.fit_target = self.target;
        self.scene_radius = ((maximum - minimum) * 0.5).length().max(1.0e-4);
        self.distance =
            (self.scene_radius / (FIELD_OF_VIEW_Y * 0.5).tan() * 1.25).max(self.scene_radius * 1.5);
        self.fit_distance = self.distance;
        self.bump_revision();
    }

    fn frame_bounds_in_viewport(&mut self, minimum: Vec3, maximum: Vec3, rectangle: Rect) {
        debug_assert!(minimum.is_finite() && maximum.is_finite());
        if !rectangle.width().is_finite()
            || !rectangle.height().is_finite()
            || rectangle.width() <= 0.0
            || rectangle.height() <= 0.0
        {
            self.frame_bounds(minimum, maximum);
            return;
        }

        self.target = (minimum + maximum) * 0.5;
        self.fit_target = self.target;
        let half_extent = (maximum - minimum) * 0.5;
        self.scene_radius = half_extent.length().max(1.0e-4);
        let legacy_distance =
            (self.scene_radius / (FIELD_OF_VIEW_Y * 0.5).tan() * 1.25).max(self.scene_radius * 1.5);

        let aspect = (rectangle.width() / rectangle.height()).max(1.0e-4);
        let vertical_tangent = (FIELD_OF_VIEW_Y * 0.5).tan();
        let horizontal_tangent = vertical_tangent * aspect;
        let projected_half_width = half_extent.dot(self.right().abs());
        let projected_half_height = half_extent.dot(self.up().abs());
        let projected_half_depth = half_extent.dot(self.forward().abs());
        let horizontal_fit = projected_half_width / horizontal_tangent;
        let vertical_fit = projected_half_height / vertical_tangent;

        // Preserve established character framing when height is the limiting
        // dimension. Broadside weapons instead use the available horizontal
        // field of view, while remaining outside the complete orbiting bounds.
        self.distance = if horizontal_fit > vertical_fit {
            (projected_half_depth + horizontal_fit * FRAME_MARGIN)
                .max(self.scene_radius * 1.05)
                .max(MIN_DISTANCE)
        } else {
            legacy_distance
        };
        self.fit_distance = self.distance;
        self.bump_revision();
    }

    fn bump_revision(&mut self) {
        self.revision = self.revision.saturating_add(1);
    }
}

fn finite_bounds(positions: impl Iterator<Item = Vec3>) -> Option<(Vec3, Vec3)> {
    let mut minimum = Vec3::splat(f32::INFINITY);
    let mut maximum = Vec3::splat(f32::NEG_INFINITY);
    let mut found = false;
    for position in positions.filter(|position| position.is_finite()) {
        minimum = minimum.min(position);
        maximum = maximum.max(position);
        found = true;
    }
    found.then_some((minimum, maximum))
}

fn center_of_handles(mesh: &WorkingMesh, handles: &HashSet<VertexHandle>) -> Option<Vec3> {
    if handles.is_empty() {
        return None;
    }
    let mut total = Vec3::ZERO;
    let mut count = 0usize;
    for (handle, vertex) in mesh.vertices() {
        if handles.contains(&handle) {
            total += Vec3::from_array(vertex.position);
            count = count.saturating_add(1);
        }
    }
    (count > 0).then_some(total / count as f32)
}

#[cfg(test)]
mod tests {
    use super::*;
    use cdmw_formats::{MeshDocument, MeshFormat, MeshLod, SourceRange, Submesh};

    #[test]
    fn pointer_ray_and_oblique_planar_drag_track_the_screen() {
        let mut camera = OrbitCamera::default();
        camera.set_orbit_state_with_roll(0.6, -0.4, 0.3, None, None);
        let viewport = rectangle(800., 600.);
        let pivot = camera.target();
        let start = camera.project(pivot, viewport).unwrap().screen;
        let end = start + Vec2::new(21., -13.);
        let (origin, direction, maximum) = camera.screen_ray(start, viewport).unwrap();
        let distance = (pivot - origin).dot(direction);
        assert!(distance >= 0. && distance <= maximum);
        assert!(
            (origin + direction * distance).abs_diff_eq(pivot, 1.0e-4),
            "ray closest point {:?}; target {:?}",
            origin + direction * distance,
            pivot
        );
        let movement = camera.plane_drag_delta(Vec3::Z, pivot, start, end, viewport);
        assert!(movement.z.abs() < 1.0e-5);
        let projected = camera.project(pivot + movement, viewport).unwrap();
        assert!(projected.screen.abs_diff_eq(end, 0.01));
    }

    fn rectangle(width: f32, height: f32) -> Rect {
        Rect::from_min_size(egui::Pos2::ZERO, egui::vec2(width, height))
    }

    fn mesh_with_positions(positions: Vec<[f32; 3]>) -> WorkingMesh {
        assert_eq!(positions.len(), 3);
        let document = MeshDocument {
            format: MeshFormat::Pam,
            source_sha256: String::new(),
            parser: "camera-test".to_owned(),
            lod_count_reported: 1,
            lods: vec![MeshLod {
                level: 0,
                submeshes: vec![Submesh {
                    name: "camera-test".to_owned(),
                    material: "camera-test".to_owned(),
                    normals: vec![[0.0, 0.0, 1.0]; positions.len()],
                    uvs: vec![[0.0, 0.0]; positions.len()],
                    source_vertex_indices: vec![0, 1, 2],
                    positions,
                    indices: vec![0, 1, 2],
                    source_range: SourceRange {
                        offset: 0,
                        length: 0,
                    },
                    vertex_stride: 0,
                    layout: "camera-test".to_owned(),
                }],
            }],
            warnings: Vec::new(),
            structural_fingerprint: String::new(),
        };
        WorkingMesh::from_document(&document)
            .unwrap_or_else(|error| panic!("camera fixture failed: {error}"))
    }

    #[test]
    fn perspective_projection_does_not_stretch_after_resize() {
        let camera = OrbitCamera::default();
        for viewport in [rectangle(1_200.0, 400.0), rectangle(400.0, 1_200.0)] {
            let left = camera.project(Vec3::new(-1.0, 0.0, 0.0), viewport).unwrap();
            let right = camera.project(Vec3::new(1.0, 0.0, 0.0), viewport).unwrap();
            let top = camera.project(Vec3::new(0.0, 1.0, 0.0), viewport).unwrap();
            let bottom = camera.project(Vec3::new(0.0, -1.0, 0.0), viewport).unwrap();
            let horizontal = (right.screen.x - left.screen.x).abs();
            let vertical = (bottom.screen.y - top.screen.y).abs();
            assert!((horizontal - vertical).abs() < 0.01);
        }
    }

    #[test]
    fn camera_changes_are_revisioned() {
        let mut camera = OrbitCamera::default();
        let initial = camera.revision();
        camera.orbit(Vec2::new(12.0, -4.0));
        assert!(camera.revision() > initial);
        let after_orbit = camera.revision();
        camera.zoom(120.0);
        assert!(camera.revision() > after_orbit);
    }

    #[test]
    fn front_and_back_presets_use_the_named_mesh_sides() {
        let mut camera = OrbitCamera::default();
        assert!(camera.eye().z < camera.target().z);
        assert!(camera.forward().z > 0.999);

        camera.set_standard_view(StandardView::Front);
        assert!(camera.eye().z < camera.target().z);
        assert!(camera.forward().z > 0.999);

        camera.set_standard_view(StandardView::Back);
        assert!(camera.eye().z > camera.target().z);
        assert!(camera.forward().z < -0.999);
    }

    #[test]
    fn semantic_view_preserves_authored_upright_and_fits_explicit_bounds() {
        let mut camera = OrbitCamera::default();
        let minimum = Vec3::new(-0.1, -0.25, -2.0);
        let maximum = Vec3::new(0.1, 0.25, 2.0);
        let viewport = rectangle(900.0, 600.0);

        assert!(camera.set_semantic_view(Vec3::X, Vec3::Z));
        camera.frame_explicit_bounds_in_viewport(minimum, maximum, viewport);

        assert!(camera.forward().dot(Vec3::X) > 0.999);
        assert!(camera.up().dot(Vec3::Z) > 0.999);
        for x in [minimum.x, maximum.x] {
            for y in [minimum.y, maximum.y] {
                for z in [minimum.z, maximum.z] {
                    let projected = camera
                        .project(Vec3::new(x, y, z), viewport)
                        .unwrap_or_else(|| panic!("semantic-view corner did not project"));
                    assert!(projected.inside_view);
                }
            }
        }
    }

    #[test]
    fn integrated_startup_turns_z_elongated_assets_broadside() {
        let mesh = mesh_with_positions(vec![
            [-0.20, -0.04, -1.0],
            [0.20, -0.04, 1.0],
            [0.0, 0.04, 1.0],
        ]);
        let mut camera = OrbitCamera::default();

        camera.frame_integrated_startup(&mesh);

        assert!(camera.forward().x.abs() > 0.75);
        assert!(camera.forward().y.abs() > 0.40);
        assert!(camera.forward().z.abs() < 1.0e-5);
        let viewport = rectangle(800.0, 600.0);
        let pommel = camera
            .project(Vec3::new(0.0, 0.0, -1.0), viewport)
            .unwrap_or_else(|| panic!("pommel did not project"));
        let tip = camera
            .project(Vec3::new(0.0, 0.0, 1.0), viewport)
            .unwrap_or_else(|| panic!("tip did not project"));
        assert!(pommel.inside_view && tip.inside_view);
        assert!((tip.screen.x - pommel.screen.x).abs() > viewport.width() * 0.45);
        assert!((tip.screen.y - pommel.screen.y).abs() < 0.01);
    }

    #[test]
    fn integrated_startup_keeps_non_depth_elongated_assets_on_front() {
        let character = mesh_with_positions(vec![
            [-0.5, -1.0, -0.25],
            [0.5, 1.0, 0.25],
            [0.0, 1.0, -0.25],
        ]);
        let already_broadside =
            mesh_with_positions(vec![[-1.0, -0.1, -0.2], [1.0, 0.1, 0.2], [1.0, -0.1, -0.2]]);
        for mesh in [&character, &already_broadside] {
            let mut camera = OrbitCamera::default();
            camera.set_standard_view(StandardView::Back);
            camera.frame_integrated_startup(mesh);
            assert!(camera.eye().z < camera.target().z);
            assert!(camera.forward().z > 0.999);
        }
    }

    #[test]
    fn wide_viewport_fit_uses_horizontal_space_without_clipping_a_broadside_weapon() {
        let positions = vec![[-0.20, -0.04, -1.0], [0.20, -0.04, 1.0], [0.0, 0.04, 1.0]];
        let mesh = mesh_with_positions(positions.clone());
        let viewport = rectangle(1_600.0, 600.0);
        let mut camera = OrbitCamera::default();
        camera.frame_integrated_startup(&mesh);

        camera.frame_all_in_viewport(&mesh, viewport);

        let projected = positions
            .into_iter()
            .map(|position| {
                camera
                    .project(Vec3::from_array(position), viewport)
                    .unwrap_or_else(|| panic!("weapon point did not project"))
            })
            .collect::<Vec<_>>();
        assert!(projected.iter().all(|point| point.inside_view));
        let minimum_x = projected
            .iter()
            .map(|point| point.screen.x)
            .fold(f32::INFINITY, f32::min);
        let maximum_x = projected
            .iter()
            .map(|point| point.screen.x)
            .fold(f32::NEG_INFINITY, f32::max);
        assert!(maximum_x - minimum_x > viewport.width() * 0.75);
    }

    #[test]
    fn wide_viewport_fit_preserves_height_limited_character_framing() {
        let character = mesh_with_positions(vec![
            [-0.5, -1.0, -0.25],
            [0.5, 1.0, 0.25],
            [0.0, 1.0, -0.25],
        ]);
        let mut camera = OrbitCamera::default();
        camera.frame_all(&character);
        let established_distance = camera.distance;

        camera.frame_all_in_viewport(&character, rectangle(1_600.0, 600.0));

        assert!((camera.distance - established_distance).abs() < 1.0e-6);
    }

    #[test]
    fn manual_frame_all_preserves_the_users_orientation() {
        let mesh = mesh_with_positions(vec![
            [-0.20, -0.04, -1.0],
            [0.20, -0.04, 1.0],
            [0.0, 0.04, 1.0],
        ]);
        let mut camera = OrbitCamera::default();
        camera.set_standard_view(StandardView::Left);
        let forward = camera.forward();

        camera.frame_all(&mesh);

        assert!(camera.forward().dot(forward) > 0.999_999);
    }

    #[test]
    fn screen_drag_maps_to_camera_plane() {
        let camera = OrbitCamera::default();
        let viewport = rectangle(800.0, 600.0);
        let delta = camera.screen_delta_to_world(Vec2::new(20.0, 0.0), viewport);
        assert!(delta.dot(camera.right()) > 0.0);
        assert!(delta.dot(camera.up()).abs() < 1.0e-6);
        assert!(delta.dot(camera.forward()).abs() < 1.0e-6);
    }

    #[test]
    fn brush_center_projects_back_to_the_pointer_at_the_eligible_depth() {
        let mut camera = OrbitCamera::default();
        for view in [StandardView::Front, StandardView::Right, StandardView::Top] {
            camera.set_standard_view(view);
            for viewport in [rectangle(1_200.0, 400.0), rectangle(400.0, 1_200.0)] {
                let anchor = camera.target() + camera.forward() * 0.4 + camera.right() * 0.2;
                let projected = camera.project(anchor, viewport).unwrap();
                let pointer = projected.screen + Vec2::new(35.0, -21.0);
                let center = camera
                    .point_on_view_plane(pointer, anchor, viewport)
                    .unwrap();
                let result = camera.project(center, viewport).unwrap();
                assert!(result.screen.distance(pointer) < 0.005);
                assert!((center - anchor).dot(camera.forward()).abs() < 1.0e-5);
                assert!((result.depth - projected.depth).abs() < 1.0e-5);
            }
        }
        let viewport = rectangle(800.0, 600.0);
        assert!(
            camera
                .point_on_view_plane(Vec2::splat(f32::NAN), Vec3::ZERO, viewport)
                .is_none()
        );
        assert!(
            camera
                .point_on_view_plane(Vec2::ZERO, camera.eye() - camera.forward(), viewport)
                .is_none()
        );
        assert!(
            camera
                .point_on_view_plane(Vec2::ZERO, Vec3::ZERO, rectangle(0.0, 0.0))
                .is_none()
        );
    }
}
