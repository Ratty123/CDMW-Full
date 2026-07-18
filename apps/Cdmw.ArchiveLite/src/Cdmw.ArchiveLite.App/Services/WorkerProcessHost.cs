using System.Collections.Concurrent;
using System.Diagnostics;
using System.IO;
using System.IO.Pipes;
using System.Text;
using System.Text.Json;
using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.App.Services;

public sealed class WorkerProcessHost : IAsyncDisposable
{
    private readonly Process _process;
    private readonly WorkerJob _job;
    private readonly NamedPipeClientStream _pipe;
    private readonly StreamReader _reader;
    private readonly StreamWriter _writer;
    private readonly SemaphoreSlim _writeGate = new(1, 1);
    private readonly ConcurrentDictionary<Guid, TaskCompletionSource<WorkerMessage>> _pending = new();
    private readonly CancellationTokenSource _lifetime = new();
    private readonly BoundedTextTail _stderr = new(64 * 1024);
    private readonly Task _readTask;
    private readonly Task _stderrTask;
    private readonly Task _stdoutTask;
    private int _disposed;

    private WorkerProcessHost(
        Process process,
        WorkerJob job,
        NamedPipeClientStream pipe,
        StreamReader reader,
        StreamWriter writer)
    {
        _process = process;
        _job = job;
        _pipe = pipe;
        _reader = reader;
        _writer = writer;
        _readTask = ReadLoopAsync(_lifetime.Token);
        _stderrTask = DrainAsync(process.StandardError, _stderr, _lifetime.Token);
        _stdoutTask = DrainAsync(process.StandardOutput, null, _lifetime.Token);
    }

    public event EventHandler<WorkerMessage>? MessageReceived;

    public bool IsConnected => Volatile.Read(ref _disposed) == 0 && _pipe.IsConnected && !_process.HasExited;

    public string DiagnosticTail => _stderr.ToString();

    public static async Task<WorkerProcessHost> StartAsync(CancellationToken cancellationToken)
    {
        var worker = ResolveWorkerPath();
        var pipeName = $"cdmw-archive-lite-{Environment.ProcessId}-{Guid.NewGuid():N}";
        var startInfo = CreateStartInfo(worker, pipeName);
        var process = Process.Start(startInfo)
            ?? throw new InvalidOperationException("The Archive Lite worker process could not be started.");
        WorkerJob? job = null;
        NamedPipeClientStream? pipe = null;
        try
        {
            job = WorkerJob.Create();
            job.Add(process);
            pipe = new NamedPipeClientStream(
                ".",
                pipeName,
                PipeDirection.InOut,
                PipeOptions.Asynchronous | PipeOptions.WriteThrough);
            using var connectTimeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            connectTimeout.CancelAfter(TimeSpan.FromSeconds(8));
            await pipe.ConnectAsync(connectTimeout.Token).ConfigureAwait(false);
            var reader = new StreamReader(pipe, new UTF8Encoding(false), false, 16 * 1024, leaveOpen: true);
            var writer = new StreamWriter(pipe, new UTF8Encoding(false), 16 * 1024, leaveOpen: true)
            {
                AutoFlush = true,
                NewLine = "\n",
            };
            return new WorkerProcessHost(process, job, pipe, reader, writer);
        }
        catch
        {
            pipe?.Dispose();
            job?.Dispose();
            try
            {
                if (!process.HasExited)
                {
                    process.Kill(entireProcessTree: true);
                }
            }
            catch
            {
                // Preserve the launch failure.
            }

            process.Dispose();
            throw;
        }
    }

    public async Task<TResult> SendAsync<TRequest, TResult>(
        string kind,
        long generation,
        TRequest payload,
        CancellationToken cancellationToken)
    {
        ObjectDisposedException.ThrowIf(Volatile.Read(ref _disposed) != 0, this);
        var requestId = Guid.NewGuid();
        var request = WorkerProtocol.Request(requestId, generation, kind, payload);
        var completion = new TaskCompletionSource<WorkerMessage>(TaskCreationOptions.RunContinuationsAsynchronously);
        if (!_pending.TryAdd(requestId, completion))
        {
            throw new InvalidOperationException("Could not register the worker request.");
        }

        try
        {
            await WriteAsync(request, cancellationToken).ConfigureAwait(false);
            using var registration = cancellationToken.Register(() => _ = SendCancelAsync(requestId));
            var response = await completion.Task.WaitAsync(cancellationToken).ConfigureAwait(false);
            if (response.Status == WorkerMessageStatus.Cancelled)
            {
                throw new OperationCanceledException(cancellationToken);
            }

            if (response.Status == WorkerMessageStatus.Error)
            {
                throw new WorkerRequestException(response.Error ?? new WorkerError("unknown", "Worker request failed."));
            }

            return WorkerProtocol.ReadPayload<TResult>(response)
                ?? throw new InvalidDataException("Worker response did not contain the expected payload.");
        }
        finally
        {
            _pending.TryRemove(requestId, out _);
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
            if (_pipe.IsConnected && !_process.HasExited)
            {
                var request = WorkerProtocol.Request(Guid.NewGuid(), long.MaxValue, WorkerProtocol.Shutdown, new { });
                await WriteAsync(request, CancellationToken.None).ConfigureAwait(false);
                using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(2));
                await _process.WaitForExitAsync(timeout.Token).ConfigureAwait(false);
            }
        }
        catch (OperationCanceledException)
        {
            // The owned job below performs the bounded forced stop.
        }
        catch (IOException)
        {
            // A disconnected worker is already stopped or stopping.
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
        }
    }

    public async ValueTask DisposeAsync() => await ShutdownAsync().ConfigureAwait(false);

    private async Task ReadLoopAsync(CancellationToken cancellationToken)
    {
        Exception? terminalError = null;
        try
        {
            while (!cancellationToken.IsCancellationRequested)
            {
                var line = await _reader.ReadLineAsync(cancellationToken).ConfigureAwait(false);
                if (line is null)
                {
                    break;
                }

                if (Encoding.UTF8.GetByteCount(line) > WorkerProtocol.MaximumMessageBytes)
                {
                    throw new InvalidDataException("Worker response exceeds the one MiB limit.");
                }

                var message = JsonSerializer.Deserialize<WorkerMessage>(line, WorkerProtocol.JsonOptions);
                if (message is null || message.ProtocolVersion != WorkerProtocol.Version)
                {
                    continue;
                }

                MessageReceived?.Invoke(this, message);
                if (message.Status is WorkerMessageStatus.Result or WorkerMessageStatus.Cancelled or WorkerMessageStatus.Error)
                {
                    if (_pending.TryGetValue(message.RequestId, out var completion))
                    {
                        completion.TrySetResult(message);
                    }
                }
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            return;
        }
        catch (Exception exception)
        {
            terminalError = exception;
        }
        finally
        {
            var failure = terminalError ?? new IOException("Archive Lite worker disconnected.");
            foreach (var completion in _pending.Values)
            {
                completion.TrySetException(failure);
            }
        }
    }

    private async Task SendCancelAsync(Guid targetRequestId)
    {
        if (Volatile.Read(ref _disposed) != 0 || !_pipe.IsConnected)
        {
            return;
        }

        try
        {
            var request = WorkerProtocol.Request(
                Guid.NewGuid(),
                long.MaxValue,
                WorkerProtocol.Cancel,
                new CancelRequest(targetRequestId));
            await WriteAsync(request, _lifetime.Token).ConfigureAwait(false);
        }
        catch
        {
            // The original request owns cancellation diagnostics.
        }
    }

    private async Task WriteAsync(WorkerMessage message, CancellationToken cancellationToken)
    {
        var json = JsonSerializer.Serialize(message, WorkerProtocol.JsonOptions);
        if (Encoding.UTF8.GetByteCount(json) > WorkerProtocol.MaximumMessageBytes)
        {
            throw new InvalidDataException("Worker request exceeds the one MiB limit.");
        }

        await _writeGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            await _writer.WriteLineAsync(json.AsMemory(), cancellationToken).ConfigureAwait(false);
        }
        finally
        {
            _writeGate.Release();
        }
    }

    private void DisposeImmediatelyCore()
    {
        _lifetime.Cancel();
        try
        {
            _pipe.Dispose();
        }
        catch
        {
            // Continue to the job-object fence.
        }

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
        foreach (var task in new[] { _readTask, _stderrTask, _stdoutTask })
        {
            try
            {
                await task.ConfigureAwait(false);
            }
            catch
            {
                // Terminal diagnostics are retained in the bounded stderr tail.
            }
        }

        try
        {
            _writer.Dispose();
        }
        catch (Exception exception) when (exception is IOException or ObjectDisposedException)
        {
            // The pipe is intentionally closed before owned process teardown.
        }
        _reader.Dispose();
        _writeGate.Dispose();
        _lifetime.Dispose();
        _process.Dispose();
    }

    private static ProcessStartInfo CreateStartInfo(WorkerLaunchPath worker, string pipeName)
    {
        var info = new ProcessStartInfo
        {
            FileName = worker.IsDll ? "dotnet" : worker.Path,
            Arguments = worker.IsDll
                ? $"\"{worker.Path}\" --pipe \"{pipeName}\""
                : $"--pipe \"{pipeName}\"",
            UseShellExecute = false,
            RedirectStandardError = true,
            RedirectStandardOutput = true,
            CreateNoWindow = true,
            WorkingDirectory = AppContext.BaseDirectory,
        };
        info.Environment["DOTNET_EnableDiagnostics"] = "0";
        return info;
    }

    private static WorkerLaunchPath ResolveWorkerPath()
    {
        var overridePath = Environment.GetEnvironmentVariable("CDMW_ARCHIVE_LITE_WORKER_PATH");
        if (!string.IsNullOrWhiteSpace(overridePath) && File.Exists(overridePath))
        {
            return new WorkerLaunchPath(Path.GetFullPath(overridePath), overridePath.EndsWith(".dll", StringComparison.OrdinalIgnoreCase));
        }

        foreach (var filename in new[] { "CdmwArchiveLite.Worker.exe", "CdmwArchiveLite.Worker.dll" })
        {
            var sibling = Path.Combine(AppContext.BaseDirectory, filename);
            if (File.Exists(sibling))
            {
                return new WorkerLaunchPath(sibling, filename.EndsWith(".dll", StringComparison.OrdinalIgnoreCase));
            }
        }

        var configuration = AppContext.BaseDirectory.Contains($"{Path.DirectorySeparatorChar}Release{Path.DirectorySeparatorChar}", StringComparison.OrdinalIgnoreCase)
            ? "Release"
            : "Debug";
        var sourceRoot = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", ".."));
        var development = Path.Combine(
            sourceRoot,
            "Cdmw.ArchiveLite.Worker",
            "bin",
            configuration,
            "net10.0-windows",
            "win-x64",
            "CdmwArchiveLite.Worker.exe");
        if (File.Exists(development))
        {
            return new WorkerLaunchPath(development, false);
        }

        throw new FileNotFoundException("CdmwArchiveLite.Worker.exe was not found beside the application or in the development output.");
    }

    private static async Task DrainAsync(StreamReader reader, BoundedTextTail? tail, CancellationToken cancellationToken)
    {
        var buffer = new char[4096];
        try
        {
            while (!cancellationToken.IsCancellationRequested)
            {
                var read = await reader.ReadAsync(buffer.AsMemory(), cancellationToken).ConfigureAwait(false);
                if (read == 0)
                {
                    break;
                }

                tail?.Append(new string(buffer, 0, read));
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            // Expected during application shutdown.
        }
    }

    private sealed record WorkerLaunchPath(string Path, bool IsDll);
}

public sealed class WorkerRequestException(WorkerError error) : Exception(error.Message)
{
    public WorkerError Error { get; } = error;
}
