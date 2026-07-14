using System.Drawing;
using System.IO;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class NetTextureSet
{
    private const int MaxTextureLoadFailures = 256;
    private readonly Dictionary<string, Task<NetTextureDecodePayload>> _decodeFlights = new(StringComparer.OrdinalIgnoreCase);
    private long _decodeAttemptCount;
    private long _decodeSuccessCount;
    private long _decodeReuseCount;
    private long _incrementalDecodeCount;
    private long _decodeSingleflightJoinCount;
    private long _decodedBitmapPruneCount;

    public long DecodeSingleflightJoinCount { get { lock (_gate) return _decodeSingleflightJoinCount; } }
    public long DecodedBitmapPruneCount { get { lock (_gate) return _decodedBitmapPruneCount; } }

    public Task<NetTextureDecodeResult> DecodeResourcesAsync(IEnumerable<NetMaterialResource> resources)
    {
        var snapshot = resources.Where(resource => !string.IsNullOrWhiteSpace(resource.Path)).ToArray();
        return DecodeResourcesCoreAsync(snapshot, incremental: true);
    }

    public Bitmap? BitmapForReference(NetMaterialTextureReference reference)
    {
        if (reference.IsEmpty)
        {
            return null;
        }
        lock (_gate)
        {
            if (_decodedByFingerprint.TryGetValue(reference.SourceCacheKey, out var exact))
            {
                return exact;
            }
            return _lastGoodResourceKeys.TryGetValue(reference.ResourceId, out var lastGoodKey)
                && _decodedByFingerprint.TryGetValue(lastGoodKey, out var lastGood)
                    ? lastGood
                    : null;
        }
    }

    public NetDdsNativeTextureData? NativeDdsForReference(NetMaterialTextureReference reference)
    {
        if (reference.IsEmpty)
        {
            return null;
        }
        lock (_gate)
        {
            if (_nativeDdsByFingerprint.TryGetValue(reference.SourceCacheKey, out var exact))
            {
                return exact;
            }
            return _lastGoodResourceKeys.TryGetValue(reference.ResourceId, out var lastGoodKey)
                && _nativeDdsByFingerprint.TryGetValue(lastGoodKey, out var lastGood)
                    ? lastGood
                    : null;
        }
    }

    internal static string TextureCacheKey(string path, string fingerprint)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return string.Empty;
        }
        var fullPath = Path.GetFullPath(path);
        if (!string.IsNullOrWhiteSpace(fingerprint))
        {
            return $"fingerprint|{fingerprint}";
        }
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

    private NetTextureDecodeResult DecodeResources(IEnumerable<NetMaterialResource> resources, bool incremental)
    {
        return DecodeResourcesCoreAsync(resources.ToArray(), incremental).GetAwaiter().GetResult();
    }

    private async Task<NetTextureDecodeResult> DecodeResourcesCoreAsync(
        IReadOnlyList<NetMaterialResource> resources,
        bool incremental)
    {
        if (incremental)
        {
            lock (_gate)
            {
                _incrementalDecodeCount++;
            }
        }

        var resourceGroups = resources
            .GroupBy(item => item.Reference.SourceCacheKey, StringComparer.OrdinalIgnoreCase)
            .ToArray();
        var tasks = resourceGroups
            .Select(group => DecodeOneResourceAsync(group.First()))
            .ToArray();
        var results = tasks.Length == 0
            ? Array.Empty<NetTextureResourceDecodeResult>()
            : await Task.WhenAll(tasks).ConfigureAwait(false);
        return new NetTextureDecodeResult(
            results.Sum(result => result.Decoded),
            results.Sum(result => result.Reused),
            results
                .SelectMany((result, index) => string.IsNullOrWhiteSpace(result.Error)
                    ? Array.Empty<KeyValuePair<string, string>>()
                    : resourceGroups[index]
                        .Select(resource => new KeyValuePair<string, string>(resource.ResourceId, result.Error)))
                .GroupBy(pair => pair.Key, StringComparer.Ordinal)
                .ToDictionary(group => group.Key, group => group.Last().Value, StringComparer.Ordinal));
    }

    private async Task<NetTextureResourceDecodeResult> DecodeOneResourceAsync(NetMaterialResource resource)
    {
        var reference = resource.Reference;
        var key = reference.SourceCacheKey;
        Task<NetTextureDecodePayload> flight;
        lock (_gate)
        {
            if (_disposed)
            {
                return new NetTextureResourceDecodeResult(resource.ResourceId, 0, 0, "texture_set_disposed");
            }
            var hasBitmap = _decodedByFingerprint.TryGetValue(key, out var cached);
            var hasNative = _nativeDdsByFingerprint.ContainsKey(key);
            if (hasBitmap || hasNative)
            {
                if (cached is not null)
                {
                    _decoded[resource.Path] = cached;
                }
                _lastGoodResourceKeys[resource.ResourceId] = key;
                _decodeReuseCount++;
                return new NetTextureResourceDecodeResult(resource.ResourceId, 0, 1, string.Empty);
            }
            if (_decodeFlights.TryGetValue(key, out var currentFlight))
            {
                flight = currentFlight;
                _decodeSingleflightJoinCount++;
            }
            else
            {
                flight = Task.Run(() =>
                {
                    var (bitmap, ddsInfo, nativeDds, error) = DecodeResource(resource.Path);
                    return new NetTextureDecodePayload(bitmap, ddsInfo, nativeDds, error);
                });
                _decodeFlights[key] = flight;
                _decodeAttemptCount++;
            }
        }

        NetTextureDecodePayload payload;
        try
        {
            payload = await flight.ConfigureAwait(false);
        }
        catch (Exception ex)
        {
            lock (_gate)
            {
                RemoveDecodeFlight(key, flight);
                RememberTextureLoadFailure(resource.Path);
            }
            return new NetTextureResourceDecodeResult(resource.ResourceId, 0, 0, ex.Message);
        }

        lock (_gate)
        {
            var finalizedFlight = RemoveDecodeFlight(key, flight);
            if (_disposed)
            {
                if (finalizedFlight)
                {
                    payload.Bitmap?.Dispose();
                }
                return new NetTextureResourceDecodeResult(resource.ResourceId, 0, 0, "texture_set_disposed");
            }
            if (payload.DdsInfo is not null)
            {
                _ddsResources[resource.Path] = payload.DdsInfo with { Path = resource.Path };
            }
            if (payload.Bitmap is null && payload.NativeDds is null)
            {
                RememberTextureLoadFailure(resource.Path);
                return new NetTextureResourceDecodeResult(resource.ResourceId, 0, 0, payload.Error);
            }

            var decoded = 0;
            var reused = 0;
            if (payload.NativeDds is not null)
            {
                if (_nativeDdsByFingerprint.ContainsKey(key))
                {
                    reused = 1;
                }
                else
                {
                    _nativeDdsByFingerprint[key] = payload.NativeDds;
                    decoded = 1;
                }
            }
            Bitmap? existing = null;
            if (payload.Bitmap is not null && _decodedByFingerprint.TryGetValue(key, out existing))
            {
                if (finalizedFlight && !ReferenceEquals(existing, payload.Bitmap))
                {
                    payload.Bitmap.Dispose();
                }
                _decodeReuseCount++;
                reused = 1;
            }
            else if (payload.Bitmap is not null)
            {
                existing = payload.Bitmap;
                _decodedByFingerprint[key] = existing;
                decoded = 1;
            }
            if (existing is not null)
            {
                _decoded[resource.Path] = existing;
            }
            if (decoded > 0)
            {
                _decodeSuccessCount++;
            }
            else if (reused > 0 && payload.Bitmap is null)
            {
                _decodeReuseCount++;
            }
            _lastGoodResourceKeys[resource.ResourceId] = key;
            _textureLoadFailures.RemoveAll(item => string.Equals(item, resource.Path, StringComparison.OrdinalIgnoreCase));
            return new NetTextureResourceDecodeResult(resource.ResourceId, decoded, reused, string.Empty);
        }
    }

    private bool RemoveDecodeFlight(string key, Task<NetTextureDecodePayload> flight)
    {
        if (_decodeFlights.TryGetValue(key, out var current) && ReferenceEquals(current, flight))
        {
            _decodeFlights.Remove(key);
            return true;
        }
        return false;
    }

    private void RememberTextureLoadFailure(string path)
    {
        _textureLoadFailures.RemoveAll(item => string.Equals(item, path, StringComparison.OrdinalIgnoreCase));
        _textureLoadFailures.Add(path);
        if (_textureLoadFailures.Count > MaxTextureLoadFailures)
        {
            _textureLoadFailures.RemoveRange(0, _textureLoadFailures.Count - MaxTextureLoadFailures);
        }
    }

    public void PruneToResources(IEnumerable<NetMaterialResource> resources)
    {
        var active = resources
            .Where(resource => !string.IsNullOrWhiteSpace(resource.Path))
            .ToArray();
        var activeResourceIds = active.Select(resource => resource.ResourceId).ToHashSet(StringComparer.Ordinal);
        var activePaths = active.Select(resource => resource.Path).ToHashSet(StringComparer.OrdinalIgnoreCase);
        var keepKeys = active.Select(resource => resource.Reference.SourceCacheKey).ToHashSet(StringComparer.OrdinalIgnoreCase);
        lock (_gate)
        {
            foreach (var resourceId in activeResourceIds)
            {
                if (_lastGoodResourceKeys.TryGetValue(resourceId, out var lastGoodKey))
                {
                    keepKeys.Add(lastGoodKey);
                }
            }
            keepKeys.UnionWith(_decodeFlights.Keys);

            var removedBitmaps = _decodedByFingerprint
                .Where(pair => !keepKeys.Contains(pair.Key))
                .Select(pair => pair.Value)
                .ToHashSet<Bitmap>(ReferenceEqualityComparer.Instance);
            foreach (var key in _decodedByFingerprint.Keys.Where(key => !keepKeys.Contains(key)).ToArray())
            {
                _decodedByFingerprint.Remove(key);
                _decodedBitmapPruneCount++;
            }
            foreach (var path in _decoded.Keys.Where(path => !activePaths.Contains(path)).ToArray())
            {
                _decoded.Remove(path);
            }
            var retainedBitmaps = _decodedByFingerprint.Values
                .Concat(_decoded.Values)
                .ToHashSet<Bitmap>(ReferenceEqualityComparer.Instance);
            foreach (var bitmap in removedBitmaps.Where(bitmap => !retainedBitmaps.Contains(bitmap)))
            {
                bitmap.Dispose();
            }
            foreach (var resourceId in _lastGoodResourceKeys.Keys.Where(id => !activeResourceIds.Contains(id)).ToArray())
            {
                _lastGoodResourceKeys.Remove(resourceId);
            }
            foreach (var bitmap in _materialPreviews.Values)
            {
                bitmap.Dispose();
            }
            _materialPreviews.Clear();
            foreach (var path in _ddsResources.Keys.Where(path => !activePaths.Contains(path)).ToArray())
            {
                _ddsResources.Remove(path);
            }
            foreach (var key in _nativeDdsByFingerprint.Keys.Where(key => !keepKeys.Contains(key)).ToArray())
            {
                _nativeDdsByFingerprint.Remove(key);
            }
            _textureLoadFailures.RemoveAll(path => !activePaths.Contains(path));
        }
    }

    private static (Bitmap? Bitmap, NetDdsTextureInfo? DdsInfo, NetDdsNativeTextureData? NativeDds, string Error) DecodeResource(string path)
    {
        if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
        {
            return (null, null, null, "texture_file_missing");
        }
        if (IsDdsPath(path))
        {
            var decoded = DecodeDds(path);
            return decoded.Bitmap is null && decoded.NativeDds is null
                ? (null, decoded.Info, null, "dds_decode_failed")
                : (decoded.Bitmap, decoded.Info, decoded.NativeDds, string.Empty);
        }
        if (!IsDecodableImagePath(path))
        {
            return (null, null, null, "unsupported_texture_format");
        }
        try
        {
            using var source = new Bitmap(path);
            return (new Bitmap(source), null, null, string.Empty);
        }
        catch (Exception ex)
        {
            return (null, null, null, ex.Message);
        }
    }
}

internal sealed record NetTextureDecodePayload(
    Bitmap? Bitmap,
    NetDdsTextureInfo? DdsInfo,
    NetDdsNativeTextureData? NativeDds,
    string Error);

internal sealed record NetTextureResourceDecodeResult(
    string ResourceId,
    int Decoded,
    int Reused,
    string Error);

internal sealed record NetTextureDecodeResult(
    int Decoded,
    int Reused,
    IReadOnlyDictionary<string, string> Failures)
{
    public bool Ok => Failures.Count == 0;
}
