//! Read-only DDS viewer. Compressed mip payloads go directly to the GPU.
use super::*;
use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct TextureViewState {
    pub channel: u32,
    pub mip: u32,
    pub reconstruct_z: bool,
    pub fit: bool,
    pub zoom: f32,
    pub pixel_ratio: f32,
    pub pan: [f32; 2],
}

impl Default for TextureViewState {
    fn default() -> Self {
        Self {
            channel: 0,
            mip: 0,
            reconstruct_z: false,
            fit: true,
            zoom: 1.0,
            pixel_ratio: 1.0,
            pan: [0.0; 2],
        }
    }
}

impl TextureViewState {
    pub fn validate(&self, mips: u32) -> Result<(), RenderError> {
        if self.channel > 4
            || self.mip >= mips
            || !self.zoom.is_finite()
            || !(0.1..=16.0).contains(&self.zoom)
            || !self.pixel_ratio.is_finite()
            || !(0.25..=8.0).contains(&self.pixel_ratio)
            || self
                .pan
                .iter()
                .any(|v| !v.is_finite() || v.abs() > 1_000_000.0)
        {
            return Err(RenderError::Texture("invalid texture view state".into()));
        }
        Ok(())
    }
}

#[repr(C)]
#[derive(Clone, Copy, bytemuck::Pod, bytemuck::Zeroable)]
struct Uniform {
    viewport: [f32; 2],
    image_size: [f32; 2],
    pan: [f32; 2],
    zoom: f32,
    mip: u32,
    channel: u32,
    signed: u32,
    reconstruct_z: u32,
    single_channel: u32,
}

pub struct TextureViewer {
    device: wgpu::Device,
    queue: wgpu::Queue,
    surface: Option<wgpu::Surface<'static>>,
    config: Option<wgpu::SurfaceConfiguration>,
    pipeline: wgpu::RenderPipeline,
    uniform: wgpu::Buffer,
    binding: Option<wgpu::BindGroup>,
    metadata: Option<cdmw_texture::DdsMetadata>,
}

impl TextureViewer {
    pub async fn new(window: Option<Arc<Window>>) -> Result<Self, RenderError> {
        let instance = wgpu::Instance::new(gpu_lifecycle::interactive_instance_descriptor());
        let surface = window
            .as_ref()
            .map(|w| instance.create_surface(w.clone()))
            .transpose()
            .map_err(|e| RenderError::Surface(e.to_string()))?;
        let adapter = instance
            .request_adapter(&wgpu::RequestAdapterOptions {
                power_preference: wgpu::PowerPreference::HighPerformance,
                force_fallback_adapter: false,
                compatible_surface: surface.as_ref(),
                apply_limit_buckets: false,
            })
            .await
            .map_err(|_| RenderError::NoAdapter)?;
        let (device, queue) = adapter
            .request_device(&wgpu::DeviceDescriptor {
                label: Some("CDMW DDS viewer"),
                required_features: requested_renderer_features(adapter.features()),
                required_limits: wgpu::Limits::default().using_resolution(adapter.limits()),
                experimental_features: wgpu::ExperimentalFeatures::disabled(),
                memory_hints: wgpu::MemoryHints::MemoryUsage,
                trace: wgpu::Trace::Off,
            })
            .await
            .map_err(|e| RenderError::Device(e.to_string()))?;
        let config = surface
            .as_ref()
            .zip(window.as_ref())
            .map(|(surface, window)| {
                let caps = surface.get_capabilities(&adapter);
                let format = caps
                    .formats
                    .iter()
                    .copied()
                    .find(|f| !f.is_srgb())
                    .ok_or(RenderError::SurfaceFormat)?;
                let size = window.inner_size();
                let config = wgpu::SurfaceConfiguration {
                    usage: wgpu::TextureUsages::RENDER_ATTACHMENT,
                    format,
                    color_space: wgpu::SurfaceColorSpace::Auto,
                    width: size.width.max(1),
                    height: size.height.max(1),
                    present_mode: wgpu::PresentMode::Fifo,
                    alpha_mode: caps.alpha_modes[0],
                    view_formats: vec![],
                    desired_maximum_frame_latency: 2,
                };
                surface.configure(&device, &config);
                Ok(config)
            })
            .transpose()?;
        let format = config
            .as_ref()
            .map_or(wgpu::TextureFormat::Rgba8Unorm, |c| c.format);
        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("DDS viewer"),
            source: wgpu::ShaderSource::Wgsl(include_str!("texture_view.wgsl").into()),
        });
        let pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("DDS quad"),
            layout: None,
            vertex: wgpu::VertexState {
                module: &shader,
                entry_point: Some("vs"),
                compilation_options: Default::default(),
                buffers: &[],
            },
            primitive: Default::default(),
            depth_stencil: None,
            multisample: Default::default(),
            fragment: Some(wgpu::FragmentState {
                module: &shader,
                entry_point: Some("fs"),
                compilation_options: Default::default(),
                targets: &[Some(wgpu::ColorTargetState {
                    format,
                    blend: None,
                    write_mask: wgpu::ColorWrites::ALL,
                })],
            }),
            multiview_mask: None,
            cache: None,
        });
        let uniform = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("DDS view state"),
            size: std::mem::size_of::<Uniform>() as u64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        Ok(Self {
            device,
            queue,
            surface,
            config,
            pipeline,
            uniform,
            binding: None,
            metadata: None,
        })
    }

    pub fn load(&mut self, bytes: &[u8]) -> Result<cdmw_texture::DdsMetadata, RenderError> {
        let mut plan = dds_upload_plan(bytes, TextureRole::Unknown, None)?;
        // Raw normalized samples for every mode, including sRGB-tagged DDS channels.
        plan.metadata.color_space = ColorSpace::Linear;
        let metadata = plan.metadata.clone();
        let uploaded = upload_planned_dds_texture(&self.device, &self.queue, bytes, plan)?;
        let view = uploaded.texture.create_view(&wgpu::TextureViewDescriptor {
            format: Some(uploaded.view_format),
            ..Default::default()
        });
        let sampler = self.device.create_sampler(&wgpu::SamplerDescriptor {
            mag_filter: wgpu::FilterMode::Nearest,
            min_filter: wgpu::FilterMode::Linear,
            ..Default::default()
        });
        let binding = self.device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("DDS viewer source"),
            layout: &self.pipeline.get_bind_group_layout(0),
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: wgpu::BindingResource::TextureView(&view),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: wgpu::BindingResource::Sampler(&sampler),
                },
                wgpu::BindGroupEntry {
                    binding: 2,
                    resource: self.uniform.as_entire_binding(),
                },
            ],
        });
        self.binding = Some(binding);
        self.metadata = Some(metadata.clone());
        Ok(metadata)
    }

    pub fn resize(&mut self, width: u32, height: u32) {
        if let (Some(surface), Some(config)) = (&self.surface, &mut self.config) {
            config.width = width.max(1);
            config.height = height.max(1);
            surface.configure(&self.device, config);
        }
    }

    fn encode(
        &self,
        target: &wgpu::TextureView,
        size: [u32; 2],
        state: TextureViewState,
        encoder: &mut wgpu::CommandEncoder,
    ) -> Result<(), RenderError> {
        let (Some(metadata), Some(binding)) = (&self.metadata, &self.binding) else {
            return Ok(());
        };
        state.validate(metadata.mip_count)?;
        let image = [
            (metadata.width >> state.mip).max(1) as f32,
            (metadata.height >> state.mip).max(1) as f32,
        ];
        let zoom = if state.fit {
            (size[0] as f32 / image[0]).min(size[1] as f32 / image[1])
        } else {
            state.zoom * state.pixel_ratio
        };
        let two_channels = matches!(
            metadata.format,
            DdsFormat::Bc5Snorm | DdsFormat::Bc5Unorm | DdsFormat::Rg8Unorm
        );
        let data = Uniform {
            viewport: size.map(|v| v as f32),
            image_size: [metadata.width as f32, metadata.height as f32],
            pan: if state.fit { [0.0; 2] } else { state.pan },
            zoom,
            mip: state.mip,
            channel: state.channel,
            signed: u32::from(matches!(
                metadata.format,
                DdsFormat::Bc4Snorm | DdsFormat::Bc5Snorm | DdsFormat::Bc6hSignedFloat
            )),
            reconstruct_z: u32::from(state.reconstruct_z && two_channels),
            single_channel: u32::from(dds_format_is_single_channel(&metadata.format)),
        };
        self.queue
            .write_buffer(&self.uniform, 0, bytemuck::bytes_of(&data));
        let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
            label: Some("DDS viewer"),
            color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                view: target,
                resolve_target: None,
                depth_slice: None,
                ops: wgpu::Operations {
                    load: wgpu::LoadOp::Clear(wgpu::Color::BLACK),
                    store: wgpu::StoreOp::Store,
                },
            })],
            depth_stencil_attachment: None,
            timestamp_writes: None,
            occlusion_query_set: None,
            multiview_mask: None,
        });
        pass.set_pipeline(&self.pipeline);
        pass.set_bind_group(0, binding, &[]);
        pass.draw(0..3, 0..1);
        Ok(())
    }

    pub fn render(&mut self, state: TextureViewState) -> Result<bool, RenderError> {
        let Some(surface) = &self.surface else {
            return Ok(false);
        };
        let config = self.config.as_ref().ok_or(RenderError::SurfaceFormat)?;
        let frame = match surface.get_current_texture() {
            wgpu::CurrentSurfaceTexture::Success(frame)
            | wgpu::CurrentSurfaceTexture::Suboptimal(frame) => frame,
            wgpu::CurrentSurfaceTexture::Occluded | wgpu::CurrentSurfaceTexture::Timeout => {
                return Ok(false);
            }
            wgpu::CurrentSurfaceTexture::Outdated | wgpu::CurrentSurfaceTexture::Lost => {
                surface.configure(&self.device, config);
                return Ok(false);
            }
            other => {
                return Err(RenderError::Surface(format!(
                    "texture surface unavailable: {other:?}"
                )));
            }
        };
        let view = frame.texture.create_view(&Default::default());
        let mut encoder = self.device.create_command_encoder(&Default::default());
        self.encode(&view, [config.width, config.height], state, &mut encoder)?;
        self.queue.submit([encoder.finish()]);
        self.queue.present(frame);
        Ok(true)
    }

    /// Uses the identical shader and compressed upload for deterministic GPU evidence.
    pub fn capture(&self, size: [u32; 2], state: TextureViewState) -> Result<Vec<u8>, RenderError> {
        if self.surface.is_some() || size.iter().any(|v| *v == 0 || *v > 4096) {
            return Err(RenderError::Texture(
                "invalid offscreen texture capture".into(),
            ));
        }
        let [width, height] = size;
        let color = create_headless_color_target(
            &self.device,
            wgpu::TextureFormat::Rgba8Unorm,
            width,
            height,
        );
        let view = color.create_view(&Default::default());
        let pitch = padded_headless_bytes_per_row(width);
        let readback = self.device.create_buffer(&wgpu::BufferDescriptor {
            label: None,
            size: u64::from(pitch) * u64::from(height),
            usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
            mapped_at_creation: false,
        });
        let mut encoder = self.device.create_command_encoder(&Default::default());
        self.encode(&view, size, state, &mut encoder)?;
        encoder.copy_texture_to_buffer(
            wgpu::TexelCopyTextureInfo {
                texture: &color,
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            wgpu::TexelCopyBufferInfo {
                buffer: &readback,
                layout: wgpu::TexelCopyBufferLayout {
                    offset: 0,
                    bytes_per_row: Some(pitch),
                    rows_per_image: Some(height),
                },
            },
            wgpu::Extent3d {
                width,
                height,
                depth_or_array_layers: 1,
            },
        );
        self.queue.submit([encoder.finish()]);
        read_headless_pixels(&self.device, &readback, width, height)
    }
}
