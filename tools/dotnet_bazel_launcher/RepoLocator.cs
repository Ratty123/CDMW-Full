namespace Cdmw.BazelLauncher;

/// <summary>
/// Finds the workspace root and the tools Bazel needs.
/// </summary>
/// <remarks>
/// The launcher can run from the source tree, from a Bazel output directory, or
/// from anywhere the user copied it, so the root is discovered by walking up
/// looking for MODULE.bazel rather than assumed from the executable location.
/// </remarks>
internal static class RepoLocator
{
    private const string WorkspaceMarker = "MODULE.bazel";

    public static DirectoryInfo? FindWorkspaceRoot(string startDirectory)
    {
        var current = new DirectoryInfo(startDirectory);
        while (current is not null)
        {
            if (File.Exists(Path.Combine(current.FullName, WorkspaceMarker)))
            {
                return current;
            }

            current = current.Parent;
        }

        return null;
    }

    public static string? FindBazel(DirectoryInfo workspaceRoot)
    {
        // The repo-local bazelisk is preferred over anything on PATH so the
        // launcher uses the same pinned Bazel version as the command line.
        var local = Path.Combine(workspaceRoot.FullName, ".tools", "bazel", "bazel.exe");
        if (File.Exists(local))
        {
            return local;
        }

        var pathValue = Environment.GetEnvironmentVariable("PATH") ?? string.Empty;
        foreach (var directory in pathValue.Split(Path.PathSeparator, StringSplitOptions.RemoveEmptyEntries))
        {
            try
            {
                var candidate = Path.Combine(directory.Trim(), "bazel.exe");
                if (File.Exists(candidate))
                {
                    return candidate;
                }
            }
            catch (ArgumentException)
            {
                // A malformed PATH entry is not worth failing discovery over.
            }
        }

        return null;
    }

    /// <summary>
    /// Bazel cannot always auto-detect MSVC. Locating it here means the user
    /// never has to set BAZEL_VC by hand before opening the launcher.
    /// </summary>
    public static string? FindVisualStudioVc()
    {
        if (Environment.GetEnvironmentVariable("BAZEL_VC") is { Length: > 0 } existing
            && Directory.Exists(existing))
        {
            return existing;
        }

        var programFilesX86 = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86);
        var programFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
        string[] editions = ["BuildTools", "Community", "Professional", "Enterprise"];

        foreach (var root in new[] { programFilesX86, programFiles })
        {
            if (string.IsNullOrEmpty(root))
            {
                continue;
            }

            foreach (var year in new[] { "2022", "2019" })
            {
                foreach (var edition in editions)
                {
                    var candidate = Path.Combine(root, "Microsoft Visual Studio", year, edition, "VC");
                    if (Directory.Exists(candidate))
                    {
                        return candidate;
                    }
                }
            }
        }

        return null;
    }
}
