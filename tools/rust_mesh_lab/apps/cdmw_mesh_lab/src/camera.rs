#![forbid(unsafe_code)]

use cdmw_mesh::{VertexHandle, WorkingMesh};
use egui::Rect;
use glam::{Mat4, Quat, Vec2, Vec3};
use std::collections::HashSet;

const FIELD_OF_VIEW_Y: f32 = 45.0_f32.to_radians();
const MIN_DISTANCE: f32 = 1.0e-4;

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
    distance: f32,
    scene_radius: f32,
    revision: u64,
}

impl Default for OrbitCamera {
    fn default() -> Self {
        Self {
            target: Vec3::ZERO,
            yaw: 0.0,
            pitch: 0.0,
            distance: 5.0,
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
        self.forward().cross(Vec3::Y).normalize_or_zero()
    }

    #[must_use]
    pub fn up(&self) -> Vec3 {
        self.right().cross(self.forward()).normalize_or_zero()
    }

    #[must_use]
    pub fn view_projection(&self, rectangle: Rect) -> Mat4 {
        let aspect = (rectangle.width() / rectangle.height().max(1.0)).max(1.0e-4);
        let near = (self.distance * 0.001).max(MIN_DISTANCE);
        let far = (self.distance + self.scene_radius * 8.0).max(near + 1.0);
        Mat4::perspective_rh(FIELD_OF_VIEW_Y, aspect, near, far)
            * Mat4::look_at_rh(self.eye(), self.target, self.up())
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

    pub fn set_standard_view(&mut self, view: StandardView) {
        (self.yaw, self.pitch) = match view {
            StandardView::Front => (0.0, 0.0),
            StandardView::Back => (std::f32::consts::PI, 0.0),
            StandardView::Left => (-std::f32::consts::FRAC_PI_2, 0.0),
            StandardView::Right => (std::f32::consts::FRAC_PI_2, 0.0),
            StandardView::Top => (0.0, -std::f32::consts::FRAC_PI_2 + 1.0e-3),
            StandardView::Bottom => (0.0, std::f32::consts::FRAC_PI_2 - 1.0e-3),
        };
        self.bump_revision();
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
        Quat::from_rotation_y(self.yaw) * Quat::from_rotation_x(self.pitch)
    }

    fn frame_positions(&mut self, positions: impl Iterator<Item = Vec3>) {
        let mut minimum = Vec3::splat(f32::INFINITY);
        let mut maximum = Vec3::splat(f32::NEG_INFINITY);
        let mut found = false;
        for position in positions.filter(|position| position.is_finite()) {
            minimum = minimum.min(position);
            maximum = maximum.max(position);
            found = true;
        }
        if !found {
            return;
        }
        self.target = (minimum + maximum) * 0.5;
        self.scene_radius = ((maximum - minimum) * 0.5).length().max(1.0e-4);
        self.distance =
            (self.scene_radius / (FIELD_OF_VIEW_Y * 0.5).tan() * 1.25).max(self.scene_radius * 1.5);
        self.bump_revision();
    }

    fn bump_revision(&mut self) {
        self.revision = self.revision.saturating_add(1);
    }
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

    fn rectangle(width: f32, height: f32) -> Rect {
        Rect::from_min_size(egui::Pos2::ZERO, egui::vec2(width, height))
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
    fn screen_drag_maps_to_camera_plane() {
        let camera = OrbitCamera::default();
        let viewport = rectangle(800.0, 600.0);
        let delta = camera.screen_delta_to_world(Vec2::new(20.0, 0.0), viewport);
        assert!(delta.x > 0.0);
        assert!(delta.y.abs() < 1.0e-6);
        assert!(delta.z.abs() < 1.0e-6);
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
