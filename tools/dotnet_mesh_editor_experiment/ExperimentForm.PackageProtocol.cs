using System.Diagnostics;
using System.IO;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
    private CancellationTokenSource? _residentPackageLoadCancellation;
    private SynchronizationContext? _residentPackageUiContext;
    private long _residentPackageLoadGeneration;
    private long _residentPackageLoadCount;

    private sealed class PreparedResidentPackage(
        string packagePath,
        ObjDocument document,
        NetMaterialSet materials,
        NetTextureSet textureSet,
        NetSceneState scene,
        double parseMilliseconds,
        double textureMilliseconds) : IDisposable
    {
        private NetTextureSet? _textureSet = textureSet;

        public string PackagePath { get; } = packagePath;
        public ObjDocument Document { get; } = document;
        public NetMaterialSet Materials { get; } = materials;
        public NetTextureSet TextureSet => _textureSet
            ?? throw new ObjectDisposedException(nameof(PreparedResidentPackage));
        public NetSceneState Scene { get; } = scene;
        public double ParseMilliseconds { get; } = parseMilliseconds;
        public double TextureMilliseconds { get; } = textureMilliseconds;

        public NetTextureSet DetachTextureSet()
        {
            var value = TextureSet;
            _textureSet = null;
            return value;
        }

        public void Dispose()
        {
            Interlocked.Exchange(ref _textureSet, null)?.Dispose();
        }
    }

    private void InitializeResidentPackageProtocol()
    {
        _residentPackageUiContext = SynchronizationContext.Current
            ?? new WindowsFormsSynchronizationContext();
    }

    private void HandleResidentPackageLoadRequest(JsonElement root)
    {
        var requestId = JsonLongValue(root, "request_id");
        var generation = JsonLongValue(root, "generation");
        var packagePath = JsonString(root, "package_path").Trim();
        if (requestId <= 0 || generation <= 0 || string.IsNullOrWhiteSpace(packagePath))
        {
            PublishResidentPackageLoadFailure(requestId, generation, "Resident package load request is incomplete.");
            return;
        }
        if (generation <= Interlocked.Read(ref _residentPackageLoadGeneration))
        {
            PublishResidentPackageLoadFailure(requestId, generation, "Resident package load request is stale.");
            return;
        }

        Interlocked.Exchange(ref _residentPackageLoadGeneration, generation);
        var operation = new CancellationTokenSource();
        Interlocked.Exchange(ref _residentPackageLoadCancellation, operation)?.Cancel();
        WriteProtocolEvent("package_load_started", new Dictionary<string, object?>
        {
            ["request_id"] = requestId,
            ["generation"] = generation,
            ["package_path"] = Path.GetFullPath(packagePath),
            ["process_id"] = Environment.ProcessId,
        });
        _ = PrepareAndApplyResidentPackageAsync(packagePath, requestId, generation, operation);
    }

    private async Task PrepareAndApplyResidentPackageAsync(
        string packagePath,
        long requestId,
        long generation,
        CancellationTokenSource operation)
    {
        PreparedResidentPackage? prepared = null;
        try
        {
            prepared = await Task.Run(
                () => PrepareResidentPackage(packagePath, _options.SimplePreview, operation.Token),
                CancellationToken.None).ConfigureAwait(false);
            operation.Token.ThrowIfCancellationRequested();
            var completion = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            try
            {
                var uiContext = _residentPackageUiContext
                    ?? throw new InvalidOperationException("Resident package UI context is not available.");
                if (_viewport.IsDisposed || _viewport.Disposing)
                {
                    throw new InvalidOperationException("Resident viewport is not available for package publication.");
                }
                uiContext.Post(_ =>
                {
                    try
                    {
                        operation.Token.ThrowIfCancellationRequested();
                        if (generation != Interlocked.Read(ref _residentPackageLoadGeneration)
                            || !ReferenceEquals(Volatile.Read(ref _residentPackageLoadCancellation), operation))
                        {
                            throw new OperationCanceledException(operation.Token);
                        }
                        ApplyPreparedResidentPackage(prepared, requestId, generation);
                        prepared = null;
                        completion.TrySetResult();
                    }
                    catch (OperationCanceledException exception)
                    {
                        completion.TrySetCanceled(exception.CancellationToken);
                    }
                    catch (Exception exception)
                    {
                        completion.TrySetException(exception);
                    }
                }, null);
            }
            catch (InvalidOperationException exception)
            {
                completion.TrySetException(exception);
            }
            await completion.Task.ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            // A newer generation or form shutdown owns the resident renderer.
        }
        catch (Exception exception)
        {
            if (generation == Interlocked.Read(ref _residentPackageLoadGeneration)
                && ReferenceEquals(Volatile.Read(ref _residentPackageLoadCancellation), operation))
            {
                PublishResidentPackageLoadFailure(requestId, generation, exception.Message);
            }
        }
        finally
        {
            prepared?.Dispose();
            Interlocked.CompareExchange(ref _residentPackageLoadCancellation, null, operation);
            operation.Dispose();
        }
    }

    private static PreparedResidentPackage PrepareResidentPackage(
        string requestedPackagePath,
        bool previewProfile,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var packagePath = Path.GetFullPath(requestedPackagePath);
        var manifestPath = Path.Combine(packagePath, "manifest.json");
        var sceneMeshPath = Path.Combine(packagePath, "scene.obj");
        var editableMeshPath = Path.Combine(packagePath, "mesh.obj");
        var metadataPath = Path.Combine(packagePath, "mesh.cdmeta.json");
        var materialsPath = Path.Combine(packagePath, "net_materials.json");
        var scenePath = Path.Combine(packagePath, "dotnet_scene.json");
        var geometryPath = File.Exists(manifestPath)
            ? manifestPath
            : File.Exists(sceneMeshPath)
                ? sceneMeshPath
                : editableMeshPath;
        if (!Directory.Exists(packagePath)
            || !File.Exists(geometryPath)
            || !File.Exists(metadataPath)
            || !File.Exists(materialsPath)
            || !File.Exists(scenePath))
        {
            throw new InvalidDataException("The resident .NET preview package is incomplete.");
        }

        var phase = Stopwatch.StartNew();
        var document = ObjDocument.Load(geometryPath);
        cancellationToken.ThrowIfCancellationRequested();
        var materials = NetMaterialSet.Load(materialsPath);
        var scene = NetSceneState.Load(scenePath, document.Submeshes.Count);
        if (previewProfile)
        {
            scene.SetInteractionMode("placement");
            scene.SetComparisonMode("replacement_only");
            scene.SetPresentationOverlayVisibility(gridVisible: false, gizmoVisible: false);
        }
        var parseMilliseconds = phase.Elapsed.TotalMilliseconds;
        var textures = NetTextureSet.Load(materials);
        try
        {
            phase.Restart();
            textures.LoadAsync(materials).GetAwaiter().GetResult();
            cancellationToken.ThrowIfCancellationRequested();
            return new PreparedResidentPackage(
                packagePath,
                document,
                materials,
                textures,
                scene,
                parseMilliseconds,
                phase.Elapsed.TotalMilliseconds);
        }
        catch
        {
            textures.Dispose();
            throw;
        }
    }

    private void ApplyPreparedResidentPackage(
        PreparedResidentPackage prepared,
        long requestId,
        long generation)
    {
        var phase = Stopwatch.StartNew();
        var previousTextures = _textureSet;
        var nextTextures = prepared.TextureSet;
        _viewport.ReplaceResidentPackage(
            prepared.Document,
            prepared.Materials,
            nextTextures,
            prepared.Scene);
        _document = prepared.Document;
        _materials = prepared.Materials;
        _textureSet = prepared.DetachTextureSet();
        _scene = prepared.Scene;
        _editedSubmeshes.Clear();
        _externalTopologyDirty = false;
        _saved = false;
        _rendererDiagnosticCache = null;
        RefreshSubmeshList();
        previousTextures.Dispose();
        var loadCount = Interlocked.Increment(ref _residentPackageLoadCount);
        _statusLabel.Text = $"Resident package loaded: {_document.Submeshes.Count} part(s).";
        WriteProtocolEvent("package_load_applied", new Dictionary<string, object?>
        {
            ["request_id"] = requestId,
            ["generation"] = generation,
            ["package_path"] = prepared.PackagePath,
            ["profile"] = _options.Profile,
            ["process_id"] = Environment.ProcessId,
            ["parse_ms"] = prepared.ParseMilliseconds,
            ["texture_ms"] = prepared.TextureMilliseconds,
            ["apply_ms"] = phase.Elapsed.TotalMilliseconds,
            ["resident_package_load_count"] = loadCount,
            ["resident_scene_load_count"] = _viewport.ResidentSceneLoadCount,
            ["renderer"] = RendererCompactStatusWithLifecycle(),
        });
    }

    private void PublishResidentPackageLoadFailure(long requestId, long generation, string message)
    {
        WritePreparedProtocolEventThreadSafe("package_load_failed", new Dictionary<string, object?>
        {
            ["request_id"] = requestId,
            ["generation"] = generation,
            ["message"] = string.IsNullOrWhiteSpace(message) ? "Resident package load failed." : message,
            ["process_id"] = Environment.ProcessId,
        });
    }

    private void CancelResidentPackageLoad()
    {
        Interlocked.Increment(ref _residentPackageLoadGeneration);
        Interlocked.Exchange(ref _residentPackageLoadCancellation, null)?.Cancel();
    }
}
