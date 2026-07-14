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
    private ObjDocument _document;
    private NetMaterialSet _materials;
    private NetTextureSet _textureSet;
    private NetSceneState _scene;
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
    private ID3D11GeometryShader? _vertexMarkerGeometryShader;
    private ID3D11PixelShader? _overlayPixelShader;
    private ID3D11InputLayout? _inputLayout;
    private ID3D11InputLayout? _overlayInputLayout;
    private ID3D11SamplerState? _samplerState;
    private ID3D11Buffer? _cameraBuffer;
    private ID3D11Buffer? _overlayCameraBuffer;
    private ID3D11RasterizerState? _rasterizerState;
    private ID3D11RasterizerState? _doubleSidedRasterizerState;
    private ID3D11BlendState? _blendState;
    private ID3D11BlendState? _transparentBlendState;
    private ID3D11BlendState? _overlayBlendState;
    private ID3D11DepthStencilState? _depthState;
    private ID3D11DepthStencilState? _transparentDepthState;
    private ID3D11DepthStencilState? _overlayDepthState;
    private ID3D11DepthStencilState? _overlayNoDepthState;
    private ID3D11DepthStencilState? _gizmoDepthState;
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
    private int _overlaySelectedSubmeshIndex = -1;
    private bool _overlayShowWire;
    private bool _overlayShowVertices;
    private bool _overlayShowXRay;
    private Point? _overlayBrushCursor;
    private float _overlayBrushRadius = 24.0f;
    private int _materialDebugMode;
    private long _texturedSolidBatchDrawCount;
    private long _untexturedSolidBatchDrawCount;
    private long _transparentSolidBatchDrawCount;
    private long _wireOverlayDrawCount;
    private long _vertexOverlayBatchDrawCount;
    private int _consecutiveRenderFailures;
    private int _deviceResetAttempts;
    private long _deviceResetAttemptCount;
    private long _deviceResetCount;
    private long _materialParameterApplyCount;
    private long _materialParameterApplyFailureCount;
    private long _affectedMaterialParameterBatchCount;
    private uint _maximumFrameLatency;
    private D3D11PresentationSettings _presentationSettings = new();

    public event Action<string>? BackendUnavailable;
    public event Action<double, double, string>? FrameRendered;

    public D3D11MaterialViewport(ObjDocument document, NetMaterialSet materials, NetTextureSet textureSet, NetSceneState scene)
    {
        _document = document;
        _materials = materials;
        _textureSet = textureSet;
        _scene = scene;
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
            _materialDebugMode = Math.Clamp(value, 0, 12);
        }
    }
    public bool ShowSolid { get; set; } = true;
    public bool TexturesEnabled { get; set; } = true;
    public D3D11PresentationSettings PresentationSettings => _presentationSettings;
    public bool IsInitialized => _device is not null && _swapChain is not null;
    public uint PresentSyncInterval => string.Equals(
        Environment.GetEnvironmentVariable("CDMW_MESH_DOTNET_D3D11_NO_VSYNC"),
        "1",
        StringComparison.OrdinalIgnoreCase) ? 0u : 1u;
    public uint MaximumFrameLatency => _maximumFrameLatency;
    public string PresentationModel => _swapChain is null ? "unavailable" : "flip_discard";

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
        bool showXRay,
        Point? brushCursor,
        float brushRadius)
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
        _overlayBrushCursor = brushCursor;
        _overlayBrushRadius = Math.Clamp(brushRadius, 1.0f, 512.0f);
    }

    public void UpdateCamera(NetViewportCamera camera)
    {
        _center = camera.Center;
        _bounds = camera.Bounds;
        _camera = camera;
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
        using var dxgiDevice1 = _device.QueryInterface<IDXGIDevice1>();
        dxgiDevice1.SetMaximumFrameLatency(1);
        _maximumFrameLatency = 1;
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
            SwapEffect = SwapEffect.FlipDiscard,
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
        Compiler.CompileFromFile(shaderPath, null, null, "GSVertexMarker", "gs_5_0", ShaderFlags.EnableStrictness, EffectFlags.None, out var markerGsBlob, out var markerGsError).CheckError();
        Compiler.CompileFromFile(shaderPath, null, null, "PSOverlay", "ps_5_0", ShaderFlags.EnableStrictness, EffectFlags.None, out var overlayPsBlob, out var overlayPsError).CheckError();
        using (vsBlob)
        using (psBlob)
        using (vsError)
        using (psError)
        using (overlayVsBlob)
        using (markerGsBlob)
        using (overlayPsBlob)
        using (overlayVsError)
        using (markerGsError)
        using (overlayPsError)
        {
            _vertexShader = _device.CreateVertexShader(vsBlob.BufferPointer.ToPointer(), vsBlob.BufferSize, null);
            _pixelShader = _device.CreatePixelShader(psBlob.BufferPointer.ToPointer(), psBlob.BufferSize, null);
            _overlayVertexShader = _device.CreateVertexShader(overlayVsBlob.BufferPointer.ToPointer(), overlayVsBlob.BufferSize, null);
            _vertexMarkerGeometryShader = _device.CreateGeometryShader(markerGsBlob.BufferPointer.ToPointer(), markerGsBlob.BufferSize, null);
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
        _rasterizerState = _device.CreateRasterizerState(new RasterizerDescription(CullMode.Back, FillMode.Solid));
        _doubleSidedRasterizerState = _device.CreateRasterizerState(new RasterizerDescription(CullMode.None, FillMode.Solid));
        _blendState = _device.CreateBlendState(BlendDescription.Opaque);
        _transparentBlendState = _device.CreateBlendState(BlendDescription.NonPremultiplied);
        _overlayBlendState = _device.CreateBlendState(BlendDescription.NonPremultiplied);
        _depthState = _device.CreateDepthStencilState(DepthStencilDescription.Default);
        var transparentDepthDescription = DepthStencilDescription.Default;
        transparentDepthDescription.DepthWriteMask = DepthWriteMask.Zero;
        _transparentDepthState = _device.CreateDepthStencilState(transparentDepthDescription);
        var overlayDepthDescription = DepthStencilDescription.Default;
        // Selection faces and outlines reuse the mesh surface positions. Accept
        // equal depth so the solid pass cannot reject its own highlight.
        overlayDepthDescription.DepthFunc = ComparisonFunction.LessEqual;
        overlayDepthDescription.DepthWriteMask = DepthWriteMask.Zero;
        _overlayDepthState = _device.CreateDepthStencilState(overlayDepthDescription);
        var overlayNoDepthDescription = DepthStencilDescription.Default;
        overlayNoDepthDescription.DepthEnable = false;
        overlayNoDepthDescription.DepthWriteMask = DepthWriteMask.Zero;
        _overlayNoDepthState = _device.CreateDepthStencilState(overlayNoDepthDescription);
        _gizmoDepthState = _device.CreateDepthStencilState(overlayNoDepthDescription);
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
        _renderTargetView = _device.CreateRenderTargetView(
            backBuffer,
            new RenderTargetViewDescription(
                backBuffer,
                RenderTargetViewDimension.Texture2D,
                Format.B8G8R8A8_UNorm_SRgb,
                0,
                0,
                1));
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

    private unsafe double RenderFrame(
        bool present = true,
        bool includeOverlays = true,
        bool replacementOnly = false)
    {
        if (_context is null || _swapChain is null || _renderTargetView is null || _depthStencilView is null || _cameraBuffer is null)
        {
            return 0.0;
        }
        if (present && string.Equals(Environment.GetEnvironmentVariable("CDMW_MESH_DOTNET_FORCE_D3D11_PRESENT_FAILURE"), "1", StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException("Forced DXGI device lost during Present for D3D11 recovery testing.");
        }
        BeginOverlayFrame();
        // The render target is sRGB. Supply the workbench background in linear
        // space so enabling correct material output does not brighten the UI.
        _context.ClearRenderTargetView(_renderTargetView, new Color4(0.00598f, 0.00719f, 0.01002f, 1.0f));
        _context.ClearDepthStencilView(_depthStencilView, DepthStencilClearFlags.Depth, 1.0f, 0);
        var previousCamera = _camera;
        var previousShowSolid = ShowSolid;
        var previousTexturesEnabled = TexturesEnabled;
        var previousMaterialDebugMode = _materialDebugMode;
        var previousShowWire = _overlayShowWire;
        var previousShowVertices = _overlayShowVertices;
        var previousShowXRay = _overlayShowXRay;
        foreach (var pane in PanesForFrame(replacementOnly))
        {
            ActivateRenderPane(pane);
            DrawActiveRenderPane(includeOverlays, replacementOnly);
            RecordActivePaneRender();
        }
        if (includeOverlays && !replacementOnly)
        {
            DrawPaneDividerOverlay();
        }
        _activeRenderPane = null;
        _camera = previousCamera;
        ShowSolid = previousShowSolid;
        TexturesEnabled = previousTexturesEnabled;
        _materialDebugMode = previousMaterialDebugMode;
        _overlayShowWire = previousShowWire;
        _overlayShowVertices = previousShowVertices;
        _overlayShowXRay = previousShowXRay;
        if (!present)
        {
            _context.Flush();
            return 0.0;
        }
        var presentStart = Stopwatch.GetTimestamp();
        _swapChain.Present(PresentSyncInterval, PresentFlags.None);
        return (Stopwatch.GetTimestamp() - presentStart) * 1000.0 / Stopwatch.Frequency;
    }

    private void DrawActiveRenderPane(bool includeOverlays, bool replacementOnly)
    {
        if (_context is null || _renderTargetView is null || _depthStencilView is null || _cameraBuffer is null)
        {
            return;
        }
        _context.RSSetState(_rasterizerState);
        _context.OMSetRenderTargets(_renderTargetView, _depthStencilView);
        _context.OMSetDepthStencilState(
            _presentationSettings.DisableDepthTest ? _overlayNoDepthState : _depthState);
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
            var visibleBatches = _batches
                .Where(batch =>
                    ActivePaneIncludes(batch.SubmeshIndex)
                    && !(replacementOnly && _scene.IsReference(batch.SubmeshIndex))
                    && !(_scene.ComparisonMode == "overlay" && _scene.IsReference(batch.SubmeshIndex))
                    && _materials.ParametersForSubmesh(batch.MaterialSubmeshIndex).Visible is not false)
                .ToArray();
            foreach (var batch in visibleBatches.Where(batch => !IsAlphaBlendBatch(batch)))
            {
                DrawSolidBatch(batch, transparent: false);
            }
            var transparentBatches = visibleBatches
                .Where(IsAlphaBlendBatch)
                .OrderByDescending(TransparentSortDistanceSquared)
                .ToArray();
            if (transparentBatches.Length > 0)
            {
                _context.OMSetBlendState(_transparentBlendState ?? _overlayBlendState);
                _context.OMSetDepthStencilState(
                    _presentationSettings.DisableDepthTest ? _overlayNoDepthState : _transparentDepthState);
                foreach (var batch in transparentBatches)
                {
                    DrawSolidBatch(batch, transparent: true);
                }
                _context.OMSetBlendState(_blendState);
                _context.OMSetDepthStencilState(
                    _presentationSettings.DisableDepthTest ? _overlayNoDepthState : _depthState);
            }
        }
        if (includeOverlays)
        {
            DrawD3D11Overlay();
        }
    }

    private bool IsAlphaBlendBatch(D3D11SubmeshBatch batch)
    {
        return string.Equals(
            _materials.AlphaModeForSubmesh(batch.MaterialSubmeshIndex),
            "blend",
            StringComparison.OrdinalIgnoreCase);
    }

    private float TransparentSortDistanceSquared(D3D11SubmeshBatch batch)
    {
        var world = ActivePaneModelMatrix(batch.SubmeshIndex) * _camera.World;
        var center = Vector3.Transform(batch.Center, world);
        var cameraDistance = Math.Max(10.0f, _camera.SceneSize * 4.0f + 10.0f);
        return Vector3.DistanceSquared(center, new Vector3(0.0f, 0.0f, -cameraDistance));
    }

    private void DrawSolidBatch(D3D11SubmeshBatch batch, bool transparent)
    {
        if (_context is null || _cameraBuffer is null)
        {
            return;
        }
        _context.RSSetState(
            _materials.DoubleSidedForSubmesh(batch.MaterialSubmeshIndex)
                ? _doubleSidedRasterizerState
                : _rasterizerState);
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
        if (transparent)
        {
            _transparentSolidBatchDrawCount++;
        }
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
        DisposeOverlayDynamicResources();
        _blendState?.Dispose();
        _transparentBlendState?.Dispose();
        _overlayBlendState?.Dispose();
        _depthState?.Dispose();
        _transparentDepthState?.Dispose();
        _overlayDepthState?.Dispose();
        _overlayNoDepthState?.Dispose();
        _gizmoDepthState?.Dispose();
        _rasterizerState?.Dispose();
        _doubleSidedRasterizerState?.Dispose();
        _cameraBuffer?.Dispose();
        _overlayCameraBuffer?.Dispose();
        _samplerState?.Dispose();
        _inputLayout?.Dispose();
        _overlayInputLayout?.Dispose();
        _pixelShader?.Dispose();
        _overlayPixelShader?.Dispose();
        _vertexMarkerGeometryShader?.Dispose();
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
            _maximumFrameLatency = 0;
        }
        _blendState = null;
        _transparentBlendState = null;
        _overlayBlendState = null;
        _depthState = null;
        _transparentDepthState = null;
        _overlayDepthState = null;
        _overlayNoDepthState = null;
        _gizmoDepthState = null;
        _rasterizerState = null;
        _doubleSidedRasterizerState = null;
        _cameraBuffer = null;
        _overlayCameraBuffer = null;
        _samplerState = null;
        _inputLayout = null;
        _overlayInputLayout = null;
        _pixelShader = null;
        _overlayPixelShader = null;
        _vertexMarkerGeometryShader = null;
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
