using System.Collections.Concurrent;
using System.Reflection;
using System.Text;
using System.Text.Json;
using Cdmw.FullArchive.Contracts;
using Cdmw.FullArchive.Core;

namespace Cdmw.FullArchive.Worker;

internal sealed class WorkerServer(Stream input, Stream output, string cacheRoot)
{
    private readonly ConcurrentDictionary<Guid, CancellationTokenSource> _operations = new();
    private readonly ConcurrentDictionary<Guid, Task> _operationTasks = new();
    private readonly SemaphoreSlim _writeGate = new(1, 1);
    private readonly CancellationTokenSource _requestedShutdown = new();
    private readonly WorkerRuntime _runtime = new(cacheRoot);

    public async Task RunAsync(CancellationToken cancellationToken)
    {
        using var linkedShutdown = CancellationTokenSource.CreateLinkedTokenSource(
            cancellationToken,
            _requestedShutdown.Token);
        var reader = new BoundedLineReader(input, WorkerProtocol.MaximumMessageBytes);
        await using var writer = new StreamWriter(output, new UTF8Encoding(false), 16 * 1024, leaveOpen: true)
        {
            AutoFlush = true,
            NewLine = "\n",
        };

        try
        {
            while (!linkedShutdown.IsCancellationRequested)
            {
                string? line;
                try
                {
                    line = await reader.ReadLineAsync(linkedShutdown.Token).ConfigureAwait(false);
                }
                catch (InvalidDataException exception)
                {
                    Console.Error.WriteLine($"Rejected oversized or invalid worker message: {exception.Message}");
                    continue;
                }
                if (line is null)
                {
                    break;
                }

                WorkerMessage? request;
                try
                {
                    request = JsonSerializer.Deserialize<WorkerMessage>(line, WorkerProtocol.JsonOptions);
                }
                catch (JsonException exception)
                {
                    Console.Error.WriteLine($"Rejected invalid worker JSON: {exception.Message}");
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
                if (request.Operation == WorkerProtocol.Cancel)
                {
                    await HandleCancelAsync(writer, request, linkedShutdown.Token).ConfigureAwait(false);
                    continue;
                }
                if (request.Operation == WorkerProtocol.Shutdown)
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
            await _runtime.DisposeAsync().ConfigureAwait(false);
            _writeGate.Dispose();
            _requestedShutdown.Dispose();
        }
    }

    private void StartOperation(StreamWriter writer, WorkerMessage request, CancellationToken serverToken)
    {
        var operation = CancellationTokenSource.CreateLinkedTokenSource(serverToken);
        if (!_operations.TryAdd(request.RequestId, operation))
        {
            _ = WriteAsync(
                writer,
                WorkerProtocol.Failure(request, "duplicate_request", "The request id is already active."),
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

    private async Task RunOperationAsync(
        StreamWriter writer,
        WorkerMessage request,
        CancellationToken cancellationToken)
    {
        try
        {
            await WriteAsync(
                writer,
                WorkerProtocol.Response(request, WorkerMessageStatus.Started, new { accepted = true }),
                cancellationToken).ConfigureAwait(false);

            WorkerMessage response;
            if (request.Operation == WorkerProtocol.Ping)
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
                    batch => WriteAsync(
                        writer,
                        WorkerProtocol.Response(request, WorkerMessageStatus.Batch, batch),
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
        var native = new NativeArchiveCore();
        return WorkerProtocol.Response(
            request,
            WorkerMessageStatus.Result,
            new PingResult(
                version,
                WorkerProtocol.Version,
                native.AbiVersion,
                ArchiveIndex.Version,
                Environment.ProcessId));
    }

    private async Task HandleCancelAsync(
        StreamWriter writer,
        WorkerMessage request,
        CancellationToken cancellationToken)
    {
        var payload = WorkerProtocol.ReadPayload<CancelRequest>(request);
        CancellationTokenSource? operation = null;
        var accepted = payload is not null && _operations.TryGetValue(payload.TargetRequestId, out operation);
        operation?.Cancel();
        await WriteAsync(
            writer,
            WorkerProtocol.Response(request, WorkerMessageStatus.Result, new { accepted }),
            cancellationToken).ConfigureAwait(false);
    }

    private async Task WriteAsync(
        StreamWriter writer,
        WorkerMessage message,
        CancellationToken cancellationToken)
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
            // Each operation writes its own terminal response.
        }
    }
}

internal sealed class BoundedLineReader(Stream stream, int maximumBytes)
{
    private static readonly UTF8Encoding StrictUtf8 = new(false, true);
    private readonly byte[] _buffer = new byte[16 * 1024];
    private int _position;
    private int _length;

    public async Task<string?> ReadLineAsync(CancellationToken cancellationToken)
    {
        using var line = new MemoryStream(Math.Min(maximumBytes, 64 * 1024));
        while (true)
        {
            if (_position >= _length)
            {
                _length = await stream.ReadAsync(_buffer, cancellationToken).ConfigureAwait(false);
                _position = 0;
                if (_length == 0)
                {
                    return line.Length == 0 ? null : Decode(line);
                }
            }
            var newline = Array.IndexOf(_buffer, (byte)'\n', _position, _length - _position);
            var end = newline >= 0 ? newline : _length;
            var count = end - _position;
            if (line.Length + count > maximumBytes)
            {
                _position = newline >= 0 ? newline + 1 : _length;
                if (newline < 0)
                {
                    await DiscardToNewlineAsync(cancellationToken).ConfigureAwait(false);
                }
                throw new InvalidDataException("Worker protocol message exceeds the one MiB limit.");
            }
            line.Write(_buffer, _position, count);
            _position = newline >= 0 ? newline + 1 : _length;
            if (newline >= 0)
            {
                return Decode(line);
            }
        }
    }

    private async Task DiscardToNewlineAsync(CancellationToken cancellationToken)
    {
        while (true)
        {
            _length = await stream.ReadAsync(_buffer, cancellationToken).ConfigureAwait(false);
            _position = 0;
            if (_length == 0)
            {
                return;
            }
            var newline = Array.IndexOf(_buffer, (byte)'\n', 0, _length);
            if (newline >= 0)
            {
                _position = newline + 1;
                return;
            }
        }
    }

    private static string Decode(MemoryStream line)
    {
        var bytes = line.GetBuffer().AsSpan(0, checked((int)line.Length));
        if (bytes.EndsWith("\r"u8))
        {
            bytes = bytes[..^1];
        }
        try
        {
            return StrictUtf8.GetString(bytes);
        }
        catch (DecoderFallbackException exception)
        {
            throw new InvalidDataException("Worker protocol message is not valid UTF-8.", exception);
        }
    }
}
