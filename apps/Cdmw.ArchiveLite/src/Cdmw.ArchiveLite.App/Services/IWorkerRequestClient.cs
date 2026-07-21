using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.App.Services;

public interface IWorkerRequestClient
{
    Task<TResult> SendAsync<TRequest, TResult>(
        string kind,
        long generation,
        TRequest payload,
        CancellationToken cancellationToken,
        IProgress<ProgressUpdate>? progress = null);
}
