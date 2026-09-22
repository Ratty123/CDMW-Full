//! Read back the production deformation function for CPU/shader comparisons.
use super::*;

#[doc(hidden)]
pub async fn run_headless_effect_mesh_deformation(
    asset: &EffectMeshAsset,
    particles: &[EffectMeshParticle],
    view: EffectMeshView,
) -> Result<Vec<[f32; 4]>, RenderError> {
    let count = asset.vertices.len().saturating_mul(particles.len());
    if count == 0 || count > 1_048_576 {
        return Err(RenderError::ResourceLimit);
    }
    let mut descriptor = wgpu::InstanceDescriptor::new_without_display_handle();
    descriptor.backends = wgpu::Backends::DX12;
    let instance = wgpu::Instance::new(descriptor);
    let adapter = instance
        .request_adapter(&wgpu::RequestAdapterOptions {
            power_preference: wgpu::PowerPreference::HighPerformance,
            force_fallback_adapter: false,
            compatible_surface: None,
            apply_limit_buckets: false,
        })
        .await
        .map_err(|_| RenderError::NoAdapter)?;
    let (device, queue) = adapter
        .request_device(&wgpu::DeviceDescriptor {
            label: Some("lightning arithmetic proof"),
            required_features: wgpu::Features::empty(),
            required_limits: wgpu::Limits::default(),
            experimental_features: wgpu::ExperimentalFeatures::disabled(),
            memory_hints: wgpu::MemoryHints::Performance,
            trace: wgpu::Trace::Off,
        })
        .await
        .map_err(|e| RenderError::Device(e.to_string()))?;
    let scope = device.push_error_scope(wgpu::ErrorFilter::Validation);
    let source = format!(
        "{}\n{}",
        effect_mesh_shader::SHADER.split("@vertex").next().unwrap(),
        r#"
struct ProofVertex { a: vec4<f32>, b: vec4<f32>, controls: vec4<f32> };
@group(0) @binding(0) var<storage,read> vertices: array<ProofVertex>;
@group(0) @binding(1) var<storage,read_write> positions: array<vec4<f32>>;
@compute @workgroup_size(64)
fn proof(@builtin(global_invocation_id) invocation: vec3<u32>) {
    let i = invocation.x;
    if i >= arrayLength(&positions) { return; }
    let v = vertices[i % arrayLength(&vertices)];
    let p = mesh_particles[i / arrayLength(&vertices)];
    let local = lightning_deform(v.a.xyz, vec3<f32>(v.a.w,v.b.xy), v.b.zw, v.controls.xyz, p);
    positions[i] = p.transform * vec4<f32>(local,1.0);
}
"#
    );
    let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
        label: Some("production lightning arithmetic"),
        source: wgpu::ShaderSource::Wgsl(source.into()),
    });
    let pipeline = device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
        label: Some("lightning proof"),
        layout: None,
        module: &shader,
        entry_point: Some("proof"),
        compilation_options: Default::default(),
        cache: None,
    });
    let input = |label, bytes, usage| {
        device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some(label),
            contents: bytes,
            usage,
        })
    };
    let vertices = input(
        "proof vertices",
        bytemuck::cast_slice(&asset.vertices),
        wgpu::BufferUsages::STORAGE,
    );
    let material = input(
        "proof material",
        bytemuck::bytes_of(&asset.lightning),
        wgpu::BufferUsages::STORAGE,
    );
    let particles = input(
        "proof particles",
        bytemuck::cast_slice(particles),
        wgpu::BufferUsages::STORAGE,
    );
    let view = input(
        "proof view",
        bytemuck::bytes_of(&view),
        wgpu::BufferUsages::UNIFORM,
    );
    let output = device.create_buffer(&wgpu::BufferDescriptor {
        label: Some("proof positions"),
        size: (count * 16) as u64,
        usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_SRC,
        mapped_at_creation: false,
    });
    let readback = device.create_buffer(&wgpu::BufferDescriptor {
        label: Some("proof readback"),
        size: (count * 16) as u64,
        usage: wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
        mapped_at_creation: false,
    });
    let binding = |group, buffers: &[&wgpu::Buffer]| {
        device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("proof binding"),
            layout: &pipeline.get_bind_group_layout(group),
            entries: &buffers
                .iter()
                .enumerate()
                .map(|(i, b)| wgpu::BindGroupEntry {
                    binding: i as u32,
                    resource: b.as_entire_binding(),
                })
                .collect::<Vec<_>>(),
        })
    };
    let geometry = binding(0, &[&vertices, &output]);
    let empty1 = binding(1, &[]);
    let empty2 = binding(2, &[]);
    let data = binding(3, &[&material, &particles, &view]);
    let mut encoder = device.create_command_encoder(&Default::default());
    {
        let mut pass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor::default());
        pass.set_pipeline(&pipeline);
        for (i, b) in [&geometry, &empty1, &empty2, &data].into_iter().enumerate() {
            pass.set_bind_group(i as u32, b, &[]);
        }
        pass.dispatch_workgroups((count as u32).div_ceil(64), 1, 1);
    }
    encoder.copy_buffer_to_buffer(&output, 0, &readback, 0, (count * 16) as u64);
    queue.submit([encoder.finish()]);
    let (sender, receiver) = std::sync::mpsc::channel();
    readback.slice(..).map_async(wgpu::MapMode::Read, move |r| {
        let _ = sender.send(r);
    });
    device
        .poll(wgpu::PollType::wait_indefinitely())
        .map_err(|e| RenderError::Device(e.to_string()))?;
    if let Some(error) = scope.pop().await {
        return Err(RenderError::Device(error.to_string()));
    }
    receiver
        .recv()
        .map_err(|e| RenderError::Device(e.to_string()))?
        .map_err(|e| RenderError::Device(e.to_string()))?;
    let mapped = readback
        .slice(..)
        .get_mapped_range()
        .map_err(|e| RenderError::Device(e.to_string()))?;
    let result = bytemuck::cast_slice::<u8, [f32; 4]>(&mapped).to_vec();
    drop(mapped);
    readback.unmap();
    Ok(result)
}
