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
            if (_decodedByFingerprint.TryGetValue(reference.CacheKey, out var exact))
            {
                return exact;
            }
            return _lastGoodResourceKeys.TryGetValue(reference.ResourceId, out var lastGoodKey)
                && _decodedByFingerprint.TryGetValue(lastGoodKey, out var lastGood)
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

        var tasks = resources
            .DistinctBy(item => item.Reference.CacheKey)
            .Select(DecodeOneResourceAsync)
            .ToArray();
        var results = tasks.Length == 0
            ? Array.Empty<NetTextureResourceDecodeResult>()
            : await Task.WhenAll(tasks).ConfigureAwait(false);
        return new NetTextureDecodeResult(
            results.Sum(result => result.Decoded),
            results.Sum(result => result.Reused),
            results
                .Where(result => !string.IsNullOrWhiteSpace(result.Error))
                .GroupBy(result => result.ResourceId, StringComparer.Ordinal)
                .ToDictionary(group => group.Key, group => group.Last().Error, StringComparer.Ordinal));
    }

    private async Task<NetTextureResourceDecodeResult> DecodeOneResourceAsync(NetMaterialResource resource)
    {
        var reference = resource.Reference;
        var key = reference.CacheKey;
        Task<NetTextureDecodePayload> flight;
        lock (_gate)
        {
            if (_disposed)
            {
                return new NetTextureResourceDecodeResult(resource.ResourceId, 0, 0, "texture_set_disposed");
            }
            if (_decodedByFingerprint.TryGetValue(key, out var cached))
            {
                _decoded[resource.Path] = cached;
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
                    var (bitmap, ddsInfo, error) = DecodeResource(resource.Path);
                    return new NetTextureDecodePayload(bitmap, ddsInfo, error);
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
            if (payload.Bitmap is null)
            {
                RememberTextureLoadFailure(resource.Path);
                return new NetTextureResourceDecodeResult(resource.ResourceId, 0, 0, payload.Error);
            }

            var decoded = 0;
            var reused = 0;
            if (_decodedByFingerprint.TryGetValue(key, out var existing))
            {
                if (finalizedFlight && !ReferenceEquals(existing, payload.Bitmap))
                {
                    payload.Bitmap.Dispose();
                }
                _decodeReuseCount++;
                reused = 1;
            }
            else
            {
                existing = payload.Bitmap;
                _decodedByFingerprint[key] = existing;
                _decodeSuccessCount++;
                decoded = 1;
            }
            _decoded[resource.Path] = existing;
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
        var keepKeys = active.Select(resource => resource.Reference.CacheKey).ToHashSet(StringComparer.OrdinalIgnoreCase);
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
            _textureLoadFailures.RemoveAll(path => !activePaths.Contains(path));
        }
    }

    private static (Bitmap? Bitmap, NetDdsTextureInfo? DdsInfo, string Error) DecodeResource(string path)
    {
        if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
        {
            return (null, null, "texture_file_missing");
        }
        if (IsDdsPath(path))
        {
            var decoded = DecodeDds(path);
            return decoded.Bitmap is null
                ? (null, decoded.Info, "dds_decode_failed")
                : (decoded.Bitmap, decoded.Info, string.Empty);
        }
        if (!IsDecodableImagePath(path))
        {
            return (null, null, "unsupported_texture_format");
        }
        try
        {
            using var source = new Bitmap(path);
            return (new Bitmap(source), null, string.Empty);
        }
        catch (Exception ex)
        {
            return (null, null, ex.Message);
        }
    }
}

internal sealed record NetTextureDecodePayload(
    Bitmap? Bitmap,
    NetDdsTextureInfo? DdsInfo,
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
