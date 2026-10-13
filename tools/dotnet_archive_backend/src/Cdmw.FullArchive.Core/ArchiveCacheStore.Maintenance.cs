namespace Cdmw.FullArchive.Core;

public sealed partial class ArchiveCacheStore
{
    private readonly long _maximumBytes;
    private readonly long _targetBytes;
    private readonly TimeSpan _maintenanceInterval;
    private readonly object _maintenanceGate = new();
    private Task _maintenanceTask = Task.CompletedTask;
    private TaskCompletionSource _maintenanceWake = new(TaskCreationOptions.RunContinuationsAsynchronously);
    private bool _maintenanceRunning;
    private bool _maintenanceRequested;
    private bool _maintenanceUrgent;
    private bool _maintenanceDraining;
    private long? _lastMaintenanceTick;

    private static readonly EnumerationOptions CacheEnumerationOptions = new()
    {
        RecurseSubdirectories = true,
        AttributesToSkip = FileAttributes.ReparsePoint,
        IgnoreInaccessible = true,
    };

    // Requests only enqueue/coalesce work. No directory scan runs on an archive,
    // preview or UI request path, including a warm catalogue open.
    internal void RequestMaintenance(bool immediate = false)
    {
        lock (_maintenanceGate)
        {
            _maintenanceRequested = true;
            _maintenanceUrgent |= immediate;
            if (immediate) _maintenanceWake.TrySetResult();
            if (_maintenanceRunning) return;
            _maintenanceRunning = true;
            _maintenanceTask = Task.Run(MaintainAsync);
        }
    }

    public Task WaitForMaintenanceAsync(CancellationToken cancellationToken)
    {
        lock (_maintenanceGate)
        {
            _maintenanceDraining = true;
            RequestMaintenance(immediate: true);
            return _maintenanceTask.WaitAsync(cancellationToken);
        }
    }

    private async Task MaintainAsync()
    {
        while (true)
        {
            Task wake;
            TimeSpan delay;
            lock (_maintenanceGate)
            {
                _maintenanceRequested = false;
                delay = _maintenanceDraining || _maintenanceUrgent || _lastMaintenanceTick is null
                    ? TimeSpan.Zero
                    : TimeSpan.FromMilliseconds(Math.Max(0,
                        _maintenanceInterval.TotalMilliseconds - (Environment.TickCount64 - _lastMaintenanceTick.Value)));
                if (delay == TimeSpan.Zero && !_maintenanceDraining && !_maintenanceUrgent && _lastMaintenanceTick is not null)
                    delay = TimeSpan.FromMilliseconds(10);
                _maintenanceUrgent = false;
                wake = _maintenanceWake.Task;
            }
            if (delay > TimeSpan.Zero) await Task.WhenAny(Task.Delay(delay), wake).ConfigureAwait(false);
            try
            {
                TrimCacheFamily();
            }
            catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
            {
                // A concurrent release, upgrade or external file lock is retried
                // at the next request. Never fail foreground archive work.
            }
            catch (Exception exception)
            {
                System.Diagnostics.Trace.TraceWarning($"Archive cache maintenance failed: {exception}");
            }
            lock (_maintenanceGate)
            {
                _lastMaintenanceTick = Environment.TickCount64;
                _maintenanceWake = new(TaskCreationOptions.RunContinuationsAsynchronously);
                if (_maintenanceRequested) continue;
                _maintenanceDraining = false;
                _maintenanceRunning = false;
                return;
            }
        }
    }

    private static bool IsSharingViolation(IOException exception) =>
        (exception.HResult & 0xFFFF) is 32 or 33;

    private static async Task<FileStream> OpenGenerationUseAsync(string path, CancellationToken cancellationToken)
    {
        var leasePath = GenerationUsePath(path);
        Directory.CreateDirectory(Path.GetDirectoryName(leasePath)!);
        while (true)
        {
            cancellationToken.ThrowIfCancellationRequested();
            try
            {
                return new FileStream(leasePath, FileMode.OpenOrCreate,
                    FileAccess.Read, FileShare.ReadWrite);
            }
            catch (IOException exception) when (IsSharingViolation(exception))
            {
                // An inactive generation is briefly locked during maintenance.
                // A sharing violation is not evidence of a corrupt catalogue.
                await Task.Delay(20, cancellationToken).ConfigureAwait(false);
            }
        }
    }

    private GenerationMaintenanceLease? TryLockInactiveGeneration(string path)
    {
        if (IsActive(path)) return null;
        if (IsOpeningGeneration(path))
        {
            RequestMaintenance();
            return null;
        }
        FileStream? marker = null;
        FileStream? index = null;
        try
        {
            var leasePath = GenerationUsePath(path);
            var leaseRoot = new DirectoryInfo(Path.GetDirectoryName(leasePath)!);
            if (leaseRoot.Exists && IsLink(leaseRoot)) return null;
            Directory.CreateDirectory(Path.GetDirectoryName(leasePath)!);
            marker = new FileStream(leasePath, FileMode.OpenOrCreate,
                FileAccess.ReadWrite, FileShare.Delete);
            var indexPath = Path.Combine(path, "archive.ali");
            if (File.Exists(indexPath))
            {
                // Older workers do not hold a generation marker. Their mapped index still
                // refuses this exclusive read, protecting their prepared paths.
                index = new FileStream(indexPath, FileMode.Open, FileAccess.Read, FileShare.Delete);
            }
            if (!IsOpeningGeneration(path)) return new(marker, index);
            index?.Dispose();
            marker.Dispose();
            RequestMaintenance();
            return null;
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            index?.Dispose();
            marker?.Dispose();
            return null;
        }
    }

    private void TrimCacheFamily()
    {
        var root = new DirectoryInfo(CatalogueRoot);
        if (!root.Exists || IsLink(root)) return;
        // Separate helpers sharing a cache also share this nonblocking sweep lock.
        using var sweep = TryOpenSweepLock();
        if (sweep is null) return;
        var directories = new List<CacheDirectory>();
        long total = root.EnumerateFiles().Where(item => !IsLink(item)).Sum(item => item.Length);
        foreach (var family in root.EnumerateDirectories().Where(item => !IsLink(item) && IsHash(item.Name, 24)))
        {
            total += family.EnumerateFiles().Where(item => !IsLink(item)).Sum(item => item.Length);
            var generations = new[] { "g", "generations", "quarantine" }
                .Select(name => new DirectoryInfo(Path.Combine(family.FullName, name)))
                .Where(item => item.Exists && !IsLink(item))
                .SelectMany(item => item.EnumerateDirectories())
                .Where(item => !IsLink(item) && (!item.Name.StartsWith(".", StringComparison.Ordinal)
                    || IsRetired(item.Name)))
                .Where(item => IsRetired(item.Name) || File.Exists(Path.Combine(item.FullName, "manifest.json")))
                .OrderByDescending(item => item.CreationTimeUtc).ToArray();
            var retainedGenerations = 0;
            foreach (var directory in generations)
            {
                var retired = IsRetired(directory.Name);
                var excess = retired || (directory.Parent!.Name != "quarantine" && retainedGenerations++ >= 2);
                var size = DirectorySize(directory.FullName);
                total += size;
                directories.Add(new(directory.FullName, size, directory.LastWriteTimeUtc, excess));
            }
        }
        var overBudget = total > _maximumBytes;
        foreach (var directory in directories.OrderBy(item => item.LastWriteUtc))
        {
            if ((!directory.ExcessGeneration && (!overBudget || total <= _targetBytes))
                || IsCurrentGeneration(directory.Path)) continue;
            using (var lease = TryLockInactiveGeneration(directory.Path))
            {
                if (lease is null || IsCurrentGeneration(directory.Path)) continue;
                total -= RetireGeneration(directory, lease);
            }
            if (!Directory.Exists(directory.Path))
            {
                try { File.Delete(GenerationUsePath(directory.Path)); }
                catch (Exception exception) when (exception is IOException or UnauthorizedAccessException) { }
            }
        }
        if (!overBudget || total <= _targetBytes) return;
        // Current indexes/catalogues are durable. Only their derived payloads
        // can be evicted, and only after every generation owner has released it.
        foreach (var directory in directories.OrderBy(item => item.LastWriteUtc))
        {
            if (!Directory.Exists(directory.Path)) continue;
            using (var probe = TryLockInactiveGeneration(directory.Path))
            {
                if (probe is null) continue;
            }
            // Build the eviction plan before holding the generation lock so
            // an archive open never waits on a recursive file inventory.
            var units = PreparedUnits(directory.Path).OrderBy(item => item.LastWriteUtc).ToArray();
            using var lease = TryLockInactiveGeneration(directory.Path);
            if (lease is null) continue;
            foreach (var unit in units)
            {
                if (IsOpeningGeneration(directory.Path)) break;
                total -= RemovePreparedUnit(unit.Files);
                if (total <= _targetBytes) return;
            }
        }
    }

    private FileStream? TryOpenSweepLock()
    {
        try
        {
            return new FileStream(Path.Combine(CatalogueRoot, ".maintenance.lock"), FileMode.OpenOrCreate,
                FileAccess.ReadWrite, FileShare.Delete);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            return null;
        }
    }

    private static long RetireGeneration(CacheDirectory directory, GenerationMaintenanceLease lease)
    {
        var retired = Path.Combine(Path.GetDirectoryName(directory.Path)!, $".retired-{Guid.NewGuid():N}");
        try
        {
            // Windows refuses directory renames while a child file is open.
            // The external marker still excludes every new generation owner;
            // an already mapped legacy index was rejected before this point.
            lease.ReleaseIndex();
            if (!CanRetire(directory.Path)) return 0;
            // Make retirement atomic before deleting children. An interrupted
            // sweep leaves a recognizable tombstone for a subsequent pass.
            Directory.Move(directory.Path, retired);
            Directory.Delete(retired, recursive: true);
            return directory.Size;
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            return Directory.Exists(retired) ? Math.Max(0, directory.Size - DirectorySize(retired)) : 0;
        }
    }

    private static bool CanRetire(string path)
    {
        var pending = new Stack<DirectoryInfo>();
        pending.Push(new(path));
        while (pending.TryPop(out var directory))
        {
            foreach (var entry in directory.EnumerateFileSystemInfos())
            {
                if (IsLink(entry)) return false;
                if (entry is DirectoryInfo child) pending.Push(child);
                else
                {
                    using var guard = new FileStream(entry.FullName, FileMode.Open, FileAccess.Read, FileShare.Delete);
                }
            }
        }
        return true;
    }

    private static IEnumerable<PreparedUnit> PreparedUnits(string generationPath)
    {
        foreach (var name in new[] { "p", "prepared" })
        {
            var root = new DirectoryInfo(Path.Combine(generationPath, name));
            if (!root.Exists || IsLink(root)) continue;
            foreach (var shard in root.EnumerateDirectories().Where(item => !IsLink(item) && IsHash(item.Name, 2)))
            {
                var files = shard.EnumerateFiles()
                    .Where(item => !IsLink(item) && item.Name.Length >= 64
                        && IsHash(item.Name[..64], 64) && item.Name.StartsWith(shard.Name, StringComparison.OrdinalIgnoreCase)
                        && (IsPreparedPayload(item.Name)
                            || IsPreparedCompanion(item.Name, ".meta.json")
                            || IsPreparedCompanion(item.Name, ".content-v1.json")
                            || IsPreparedCompanion(item.Name, ".content-v1.txt")));
                foreach (var group in files.GroupBy(item => item.Name[..64], StringComparer.OrdinalIgnoreCase))
                {
                    var unit = group.ToArray();
                    yield return new(unit, unit.Max(item => item.LastWriteTimeUtc));
                }
            }
        }
    }

    private static long RemovePreparedUnit(FileInfo[] files)
    {
        var guards = new List<FileStream>();
        long removed = 0;
        try
        {
            // Open every payload/metadata/analysis companion before deleting
            // any of them. Even an external reader prevents the whole eviction.
            foreach (var file in files)
                guards.Add(new FileStream(file.FullName, FileMode.Open, FileAccess.Read, FileShare.Delete));
            foreach (var file in files)
            {
                File.Delete(file.FullName);
                removed += file.Length;
            }
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            // Count only successful removals; an inaccessible unit stays eligible.
        }
        finally
        {
            foreach (var guard in guards) guard.Dispose();
        }
        return removed;
    }

    private static bool IsLink(FileSystemInfo entry) => (entry.Attributes & FileAttributes.ReparsePoint) != 0;
    private static bool IsPreparedPayload(string name) => name.Length == 64
        || (name.Length is > 65 and <= 80 && name[64] == '.' && name.IndexOf('.', 65) < 0);
    private static bool IsPreparedCompanion(string name, string suffix) =>
        name.EndsWith(suffix, StringComparison.OrdinalIgnoreCase) && IsPreparedPayload(name[..^suffix.Length]);
    private static bool IsHash(string text, int length) => text.Length == length && text.All(Uri.IsHexDigit);
    internal static string GenerationUsePath(string path) =>
        Path.Combine(Directory.GetParent(path)!.Parent!.FullName, ".leases", Path.GetFileName(path) + ".lock");
    private static bool IsRetired(string name) => name.StartsWith(".retired-", StringComparison.Ordinal) && IsHash(name[9..], 32);
    private bool IsOpeningGeneration(string path)
    {
        var rootId = Directory.GetParent(path)?.Parent?.Name;
        return rootId is not null && _rootGates.TryGetValue(rootId, out var gate) && gate.CurrentCount == 0;
    }
    private sealed record CacheDirectory(string Path, long Size, DateTime LastWriteUtc, bool ExcessGeneration);
    private sealed record PreparedUnit(FileInfo[] Files, DateTime LastWriteUtc);

    private sealed class GenerationMaintenanceLease(FileStream marker, FileStream? index) : IDisposable
    {
        public void ReleaseIndex() => index?.Dispose();
        public void Dispose()
        {
            index?.Dispose();
            marker.Dispose();
        }
    }
}
