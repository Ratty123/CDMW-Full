using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using System.Windows;
using System.Windows.Interop;
using Cdmw.ArchiveLite.App.Infrastructure;
using Cdmw.ArchiveLite.App.Services;

namespace Cdmw.ArchiveLite.App.Controls;

public sealed class DotNetModelPreviewHost : HwndHost
{
    private const string RequiredRendererBackend = "d3d11_vortice_shader";
    private const int WsChild = 0x40000000;
    private const int WsVisible = 0x10000000;
    private const int WsClipChildren = 0x02000000;
    private const int WsClipSiblings = 0x04000000;
    private readonly SemaphoreSlim _switchGate = new(1, 1);
    private readonly object _sessionGate = new();
    private CancellationTokenSource? _switchCancellation;
    private ModelRendererSession? _currentSession;
    private ModelRendererSession? _startingSession;
    private IntPtr _hostHandle;
    private long _generation;
    private int _shutdown;

    public static readonly DependencyProperty PackagePathProperty = DependencyProperty.Register(
        nameof(PackagePath),
        typeof(string),
        typeof(DotNetModelPreviewHost),
        new FrameworkPropertyMetadata(null, FrameworkPropertyMetadataOptions.None, OnPackagePathChanged));

    private static readonly DependencyPropertyKey StatusTextPropertyKey = DependencyProperty.RegisterReadOnly(
        nameof(StatusText),
        typeof(string),
        typeof(DotNetModelPreviewHost),
        new PropertyMetadata(string.Empty));

    public static readonly DependencyProperty StatusTextProperty = StatusTextPropertyKey.DependencyProperty;

    private static readonly DependencyPropertyKey IsLoadingPropertyKey = DependencyProperty.RegisterReadOnly(
        nameof(IsLoading),
        typeof(bool),
        typeof(DotNetModelPreviewHost),
        new PropertyMetadata(false));

    public static readonly DependencyProperty IsLoadingProperty = IsLoadingPropertyKey.DependencyProperty;

    private static readonly DependencyPropertyKey IsReadyPropertyKey = DependencyProperty.RegisterReadOnly(
        nameof(IsReady),
        typeof(bool),
        typeof(DotNetModelPreviewHost),
        new PropertyMetadata(false));

    public static readonly DependencyProperty IsReadyProperty = IsReadyPropertyKey.DependencyProperty;

    public string? PackagePath
    {
        get => (string?)GetValue(PackagePathProperty);
        set => SetValue(PackagePathProperty, value);
    }

    public string StatusText => (string)GetValue(StatusTextProperty);
    public bool IsLoading => (bool)GetValue(IsLoadingProperty);
    public bool IsReady => (bool)GetValue(IsReadyProperty);

    public async Task ShutdownAsync()
    {
        if (Interlocked.Exchange(ref _shutdown, 1) != 0)
        {
            return;
        }
        Interlocked.Increment(ref _generation);
        Interlocked.Exchange(ref _switchCancellation, null)?.Cancel();
        await _switchGate.WaitAsync().ConfigureAwait(true);
        try
        {
            ModelRendererSession? current;
            ModelRendererSession? starting;
            lock (_sessionGate)
            {
                current = _currentSession;
                starting = _startingSession;
                _currentSession = null;
                _startingSession = null;
            }
            if (starting is not null && !ReferenceEquals(starting, current))
            {
                await starting.ShutdownAsync().ConfigureAwait(true);
            }
            if (current is not null)
            {
                await current.ShutdownAsync().ConfigureAwait(true);
            }
            SetValue(IsLoadingPropertyKey, false);
            SetValue(IsReadyPropertyKey, false);
            SetValue(StatusTextPropertyKey, string.Empty);
        }
        finally
        {
            _switchGate.Release();
        }
    }

    protected override HandleRef BuildWindowCore(HandleRef hwndParent)
    {
        _hostHandle = CreateWindowExW(
            0,
            "STATIC",
            string.Empty,
            WsChild | WsVisible | WsClipChildren | WsClipSiblings,
            0,
            0,
            1,
            1,
            hwndParent.Handle,
            IntPtr.Zero,
            GetModuleHandleW(null),
            IntPtr.Zero);
        if (_hostHandle == IntPtr.Zero)
        {
            throw new InvalidOperationException($"Could not create the .NET preview host window (Win32 {Marshal.GetLastWin32Error()}).");
        }
        BeginSwitch(PackagePath);
        return new HandleRef(this, _hostHandle);
    }

    protected override void DestroyWindowCore(HandleRef hwnd)
    {
        DisposeSessionsImmediately();
        if (hwnd.Handle != IntPtr.Zero)
        {
            _ = DestroyWindow(hwnd.Handle);
        }
        _hostHandle = IntPtr.Zero;
    }

    private static void OnPackagePathChanged(DependencyObject dependencyObject, DependencyPropertyChangedEventArgs args)
    {
        ((DotNetModelPreviewHost)dependencyObject).BeginSwitch(args.NewValue as string);
    }

    private void BeginSwitch(string? packagePath)
    {
        if (_hostHandle == IntPtr.Zero || Volatile.Read(ref _shutdown) != 0)
        {
            return;
        }
        var generation = Interlocked.Increment(ref _generation);
        var operation = new CancellationTokenSource();
        Interlocked.Exchange(ref _switchCancellation, operation)?.Cancel();
        _ = SwitchAsync(packagePath, generation, operation);
    }

    private async Task SwitchAsync(string? packagePath, long generation, CancellationTokenSource operation)
    {
        try
        {
            await _switchGate.WaitAsync(operation.Token).ConfigureAwait(true);
            try
            {
                if (string.IsNullOrWhiteSpace(packagePath))
                {
                    var prior = TakeCurrentSession();
                    if (prior is not null)
                    {
                        await prior.ShutdownAsync().ConfigureAwait(true);
                    }
                    if (generation == Volatile.Read(ref _generation))
                    {
                        SetValue(IsLoadingPropertyKey, false);
                        SetValue(IsReadyPropertyKey, false);
                        SetValue(StatusTextPropertyKey, string.Empty);
                    }
                    return;
                }

                SetValue(IsLoadingPropertyKey, true);
                SetValue(StatusTextPropertyKey, LocalizationManager.Get("RendererStarting"));
                var session = await ModelRendererSession.StartAsync(
                    packagePath,
                    _hostHandle,
                    status => SetStatusIfCurrent(generation, status),
                    operation.Token).ConfigureAwait(true);
                lock (_sessionGate)
                {
                    _startingSession = session;
                }
                try
                {
                    using var readyTimeout = CancellationTokenSource.CreateLinkedTokenSource(operation.Token);
                    readyTimeout.CancelAfter(TimeSpan.FromSeconds(30));
                    var backend = await session.Ready.WaitAsync(readyTimeout.Token).ConfigureAwait(true);
                    if (!string.Equals(backend, RequiredRendererBackend, StringComparison.Ordinal))
                    {
                        throw new InvalidDataException($"The preview renderer reported unsupported backend '{backend}'.");
                    }
                    operation.Token.ThrowIfCancellationRequested();
                    if (generation != Volatile.Read(ref _generation))
                    {
                        throw new OperationCanceledException(operation.Token);
                    }

                    ModelRendererSession? prior;
                    lock (_sessionGate)
                    {
                        prior = _currentSession;
                        _currentSession = session;
                        _startingSession = null;
                    }
                    SetValue(IsReadyPropertyKey, true);
                    SetValue(IsLoadingPropertyKey, false);
                    SetValue(StatusTextPropertyKey, LocalizationManager.Get("RendererReady"));
                    if (prior is not null)
                    {
                        await prior.ShutdownAsync().ConfigureAwait(true);
                    }
                }
                catch
                {
                    lock (_sessionGate)
                    {
                        if (ReferenceEquals(_startingSession, session))
                        {
                            _startingSession = null;
                        }
                    }
                    await session.ShutdownAsync().ConfigureAwait(true);
                    throw;
                }
            }
            finally
            {
                _switchGate.Release();
            }
        }
        catch (OperationCanceledException)
        {
            // A newer preview selection or application shutdown owns the host.
        }
        catch (Exception exception)
        {
            if (generation == Volatile.Read(ref _generation) && Volatile.Read(ref _shutdown) == 0)
            {
                var prior = TakeCurrentSession();
                if (prior is not null)
                {
                    await prior.ShutdownAsync().ConfigureAwait(true);
                }
                SetValue(IsReadyPropertyKey, false);
                SetValue(IsLoadingPropertyKey, false);
                SetValue(StatusTextPropertyKey, LocalizationManager.Format("RendererFailed", exception.Message));
            }
        }
        finally
        {
            Interlocked.CompareExchange(ref _switchCancellation, null, operation);
            operation.Dispose();
        }
    }

    private void SetStatusIfCurrent(long generation, string status)
    {
        if (!Dispatcher.CheckAccess())
        {
            _ = Dispatcher.BeginInvoke(() => SetStatusIfCurrent(generation, status));
            return;
        }
        if (generation == Volatile.Read(ref _generation) && Volatile.Read(ref _shutdown) == 0)
        {
            SetValue(StatusTextPropertyKey, status);
        }
    }

    private ModelRendererSession? TakeCurrentSession()
    {
        lock (_sessionGate)
        {
            var current = _currentSession;
            _currentSession = null;
            return current;
        }
    }

    private void DisposeSessionsImmediately()
    {
        Interlocked.Increment(ref _generation);
        Interlocked.Exchange(ref _switchCancellation, null)?.Cancel();
        lock (_sessionGate)
        {
            _startingSession?.DisposeImmediately();
            if (!ReferenceEquals(_currentSession, _startingSession))
            {
                _currentSession?.DisposeImmediately();
            }
            _startingSession = null;
            _currentSession = null;
        }
    }

    [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr CreateWindowExW(
        int extendedStyle,
        string className,
        string windowName,
        int style,
        int x,
        int y,
        int width,
        int height,
        IntPtr parent,
        IntPtr menu,
        IntPtr instance,
        IntPtr parameter);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool DestroyWindow(IntPtr window);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    private static extern IntPtr GetModuleHandleW(string? moduleName);

    private sealed class ModelRendererSession : IDisposable
    {
        private readonly Process _process;
        private readonly WorkerJob _job;
        private readonly string _runtimeRoot;
        private readonly CancellationTokenSource _lifetime = new();
        private readonly BoundedTextTail _stderr = new(64 * 1024);
        private readonly BoundedTextTail _stdout = new(64 * 1024);
        private readonly Task _stdoutTask;
        private readonly Task _stderrTask;
        private readonly Task _exitTask;
        private readonly TaskCompletionSource<string> _ready = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private readonly string _initialSessionId;
        private readonly string _initialDisplayMode;
        private string _readyBackend = string.Empty;
        private bool _initialDisplayRequested;
        private int _disposed;

        private ModelRendererSession(
            Process process,
            WorkerJob job,
            string runtimeRoot,
            Action<string> status,
            string initialSessionId,
            string initialDisplayMode)
        {
            _process = process;
            _job = job;
            _runtimeRoot = runtimeRoot;
            _initialSessionId = initialSessionId;
            _initialDisplayMode = initialDisplayMode;
            _stdoutTask = ReadProtocolAsync(process.StandardOutput, status, _lifetime.Token);
            _stderrTask = DrainAsync(process.StandardError, _stderr, _lifetime.Token);
            _exitTask = ObserveExitAsync();
        }

        public Task<string> Ready => _ready.Task;

        public static Task<ModelRendererSession> StartAsync(
            string packagePath,
            IntPtr parentHandle,
            Action<string> status,
            CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var package = Path.GetFullPath(packagePath);
            var manifest = Path.Combine(package, "manifest.json");
            var metadata = Path.Combine(package, "mesh.cdmeta.json");
            if (!Directory.Exists(package)
                || !File.Exists(manifest)
                || !File.Exists(metadata)
                || !File.Exists(Path.Combine(package, "net_materials.json"))
                || !File.Exists(Path.Combine(package, "dotnet_scene.json")))
            {
                throw new InvalidDataException("The read-only .NET preview package is incomplete.");
            }
            var initialDisplay = ReadInitialDisplay(package);

            var renderer = ResolveRendererPath();
            var runtimeRoot = CreateRuntimeRoot();
            var output = Path.Combine(runtimeRoot, "output");
            Directory.CreateDirectory(output);
            var startInfo = new ProcessStartInfo
            {
                FileName = renderer,
                UseShellExecute = false,
                RedirectStandardInput = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true,
                WorkingDirectory = Path.GetDirectoryName(renderer) ?? AppContext.BaseDirectory,
                StandardOutputEncoding = new UTF8Encoding(false),
                StandardErrorEncoding = new UTF8Encoding(false),
            };
            foreach (var argument in new[]
            {
                "--input-package", package,
                "--mesh", manifest,
                "--metadata", metadata,
                "--status", Path.Combine(runtimeRoot, "status.json"),
                "--output", output,
                "--edit-operations", Path.Combine(runtimeRoot, "edit_operations.json"),
                "--evaluation", Path.Combine(runtimeRoot, "evaluation.md"),
                "--embedded",
                "--simple-preview",
                "--parent-hwnd", parentHandle.ToInt64().ToString(System.Globalization.CultureInfo.InvariantCulture),
            })
            {
                startInfo.ArgumentList.Add(argument);
            }
            startInfo.Environment["DOTNET_EnableDiagnostics"] = "0";

            Process? process = null;
            WorkerJob? job = null;
            try
            {
                process = Process.Start(startInfo)
                    ?? throw new InvalidOperationException("The .NET/Vortice previewer could not be started.");
                process.StandardInput.AutoFlush = true;
                job = WorkerJob.Create();
                job.Add(process);
                return Task.FromResult(new ModelRendererSession(
                    process,
                    job,
                    runtimeRoot,
                    status,
                    initialDisplay.SessionId,
                    initialDisplay.Mode));
            }
            catch
            {
                job?.Dispose();
                try
                {
                    if (process is { HasExited: false })
                    {
                        process.Kill(entireProcessTree: true);
                    }
                }
                catch
                {
                    // Preserve the renderer launch failure.
                }
                process?.Dispose();
                DeleteRuntimeRoot(runtimeRoot);
                throw;
            }
        }

        public async Task ShutdownAsync()
        {
            if (Interlocked.Exchange(ref _disposed, 1) != 0)
            {
                return;
            }
            try
            {
                if (!_process.HasExited)
                {
                    await _process.StandardInput.WriteLineAsync("{\"event\":\"close_request\"}").ConfigureAwait(false);
                    using var timeout = new CancellationTokenSource(TimeSpan.FromMilliseconds(1500));
                    await _process.WaitForExitAsync(timeout.Token).ConfigureAwait(false);
                }
            }
            catch (OperationCanceledException)
            {
                // The job-object fence below performs the bounded forced stop.
            }
            catch (IOException)
            {
                // The renderer has already disconnected.
            }
            finally
            {
                DisposeImmediatelyCore();
                await ObserveTasksAsync().ConfigureAwait(false);
            }
        }

        public void DisposeImmediately()
        {
            if (Interlocked.Exchange(ref _disposed, 1) == 0)
            {
                DisposeImmediatelyCore();
                _ = ObserveTasksAsync();
            }
        }

        public void Dispose() => DisposeImmediately();

        private async Task ReadProtocolAsync(StreamReader reader, Action<string> status, CancellationToken cancellationToken)
        {
            try
            {
                while (!cancellationToken.IsCancellationRequested)
                {
                    var line = await reader.ReadLineAsync(cancellationToken).ConfigureAwait(false);
                    if (line is null)
                    {
                        break;
                    }
                    _stdout.Append(line + Environment.NewLine);
                    if (Encoding.UTF8.GetByteCount(line) > 1024 * 1024)
                    {
                        throw new InvalidDataException("The .NET previewer emitted an oversized protocol message.");
                    }
                    try
                    {
                        using var message = JsonDocument.Parse(line);
                        var root = message.RootElement;
                        var eventName = JsonString(root, "event").Trim().ToLowerInvariant();
                        switch (eventName)
                        {
                            case "protocol_ready":
                                status(LocalizationManager.Get("RendererLoading"));
                                break;
                            case "ready":
                                var backend = root.TryGetProperty("renderer", out var renderer)
                                    ? JsonString(renderer, "backend")
                                    : string.Empty;
                                _readyBackend = backend;
                                if (string.IsNullOrWhiteSpace(_initialDisplayMode))
                                {
                                    _ready.TrySetResult(backend);
                                }
                                else
                                {
                                    await RequestInitialDisplayAsync().ConfigureAwait(false);
                                }
                                break;
                            case "viewport_display_applied":
                                if (_initialDisplayRequested
                                    && string.Equals(JsonString(root, "mode"), _initialDisplayMode, StringComparison.OrdinalIgnoreCase))
                                {
                                    _ready.TrySetResult(_readyBackend);
                                }
                                break;
                            case "viewport_display_failed":
                                if (_initialDisplayRequested)
                                {
                                    _ready.TrySetException(new InvalidDataException(
                                        JsonString(root, "message", "The renderer rejected the requested HKX structure view.")));
                                }
                                break;
                            case "error":
                                _ready.TrySetException(new InvalidDataException(
                                    JsonString(root, "message", LocalizationManager.Get("RendererUnknownError"))));
                                break;
                        }
                    }
                    catch (JsonException)
                    {
                        // Retain non-protocol diagnostics in the bounded stdout tail.
                    }
                }
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                // Expected during preview replacement or application shutdown.
            }
            catch (Exception exception)
            {
                _ready.TrySetException(exception);
            }
        }

        private async Task RequestInitialDisplayAsync()
        {
            if (_initialDisplayRequested)
            {
                return;
            }
            _initialDisplayRequested = true;
            var sessionState = JsonSerializer.Serialize(new Dictionary<string, object?>
            {
                ["event"] = "session_state",
                ["session_id"] = _initialSessionId,
            });
            var displayUpdate = JsonSerializer.Serialize(new Dictionary<string, object?>
            {
                ["event"] = "viewport_display_update",
                ["session_id"] = _initialSessionId,
                ["mode"] = _initialDisplayMode,
            });
            await _process.StandardInput.WriteLineAsync(sessionState).ConfigureAwait(false);
            await _process.StandardInput.WriteLineAsync(displayUpdate).ConfigureAwait(false);
        }

        private async Task ObserveExitAsync()
        {
            try
            {
                await _process.WaitForExitAsync(_lifetime.Token).ConfigureAwait(false);
                if (!_ready.Task.IsCompleted)
                {
                    var detail = _stderr.ToString().Trim();
                    _ready.TrySetException(new InvalidOperationException(string.IsNullOrWhiteSpace(detail)
                        ? $"The .NET previewer exited before its first frame (code {_process.ExitCode})."
                        : detail));
                }
            }
            catch (OperationCanceledException) when (_lifetime.IsCancellationRequested)
            {
                // Expected during owned teardown.
            }
        }

        private void DisposeImmediatelyCore()
        {
            _lifetime.Cancel();
            _job.Dispose();
            try
            {
                if (!_process.HasExited)
                {
                    _process.Kill(entireProcessTree: true);
                }
            }
            catch
            {
                // Job disposal is the primary process-tree teardown.
            }
        }

        private async Task ObserveTasksAsync()
        {
            foreach (var task in new[] { _stdoutTask, _stderrTask, _exitTask })
            {
                try
                {
                    await task.ConfigureAwait(false);
                }
                catch
                {
                    // Bounded protocol and stderr diagnostics own the useful failure detail.
                }
            }
            _lifetime.Dispose();
            _process.Dispose();
            DeleteRuntimeRoot(_runtimeRoot);
        }

        private static async Task DrainAsync(StreamReader reader, BoundedTextTail tail, CancellationToken cancellationToken)
        {
            var buffer = new char[4096];
            try
            {
                while (!cancellationToken.IsCancellationRequested)
                {
                    var count = await reader.ReadAsync(buffer.AsMemory(), cancellationToken).ConfigureAwait(false);
                    if (count == 0)
                    {
                        break;
                    }
                    tail.Append(new string(buffer, 0, count));
                }
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                // Expected during owned teardown.
            }
        }

        private static string ResolveRendererPath()
        {
            var overridePath = Environment.GetEnvironmentVariable("CDMW_ARCHIVE_LITE_DOTNET_PREVIEW_PATH");
            if (!string.IsNullOrWhiteSpace(overridePath) && File.Exists(overridePath))
            {
                return Path.GetFullPath(overridePath);
            }
            var packaged = Path.Combine(AppContext.BaseDirectory, "renderer", "cdmw-mesh-dotnet-editor.exe");
            if (File.Exists(packaged))
            {
                return packaged;
            }
            for (var current = new DirectoryInfo(AppContext.BaseDirectory); current is not null; current = current.Parent)
            {
                foreach (var configuration in new[] { "Release", "Debug" })
                {
                    var candidate = Path.Combine(
                        current.FullName,
                        "tools",
                        "dotnet_mesh_editor_experiment",
                        "bin",
                        configuration,
                        "net8.0-windows",
                        "cdmw-mesh-dotnet-editor.exe");
                    if (File.Exists(candidate))
                    {
                        return candidate;
                    }
                }
            }
            throw new FileNotFoundException(
                "cdmw-mesh-dotnet-editor.exe was not found. Rebuild the Archive Lite portable package or set CDMW_ARCHIVE_LITE_DOTNET_PREVIEW_PATH.");
        }

        private static (string SessionId, string Mode) ReadInitialDisplay(string package)
        {
            var reportPath = Path.Combine(package, "archive_lite_hkx_preview.json");
            if (!File.Exists(reportPath))
            {
                return (string.Empty, string.Empty);
            }
            using var report = JsonDocument.Parse(File.ReadAllBytes(reportPath));
            var mode = JsonString(report.RootElement, "preferred_display_mode").Trim().ToLowerInvariant();
            if (!string.Equals(mode, "xray", StringComparison.Ordinal))
            {
                throw new InvalidDataException($"The HKX preview requested unsupported display mode '{mode}'.");
            }
            using var scene = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(package, "dotnet_scene.json")));
            var sessionId = JsonString(scene.RootElement, "session_id").Trim();
            if (string.IsNullOrWhiteSpace(sessionId))
            {
                throw new InvalidDataException("The HKX preview scene has no renderer session identity.");
            }
            return (sessionId, mode);
        }

        private static string CreateRuntimeRoot()
        {
            var dataRoot = Path.Combine(AppDataPaths.Cache, "preview", "runtime");
            Directory.CreateDirectory(dataRoot);
            var runtime = Path.Combine(dataRoot, Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(runtime);
            return runtime;
        }

        private static void DeleteRuntimeRoot(string runtimeRoot)
        {
            try
            {
                var root = Path.Combine(AppDataPaths.Cache, "preview", "runtime");
                var resolvedRoot = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
                var resolvedRuntime = Path.GetFullPath(runtimeRoot);
                if (resolvedRuntime.StartsWith(resolvedRoot + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)
                    && Directory.Exists(resolvedRuntime))
                {
                    Directory.Delete(resolvedRuntime, recursive: true);
                }
            }
            catch
            {
                // Bounded cache maintenance can remove a stale runtime folder later.
            }
        }

        private static string JsonString(JsonElement element, string name, string fallback = "")
        {
            return element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
                ? value.GetString() ?? fallback
                : fallback;
        }
    }
}
