using Cdmw.ArchiveLite.Contracts;
using Cdmw.ArchiveLite.Core;

namespace Cdmw.ArchiveLite.Worker;

internal sealed class WorkerRuntime : IDisposable
{
    private readonly NativeArchiveCore _native = new();
    private readonly ArchiveSessionManager _sessions;
    private readonly ArchiveQueryService _queries;
    private readonly ArchiveCacheHealthService _cacheHealth;
    private readonly GameInstallDiscoveryService _gameDiscovery;
    private readonly ArchiveFacetsService _facets;
    private readonly ArchiveItemNameIndexService _nameIndex;
    private readonly ArchiveAssociationService _associations;
    private readonly ArchivePreviewService _previews;
    private readonly TextSearchService _textSearch;
    private readonly ArchiveExportService _exports;

    public WorkerRuntime()
    {
        ArchiveLiteCacheMaintenance.Prune(ArchiveLiteDataPaths.Cache, 5L * 1024L * 1024L * 1024L);
        _native.EnsureCompatible();
        _sessions = new ArchiveSessionManager(_native);
        _queries = new ArchiveQueryService(_sessions);
        _cacheHealth = new ArchiveCacheHealthService();
        _gameDiscovery = new GameInstallDiscoveryService();
        _facets = new ArchiveFacetsService(_sessions);
        _nameIndex = new ArchiveItemNameIndexService(_sessions, _native);
        _associations = new ArchiveAssociationService(_sessions, _native);
        var modelPreviews = new NativeModelPreviewService();
        _previews = new ArchivePreviewService(_sessions, _native, modelPreviews);
        _textSearch = new TextSearchService(_sessions, _native);
        _exports = new ArchiveExportService(
            _sessions,
            _queries,
            _native,
            new NativeModelExportService(modelPreviews));
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
                    var result = await _sessions.OpenAsync(payload, cancellationToken, publishProgress).ConfigureAwait(false);
                    return WorkerProtocol.Response(request, WorkerMessageStatus.Result, result);
                }
            case WorkerProtocol.QueryArchive:
                {
                    var payload = RequirePayload<ArchiveQuerySpec>(request);
                    var result = await _queries.QueryAsync(payload, request.Generation, cancellationToken).ConfigureAwait(false);
                    return WorkerProtocol.Response(request, WorkerMessageStatus.Result, result);
                }
            case WorkerProtocol.InspectArchiveCache:
                {
                    var payload = RequirePayload<ArchiveCacheHealthRequest>(request);
                    var result = await _cacheHealth.InspectAsync(payload, publishProgress, cancellationToken).ConfigureAwait(false);
                    return WorkerProtocol.Response(request, WorkerMessageStatus.Result, result);
                }
            case WorkerProtocol.DiscoverGameRoots:
                {
                    _ = RequirePayload<GameInstallDiscoveryRequest>(request);
                    var result = await _gameDiscovery.DiscoverAsync(cancellationToken).ConfigureAwait(false);
                    return WorkerProtocol.Response(request, WorkerMessageStatus.Result, result);
                }
            case WorkerProtocol.ArchiveFacets:
                {
                    var payload = RequirePayload<ArchiveFacetsRequest>(request);
                    var result = await _facets.LoadAsync(payload, publishProgress, cancellationToken).ConfigureAwait(false);
                    return WorkerProtocol.Response(request, WorkerMessageStatus.Result, result);
                }
            case WorkerProtocol.BuildNameIndex:
                {
                    var payload = RequirePayload<BuildNameIndexRequest>(request);
                    var result = await _nameIndex.BuildAsync(payload, publishProgress, cancellationToken).ConfigureAwait(false);
                    return WorkerProtocol.Response(request, WorkerMessageStatus.Result, result);
                }
            case WorkerProtocol.FindAssociatedAssets:
                {
                    var payload = RequirePayload<FindAssociatedAssetsRequest>(request);
                    var result = await _associations.FindAsync(payload, publishProgress, cancellationToken).ConfigureAwait(false);
                    return WorkerProtocol.Response(request, WorkerMessageStatus.Result, result);
                }
            case WorkerProtocol.Preview:
                {
                    var payload = RequirePayload<PreviewRequest>(request);
                    var result = await _previews.BuildAsync(payload, cancellationToken, publishProgress).ConfigureAwait(false);
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
