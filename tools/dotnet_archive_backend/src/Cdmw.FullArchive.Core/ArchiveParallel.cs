using System.Runtime.ExceptionServices;

namespace Cdmw.FullArchive.Core;

/// <summary>
/// Splits a pass over archive rows into fixed chunks that run in parallel. Callers
/// keep one result per chunk and join them in chunk order, so the output is the
/// same as a sequential pass.
/// </summary>
internal static class ArchiveParallel
{
    public const int ChunkSize = 16_384;

    public static int DegreeOfParallelism { get; } = Math.Clamp(Environment.ProcessorCount, 1, 8);

    /// <summary>At least one chunk, so an empty pass still runs its body once over [0, 0).</summary>
    public static int ChunkCount(long total) => Math.Max(1, checked((int)((total + ChunkSize - 1) / ChunkSize)));

    /// <summary>
    /// Runs <paramref name="body"/> once per chunk with its index and its
    /// [start, end) range. The first failure is rethrown as itself rather than
    /// wrapped, and a cancelled token surfaces as <see cref="OperationCanceledException"/>.
    /// </summary>
    public static void ForEachChunk(long total, CancellationToken cancellationToken, Action<int, long, long> body)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var chunks = ChunkCount(total);
        if (chunks <= 1)
        {
            body(0, 0, total);
            return;
        }
        For(chunks, cancellationToken, chunk =>
        {
            var start = (long)chunk * ChunkSize;
            body(chunk, start, Math.Min(total, start + ChunkSize));
        });
    }

    /// <summary>
    /// Sorts the joined chunks. Each chunk is sorted in parallel and the runs are
    /// merged pairwise in parallel rounds. <paramref name="comparison"/> must be a
    /// total order with no ties between distinct items, so the result is the one
    /// order a sequential sort of the joined list would also produce.
    /// </summary>
    public static T[] SortedConcat<T>(IReadOnlyList<List<T>?> chunks, Comparison<T> comparison, CancellationToken cancellationToken)
    {
        var runs = chunks.Where(static chunk => chunk is { Count: > 0 }).Select(static chunk => chunk!.ToArray()).ToArray();
        if (runs.Length == 0)
        {
            return [];
        }
        For(runs.Length, cancellationToken, run => Array.Sort(runs[run], comparison));
        while (runs.Length > 1)
        {
            var merged = new T[(runs.Length + 1) / 2][];
            var current = runs;
            For(merged.Length, cancellationToken, pair =>
            {
                var left = current[pair * 2];
                merged[pair] = pair * 2 + 1 < current.Length ? Merge(left, current[pair * 2 + 1], comparison) : left;
            });
            runs = merged;
        }
        return runs[0];
    }

    private static T[] Merge<T>(T[] left, T[] right, Comparison<T> comparison)
    {
        var result = new T[left.Length + right.Length];
        int leftIndex = 0, rightIndex = 0, position = 0;
        while (leftIndex < left.Length && rightIndex < right.Length)
        {
            result[position++] = comparison(left[leftIndex], right[rightIndex]) <= 0 ? left[leftIndex++] : right[rightIndex++];
        }
        Array.Copy(left, leftIndex, result, position, left.Length - leftIndex);
        position += left.Length - leftIndex;
        Array.Copy(right, rightIndex, result, position, right.Length - rightIndex);
        return result;
    }

    private static void For(int count, CancellationToken cancellationToken, Action<int> body)
    {
        try
        {
            Parallel.For(
                0,
                count,
                new ParallelOptions { MaxDegreeOfParallelism = DegreeOfParallelism, CancellationToken = cancellationToken },
                body);
        }
        catch (AggregateException error)
        {
            var inner = error.Flatten().InnerExceptions;
            var first = inner.FirstOrDefault(static item => item is OperationCanceledException) ?? inner[0];
            ExceptionDispatchInfo.Capture(first).Throw();
            throw;
        }
    }

    /// <summary>Joins per-chunk lists in chunk order.</summary>
    public static T[] Concat<T>(IReadOnlyList<List<T>?> chunks)
    {
        var count = 0;
        foreach (var chunk in chunks)
        {
            count = checked(count + (chunk?.Count ?? 0));
        }
        var result = new T[count];
        var position = 0;
        foreach (var chunk in chunks)
        {
            if (chunk is null)
            {
                continue;
            }
            chunk.CopyTo(result, position);
            position += chunk.Count;
        }
        return result;
    }
}
