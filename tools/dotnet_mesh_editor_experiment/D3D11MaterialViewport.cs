using System.Diagnostics;
using System.Drawing.Imaging;
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
    private readonly Dictionary<string, ID3D11ShaderResourceView> _textureSrvCache = new(StringComparer.OrdinalIgnoreCase);
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
    private bool _overlayShowXRay;
    private int _materialDebugMode;
    private int _consecutiveRenderFailures;
    private int _deviceResetAttempts;

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
    public int MaterialDebugMode
    {
        get => _materialDebugMode;
        set
        {
            _materialDebugMode = Math.Clamp(value, 0, 6);
            Invalidate();
        }
    }
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
        _overlayShowXRay = showXRay;
        Invalidate();
    }

    public void RefreshGeometry()
    {
        _geometryDirty = true;
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
        if (!File.Exists(outputPath))
        {
            File.WriteAllText(outputPath, shaderText, Encoding.UTF8);
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

    private void RebuildGeometry()
    {
        DisposeBatches();
        if (_device is null)
        {
            return;
        }
        for (var submeshIndex = 0; submeshIndex < _document.Submeshes.Count; submeshIndex++)
        {
            var batch = BuildBatch(submeshIndex, _document.Submeshes[submeshIndex]);
            if (batch is not null)
            {
                _batches.Add(batch);
            }
        }
        _geometryDirty = false;
    }

    private unsafe D3D11SubmeshBatch? BuildBatch(int submeshIndex, ObjSubmesh submesh)
    {
        if (_device is null)
        {
            return null;
        }
        var vertices = new List<D3D11MaterialVertex>();
        var indices = new List<int>();
        foreach (var face in submesh.Faces)
        {
            if (face.Corners.Length != 3)
            {
                continue;
            }
            var normal = FaceNormal(submesh, face);
            var tangentSpace = FaceTangentSpace(submesh, face, normal);
            var start = vertices.Count;
            var valid = true;
            foreach (var corner in face.Corners)
            {
                if (corner.VertexIndex < 0 || corner.VertexIndex >= submesh.Vertices.Count)
                {
                    valid = false;
                    break;
                }
                var position = submesh.Vertices[corner.VertexIndex];
                var cornerNormal = NormalForCorner(submesh, corner, normal);
                var uv = corner.UvIndex >= 0 && corner.UvIndex < submesh.Uvs.Count ? submesh.Uvs[corner.UvIndex] : new Vec2(0, 0);
                vertices.Add(new D3D11MaterialVertex(
                    new Vector3(position.X, position.Y, position.Z),
                    new Vector3((float)cornerNormal.X, (float)cornerNormal.Y, (float)cornerNormal.Z),
                    new Vector3((float)tangentSpace.Tangent.X, (float)tangentSpace.Tangent.Y, (float)tangentSpace.Tangent.Z),
                    new Vector3((float)tangentSpace.Bitangent.X, (float)tangentSpace.Bitangent.Y, (float)tangentSpace.Bitangent.Z),
                    new Vector2(uv.U, 1.0f - uv.V)));
            }
            if (!valid)
            {
                while (vertices.Count > start)
                {
                    vertices.RemoveAt(vertices.Count - 1);
                }
                continue;
            }
            indices.Add(start);
            indices.Add(start + 1);
            indices.Add(start + 2);
        }
        if (vertices.Count == 0 || indices.Count == 0)
        {
            return null;
        }
        fixed (D3D11MaterialVertex* vertexPtr = vertices.ToArray())
        fixed (int* indexPtr = indices.ToArray())
        {
            var vertexBuffer = _device.CreateBuffer(new BufferDescription((uint)(vertices.Count * Marshal.SizeOf<D3D11MaterialVertex>()), BindFlags.VertexBuffer), new SubresourceData((IntPtr)vertexPtr));
            var indexBuffer = _device.CreateBuffer(new BufferDescription((uint)(indices.Count * sizeof(int)), BindFlags.IndexBuffer), new SubresourceData((IntPtr)indexPtr));
            return new D3D11SubmeshBatch(vertexBuffer, indexBuffer, indices.Count, CreateMaterialResources(submeshIndex));
        }
    }

    private D3D11MaterialResources CreateMaterialResources(int submeshIndex)
    {
        return new D3D11MaterialResources(
            CreateTextureSrv(_materials.BaseTexturePathForSubmesh(submeshIndex)),
            CreateTextureSrv(_materials.NormalTexturePathForSubmesh(submeshIndex)),
            CreateTextureSrv(_materials.SpecularTexturePathForSubmesh(submeshIndex)),
            CreateTextureSrv(_materials.RoughnessTexturePathForSubmesh(submeshIndex)),
            CreateTextureSrv(_materials.MetallicTexturePathForSubmesh(submeshIndex)),
            CreateTextureSrv(_materials.HeightTexturePathForSubmesh(submeshIndex)),
            CreateTextureSrv(_materials.EmissiveTexturePathForSubmesh(submeshIndex)));
    }

    private unsafe ID3D11ShaderResourceView? CreateTextureSrv(string path)
    {
        if (_device is null)
        {
            return null;
        }
        var bitmap = _textureSet.BitmapForPath(path);
        if (bitmap is null)
        {
            return null;
        }
        var cacheKey = TextureCacheKey(path);
        if (_textureSrvCache.TryGetValue(cacheKey, out var cached))
        {
            return cached;
        }
        using var converted = new Bitmap(bitmap.Width, bitmap.Height, PixelFormat.Format32bppArgb);
        using (var graphics = Graphics.FromImage(converted))
        {
            graphics.DrawImageUnscaled(bitmap, 0, 0);
        }
        var rect = new Rectangle(0, 0, converted.Width, converted.Height);
        var data = converted.LockBits(rect, ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
        try
        {
            var desc = new Texture2DDescription
            {
                Width = (uint)converted.Width,
                Height = (uint)converted.Height,
                MipLevels = 1,
                ArraySize = 1,
                Format = Format.B8G8R8A8_UNorm,
                SampleDescription = new SampleDescription(1, 0),
                Usage = ResourceUsage.Immutable,
                BindFlags = BindFlags.ShaderResource,
            };
            using var texture = _device.CreateTexture2D(desc, new[] { new SubresourceData(data.Scan0, (uint)data.Stride) });
            var srv = _device.CreateShaderResourceView(texture);
            _textureSrvCache[cacheKey] = srv;
            return srv;
        }
        finally
        {
            converted.UnlockBits(data);
        }
    }

    private static string TextureCacheKey(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return string.Empty;
        }
        var fullPath = Path.GetFullPath(path);
        try
        {
            var info = new FileInfo(fullPath);
            return $"{fullPath}|{info.Length}|{info.LastWriteTimeUtc.Ticks}";
        }
        catch
        {
            return fullPath;
        }
    }

    private void ClearTextureCache()
    {
        foreach (var srv in _textureSrvCache.Values)
        {
            srv.Dispose();
        }
        _textureSrvCache.Clear();
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
        foreach (var batch in _batches)
        {
            var constants = BuildCameraConstants(batch.Materials);
            _context.UpdateSubresource(ref constants, _cameraBuffer);
            _context.VSSetConstantBuffer(0u, _cameraBuffer);
            _context.PSSetConstantBuffer(0u, _cameraBuffer);
            var srvs = batch.Materials.ToSrvArray();
            _context.PSSetShaderResources(0u, srvs);
            _context.IASetVertexBuffer(0u, batch.VertexBuffer, (uint)Marshal.SizeOf<D3D11MaterialVertex>());
            _context.IASetIndexBuffer(batch.IndexBuffer, Format.R32_UInt, 0);
            _context.DrawIndexed((uint)batch.IndexCount, 0, 0);
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
            return _renderTargetView is not null && _depthStencilView is not null;
        }
        catch (Exception resetError)
        {
            LastError = resetError.Message;
            DeviceRemovedReason = $"{reason}; reset_failed={resetError.Message}";
            DisposeDeviceResources(clearDeviceContext: true);
            return false;
        }
    }

    private D3D11CameraConstants BuildCameraConstants(D3D11MaterialResources materials)
    {
        return new D3D11CameraConstants
        {
            WorldViewProjection = _camera.WorldViewProjection,
            World = _camera.World,
            CameraPosition = -_camera.Forward * Math.Max(10.0f, _camera.SceneSize * 4.0f + 10.0f),
            MaterialRoughness = 0.45f,
            LightDirection = Vector3.Normalize(new Vector3(-0.35f, -0.55f, -0.65f)),
            MaterialMetallic = 0.0f,
            LightColor = new Vector3(1.0f, 0.98f, 0.92f),
            MaterialHeightScale = 0.025f,
            AmbientColor = new Vector3(0.22f, 0.24f, 0.28f),
            MaterialHasNormal = materials.Normal is null ? 0.0f : 1.0f,
            MaterialHasBase = materials.Base is null ? 0.0f : 1.0f,
            MaterialHasSpecular = materials.Specular is null ? 0.0f : 1.0f,
            MaterialHasRoughness = materials.Roughness is null ? 0.0f : 1.0f,
            MaterialHasMetallic = materials.Metallic is null ? 0.0f : 1.0f,
            MaterialHasHeight = materials.Height is null ? 0.0f : 1.0f,
            MaterialHasEmissive = materials.Emissive is null ? 0.0f : 1.0f,
            MaterialDebugMode = _materialDebugMode,
        };
    }

    private static System.Windows.Media.Media3D.Vector3D NormalForCorner(ObjSubmesh submesh, ObjCorner corner, System.Windows.Media.Media3D.Vector3D fallback)
    {
        if (corner.NormalIndex >= 0 && corner.NormalIndex < submesh.Normals.Count)
        {
            var normal = submesh.Normals[corner.NormalIndex];
            var vector = new System.Windows.Media.Media3D.Vector3D(normal.X, normal.Y, normal.Z);
            if (vector.LengthSquared > 0.0001)
            {
                vector.Normalize();
                return vector;
            }
        }
        return fallback;
    }

    private static (System.Windows.Media.Media3D.Vector3D Tangent, System.Windows.Media.Media3D.Vector3D Bitangent) FaceTangentSpace(ObjSubmesh submesh, ObjFace face, System.Windows.Media.Media3D.Vector3D normal)
    {
        if (face.Corners.Length != 3 || face.Corners.Any(corner => corner.VertexIndex < 0 || corner.VertexIndex >= submesh.Vertices.Count || corner.UvIndex < 0 || corner.UvIndex >= submesh.Uvs.Count))
        {
            return FallbackTangentSpace(normal);
        }
        var p0 = submesh.Vertices[face.Corners[0].VertexIndex];
        var p1 = submesh.Vertices[face.Corners[1].VertexIndex];
        var p2 = submesh.Vertices[face.Corners[2].VertexIndex];
        var uv0 = submesh.Uvs[face.Corners[0].UvIndex];
        var uv1 = submesh.Uvs[face.Corners[1].UvIndex];
        var uv2 = submesh.Uvs[face.Corners[2].UvIndex];
        var edge1 = new System.Windows.Media.Media3D.Vector3D(p1.X - p0.X, p1.Y - p0.Y, p1.Z - p0.Z);
        var edge2 = new System.Windows.Media.Media3D.Vector3D(p2.X - p0.X, p2.Y - p0.Y, p2.Z - p0.Z);
        var du1 = uv1.U - uv0.U;
        var dv1 = uv1.V - uv0.V;
        var du2 = uv2.U - uv0.U;
        var dv2 = uv2.V - uv0.V;
        var determinant = (du1 * dv2) - (du2 * dv1);
        if (Math.Abs(determinant) < 0.000001)
        {
            return FallbackTangentSpace(normal);
        }
        var scale = 1.0 / determinant;
        var tangent = (edge1 * dv2 - edge2 * dv1) * scale;
        var bitangent = (edge2 * du1 - edge1 * du2) * scale;
        tangent.Normalize();
        bitangent.Normalize();
        return (tangent, bitangent);
    }

    private static (System.Windows.Media.Media3D.Vector3D Tangent, System.Windows.Media.Media3D.Vector3D Bitangent) FallbackTangentSpace(System.Windows.Media.Media3D.Vector3D normal)
    {
        var tangent = System.Windows.Media.Media3D.Vector3D.CrossProduct(normal, Math.Abs(normal.Y) < 0.95 ? new System.Windows.Media.Media3D.Vector3D(0, 1, 0) : new System.Windows.Media.Media3D.Vector3D(1, 0, 0));
        if (tangent.LengthSquared < 0.0001)
        {
            tangent = new System.Windows.Media.Media3D.Vector3D(1, 0, 0);
        }
        tangent.Normalize();
        var bitangent = System.Windows.Media.Media3D.Vector3D.CrossProduct(normal, tangent);
        bitangent.Normalize();
        return (tangent, bitangent);
    }

    private static System.Windows.Media.Media3D.Vector3D FaceNormal(ObjSubmesh submesh, ObjFace face)
    {
        if (face.Corners.Length != 3)
        {
            return new System.Windows.Media.Media3D.Vector3D(0, 1, 0);
        }
        var ia = face.Corners[0].VertexIndex;
        var ib = face.Corners[1].VertexIndex;
        var ic = face.Corners[2].VertexIndex;
        if (ia < 0 || ib < 0 || ic < 0 || ia >= submesh.Vertices.Count || ib >= submesh.Vertices.Count || ic >= submesh.Vertices.Count)
        {
            return new System.Windows.Media.Media3D.Vector3D(0, 1, 0);
        }
        var a = submesh.Vertices[ia];
        var b = submesh.Vertices[ib];
        var c = submesh.Vertices[ic];
        var ab = new System.Windows.Media.Media3D.Vector3D(b.X - a.X, b.Y - a.Y, b.Z - a.Z);
        var ac = new System.Windows.Media.Media3D.Vector3D(c.X - a.X, c.Y - a.Y, c.Z - a.Z);
        var normal = System.Windows.Media.Media3D.Vector3D.CrossProduct(ab, ac);
        if (normal.LengthSquared < 0.0001)
        {
            return new System.Windows.Media.Media3D.Vector3D(0, 1, 0);
        }
        normal.Normalize();
        return normal;
    }

    private void UnbindGeometryResources()
    {
        if (_context is null)
        {
            return;
        }
        _context.PSSetShaderResources(0u, new ID3D11ShaderResourceView?[] { null, null, null, null, null, null, null });
        _context.IASetVertexBuffer(0u, (ID3D11Buffer?)null, 0u);
        _context.IASetIndexBuffer((ID3D11Buffer?)null, Format.Unknown, 0);
        _context.OMSetRenderTargets((ID3D11RenderTargetView?)null, null);
    }

    private void DisposeBatches()
    {
        UnbindGeometryResources();
        foreach (var batch in _batches)
        {
            batch.Dispose();
        }
        _batches.Clear();
    }

    private void DisposeDeviceResources(bool clearDeviceContext)
    {
        DisposeBatches();
        ClearTextureCache();
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
}

internal sealed class D3D11SubmeshBatch : IDisposable
{
    public D3D11SubmeshBatch(ID3D11Buffer vertexBuffer, ID3D11Buffer indexBuffer, int indexCount, D3D11MaterialResources materials)
    {
        VertexBuffer = vertexBuffer;
        IndexBuffer = indexBuffer;
        IndexCount = indexCount;
        Materials = materials;
    }

    public ID3D11Buffer VertexBuffer { get; }
    public ID3D11Buffer IndexBuffer { get; }
    public int IndexCount { get; }
    public D3D11MaterialResources Materials { get; }

    public void Dispose()
    {
        Materials.Dispose();
        IndexBuffer.Dispose();
        VertexBuffer.Dispose();
    }
}

internal sealed class D3D11MaterialResources : IDisposable
{
    public D3D11MaterialResources(ID3D11ShaderResourceView? baseTexture, ID3D11ShaderResourceView? normal, ID3D11ShaderResourceView? specular, ID3D11ShaderResourceView? roughness, ID3D11ShaderResourceView? metallic, ID3D11ShaderResourceView? height, ID3D11ShaderResourceView? emissive)
    {
        Base = baseTexture;
        Normal = normal;
        Specular = specular;
        Roughness = roughness;
        Metallic = metallic;
        Height = height;
        Emissive = emissive;
    }

    public ID3D11ShaderResourceView? Base { get; }
    public ID3D11ShaderResourceView? Normal { get; }
    public ID3D11ShaderResourceView? Specular { get; }
    public ID3D11ShaderResourceView? Roughness { get; }
    public ID3D11ShaderResourceView? Metallic { get; }
    public ID3D11ShaderResourceView? Height { get; }
    public ID3D11ShaderResourceView? Emissive { get; }

    public ID3D11ShaderResourceView?[] ToSrvArray()
    {
        return new[] { Base, Normal, Specular, Roughness, Metallic, Height, Emissive };
    }

    public void Dispose()
    {
        // SRVs are device-scoped and shared by D3D11MaterialViewport's texture cache.
    }
}
