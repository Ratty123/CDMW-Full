namespace Cdmw.ArchiveLite.Core;

public sealed class ArchiveWorkPriority
{
    private int _foregroundCount;

    public bool HasForegroundWork => Volatile.Read(ref _foregroundCount) > 0;

    public IDisposable EnterForeground()
    {
        Interlocked.Increment(ref _foregroundCount);
        return new ForegroundLease(this);
    }

    public async Task WaitForForegroundAsync(CancellationToken cancellationToken)
    {
        while (HasForegroundWork)
        {
            await Task.Delay(40, cancellationToken).ConfigureAwait(false);
        }
    }

    private sealed class ForegroundLease(ArchiveWorkPriority owner) : IDisposable
    {
        private ArchiveWorkPriority? _owner = owner;

        public void Dispose()
        {
            if (Interlocked.Exchange(ref _owner, null) is { } current)
            {
                Interlocked.Decrement(ref current._foregroundCount);
            }
        }
    }
}
