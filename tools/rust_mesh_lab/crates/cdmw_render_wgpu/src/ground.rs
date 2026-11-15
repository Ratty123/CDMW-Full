//! Studio floor beneath the previewed model: a ground plane at the lowest
//! visible point with an anti-aliased grid, a red X axis line and a blue Z axis
//! line, and the key-light shadow. CDMW Next's floor is the reference for size
//! and spacing (half-size four bounds radii, a cell of a quarter radius).

use bytemuck::{Pod, Zeroable};
use glam::Vec3;
use wgpu::util::DeviceExt;

/// Fragment and vertex entry points appended to the main shader module, so the
/// floor shares the camera uniform, shadow map and presentation helpers.
pub(crate) const WGSL: &str = r#"
struct GroundOut {
    @builtin(position) position: vec4<f32>,
    @location(0) world: vec3<f32>,
    @location(1) params: vec4<f32>,
};

@vertex
fn vs_ground(@location(0) position: vec3<f32>, @location(1) params: vec4<f32>) -> GroundOut {
    var out: GroundOut;
    out.position = camera.view_projection * vec4<f32>(position, 1.0);
    out.world = position;
    out.params = params;
    return out;
}

fn ground_line(distance: f32, pixel: f32) -> f32 {
    return 1.0 - clamp(abs(distance) / max(pixel, 0.000001) - 0.5, 0.0, 1.0);
}

@fragment
fn fs_ground(input: GroundOut) -> @location(0) vec4<f32> {
    var colour = vec3<f32>(0.29, 0.31, 0.36);
    if input.params.z > 0.5 {
        let cell = max(input.params.x, 0.0001);
        let coord = input.world.xz / cell;
        let deriv = max(fwidth(coord), vec2<f32>(0.0001));
        let distance = abs(fract(coord - vec2<f32>(0.5)) - vec2<f32>(0.5)) / deriv;
        let grid = 1.0 - clamp(min(distance.x, distance.y), 0.0, 1.0);
        // Fade the grid out where its cells shrink below a few pixels.
        let fade = clamp(1.6 - max(deriv.x, deriv.y) * 3.0, 0.0, 1.0);
        colour = mix(colour, colour * 1.5, grid * 0.6 * fade);
        let x_axis = ground_line(input.world.z, fwidth(input.world.z) * 1.5);
        let z_axis = ground_line(input.world.x, fwidth(input.world.x) * 1.5);
        colour = mix(colour, vec3<f32>(0.62, 0.20, 0.17), x_axis * 0.85);
        colour = mix(colour, vec3<f32>(0.18, 0.34, 0.62), z_axis * 0.85);
    }
    colour *= mix(0.55, 1.0, shadow_visibility(input.world, vec3<f32>(0.0, 1.0, 0.0)));
    if input.params.y > 0.5 {
        // Diagnostic views show raw linear values, so the floor darkens with
        // the background as it does in CDMW Next.
        return present_srgb(srgb_to_linear(colour), 1.0);
    }
    return present_srgb(colour, 1.0);
}
"#;

#[repr(C)]
#[derive(Debug, Clone, Copy, PartialEq, Pod, Zeroable)]
pub(crate) struct GroundVertex {
    position: [f32; 3],
    /// x: grid cell size, y: diagnostic darkening, z: grid on, w: unused.
    params: [f32; 4],
}

impl GroundVertex {
    const ATTRIBUTES: [wgpu::VertexAttribute; 2] =
        wgpu::vertex_attr_array![0 => Float32x3, 1 => Float32x4];

    pub(crate) fn layout() -> wgpu::VertexBufferLayout<'static> {
        wgpu::VertexBufferLayout {
            array_stride: std::mem::size_of::<Self>() as wgpu::BufferAddress,
            step_mode: wgpu::VertexStepMode::Vertex,
            attributes: &Self::ATTRIBUTES,
        }
    }
}

/// The floor quad for world-space bounds `low`..`high` (Y up).
#[must_use]
pub(crate) fn quad(low: Vec3, high: Vec3, grid: bool, darken: bool) -> [GroundVertex; 6] {
    let center = (low + high) * 0.5;
    let radius = ((high - low).length() * 0.5).max(0.05);
    let size = radius * 4.0;
    let y = low.y - 0.0005 * radius;
    let params = [
        (radius * 0.25).max(0.01),
        f32::from(u8::from(darken)),
        f32::from(u8::from(grid)),
        0.0,
    ];
    let corner = |x: f32, z: f32| GroundVertex {
        position: [center.x + x * size, y, center.z + z * size],
        params,
    };
    let (a, b, c, d) = (
        corner(-1.0, -1.0),
        corner(-1.0, 1.0),
        corner(1.0, 1.0),
        corner(1.0, -1.0),
    );
    [a, b, c, a, c, d]
}

pub(crate) struct Ground {
    pipeline: wgpu::RenderPipeline,
    buffer: wgpu::Buffer,
    last: std::cell::Cell<Option<[GroundVertex; 6]>>,
}

impl Ground {
    pub(crate) fn new(
        device: &wgpu::Device,
        format: wgpu::TextureFormat,
        layout: &wgpu::PipelineLayout,
        shader: &wgpu::ShaderModule,
        sample_count: u32,
    ) -> Self {
        let pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("CDMW Rust Mesh Lab ground pipeline"),
            layout: Some(layout),
            vertex: wgpu::VertexState {
                module: shader,
                entry_point: Some("vs_ground"),
                compilation_options: wgpu::PipelineCompilationOptions::default(),
                buffers: &[Some(GroundVertex::layout())],
            },
            primitive: wgpu::PrimitiveState {
                topology: wgpu::PrimitiveTopology::TriangleList,
                cull_mode: None,
                front_face: wgpu::FrontFace::Ccw,
                ..Default::default()
            },
            depth_stencil: Some(wgpu::DepthStencilState {
                format: crate::DEPTH_FORMAT,
                depth_write_enabled: Some(true),
                depth_compare: Some(wgpu::CompareFunction::LessEqual),
                stencil: wgpu::StencilState::default(),
                bias: wgpu::DepthBiasState::default(),
            }),
            multisample: wgpu::MultisampleState {
                count: sample_count,
                ..Default::default()
            },
            fragment: Some(wgpu::FragmentState {
                module: shader,
                entry_point: Some("fs_ground"),
                compilation_options: wgpu::PipelineCompilationOptions::default(),
                targets: &[Some(wgpu::ColorTargetState {
                    format,
                    blend: Some(wgpu::BlendState::REPLACE),
                    write_mask: wgpu::ColorWrites::ALL,
                })],
            }),
            multiview_mask: None,
            cache: None,
        });
        let buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("CDMW Rust Mesh Lab ground vertices"),
            contents: bytemuck::cast_slice(&quad(Vec3::ZERO, Vec3::ONE, true, false)),
            usage: wgpu::BufferUsages::VERTEX | wgpu::BufferUsages::COPY_DST,
        });
        Self {
            pipeline,
            buffer,
            last: std::cell::Cell::new(None),
        }
    }

    /// Uploads the quad when it changed and records the draw.
    pub(crate) fn draw(
        &self,
        queue: &wgpu::Queue,
        pass: &mut wgpu::RenderPass<'_>,
        vertices: [GroundVertex; 6],
    ) {
        if self.last.get() != Some(vertices) {
            queue.write_buffer(&self.buffer, 0, bytemuck::cast_slice(&vertices));
            self.last.set(Some(vertices));
        }
        pass.set_pipeline(&self.pipeline);
        pass.set_vertex_buffer(0, self.buffer.slice(..));
        pass.draw(0..6, 0..1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn floor_sits_under_the_bounds_and_scales_with_them() {
        let low = Vec3::new(-1.0, 0.25, -0.5);
        let high = Vec3::new(1.0, 2.0, 0.5);
        let quad = quad(low, high, true, false);
        let radius = (high - low).length() * 0.5;
        assert!(
            quad.iter()
                .all(|v| v.position[1] < low.y && v.position[1] > low.y - 0.01)
        );
        let xs: Vec<f32> = quad.iter().map(|v| v.position[0]).collect();
        let span = xs.iter().cloned().fold(f32::MIN, f32::max)
            - xs.iter().cloned().fold(f32::MAX, f32::min);
        assert!((span - radius * 8.0).abs() < 1e-4);
        assert!((quad[0].params[0] - radius * 0.25).abs() < 1e-5);
        assert_eq!(quad[0].params[2], 1.0);
        assert_eq!(
            super::quad(low, high, false, true)[0].params[1..3],
            [1.0, 0.0]
        );
    }
}
