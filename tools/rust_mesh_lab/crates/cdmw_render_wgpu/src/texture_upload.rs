//! Bounded DDS row uploads shared by immediate and frame-sliced preparation.
use super::*;
use std::borrow::Cow;

pub(super) struct PendingDdsUpload {
    plan: cdmw_texture::DdsUploadPlan,
    texture: Arc<wgpu::Texture>,
    format: wgpu::TextureFormat,
    view_format: wgpu::TextureFormat,
    level: usize,
    row: u32,
}

/// Offscreen proof: compare every mip's rendered pixels after immediate and
/// bounded row uploads, including cancellation of an unfinished upload.
pub async fn run_headless_texture_upload_comparison(sources: &[Vec<u8>]) -> Result<usize, RenderError> {
    let mut descriptor = wgpu::InstanceDescriptor::new_without_display_handle();
    descriptor.backends = wgpu::Backends::DX12;
    let instance = wgpu::Instance::new(descriptor);
    let adapter = instance.request_adapter(&wgpu::RequestAdapterOptions {
        power_preference: wgpu::PowerPreference::HighPerformance,
        compatible_surface: None, force_fallback_adapter: false, apply_limit_buckets: false,
    }).await.map_err(|_| RenderError::NoAdapter)?;
    let (device, queue) = adapter.request_device(&wgpu::DeviceDescriptor {
        label: Some("DDS streaming comparison"),
        required_features: requested_renderer_features(adapter.features()),
        required_limits: wgpu::Limits::default(),
        experimental_features: wgpu::ExperimentalFeatures::disabled(),
        memory_hints: wgpu::MemoryHints::MemoryUsage, trace: wgpu::Trace::Off,
    }).await.map_err(|error| RenderError::Device(error.to_string()))?;
    let scope = device.push_error_scope(wgpu::ErrorFilter::Validation);
    let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
        label: Some("DDS streaming pixels"), source: wgpu::ShaderSource::Wgsl(Cow::Borrowed(r#"
        @group(0) @binding(0) var source: texture_2d<f32>;
        @vertex fn vs(@builtin(vertex_index) index: u32) -> @builtin(position) vec4<f32> {
            let points = array<vec2<f32>,3>(vec2(-1.0,-1.0),vec2(3.0,-1.0),vec2(-1.0,3.0));
            return vec4(points[index],0.0,1.0);
        }
        @fragment fn fs(@builtin(position) position: vec4<f32>) -> @location(0) vec4<f32> {
            return textureLoad(source,vec2<i32>(position.xy),0);
        }
        "#)),
    });
    let format = wgpu::TextureFormat::Rgba8Unorm;
    let pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
        label: Some("DDS streaming proof"), layout: None,
        vertex: wgpu::VertexState { module:&shader, entry_point:Some("vs"), compilation_options:Default::default(), buffers:&[] },
        primitive:Default::default(), depth_stencil:None, multisample:Default::default(),
        fragment:Some(wgpu::FragmentState { module:&shader, entry_point:Some("fs"), compilation_options:Default::default(),
            targets:&[Some(wgpu::ColorTargetState { format, blend:None, write_mask:wgpu::ColorWrites::ALL })] }),
        multiview_mask:None, cache:None,
    });
    let mut compared = 0;
    for bytes in sources {
        let plan = dds_upload_plan(bytes, TextureRole::BaseColor, None)?;
        let budget = plan.levels.iter().map(|level| level.bytes_per_row as usize).max().unwrap_or(1) * 2 + 7;
        let immediate = upload_planned_dds_texture(&device, &queue, bytes, plan.clone())?;
        let mut cancelled = PendingDdsUpload::new(&device, plan.clone())?;
        cancelled.advance(&queue, bytes, budget)?;
        drop(cancelled);
        let mut staged = PendingDdsUpload::new(&device, plan.clone())?;
        while !staged.complete() {
            let used = staged.advance(&queue, bytes, budget)?;
            if used == 0 || used > budget { return Err(RenderError::Texture("DDS slice exceeded its budget or stalled".into())); }
            queue.submit([]);
        }
        let staged = staged.finish()?;
        for level in &plan.levels {
            let mut images = Vec::new();
            for texture in [&immediate, &staged] {
                let source = texture.texture.create_view(&wgpu::TextureViewDescriptor {
                    format:Some(texture.view_format), base_mip_level:level.level, mip_level_count:Some(1), ..Default::default()
                });
                let binding = device.create_bind_group(&wgpu::BindGroupDescriptor {
                    label:None, layout:&pipeline.get_bind_group_layout(0),
                    entries:&[wgpu::BindGroupEntry { binding:0, resource:wgpu::BindingResource::TextureView(&source) }],
                });
                let color = create_headless_color_target(&device, format, level.width, level.height);
                let view = color.create_view(&Default::default());
                let pitch = padded_headless_bytes_per_row(level.width);
                let readback = device.create_buffer(&wgpu::BufferDescriptor {
                    label:None, size:u64::from(pitch)*u64::from(level.height),
                    usage:wgpu::BufferUsages::COPY_DST|wgpu::BufferUsages::MAP_READ, mapped_at_creation:false,
                });
                let mut encoder = device.create_command_encoder(&Default::default());
                {
                    let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                        label:None, color_attachments:&[Some(wgpu::RenderPassColorAttachment {
                            view:&view, resolve_target:None, depth_slice:None,
                            ops:wgpu::Operations { load:wgpu::LoadOp::Clear(wgpu::Color::TRANSPARENT), store:wgpu::StoreOp::Store },
                        })], depth_stencil_attachment:None, timestamp_writes:None, occlusion_query_set:None, multiview_mask:None,
                    });
                    pass.set_pipeline(&pipeline); pass.set_bind_group(0,&binding,&[]); pass.draw(0..3,0..1);
                }
                encoder.copy_texture_to_buffer(wgpu::TexelCopyTextureInfo { texture:&color,mip_level:0,origin:wgpu::Origin3d::ZERO,aspect:wgpu::TextureAspect::All },
                    wgpu::TexelCopyBufferInfo { buffer:&readback, layout:wgpu::TexelCopyBufferLayout { offset:0,bytes_per_row:Some(pitch),rows_per_image:Some(level.height) } },
                    wgpu::Extent3d { width:level.width,height:level.height,depth_or_array_layers:1 });
                queue.submit([encoder.finish()]);
                images.push(read_headless_pixels(&device,&readback,level.width,level.height)?);
            }
            if images[0] != images[1] { return Err(RenderError::Texture(format!("DDS streaming changed mip {}",level.level))); }
            compared += 1;
        }
    }
    if let Some(error) = scope.pop().await { return Err(RenderError::Texture(error.to_string())); }
    Ok(compared)
}

impl PendingDdsUpload {
    pub(super) fn new(device: &wgpu::Device, plan: cdmw_texture::DdsUploadPlan) -> Result<Self, RenderError> {
        let view_format = map_dds_format(&plan.metadata.format, plan.metadata.color_space)?;
        let format = map_dds_format(&plan.metadata.format, ColorSpace::Linear)?;
        validate_dds_upload_requirements(&plan, format, &device.limits(), device.features())?;
        let alternate_view_formats = map_dds_format(&plan.metadata.format, ColorSpace::Srgb)
            .ok().filter(|candidate| *candidate != format).into_iter().collect::<Vec<_>>();
        let texture = Arc::new(device.create_texture(&wgpu::TextureDescriptor {
            label: Some("CDMW DDS upload"),
            size: wgpu::Extent3d { width: plan.metadata.width, height: plan.metadata.height, depth_or_array_layers: 1 },
            mip_level_count: plan.metadata.mip_count, sample_count: 1,
            dimension: wgpu::TextureDimension::D2, format,
            usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
            view_formats: &alternate_view_formats,
        }));
        Ok(Self { plan, texture, format, view_format, level: 0, row: 0 })
    }

    pub(super) fn complete(&self) -> bool { self.level == self.plan.levels.len() }

    pub(super) fn sha256(&self) -> &str { &self.plan.metadata.source_sha256 }

    pub(super) fn advance(&mut self, queue: &wgpu::Queue, bytes: &[u8], budget: usize) -> Result<usize, RenderError> {
        let mut used = 0;
        while let Some(level) = self.plan.levels.get(self.level) {
            let row_bytes = level.bytes_per_row as usize;
            let rows = ((budget - used) / row_bytes).min((level.rows_per_image - self.row) as usize) as u32;
            if rows == 0 { break; }
            let length = rows as usize * row_bytes;
            let start = level.byte_offset + self.row as usize * row_bytes;
            let source = bytes.get(start..start + length).ok_or_else(|| RenderError::Texture("DDS upload slice is truncated".into()))?;
            let (_, block_height) = self.format.block_dimensions();
            queue.write_texture(
                wgpu::TexelCopyTextureInfo {
                    texture: &self.texture, mip_level: level.level,
                    origin: wgpu::Origin3d { x: 0, y: self.row * block_height, z: 0 },
                    aspect: wgpu::TextureAspect::All,
                },
                source,
                wgpu::TexelCopyBufferLayout { offset: 0, bytes_per_row: Some(level.bytes_per_row), rows_per_image: Some(rows) },
                dds_mip_upload_extent(level.width, rows * block_height, self.format),
            );
            used += length;
            self.row += rows;
            if self.row == level.rows_per_image { self.level += 1; self.row = 0; }
        }
        Ok(used)
    }

    pub(super) fn finish(self) -> Result<UploadedDdsTexture, RenderError> {
        if !self.complete() { return Err(RenderError::Texture("DDS upload is incomplete".into())); }
        Ok(UploadedDdsTexture {
            texture: self.texture, view_format: self.view_format,
            source_sha256: self.plan.metadata.source_sha256,
            single_channel: dds_format_is_single_channel(&self.plan.metadata.format),
        })
    }
}
