using System.Collections.Concurrent;
using System.Runtime.CompilerServices;
using System.Text.Json;
using Cdmw.FullArchive.Contracts;

namespace Cdmw.FullArchive.Core;

public sealed class ArchiveNpcCatalogService(ArchiveSessionManager sessions, NativeArchiveCore native)
{
    private readonly ConcurrentDictionary<string, SemaphoreSlim> _gates = new(StringComparer.Ordinal);
    private static readonly JsonSerializerOptions CacheOptions = new() { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };
    // Model file name -> item IDs, per published item catalogue.
    private static readonly ConditionalWeakTable<ArchiveItemCatalog, Dictionary<string, int[]>> ItemModels = new();

    public async Task<BuildNpcCatalogResult> BuildAsync(BuildNpcCatalogRequest request,
        Func<ProgressUpdate, Task>? progress, CancellationToken token)
    {
        var session = sessions.GetRequired(request.SessionId);
        if (session.TryGetNpcCatalog(out var present)) return Summary(session.Id, present!, true);
        var gate = _gates.GetOrAdd(session.GenerationPath, static _ => new SemaphoreSlim(1, 1));
        await gate.WaitAsync(token).ConfigureAwait(false);
        try
        {
            if (session.TryGetNpcCatalog(out present)) return Summary(session.Id, present!, true);
            var signature = session.Fingerprint + ":" + ArchiveItemSources.MountSignature(session.PackageRoot);
            var cachePath = Path.Combine(session.GenerationPath, $"npc-catalog-v{ArchiveNpcCatalogBuilder.Version}.json");
            var snapshot = await ReadCacheAsync(cachePath, signature, token).ConfigureAwait(false);
            var usedCache = snapshot is not null;
            if (snapshot is null)
            {
                snapshot = await Task.Run(() => ArchiveNpcCatalogBuilder.Build(session.PackageRoot, signature,
                    Enumerate(session, token), entry => native.Decode(entry).Bytes, token,
                    (done, total, phase) => {
                        if ((done & 0x3F) == 0 && progress is not null)
                            progress(new ProgressUpdate(done, total, "npc_catalog", phase)).GetAwaiter().GetResult();
                    }), token).ConfigureAwait(false);
                await WriteCacheAsync(cachePath, snapshot, session.Id, token).ConfigureAwait(false);
            }
            token.ThrowIfCancellationRequested();
            sessions.GetRequired(session.Id);
            var catalog = new ArchiveNpcCatalog(snapshot);
            session.SetNpcCatalog(catalog);
            return Summary(session.Id, catalog, usedCache);
        }
        finally { gate.Release(); }
    }

    public async Task<NpcCatalogSearchResult> SearchAsync(NpcCatalogSearchRequest request,
        Func<ProgressUpdate, Task>? progress, CancellationToken token)
    {
        var catalog = await RequiredAsync(request.SessionId, progress, token).ConfigureAwait(false);
        token.ThrowIfCancellationRequested();
        return catalog.Search(request);
    }

    public async Task<NpcOutfitResult> OutfitAsync(NpcOutfitRequest request,
        Func<ProgressUpdate, Task>? progress, CancellationToken token)
    {
        var catalog = await RequiredAsync(request.SessionId, progress, token).ConfigureAwait(false);
        var session = sessions.GetRequired(request.SessionId);
        var key = request.Key ?? "";
        if (!key.StartsWith("npc:", StringComparison.Ordinal) && !key.StartsWith("appearance:", StringComparison.Ordinal))
            key = "appearance:" + ArchiveCharacterReferences.Normalize(key);
        var record = catalog.GetRequired(key);
        var outfits = record.Outfits.AsEnumerable();
        if (!string.IsNullOrWhiteSpace(request.AppearancePath))
        {
            var wanted = ArchiveCharacterReferences.Normalize(request.AppearancePath);
            outfits = outfits.Where(outfit => ArchiveCharacterReferences.Normalize(outfit.AppearancePath) == wanted);
        }
        var selected = outfits.ToArray();
        var items = session.TryGetItemCatalog(out var itemCatalog) && itemCatalog is not null ? ItemsByModel(itemCatalog) : null;
        if (items is not null)
            selected = selected.Select(outfit => outfit with { Pieces = outfit.Pieces.Select(piece => piece.ModelPath.Length == 0 ? piece
                : piece with { ItemIds = items.GetValueOrDefault(Path.GetFileName(ArchiveCharacterReferences.Normalize(piece.ModelPath))) ?? [] }).ToArray() }).ToArray();
        token.ThrowIfCancellationRequested();
        var others = record.SearchNames.Where(name => !name.Equals(record.Row.DisplayName, StringComparison.OrdinalIgnoreCase)
            && !name.Equals(record.Row.InternalName, StringComparison.OrdinalIgnoreCase)
            && !name.Equals(record.Row.CharacterId.ToString(System.Globalization.CultureInfo.InvariantCulture), StringComparison.Ordinal))
            .Take(32).ToArray();
        return new(session.Id, record.Row, selected, others, items is not null);
    }

    public async Task<NpcWearersResult> WearersAsync(NpcWearersRequest request,
        Func<ProgressUpdate, Task>? progress, CancellationToken token)
    {
        var catalog = await RequiredAsync(request.SessionId, progress, token).ConfigureAwait(false);
        token.ThrowIfCancellationRequested();
        return catalog.Wearers(request.SessionId, request.Piece, request.MaximumResults);
    }

    private static Dictionary<string, int[]> ItemsByModel(ArchiveItemCatalog catalog) =>
        ItemModels.GetValue(catalog, static items => items.Items
            .SelectMany(static item => item.PacFiles.Select(path => (File: Path.GetFileName(ArchiveCharacterReferences.Normalize(path)), item.ItemId)))
            .Where(static pair => pair.File.Length > 0)
            .GroupBy(static pair => pair.File, StringComparer.OrdinalIgnoreCase)
            .ToDictionary(static group => group.Key, static group => group.Select(static pair => pair.ItemId).Distinct().Order().Take(16).ToArray(),
                StringComparer.OrdinalIgnoreCase));

    private static async Task<NpcCatalogSnapshot?> ReadCacheAsync(string cachePath, string signature, CancellationToken token)
    {
        if (!File.Exists(cachePath)) return null;
        try
        {
            if (new FileInfo(cachePath).Length > 256 * 1024 * 1024) return null;
            await using var stream = new FileStream(
                cachePath,
                FileMode.Open,
                FileAccess.Read,
                FileShare.ReadWrite | FileShare.Delete,
                16 * 1024,
                FileOptions.Asynchronous | FileOptions.SequentialScan);
            var cached = await JsonSerializer.DeserializeAsync<NpcCatalogSnapshot>(stream, CacheOptions, token).ConfigureAwait(false);
            return cached is not null && cached.Version == ArchiveNpcCatalogBuilder.Version && cached.Signature == signature ? cached : null;
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or JsonException or NotSupportedException) { return null; }
    }

    private async Task WriteCacheAsync(string cachePath, NpcCatalogSnapshot snapshot, string sessionId, CancellationToken token)
    {
        var temporary = cachePath + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try
        {
            await using (var output = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            {
                await JsonSerializer.SerializeAsync(output, snapshot, CacheOptions, token).ConfigureAwait(false);
                await output.FlushAsync(token).ConfigureAwait(false);
            }
            token.ThrowIfCancellationRequested();
            sessions.GetRequired(sessionId);
            File.Move(temporary, cachePath, overwrite: true);
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            // Best-effort cache write; concurrent readers or sharing violations leave the in-memory build intact.
        }
        finally
        {
            try { if (File.Exists(temporary)) File.Delete(temporary); }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException) { }
        }
    }

    private async Task<ArchiveNpcCatalog> RequiredAsync(string sessionId, Func<ProgressUpdate, Task>? progress, CancellationToken token)
    {
        await BuildAsync(new(sessionId), progress, token).ConfigureAwait(false);
        sessions.GetRequired(sessionId).TryGetNpcCatalog(out var catalog);
        return catalog ?? throw new InvalidOperationException("NPC catalogue was not published.");
    }

    private static IEnumerable<ArchiveEntryDto> Enumerate(ArchiveSession session, CancellationToken token) =>
        ArchiveCatalogInventory.CharacterEntries(session, ArchiveNpcCatalogBuilder.InventoryExtensions, token);

    private static BuildNpcCatalogResult Summary(string sessionId, ArchiveNpcCatalog catalog, bool cached)
    {
        var snapshot = catalog.Snapshot;
        return new(sessionId, cached, snapshot.Records.Count(static record => record.Row.CharacterId != 0),
            snapshot.Records.Count(static record => record.Row.CharacterId == 0), snapshot.Statistics, snapshot.Warnings);
    }
}
