using System.Diagnostics;
using System.IO;
using System.Numerics;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using Vortice.D3DCompiler;
using Vortice.Direct3D;
using Vortice.Direct3D11;
using Vortice.DXGI;
using Vortice.Mathematics;
using static Vortice.Direct3D11.D3D11;

namespace Cdmw.MeshEditorExperiment;

#pragma warning disable CS8625, CS8620, CS9191

internal sealed partial class D3D11MaterialViewport : Control
{
    private readonly ObjDocument _document;
    private readonly NetMaterialSet _materials;
    private readonly NetTextureSet _textureSet;
    private readonly List<D3D11SubmeshBatch> _batches = new();
    private readonly Dictionary<string, D3D11TextureSrvCacheEntry> _textureSrvCache = new(StringComparer.OrdinalIgnoreCase);
    private ID3D11Device? _device;
    private ID3D11DeviceContext? _context;
    private IDXGISwapChain1? _swapChain;
    private ID3D11RenderTargetView? _renderTargetView;
    private ID3D11Texture2D? _depthTexture;
    private ID3D11DepthStencilView? _depthStencilView;
    private ID3D11VertexShader? _vertexShader;
    private ID3D11PixelShader? _pixelShader;
    private ID3D11VertexShader? _overlayVertexShader;
    private ID3D11PixelShader? _overlayPixelShader;
    private ID3D11InputLayout? _inputLayout;
    private ID3D11InputLayout? _overlayInputLayout;
    private ID3D11SamplerState? _samplerState;
    private ID3D11Buffer? _cameraBuffer;
    private ID3D11Buffer? _overlayCameraBuffer;
    private ID3D11RasterizerState? _rasterizerState;
    private ID3D11BlendState? _blendState;
    private ID3D11BlendState? _overlayBlendState;
    private ID3D11DepthStencilState? _depthState;
    private ID3D11DepthStencilState? _overlayDepthState;
    private int _renderWidth;
    private int _renderHeight;
    private bool _renderResourcesDirty = true;
    private bool _geometryDirty = true;
    private Vec3 _center;
    private (Vec3 Min, Vec3 Max) _bounds;
    private NetViewportCamera _camera;
    private NetEdgeTopology _overlayTopology = NetEdgeTopology.Empty;
    private IReadOnlySet<int> _overlaySelectedEdges = new HashSet<int>();
    private int _overlayHoverEdgeId = -1;
    private Rectangle? _overlaySelectionRectangle;
    private IReadOnlyDictionary<int, HashSet<int>> _overlaySelectedVertices = new Dictionary<int, HashSet<int>>();
    private IReadOnlyDictionary<int, HashSet<int>> _overlaySelectedFaces = new Dictionary<int, HashSet<int>>();
    private IReadOnlySet<int> _overlaySelectedSources = new HashSet<int>();
    private int _overlaySelectedSubmeshIndex;
    private bool _overlayShowWire;
    private bool _overlayShowVertices;
    private bool _overlayShowXRay;
    private int _materialDebugMode;
    private long _texturedSolidBatchDrawCount;
    private long _untexturedSolidBatchDrawCount;
    private long _wireOverlayDrawCount;
    private long _vertexOverlayBatchDrawCount;
    private int _consecutiveRenderFailures;
    private int _deviceResetAttempts;
    private long _deviceResetAttemptCount;
    private long _deviceResetCount;
    private long _materialParameterApplyCount;
    private long _materialParameterApplyFailureCount;
    private long _affectedMaterialParameterBatchCount;

    public event Action<string>? BackendUnavailable;
    public event Action<double, double, string>? FrameRendered;

    public D3D11MaterialViewport(ObjDocument document, NetMaterialSet materials, NetTextureSet textureSet)
    {
        _document = document;
        _materials = materials;
        _textureSet = textureSet;
        SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.Opaque | ControlStyles.ResizeRedraw | ControlStyles.UserPaint, true);
        Dock = DockStyle.Fill;
        BackColor = System.Drawing.Color.FromArgb(18, 20, 24);
    }

    public string BackendName => "d3d11_vortice_shader";
    public string LastError { get; private set; } = string.Empty;
    public string DeviceRemovedReason { get; private set; } = string.Empty;
    public long GeometryUploadCount => _fullGeometryRebuildCount;
    public long DeviceResetAttemptCount => _deviceResetAttemptCount;
    public long DeviceResetCount => _deviceResetCount;
    public int MaterialDebugMode
    {
        get => _materialDebugMode;
        set
        {
            _materialDebugMode = Math.Clamp(value, 0, 6);
            Invalidate();
        }
    }
    public bool ShowSolid { get; set; } = true;
    public bool TexturesEnabled { get; set; } = true;
    public bool IsInitialized => _device is not null && _swapChain is not null;

    public void UpdateOverlay(
        NetEdgeTopology topology,
        IReadOnlySet<int> selectedEdges,
        int hoverEdgeId,
        Rectangle? selectionRectangle,
        IReadOnlyDictionary<int, HashSet<int>> selectedVertices,
        IReadOnlyDictionary<int, HashSet<int>> selectedFaces,
        IReadOnlySet<int> selectedSources,
        int selectedSubmeshIndex,
        bool showWire,
        bool showVertices,
        bool showXRay)
    {
        _overlayTopology = topology;
        _overlaySelectedEdges = selectedEdges;
        _overlayHoverEdgeId = hoverEdgeId;
        _overlaySelectionRectangle = selectionRectangle;
        _overlaySelectedVertices = selectedVertices;
        _overlaySelectedFaces = selectedFaces;
        _overlaySelectedSources = selectedSources;
        _overlaySelectedSubmeshIndex = selectedSubmeshIndex;
        _overlayShowWire = showWire;
        _overlayShowVertices = showVertices;
        _overlayShowXRay = showXRay;
        Invalidate();
    }

    public void UpdateCamera(NetViewportCamera camera)
    {
        _center = camera.Center;
        _bounds = camera.Bounds;
        _camera = camera;
        Invalidate();
    }

    public bool TryInitialize(out string error)
    {
        error = string.Empty;
        try
        {
            CreateControl();
            if (!IsHandleCreated)
            {
                throw new InvalidOperationException("D3D11 viewport handle was not created.");
            }
            InitializeDevice();
            if (_device is null || _context is null || _swapChain is null || _vertexShader is null || _pixelShader is null || _inputLayout is null || _cameraBuffer is null || _overlayVertexShader is null || _overlayPixelShader is null || _overlayInputLayout is null || _overlayCameraBuffer is null)
            {
                throw new InvalidOperationException("D3D11 device, shaders, swap chain, overlay pipeline, or pipeline state did not initialize.");
            }
            ResizeSwapChainResources();
            RebuildGeometry();
            if (_renderTargetView is null || _depthStencilView is null)
            {
                throw new InvalidOperationException("D3D11 render or depth target did not initialize.");
            }
            LastError = string.Empty;
            _consecutiveRenderFailures = 0;
            return true;
        }
        catch (Exception ex)
        {
            error = ex.Message;
            LastError = ex.Message;
            DisposeDeviceResources(clearDeviceContext: true);
            return false;
        }
    }

    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);
    }

    protected override void OnResize(EventArgs e)
    {
        base.OnResize(e);
        _renderResourcesDirty = true;
        Invalidate();
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        if (!EnsureDeviceReady())
        {
            e.Graphics.Clear(BackColor);
            return;
        }
        var frameStart = Stopwatch.GetTimestamp();
        try
        {
            var presentMs = RenderFrame();
            _consecutiveRenderFailures = 0;
            _deviceResetAttempts = 0;
            var frameMs = (Stopwatch.GetTimestamp() - frameStart) * 1000.0 / Stopwatch.Frequency;
            FrameRendered?.Invoke(frameMs, presentMs, DeviceRemovedReason);
        }
        catch (Exception ex) when (IsDeviceLostException(ex))
        {
            LastError = ex.Message;
            DeviceRemovedReason = DeviceLostReason(ex);
            e.Graphics.Clear(BackColor);
            if (!TryResetDeviceAfterLoss(DeviceRemovedReason))
            {
                BackendUnavailable?.Invoke($"D3D11 device lost and reset failed: {DeviceRemovedReason}");
            }
        }
        catch (Exception ex)
        {
            LastError = ex.Message;
            _consecutiveRenderFailures++;
            e.Graphics.Clear(BackColor);
            if (_consecutiveRenderFailures >= 2)
            {
                BackendUnavailable?.Invoke($"D3D11 render failed repeatedly: {ex.Message}");
            }
        }
    }

    private bool EnsureDeviceReady()
    {
        try
        {
            if (!IsHandleCreated)
            {
                return false;
            }
            if (_device is null)
            {
                InitializeDevice();
            }
            if (_device is null || _context is null || _swapChain is null)
            {
                return false;
            }
            if (_renderResourcesDirty || _renderWidth != Math.Max(1, ClientSize.Width) || _renderHeight != Math.Max(1, ClientSize.Height))
            {
                ResizeSwapChainResources();
            }
            if (_geometryDirty)
            {
                RebuildGeometry();
            }
            else
            {
                ApplyPendingTopologyUpdates();
                ApplyPendingVertexUpdates();
                RebuildMaterialResourcesIfDirty();
            }
            LastError = string.Empty;
            return _renderTargetView is not null && _cameraBuffer is not null && _overlayCameraBuffer is not null;
        }
        catch (Exception ex) when (IsDeviceLostException(ex))
        {
            LastError = ex.Message;
            DeviceRemovedReason = DeviceLostReason(ex);
            return TryResetDeviceAfterLoss(DeviceRemovedReason);
        }
        catch (Exception ex)
        {
            LastError = ex.Message;
            _consecutiveRenderFailures++;
            if (_consecutiveRenderFailures >= 2)
            {
                BackendUnavailable?.Invoke($"D3D11 setup failed repeatedly: {ex.Message}");
            }
            return false;
        }
    }

    private void InitializeDevice()
    {
        if (_device is not null || !IsHandleCreated)
        {
            return;
        }
        if (string.Equals(Environment.GetEnvironmentVariable("CDMW_MESH_DOTNET_FORCE_D3D11_FAILURE"), "1", StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException("D3D11 initialization failure forced by CDMW_MESH_DOTNET_FORCE_D3D11_FAILURE.");
        }
        var featureLevels = new[] { FeatureLevel.Level_11_1, FeatureLevel.Level_11_0, FeatureLevel.Level_10_1, FeatureLevel.Level_10_0 };
        _device = Vortice.Direct3D11.D3D11.D3D11CreateDevice(
            DriverType.Hardware,
            DeviceCreationFlags.BgraSupport,
            featureLevels);
        _context = _device.ImmediateContext;
        using var dxgiDevice = _device.QueryInterface<IDXGIDevice>();
        using var adapter = dxgiDevice.GetAdapter();
        using var factory = adapter.GetParent<IDXGIFactory2>();
        var swapChainDescription = new SwapChainDescription1
        {
            Width = (uint)Math.Max(1, ClientSize.Width),
            Height = (uint)Math.Max(1, ClientSize.Height),
            Format = Format.B8G8R8A8_UNorm,
            Stereo = false,
            SampleDescription = new SampleDescription(1, 0),
            BufferUsage = Usage.RenderTargetOutput,
            BufferCount = 2,
            Scaling = Scaling.Stretch,
            SwapEffect = SwapEffect.Discard,
            AlphaMode = AlphaMode.Ignore,
        };
        _swapChain = factory.CreateSwapChainForHwnd(_device, Handle, swapChainDescription);
        CompileShaders();
        CreatePipelineStates();
        _renderResourcesDirty = true;
        DiscardPendingVertexUpdates();
        _geometryDirty = true;
    }

    private unsafe void CompileShaders()
    {
        if (_device is null)
        {
            return;
        }
        var shaderPath = ResolveShaderPath();
        Compiler.CompileFromFile(shaderPath, null, null, "VSMain", "vs_5_0", ShaderFlags.EnableStrictness, EffectFlags.None, out var vsBlob, out var vsError).CheckError();
        Compiler.CompileFromFile(shaderPath, null, null, "PSMain", "ps_5_0", ShaderFlags.EnableStrictness, EffectFlags.None, out var psBlob, out var psError).CheckError();
        Compiler.CompileFromFile(shaderPath, null, null, "VSOverlay", "vs_5_0", ShaderFlags.EnableStrictness, EffectFlags.None, out var overlayVsBlob, out var overlayVsError).CheckError();
        Compiler.CompileFromFile(shaderPath, null, null, "PSOverlay", "ps_5_0", ShaderFlags.EnableStrictness, EffectFlags.None, out var overlayPsBlob, out var overlayPsError).CheckError();
        using (vsBlob)
        using (psBlob)
        using (vsError)
        using (psError)
        using (overlayVsBlob)
        using (overlayPsBlob)
        using (overlayVsError)
        using (overlayPsError)
        {
            _vertexShader = _device.CreateVertexShader(vsBlob.BufferPointer.ToPointer(), vsBlob.BufferSize, null);
            _pixelShader = _device.CreatePixelShader(psBlob.BufferPointer.ToPointer(), psBlob.BufferSize, null);
            _overlayVertexShader = _device.CreateVertexShader(overlayVsBlob.BufferPointer.ToPointer(), overlayVsBlob.BufferSize, null);
            _overlayPixelShader = _device.CreatePixelShader(overlayPsBlob.BufferPointer.ToPointer(), overlayPsBlob.BufferSize, null);
            var elements = new[]
            {
                new InputElementDescription("POSITION", 0, Format.R32G32B32_Float, 0, 0),
                new InputElementDescription("NORMAL", 0, Format.R32G32B32_Float, 12, 0),
                new InputElementDescription("TANGENT", 0, Format.R32G32B32_Float, 24, 0),
                new InputElementDescription("BINORMAL", 0, Format.R32G32B32_Float, 36, 0),
                new InputElementDescription("TEXCOORD", 0, Format.R32G32_Float, 48, 0),
            };
            _inputLayout = _device.CreateInputLayout(elements, vsBlob);
            _overlayInputLayout = _device.CreateInputLayout(
                new[] { new InputElementDescription("POSITION", 0, Format.R32G32B32_Float, 0, 0) },
                overlayVsBlob);
        }
    }

    private static string ResolveShaderPath()
    {
        var candidates = new[]
        {
            Path.Combine(AppContext.BaseDirectory, "D3D11MaterialShaders.hlsl"),
            Path.Combine(AppContext.BaseDirectory, "tools", "dotnet_mesh_editor_experiment", "D3D11MaterialShaders.hlsl"),
            Environment.ProcessPath is { Length: > 0 } processPath
                ? Path.Combine(Path.GetDirectoryName(processPath) ?? string.Empty, "D3D11MaterialShaders.hlsl")
                : string.Empty,
        };
        foreach (var candidate in candidates)
        {
            if (!string.IsNullOrWhiteSpace(candidate) && File.Exists(candidate))
            {
                return candidate;
            }
        }
        var embedded = System.Reflection.Assembly.GetExecutingAssembly().GetManifestResourceStream("D3D11MaterialShaders.hlsl");
        if (embedded is null)
        {
            throw new FileNotFoundException("D3D11MaterialShaders.hlsl was not found beside the .NET helper and was not embedded as a resource.");
        }
        string shaderText;
        using (embedded)
        using (var reader = new StreamReader(embedded, Encoding.UTF8, detectEncodingFromByteOrderMarks: true, leaveOpen: false))
        {
            shaderText = reader.ReadToEnd();
        }
        var shaderBytes = Encoding.UTF8.GetBytes(shaderText);
        var shaderHash = Convert.ToHexString(SHA256.HashData(shaderBytes)).ToLowerInvariant()[..16];
        var helperVersion = System.Reflection.Assembly.GetExecutingAssembly().GetName().Version?.ToString() ?? "dev";
        var outputDir = Path.Combine(Path.GetTempPath(), "cdmw-dotnet-mesh-editor-shaders", $"{helperVersion}-{shaderHash}");
        Directory.CreateDirectory(outputDir);
        var outputPath = Path.Combine(outputDir, "D3D11MaterialShaders.hlsl");
        if (!File.Exists(outputPath) || !File.ReadAllBytes(outputPath).AsSpan().SequenceEqual(shaderBytes))
        {
            File.WriteAllBytes(outputPath, shaderBytes);
        }
        return outputPath;
    }

    private void CreatePipelineStates()
    {
        if (_device is null)
        {
            return;
        }
        _samplerState = _device.CreateSamplerState(new SamplerDescription(Filter.MinMagMipLinear, TextureAddressMode.Wrap, TextureAddressMode.Wrap, TextureAddressMode.Wrap));
        _rasterizerState = _device.CreateRasterizerState(new RasterizerDescription(CullMode.None, FillMode.Solid));
        _blendState = _device.CreateBlendState(BlendDescription.Opaque);
        _overlayBlendState = _device.CreateBlendState(BlendDescription.NonPremultiplied);
        _depthState = _device.CreateDepthStencilState(DepthStencilDescription.Default);
        var overlayDepthDescription = DepthStencilDescription.Default;
        overlayDepthDescription.DepthEnable = false;
        overlayDepthDescription.DepthWriteMask = DepthWriteMask.Zero;
        _overlayDepthState = _device.CreateDepthStencilState(overlayDepthDescription);
        _cameraBuffer = _device.CreateBuffer(new BufferDescription((uint)Marshal.SizeOf<D3D11CameraConstants>(), BindFlags.ConstantBuffer));
        _overlayCameraBuffer = _device.CreateBuffer(new BufferDescription((uint)Marshal.SizeOf<D3D11OverlayConstants>(), BindFlags.ConstantBuffer));
    }

    private void ResizeSwapChainResources()
    {
        if (_device is null || _context is null || _swapChain is null)
        {
            return;
        }
        _context.OMSetRenderTargets((ID3D11RenderTargetView?)null, null);
        _renderTargetView?.Dispose();
        _depthStencilView?.Dispose();
        _depthTexture?.Dispose();
        _renderTargetView = null;
        _depthStencilView = null;
        _depthTexture = null;
        _renderWidth = Math.Max(1, ClientSize.Width);
        _renderHeight = Math.Max(1, ClientSize.Height);
        _swapChain.ResizeBuffers(0, (uint)_renderWidth, (uint)_renderHeight, Format.Unknown, SwapChainFlags.None).CheckError();
        using var backBuffer = _swapChain.GetBuffer<ID3D11Texture2D>(0);
        _renderTargetView = _device.CreateRenderTargetView(backBuffer);
        var depthDescription = new Texture2DDescription
        {
            Width = (uint)_renderWidth,
            Height = (uint)_renderHeight,
            MipLevels = 1,
            ArraySize = 1,
            Format = Format.D24_UNorm_S8_UInt,
            SampleDescription = new SampleDescription(1, 0),
            Usage = ResourceUsage.Default,
            BindFlags = BindFlags.DepthStencil,
        };
        _depthTexture = _device.CreateTexture2D(depthDescription);
        _depthStencilView = _device.CreateDepthStencilView(_depthTexture);
        _renderResourcesDirty = false;
    }

    private unsafe double RenderFrame()
    {
        if (_context is null || _swapChain is null || _renderTargetView is null || _depthStencilView is null || _cameraBuffer is null)
        {
            return 0.0;
        }
        if (string.Equals(Environment.GetEnvironmentVariable("CDMW_MESH_DOTNET_FORCE_D3D11_PRESENT_FAILURE"), "1", StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException("Forced DXGI device lost during Present for D3D11 recovery testing.");
        }
        _context.ClearRenderTargetView(_renderTargetView, new Color4(0.07f, 0.08f, 0.1f, 1.0f));
        _context.ClearDepthStencilView(_depthStencilView, DepthStencilClearFlags.Depth, 1.0f, 0);
        _context.RSSetViewport(new Viewport(0, 0, _renderWidth, _renderHeight, 0, 1));
        _context.RSSetState(_rasterizerState);
        _context.OMSetRenderTargets(_renderTargetView, _depthStencilView);
        _context.OMSetDepthStencilState(_depthState);
        _context.OMSetBlendState(_blendState);
        _context.IASetPrimitiveTopology(PrimitiveTopology.TriangleList);
        _context.IASetInputLayout(_inputLayout);
        _context.VSSetShader(_vertexShader);
        _context.PSSetShader(_pixelShader);
        if (_samplerState is not null)
        {
            _context.PSSetSampler(0u, _samplerState);
        }
        _context.VSSetConstantBuffer(0u, _cameraBuffer);
        _context.PSSetConstantBuffer(0u, _cameraBuffer);
        if (ShowSolid)
        {
            foreach (var batch in _batches)
            {
                if (_materials.ParametersForSubmesh(batch.SubmeshIndex).Visible is false) continue;
                var constants = BuildCameraConstants(batch);
                _context.UpdateSubresource(ref constants, _cameraBuffer);
                _context.PSSetShaderResources(0u, batch.Materials.ShaderResources);
                _context.IASetVertexBuffer(0u, batch.VertexBuffer, D3D11SubmeshBatch.VertexStride);
                _context.IASetIndexBuffer(batch.IndexBuffer, Format.R32_UInt, 0);
                _context.DrawIndexed((uint)batch.IndexCount, 0, 0);
                if (TexturesEnabled)
                {
                    _texturedSolidBatchDrawCount++;
                }
                else
                {
                    _untexturedSolidBatchDrawCount++;
                }
            }
        }
        DrawD3D11Overlay();
        var syncInterval = string.Equals(Environment.GetEnvironmentVariable("CDMW_MESH_DOTNET_D3D11_NO_VSYNC"), "1", StringComparison.OrdinalIgnoreCase) ? 0u : 1u;
        var presentStart = Stopwatch.GetTimestamp();
        _swapChain.Present(syncInterval, PresentFlags.None);
        return (Stopwatch.GetTimestamp() - presentStart) * 1000.0 / Stopwatch.Frequency;
    }

    private static bool IsDeviceLostException(Exception ex)
    {
        const int dxgiErrorDeviceRemoved = unchecked((int)0x887A0005);
        const int dxgiErrorDeviceReset = unchecked((int)0x887A0007);
        const int dxgiErrorDriverInternalError = unchecked((int)0x887A0020);
        return ex.HResult is dxgiErrorDeviceRemoved or dxgiErrorDeviceReset or dxgiErrorDriverInternalError
            || ex.Message.Contains("DXGI_ERROR_DEVICE_REMOVED", StringComparison.OrdinalIgnoreCase)
            || ex.Message.Contains("DXGI_ERROR_DEVICE_RESET", StringComparison.OrdinalIgnoreCase)
            || ex.Message.Contains("Forced DXGI device lost", StringComparison.OrdinalIgnoreCase);
    }

    private static string DeviceLostReason(Exception ex)
    {
        return $"hresult=0x{ex.HResult:X8}; {ex.Message}";
    }

    private bool TryResetDeviceAfterLoss(string reason)
    {
        _deviceResetAttempts++;
        _deviceResetAttemptCount++;
        if (_deviceResetAttempts > 2)
        {
            return false;
        }
        try
        {
            DisposeDeviceResources(clearDeviceContext: true);
            InitializeDevice();
            ResizeSwapChainResources();
            RebuildGeometry();
            LastError = string.Empty;
            DeviceRemovedReason = reason;
            _consecutiveRenderFailures = 0;
            Invalidate();
            var reset = _renderTargetView is not null && _depthStencilView is not null;
            if (reset)
            {
                _deviceResetCount++;
            }
            return reset;
        }
        catch (Exception resetError)
        {
            LastError = resetError.Message;
            DeviceRemovedReason = $"{reason}; reset_failed={resetError.Message}";
            DisposeDeviceResources(clearDeviceContext: true);
            return false;
        }
    }

    public bool TryApplyMaterialParameters(IReadOnlyCollection<int> affectedSubmeshes, out string error)
    {
        error = string.Empty;
        if (_device is null || _context is null || _cameraBuffer is null)
        {
            error = "D3D11 material renderer is not initialized.";
            _materialParameterApplyFailureCount++;
            return false;
        }
        var affected = affectedSubmeshes.ToHashSet();
        _affectedMaterialParameterBatchCount += _batches.Count(batch => affected.Contains(batch.SubmeshIndex));
        _materialParameterApplyCount++;
        Invalidate();
        return true;
    }

    private D3D11CameraConstants BuildCameraConstants(D3D11SubmeshBatch batch)
    {
        var materials = batch.Materials;
        var parameters = _materials.ParametersForSubmesh(batch.SubmeshIndex);
        var tint = parameters.TintColor ?? Vector3.One;
        var emissiveColor = parameters.EmissiveColor ?? Vector3.One;
        return new D3D11CameraConstants
        {
            WorldViewProjection = _camera.WorldViewProjection,
            World = _camera.World,
            CameraPosition = -_camera.Forward * Math.Max(10.0f, _camera.SceneSize * 4.0f + 10.0f),
            MaterialRoughness = 0.45f,
            LightDirection = Vector3.Normalize(new Vector3(-0.35f, -0.55f, -0.65f)),
            MaterialMetallic = 0.0f,
            LightColor = new Vector3(1.0f, 0.98f, 0.92f),
            MaterialHeightScale = parameters.HeightScale ?? 0.025f,
            AmbientColor = new Vector3(0.22f, 0.24f, 0.28f),
            MaterialHasNormal = materials.Normal is null ? 0.0f : 1.0f,
            MaterialHasBase = materials.Base is null ? 0.0f : 1.0f,
            MaterialHasSpecular = materials.Specular is null ? 0.0f : 1.0f,
            MaterialHasRoughness = materials.Roughness is null ? 0.0f : 1.0f,
            MaterialHasMetallic = materials.Metallic is null ? 0.0f : 1.0f,
            MaterialHasHeight = materials.Height is null ? 0.0f : 1.0f,
            MaterialHasEmissive = materials.Emissive is null ? 0.0f : 1.0f,
            MaterialDebugMode = TexturesEnabled ? _materialDebugMode : 7.0f,
            MaterialBaseAdjustments = new Vector4(
                parameters.TextureBrightness ?? 1.0f,
                parameters.Contrast ?? 1.0f,
                parameters.Saturation ?? 1.0f,
                parameters.Gamma ?? 1.0f),
            MaterialTint = new Vector4(tint, parameters.TintColor.HasValue ? 1.0f : 0.0f),
            MaterialBaseAdvanced = new Vector4(
                (parameters.BaseColorLift ?? 0) / 255.0f,
                (parameters.ValueMax ?? 255) / 255.0f,
                (parameters.AutoBalance ?? 0) / 100.0f,
                (parameters.ShadowLift ?? 0) / 100.0f),
            MaterialBasePost = new Vector4(parameters.PostContrastBrightness ?? 1.0f, 0.0f, 0.0f, 0.0f),
            MaterialSurfaceOverrides = new Vector4(
                parameters.Roughness ?? 0.0f,
                parameters.Metalness ?? 0.0f,
                parameters.Specular ?? 0.0f,
                parameters.HeightScale ?? 0.0f),
            MaterialSurfaceOverrideFlags = new Vector4(
                parameters.Roughness.HasValue ? 1.0f : 0.0f,
                parameters.Metalness.HasValue ? 1.0f : 0.0f,
                parameters.Specular.HasValue ? 1.0f : 0.0f,
                parameters.HeightScale.HasValue ? 1.0f : 0.0f),
            MaterialSurfaceTransforms = new Vector4(
                parameters.RoughnessScale ?? 1.0f,
                (parameters.RoughnessMin ?? 0) / 255.0f,
                (parameters.RoughnessMax ?? 255) / 255.0f,
                parameters.RoughnessInverted == true ? 1.0f : 0.0f),
            MaterialSurfaceTransforms2 = new Vector4(
                parameters.MetalnessScale ?? 1.0f,
                (parameters.MetalnessMin ?? 0) / 255.0f,
                (parameters.MetalnessMax ?? 255) / 255.0f,
                parameters.MetalnessInverted == true ? 1.0f : 0.0f),
            MaterialSurfaceBlends = new Vector4(
                parameters.RoughnessBlendTarget ?? 0.0f,
                parameters.RoughnessBlendStrength ?? 0.0f,
                parameters.MetalnessBlendTarget ?? 0.0f,
                parameters.MetalnessBlendStrength ?? 0.0f),
            MaterialEmissiveOverride = new Vector4(
                emissiveColor,
                parameters.EmissiveIntensity ?? 1.0f),
            MaterialEmissiveOverrideFlags = new Vector4(
                parameters.EmissiveColor.HasValue ? 1.0f : 0.0f,
                parameters.EmissiveIntensity.HasValue ? 1.0f : 0.0f,
                0.0f,
                0.0f),
        };
    }

    private void UnbindGeometryResources()
    {
        if (_context is null)
        {
            return;
        }
        _context.PSSetShaderResources(0u, EmptyMaterialShaderResources);
        _context.IASetVertexBuffer(0u, (ID3D11Buffer?)null, 0u);
        _context.IASetIndexBuffer((ID3D11Buffer?)null, Format.Unknown, 0);
        _context.OMSetRenderTargets((ID3D11RenderTargetView?)null, null);
    }

    private void DisposeBatches()
    {
        UnbindGeometryResources();
        foreach (var batch in _batches)
        {
            DisposeBatch(batch);
        }
        _batches.Clear();
        _residentGeometryBytes = 0;
    }

    private void DisposeDeviceResources(bool clearDeviceContext)
    {
        DisposeBatches();
        ClearTextureCache();
        DiscardTextureResourceRefreshState();
        _blendState?.Dispose();
        _overlayBlendState?.Dispose();
        _depthState?.Dispose();
        _overlayDepthState?.Dispose();
        _rasterizerState?.Dispose();
        _cameraBuffer?.Dispose();
        _overlayCameraBuffer?.Dispose();
        _samplerState?.Dispose();
        _inputLayout?.Dispose();
        _overlayInputLayout?.Dispose();
        _pixelShader?.Dispose();
        _overlayPixelShader?.Dispose();
        _vertexShader?.Dispose();
        _overlayVertexShader?.Dispose();
        _depthStencilView?.Dispose();
        _depthTexture?.Dispose();
        _renderTargetView?.Dispose();
        _swapChain?.Dispose();
        if (clearDeviceContext)
        {
            _context?.ClearState();
            _context?.Flush();
            _context?.Dispose();
            _device?.Dispose();
            _context = null;
            _device = null;
        }
        _blendState = null;
        _overlayBlendState = null;
        _depthState = null;
        _overlayDepthState = null;
        _rasterizerState = null;
        _cameraBuffer = null;
        _overlayCameraBuffer = null;
        _samplerState = null;
        _inputLayout = null;
        _overlayInputLayout = null;
        _pixelShader = null;
        _overlayPixelShader = null;
        _vertexShader = null;
        _overlayVertexShader = null;
        _depthStencilView = null;
        _depthTexture = null;
        _renderTargetView = null;
        _swapChain = null;
        _renderResourcesDirty = true;
        DiscardPendingVertexUpdates();
        _geometryDirty = true;
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            DisposeDeviceResources(clearDeviceContext: true);
        }
        base.Dispose(disposing);
    }
}

[StructLayout(LayoutKind.Sequential)]
internal readonly record struct D3D11MaterialVertex(Vector3 Position, Vector3 Normal, Vector3 Tangent, Vector3 Bitangent, Vector2 TexCoord);

[StructLayout(LayoutKind.Sequential)]
internal struct D3D11CameraConstants
{
    public Matrix4x4 WorldViewProjection;
    public Matrix4x4 World;
    public Vector3 CameraPosition;
    public float MaterialRoughness;
    public Vector3 LightDirection;
    public float MaterialMetallic;
    public Vector3 LightColor;
    public float MaterialHeightScale;
    public Vector3 AmbientColor;
    public float MaterialHasNormal;
    public float MaterialHasBase;
    public float MaterialHasSpecular;
    public float MaterialHasRoughness;
    public float MaterialHasMetallic;
    public float MaterialHasHeight;
    public float MaterialHasEmissive;
    public float MaterialDebugMode;
    public float MaterialPadding;
    public Vector4 MaterialBaseAdjustments;
    public Vector4 MaterialTint;
    public Vector4 MaterialBaseAdvanced;
    public Vector4 MaterialBasePost;
    public Vector4 MaterialSurfaceOverrides;
    public Vector4 MaterialSurfaceOverrideFlags;
    public Vector4 MaterialSurfaceTransforms;
    public Vector4 MaterialSurfaceTransforms2;
    public Vector4 MaterialSurfaceBlends;
    public Vector4 MaterialEmissiveOverride;
    public Vector4 MaterialEmissiveOverrideFlags;
}
