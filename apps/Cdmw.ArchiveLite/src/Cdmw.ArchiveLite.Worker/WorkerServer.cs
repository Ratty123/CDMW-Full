using System.Collections.Concurrent;
using System.Reflection;
using System.Text;
using System.Text.Json;
using Cdmw.ArchiveLite.Contracts;
using Cdmw.ArchiveLite.Core;

namespace Cdmw.ArchiveLite.Worker;

internal sealed class WorkerServer(Stream stream)
{
    private readonly ConcurrentDictionary<Guid, CancellationTokenSource> _operations = new();
    private readonly ConcurrentDictionary<Guid, Task> _operationTasks = new();
    private readonly SemaphoreSlim _writeGate = new(1, 1);
    private readonly CancellationTokenSource _requestedShutdown = new();
    private readonly WorkerRuntime _runtime = new();

    public async Task RunAsync(CancellationToken cancellationToken)
    {
        using var linkedShutdown = CancellationTokenSource.CreateLinkedTokenSource(
            cancellationToken,
            _requestedShutdown.Token);
        using var reader = new StreamReader(stream, new UTF8Encoding(false), false, 16 * 1024, leaveOpen: true);
        using var writer = new StreamWriter(stream, new UTF8Encoding(false), 16 * 1024, leaveOpen: true)
        {
            AutoFlush = true,
            NewLine = "\n",
        };

        try
        {
            while (!linkedShutdown.IsCancellationRequested)
            {
                var line = await reader.ReadLineAsync(linkedShutdown.Token).ConfigureAwait(false);
                if (line is null)
                {
                    break;
                }

                if (Encoding.UTF8.GetByteCount(line) > WorkerProtocol.MaximumMessageBytes)
                {
                    throw new InvalidDataException("Worker protocol message exceeds the one MiB limit.");
                }

                WorkerMessage? request;
                try
                {
                    request = JsonSerializer.Deserialize<WorkerMessage>(line, WorkerProtocol.JsonOptions);
                }
                catch (JsonException exception)
                {
                    Console.Error.WriteLine($"Rejected invalid worker message: {exception.Message}");
                    continue;
                }

                if (request is null || request.Status != WorkerMessageStatus.Request)
                {
                    continue;
                }

                if (request.ProtocolVersion != WorkerProtocol.Version)
                {
                    await WriteAsync(
                        writer,
                        WorkerProtocol.Failure(request, "protocol_mismatch", "Unsupported worker protocol version."),
                        linkedShutdown.Token).ConfigureAwait(false);
                    continue;
                }

                if (request.Kind == WorkerProtocol.Cancel)
                {
                    await HandleCancelAsync(writer, request, linkedShutdown.Token).ConfigureAwait(false);
                    continue;
                }

                if (request.Kind == WorkerProtocol.Shutdown)
                {
                    await WriteAsync(
                        writer,
                        WorkerProtocol.Response(request, WorkerMessageStatus.Result, new { accepted = true }),
                        linkedShutdown.Token).ConfigureAwait(false);
                    _requestedShutdown.Cancel();
                    break;
                }

                StartOperation(writer, request, linkedShutdown.Token);
            }
        }
        finally
        {
            _requestedShutdown.Cancel();
            foreach (var operation in _operations.Values)
            {
                operation.Cancel();
            }

            var pending = _operationTasks.Values.ToArray();
            if (pending.Length > 0)
            {
                await Task.WhenAll(pending.Select(IgnoreFailureAsync)).ConfigureAwait(false);
            }

            foreach (var operation in _operations.Values)
            {
                operation.Dispose();
            }
            _runtime.Dispose();
        }
    }

    private void StartOperation(StreamWriter writer, WorkerMessage request, CancellationToken serverToken)
    {
        var operation = CancellationTokenSource.CreateLinkedTokenSource(serverToken);
        if (!_operations.TryAdd(request.RequestId, operation))
        {
            _ = WriteAsync(
                writer,
                WorkerProtocol.Failure(request, "duplicate_request", "The request ID is already active."),
                serverToken);
            operation.Dispose();
            return;
        }

        var task = RunOperationAsync(writer, request, operation.Token);
        _operationTasks[request.RequestId] = task;
        _ = task.ContinueWith(
            completedTask =>
            {
                _ = completedTask.Exception;
                _operationTasks.TryRemove(request.RequestId, out _);
                if (_operations.TryRemove(request.RequestId, out var completed))
                {
                    completed.Dispose();
                }
            },
            CancellationToken.None,
            TaskContinuationOptions.ExecuteSynchronously,
            TaskScheduler.Default);
    }

    private async Task RunOperationAsync(StreamWriter writer, WorkerMessage request, CancellationToken cancellationToken)
    {
        try
        {
            await WriteAsync(
                writer,
                WorkerProtocol.Response(request, WorkerMessageStatus.Started, new { accepted = true }),
                cancellationToken).ConfigureAwait(false);

            WorkerMessage response;
            if (request.Kind == WorkerProtocol.Ping)
            {
                response = HandlePing(request);
            }
            else
            {
                response = await _runtime.HandleAsync(
                    request,
                    update => WriteAsync(
                        writer,
                        WorkerProtocol.Response(request, WorkerMessageStatus.Progress, update),
                        cancellationToken),
                    cancellationToken).ConfigureAwait(false);
            }
            await WriteAsync(writer, response, cancellationToken).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            await WriteAsync(
                writer,
                WorkerProtocol.Response(request, WorkerMessageStatus.Cancelled, new { cancelled = true }),
                CancellationToken.None).ConfigureAwait(false);
        }
        catch (ArchiveCacheRefreshRequiredException exception)
        {
            await WriteAsync(
                writer,
                WorkerProtocol.Failure(request, "cache_refresh_required", exception.Message),
                CancellationToken.None).ConfigureAwait(false);
        }
        catch (Exception exception)
        {
            await WriteAsync(
                writer,
                WorkerProtocol.Failure(request, "worker_failure", exception.Message, exception.ToString()),
                CancellationToken.None).ConfigureAwait(false);
        }
    }

    private static WorkerMessage HandlePing(WorkerMessage request)
    {
        var version = Assembly.GetExecutingAssembly().GetName().Version?.ToString() ?? "0.0.0";
        return WorkerProtocol.Response(
            request,
            WorkerMessageStatus.Result,
            new PingResult(version, WorkerProtocol.Version, Environment.ProcessId));
    }

    private async Task HandleCancelAsync(StreamWriter writer, WorkerMessage request, CancellationToken cancellationToken)
    {
        var payload = WorkerProtocol.ReadPayload<CancelRequest>(request);
        CancellationTokenSource? operation = null;
        var accepted = payload is not null &&
            _operations.TryGetValue(payload.TargetRequestId, out operation);
        if (operation is not null)
        {
            operation.Cancel();
        }

        await WriteAsync(
            writer,
            WorkerProtocol.Response(request, WorkerMessageStatus.Result, new { accepted }),
            cancellationToken).ConfigureAwait(false);
    }

    private async Task WriteAsync(StreamWriter writer, WorkerMessage message, CancellationToken cancellationToken)
    {
        var json = JsonSerializer.Serialize(message, WorkerProtocol.JsonOptions);
        if (Encoding.UTF8.GetByteCount(json) > WorkerProtocol.MaximumMessageBytes)
        {
            throw new InvalidDataException("Worker response exceeds the one MiB limit.");
        }

        await _writeGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            await writer.WriteLineAsync(json.AsMemory(), cancellationToken).ConfigureAwait(false);
        }
        finally
        {
            _writeGate.Release();
        }
    }

    private static async Task IgnoreFailureAsync(Task task)
    {
        try
        {
            await task.ConfigureAwait(false);
        }
        catch
        {
            // The terminal response owns operation diagnostics.
        }
    }
}
