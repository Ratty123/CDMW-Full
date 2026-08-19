using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Numerics;
using System.Runtime.InteropServices;
using Vortice.Direct3D;
using Vortice.Direct3D11;
using Vortice.DXGI;

namespace Cdmw.MeshEditorExperiment;

/// <summary>
/// The effect particle preview: an approximate CPU simulation of the effect the
/// package describes (effect_preview.json beside the mesh), drawn as camera-facing
/// sprites in the effect's frame, which is the placement of the package's editable
/// submesh (the effect box the gizmo moves). Fire that looks like that fire, roughly
/// where it will be; not the game's pixels.
/// </summary>
internal sealed partial class D3D11MaterialViewport
{
    private const int EffectParticlePumpMilliseconds = 33;
    private const int EffectParticleInitialVertexCapacity = 6 * 1024;
    private static readonly uint EffectParticleVertexStride = (uint)Marshal.SizeOf<D3D11EffectParticleVertex>();

    private EffectParticlePreview? _effectPreview;
    private readonly List<EffectEmitterSimulation> _effectEmitterSimulations = new();
    private readonly List<EffectParticleVertex> _effectParticleVertices = new(EffectParticleInitialVertexCapacity);
    private readonly Dictionary<string, ID3D11ShaderResourceView?> _effectParticleTextures = new(StringComparer.OrdinalIgnoreCase);
    private ID3D11Buffer? _effectParticleVertexBuffer;
    private int _effectParticleVertexCapacity;
    private ID3D11VertexShader? _effectParticleVertexShader;
    private ID3D11PixelShader? _effectParticlePixelShader;
    private ID3D11InputLayout? _effectParticleInputLayout;
    private ID3D11BlendState? _effectParticleAdditiveBlendState;
    private System.Windows.Forms.Timer? _effectParticlePump;
    private long _effectParticleLastTimestamp;
    private bool _effectParticlesEnabled = true;
    private int _effectParticleDrawnLastFrame;
    private long _effectParticleFrameCount;

    public bool HasEffectParticlePreview => _effectPreview is not null && _effectEmitterSimulations.Count > 0;

    /// <summary>
    /// Read effect_preview.json from `packageDirectory` (none: clear the preview) and
    /// start simulating; the pump keeps frames coming while a preview is loaded.
    /// </summary>
    public void LoadEffectParticlePreview(string? packageDirectory)
    {
        ClearEffectParticlePreview();
        EffectParticlePreview? preview;
        try
        {
            preview = EffectParticlePreview.Load(packageDirectory);
        }
        catch (Exception exception)
        {
            LastError = $"effect_preview.json did not read: {exception.Message}";
            preview = null;
        }
        if (preview is null || preview.Emitters.Count == 0)
        {
            return;
        }
        _effectPreview = preview;
        var seed = 1;
        foreach (var emitter in preview.Emitters)
        {
            _effectEmitterSimulations.Add(new EffectEmitterSimulation(emitter, seed++));
        }
        _effectParticleLastTimestamp = Stopwatch.GetTimestamp();
        EnsureEffectParticlePump();
        Invalidate();
    }

    public void ClearEffectParticlePreview()
    {
        _effectPreview = null;
        _effectEmitterSimulations.Clear();
        _effectParticleVertices.Clear();
        _effectParticleDrawnLastFrame = 0;
        DisposeEffectParticleTextures();
        if (_effectParticlePump is not null)
        {
            _effectParticlePump.Stop();
        }
    }

    public void SetEffectParticlesEnabled(bool enabled)
    {
        _effectParticlesEnabled = enabled;
        if (enabled && HasEffectParticlePreview)
        {
            _effectParticleLastTimestamp = Stopwatch.GetTimestamp();
            EnsureEffectParticlePump();
        }
        else
        {
            _effectParticlePump?.Stop();
        }
        Invalidate();
    }

    public Dictionary<string, object?> EffectParticlePreviewStatus()
    {
        var preview = _effectPreview;
        var particles = 0;
        foreach (var simulation in _effectEmitterSimulations)
        {
            particles += simulation.ParticleCount;
        }
        return new Dictionary<string, object?>
        {
            ["loaded"] = preview is not null,
            ["enabled"] = _effectParticlesEnabled,
            ["stem"] = preview?.Stem ?? string.Empty,
            ["emitters"] = preview?.Emitters.Count ?? 0,
            ["textures"] = _effectParticleTextures.Count(pair => pair.Value is not null),
            ["particles"] = particles,
            ["vertices_last_frame"] = _effectParticleDrawnLastFrame,
            ["frames"] = _effectParticleFrameCount,
            ["notes"] = preview?.Notes.ToArray() ?? Array.Empty<string>(),
        };
    }

    private void EnsureEffectParticlePump()
    {
        if (_effectParticlePump is null)
        {
            _effectParticlePump = new System.Windows.Forms.Timer { Interval = EffectParticlePumpMilliseconds };
            _effectParticlePump.Tick += OnEffectParticlePumpTick;
        }
        if (!_effectParticlePump.Enabled)
        {
            _effectParticlePump.Start();
        }
    }

    private void OnEffectParticlePumpTick(object? sender, EventArgs e)
    {
        if (!HasEffectParticlePreview || !_effectParticlesEnabled || IsDisposed)
        {
            _effectParticlePump?.Stop();
            return;
        }
        if (Visible)
        {
            Invalidate();
        }
    }

    private void CreateEffectParticleShaders(byte[] vertexBytecode, byte[] pixelBytecode)
    {
        if (_device is null)
        {
            return;
        }
        _effectParticleVertexShader?.Dispose();
        _effectParticlePixelShader?.Dispose();
        _effectParticleInputLayout?.Dispose();
        _effectParticleVertexShader = _device.CreateVertexShader(vertexBytecode);
        _effectParticlePixelShader = _device.CreatePixelShader(pixelBytecode);
        _effectParticleInputLayout = _device.CreateInputLayout(
            new[]
            {
                new InputElementDescription("POSITION", 0, Format.R32G32B32_Float, 0, 0),
                new InputElementDescription("COLOR", 0, Format.R32G32B32A32_Float, 12, 0),
                new InputElementDescription("TEXCOORD", 0, Format.R32G32_Float, 28, 0),
            },
            vertexBytecode);
    }

    private void CreateEffectParticlePipelineStates()
    {
        if (_device is null)
        {
            return;
        }
        _effectParticleAdditiveBlendState?.Dispose();
        _effectParticleAdditiveBlendState = _device.CreateBlendState(
            new BlendDescription(Blend.SourceAlpha, Blend.One, Blend.One, Blend.One));
    }

    private void DisposeEffectParticleDeviceResources()
    {
        DisposeEffectParticleTextures();
        _effectParticleVertexBuffer?.Dispose();
        _effectParticleVertexBuffer = null;
        _effectParticleVertexCapacity = 0;
        _effectParticleAdditiveBlendState?.Dispose();
        _effectParticleAdditiveBlendState = null;
        _effectParticleInputLayout?.Dispose();
        _effectParticleInputLayout = null;
        _effectParticleVertexShader?.Dispose();
        _effectParticleVertexShader = null;
        _effectParticlePixelShader?.Dispose();
        _effectParticlePixelShader = null;
    }

    private void DisposeEffectParticleTextures()
    {
        foreach (var view in _effectParticleTextures.Values)
        {
            view?.Dispose();
        }
        _effectParticleTextures.Clear();
    }

    private ID3D11ShaderResourceView? EffectParticleTexture(string path)
    {
        if (string.IsNullOrWhiteSpace(path) || _device is null || _context is null)
        {
            return null;
        }
        if (_effectParticleTextures.TryGetValue(path, out var cached))
        {
            return cached;
        }
        ID3D11ShaderResourceView? view = null;
        try
        {
            // the compressed blocks first: the CPU decoder has no case for BC7, and the
            // sprites of half the shipped effects are BC7, which left those emitters
            // drawing as flat untextured quads
            view = CreateEffectParticleSrvFromNative(NetTextureSet.DecodeDdsFileToNative(path));
            if (view is null)
            {
                using var bitmap = NetTextureSet.DecodeDdsFileToBitmap(path);
                if (bitmap is not null)
                {
                    view = CreateEffectParticleSrv(bitmap);
                }
            }
        }
        catch (Exception exception)
        {
            LastError = $"sprite {Path.GetFileName(path)} did not upload: {exception.Message}";
            view = null;
        }
        _effectParticleTextures[path] = view;
        return view;
    }

    /// <summary>
    /// A sprite uploaded as it sits in the file, blocks and mips untouched, and sampled
    /// as sRGB. The sheets are authored that way, and read as though they were linear
    /// every sprite's dark surround is lifted to a grey the additive pass adds on top:
    /// the fire arrives as a grid of visible rectangles with flames inside them.
    /// </summary>
    private unsafe ID3D11ShaderResourceView? CreateEffectParticleSrvFromNative(NetDdsNativeTextureData? nativeDds)
    {
        if (_device is null || nativeDds is null || nativeDds.Data.Length == 0 || nativeDds.Subresources.Count == 0)
        {
            return null;
        }
        ID3D11Texture2D? texture = null;
        try
        {
            var (resourceFormat, viewFormat) = NativeDdsFormats(nativeDds.FormatKey, useSrgb: true);
            var subresources = new SubresourceData[nativeDds.Subresources.Count];
            fixed (byte* dataPointer = nativeDds.Data)
            {
                for (var index = 0; index < nativeDds.Subresources.Count; index++)
                {
                    var subresource = nativeDds.Subresources[index];
                    subresources[index] = new SubresourceData(
                        (IntPtr)(dataPointer + subresource.Offset),
                        (uint)subresource.RowPitch,
                        (uint)subresource.SlicePitch);
                }
                texture = _device.CreateTexture2D(
                    new Texture2DDescription
                    {
                        Width = (uint)nativeDds.Width,
                        Height = (uint)nativeDds.Height,
                        MipLevels = (uint)nativeDds.Subresources.Count,
                        ArraySize = 1,
                        Format = resourceFormat,
                        SampleDescription = new SampleDescription(1, 0),
                        Usage = ResourceUsage.Immutable,
                        BindFlags = BindFlags.ShaderResource,
                    },
                    subresources);
            }
            return _device.CreateShaderResourceView(
                texture,
                new ShaderResourceViewDescription(
                    texture,
                    ShaderResourceViewDimension.Texture2D,
                    viewFormat,
                    0,
                    (uint)nativeDds.Subresources.Count,
                    0,
                    1));
        }
        catch (Exception)
        {
            // the bitmap route is asked next; its failure is the one worth reporting
            return null;
        }
        finally
        {
            texture?.Dispose();
        }
    }

    private ID3D11ShaderResourceView? CreateEffectParticleSrv(Bitmap source)
    {
        if (_device is null || _context is null)
        {
            return null;
        }
        using var converted = new Bitmap(source.Width, source.Height, PixelFormat.Format32bppArgb);
        using (var graphics = Graphics.FromImage(converted))
        {
            graphics.DrawImageUnscaled(source, 0, 0);
        }
        var rect = new Rectangle(0, 0, converted.Width, converted.Height);
        var data = converted.LockBits(rect, ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
        ID3D11Texture2D? texture = null;
        try
        {
            var mipCount = EditableMipLevelCount(converted.Width, converted.Height);
            var description = new Texture2DDescription
            {
                Width = (uint)converted.Width,
                Height = (uint)converted.Height,
                MipLevels = (uint)mipCount,
                ArraySize = 1,
                Format = Format.B8G8R8A8_Typeless,
                SampleDescription = new SampleDescription(1, 0),
                Usage = ResourceUsage.Default,
                BindFlags = BindFlags.ShaderResource | BindFlags.RenderTarget,
                MiscFlags = ResourceOptionFlags.GenerateMips,
            };
            texture = _device.CreateTexture2D(description);
            _context.UpdateSubresource(texture, 0, null, data.Scan0, (uint)data.Stride, 0);
            var view = _device.CreateShaderResourceView(
                texture,
                new ShaderResourceViewDescription(
                    texture,
                    ShaderResourceViewDimension.Texture2D,
                    // sRGB for the same reason the block-compressed road takes it: the
                    // sheets are authored in it, and the dark surround of every sprite
                    // reads as a grey rectangle without it
                    Format.B8G8R8A8_UNorm_SRgb,
                    0,
                    (uint)mipCount,
                    0,
                    1));
            _context.GenerateMips(view);
            return view;
        }
        finally
        {
            converted.UnlockBits(data);
            texture?.Dispose();
        }
    }

    private void EnsureEffectParticleVertexCapacity(int requiredVertexCount)
    {
        if (_device is null)
        {
            return;
        }
        if (_effectParticleVertexBuffer is not null && _effectParticleVertexCapacity >= requiredVertexCount)
        {
            return;
        }
        var nextCapacity = Math.Max(EffectParticleInitialVertexCapacity, _effectParticleVertexCapacity);
        while (nextCapacity < requiredVertexCount)
        {
            nextCapacity *= 2;
        }
        _effectParticleVertexBuffer?.Dispose();
        _effectParticleVertexBuffer = _device.CreateBuffer(new BufferDescription(
            checked((uint)(nextCapacity * (long)EffectParticleVertexStride)),
            BindFlags.VertexBuffer,
            ResourceUsage.Dynamic,
            CpuAccessFlags.Write));
        _effectParticleVertexCapacity = nextCapacity;
    }

    private unsafe void UploadEffectParticleVertices(List<EffectParticleVertex> vertices)
    {
        if (_context is null || _effectParticleVertexBuffer is null)
        {
            return;
        }
        var mapped = _context.Map(_effectParticleVertexBuffer, 0, MapMode.WriteDiscard, Vortice.Direct3D11.MapFlags.None);
        try
        {
            var destination = (D3D11EffectParticleVertex*)mapped.DataPointer;
            for (var index = 0; index < vertices.Count; index++)
            {
                var vertex = vertices[index];
                destination[index] = new D3D11EffectParticleVertex(vertex.Position, vertex.Color, vertex.TexCoord);
            }
        }
        finally
        {
            _context.Unmap(_effectParticleVertexBuffer, 0);
        }
    }

    /// <summary>The scene's editable submesh the effect frame follows: the package's first editable, else 0.</summary>
    private int EffectFrameSubmeshIndex()
    {
        for (var index = 0; index < _document.Submeshes.Count; index++)
        {
            if (_scene.IsEditable(index))
            {
                return index;
            }
        }
        return 0;
    }

    private void DrawEffectParticles(bool replacementOnly)
    {
        _ = replacementOnly;
        if (!_effectParticlesEnabled
            || !HasEffectParticlePreview
            || _context is null
            || _device is null
            || _overlayCameraBuffer is null
            || _effectParticleVertexShader is null
            || _effectParticlePixelShader is null
            || _effectParticleInputLayout is null)
        {
            _effectParticleDrawnLastFrame = 0;
            return;
        }
        var now = Stopwatch.GetTimestamp();
        var deltaSeconds = (float)((now - _effectParticleLastTimestamp) / (double)Stopwatch.Frequency);
        _effectParticleLastTimestamp = now;
        if (deltaSeconds > 0.25f)
        {
            // a long pause (a hidden pane, a modal dialog) is not two hundred frames of fire
            deltaSeconds = 0.033f;
        }
        var submeshIndex = EffectFrameSubmeshIndex();
        var model = ActivePaneModelMatrix(submeshIndex);
        var modelScale = MathF.Max(1e-4f, new Vector3(model.M11, model.M12, model.M13).Length());
        var right = _camera.Right;
        var up = _camera.Up;
        if (right.LengthSquared() < 1e-8f || up.LengthSquared() < 1e-8f)
        {
            right = Vector3.UnitX;
            up = Vector3.UnitY;
        }

        _effectParticleVertices.Clear();
        var ranges = new List<(int Start, int Count, string Texture, bool Additive, bool Beam)>();
        foreach (var simulation in _effectEmitterSimulations)
        {
            simulation.Step(deltaSeconds);
            var start = _effectParticleVertices.Count;
            var count = simulation.AppendVertices(_effectParticleVertices, model, right, up, modelScale);
            if (count > 0)
            {
                ranges.Add((start, count, simulation.Emitter.TexturePath, simulation.Emitter.IsAdditive, simulation.Emitter.IsBeam));
            }
        }
        _effectParticleFrameCount++;
        _effectParticleDrawnLastFrame = _effectParticleVertices.Count;
        if (_effectParticleVertices.Count == 0)
        {
            return;
        }
        if (Environment.GetEnvironmentVariable("CDMW_EFFECT_PARTICLE_DEBUG") is { Length: > 0 } debugPath && _effectParticleFrameCount % 30 == 1)
        {
            var low = new Vector3(float.MaxValue);
            var high = new Vector3(float.MinValue);
            foreach (var vertex in _effectParticleVertices)
            {
                low = Vector3.Min(low, vertex.Position);
                high = Vector3.Max(high, vertex.Position);
            }
            try
            {
                File.AppendAllText(debugPath, $"frame {_effectParticleFrameCount} vertices {_effectParticleVertices.Count} bounds {low} .. {high} model scale {modelScale} model {model.Translation} emitters {string.Join("; ", ranges.Select(r => $"{r.Count}:{(r.Beam ? "beam" : "sprite")}"))} first {_effectParticleVertices[0].Position} colour {_effectParticleVertices[0].Color}\n");
            }
            catch (IOException)
            {
            }
        }
        EnsureEffectParticleVertexCapacity(_effectParticleVertices.Count);
        UploadEffectParticleVertices(_effectParticleVertices);
        if (_effectParticleVertexBuffer is null)
        {
            return;
        }

        var constants = new D3D11OverlayConstants
        {
            WorldViewProjection = _camera.WorldViewProjection,
            Color = Vector4.One,
            MarkerSettings = new Vector4(
                Math.Max(1.0f, _camera.ViewportWidth),
                Math.Max(1.0f, _camera.ViewportHeight),
                0.0f,
                0.0f),
        };
        _context.IASetInputLayout(_effectParticleInputLayout);
        _context.IASetPrimitiveTopology(PrimitiveTopology.TriangleList);
        _context.IASetVertexBuffer(0u, _effectParticleVertexBuffer, EffectParticleVertexStride);
        _context.VSSetShader(_effectParticleVertexShader);
        _context.GSSetShader(null);
        _context.PSSetShader(_effectParticlePixelShader);
        _context.VSSetConstantBuffer(1u, _overlayCameraBuffer);
        _context.PSSetConstantBuffer(1u, _overlayCameraBuffer);
        if (_samplerState is not null)
        {
            _context.PSSetSampler(0u, _samplerState);
        }
        _context.RSSetState(_doubleSidedRasterizerState ?? _rasterizerState);
        _context.OMSetDepthStencilState(
            _presentationSettings.DisableDepthTest ? _overlayNoDepthState : _transparentDepthState);
        foreach (var range in ranges)
        {
            var texture = EffectParticleTexture(range.Texture);
            constants.MarkerSettings.Z = texture is not null ? 1.0f : 0.0f;
            constants.MarkerSettings.W = range.Beam ? 1.0f : 0.0f;
            _context.UpdateSubresource(in constants, _overlayCameraBuffer);
            _context.PSSetShaderResource(11u, texture);
            _context.OMSetBlendState(range.Additive
                ? _effectParticleAdditiveBlendState ?? _transparentBlendState ?? _overlayBlendState
                : _transparentBlendState ?? _overlayBlendState);
            _context.Draw((uint)range.Count, (uint)range.Start);
        }
        _context.PSSetShaderResource(11u, null);
        // back to the solid pass's state for whatever draws next
        _context.RSSetState(_rasterizerState);
        _context.OMSetBlendState(_blendState);
        _context.OMSetDepthStencilState(
            _presentationSettings.DisableDepthTest ? _overlayNoDepthState : _depthState);
        _context.IASetInputLayout(_inputLayout);
        _context.VSSetShader(_vertexShader);
        _context.PSSetShader(_pixelShader);
        _context.VSSetConstantBuffer(0u, _cameraBuffer);
        _context.PSSetConstantBuffer(0u, _cameraBuffer);
    }
}

[StructLayout(LayoutKind.Sequential)]
internal readonly record struct D3D11EffectParticleVertex(Vector3 Position, Vector4 Color, Vector2 TexCoord);
