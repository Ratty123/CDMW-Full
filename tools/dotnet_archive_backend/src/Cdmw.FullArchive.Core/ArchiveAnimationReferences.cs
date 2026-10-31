namespace Cdmw.FullArchive.Core;

// Animation files the general token scanner cannot reach: a clip's distance LOD
// has a different stem, and charts name sub-charts and sequences without an
// extension. Mirrors cdmw/domain/archives/resource_paths.py; the Python side
// classifies whatever this delivers, so only exact installed paths are added.
internal static class ArchiveAnimationReferences
{
    private const string MotionRoot = "character/motion/";
    private const string MotionLodRoot = "character/motion/motion_lod__/";
    private const string ActionChartRoot = "actionchart/bin__/";
    private const string SequenceRoot = "sequencer/";
    private const int MaximumChartNames = 4096;

    // Base clip <-> distance LOD; every installed LOD follows this layout.
    public static IEnumerable<string> ClipCompanionPaths(string normalizedPath)
    {
        if (!normalizedPath.EndsWith(".paa", StringComparison.Ordinal)) yield break;
        if (normalizedPath.StartsWith(MotionLodRoot, StringComparison.Ordinal))
        {
            var relative = normalizedPath[MotionLodRoot.Length..^4];
            if (relative.EndsWith("_lod", StringComparison.Ordinal))
                yield return MotionRoot + relative[..^4] + ".paa";
        }
        else if (normalizedPath.StartsWith(MotionRoot, StringComparison.Ordinal))
        {
            yield return MotionLodRoot + normalizedPath[MotionRoot.Length..^4] + "_lod.paa";
        }
    }

    // Chart strings are `<strlen + 1><ASCII><NUL>`. Only extensionless paths are
    // returned here, as the installed sub-chart and sequence paths they can name;
    // names with an extension already reach the general scanner.
    public static (IReadOnlyCollection<string> Paths, bool Truncated) ChartResourcePaths(
        byte[] data, CancellationToken cancellationToken)
    {
        var paths = new HashSet<string>(StringComparer.Ordinal);
        for (var end = 1; end < data.Length; end++)
        {
            if ((end & 0xFFFF) == 0) cancellationToken.ThrowIfCancellationRequested();
            if (data[end] != 0 || !IsPathByte(data[end - 1])) continue;
            var start = end;
            while (start > 0 && end - start < 254 && IsPathByte(data[start - 1])) start--;
            for (var candidate = start; candidate < end - 2; candidate++)
            {
                if (candidate == 0 || data[candidate - 1] != end - candidate + 1) continue;
                var text = System.Text.Encoding.ASCII.GetString(data, candidate, end - candidate)
                    .Replace('\\', '/').Trim('/').ToLowerInvariant();
                var name = text[(text.LastIndexOf('/') + 1)..];
                if (text.Contains('/') && !name.Contains('.'))
                {
                    if (paths.Count + 2 > MaximumChartNames) return (paths, true);
                    paths.Add(ActionChartRoot + text + ".paac");
                    paths.Add(SequenceRoot + text + ".paseq");
                }
                break;
            }
        }
        return (paths, false);
    }

    private static bool IsPathByte(byte value) =>
        value is >= (byte)'a' and <= (byte)'z' or >= (byte)'A' and <= (byte)'Z' or >= (byte)'0' and <= (byte)'9'
            or (byte)'_' or (byte)'.' or (byte)'/' or (byte)'\\' or (byte)'-' or (byte)'(' or (byte)')';
}
