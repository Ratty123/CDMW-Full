using Cdmw.ArchiveLite.Contracts;
using Cdmw.ArchiveLite.Core;

namespace Cdmw.ArchiveLite.Worker;

internal sealed class WorkerRuntime : IDisposable
{
    private readonly NativeArchiveCore _native = new();
    private readonly ArchiveSessionManager _sessions;
    private readonly ArchiveQueryService _queries;
    private readonly ArchivePreviewService _previews;
    private readonly TextSearchService _textSearch;
    private readonly ArchiveExportService _exports;

    public WorkerRuntime()
    {
        ArchiveLiteCacheMaintenance.Prune(ArchiveLiteDataPaths.Cache, 5L * 1024L * 1024L * 1024L);
        _native.EnsureCompatible();
        _sessions = new ArchiveSessionManager(_native);
        _queries = new ArchiveQueryService(_sessions);
        _previews = new ArchivePreviewService(_sessions, _native);
        _textSearch = new TextSearchService(_sessions, _native);
        _exports = new ArchiveExportService(_sessions, _queries, _native);
    }

    public async Task<WorkerMessage> HandleAsync(
        WorkerMessage request,
        Func<ProgressUpdate, Task> publishProgress,
        CancellationToken cancellationToken)
    {
        switch (request.Kind)
        {
            case WorkerProtocol.OpenArchive:
                {
                    var payload = RequirePayload<OpenArchiveRequest>(request);
                    var result = await _sessions.OpenAsync(payload, cancellationToken).ConfigureAwait(false);
                    return WorkerProtocol.Response(request, WorkerMessageStatus.Result, result);
                }
            case WorkerProtocol.QueryArchive:
                {
                    var payload = RequirePayload<ArchiveQuerySpec>(request);
                    var result = await _queries.QueryAsync(payload, request.Generation, cancellationToken).ConfigureAwait(false);
                    return WorkerProtocol.Response(request, WorkerMessageStatus.Result, result);
                }
            case WorkerProtocol.Preview:
                {
                    var payload = RequirePayload<PreviewRequest>(request);
                    var result = await _previews.BuildAsync(payload, cancellationToken).ConfigureAwait(false);
                    return WorkerProtocol.Response(request, WorkerMessageStatus.Result, result);
                }
            case WorkerProtocol.TextSearch:
                {
                    var payload = RequirePayload<TextSearchRequest>(request);
                    var result = await _textSearch.SearchAsync(payload, cancellationToken).ConfigureAwait(false);
                    return WorkerProtocol.Response(request, WorkerMessageStatus.Result, result);
                }
            case WorkerProtocol.Export:
                {
                    var payload = RequirePayload<ExportPlanRequest>(request);
                    var result = await _exports.ExportAsync(
                        payload,
                        publishProgress,
                        cancellationToken).ConfigureAwait(false);
                    return WorkerProtocol.Response(request, WorkerMessageStatus.Result, result);
                }
            default:
                return WorkerProtocol.Failure(request, "unsupported_request", $"Unsupported request kind '{request.Kind}'.");
        }
    }

    public void Dispose() => _sessions.Dispose();

    private static T RequirePayload<T>(WorkerMessage request)
    {
        return WorkerProtocol.ReadPayload<T>(request)
            ?? throw new InvalidDataException($"Worker request '{request.Kind}' has no valid payload.");
    }
}
