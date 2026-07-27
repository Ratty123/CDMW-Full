namespace Cdmw.BazelLauncher;

internal enum CommandKind
{
    /// <summary>Run the repo-local bazelisk.</summary>
    Bazel,

    /// <summary>Run a batch script through cmd.exe.</summary>
    Script,
}

/// <summary>
/// One thing the launcher can run. Titles say what you get; subtitles say what
/// it costs and what it does not do.
/// </summary>
internal sealed record BuildAction(
    string Title,
    string Subtitle,
    string Description,
    CommandKind Kind,
    IReadOnlyList<string> Arguments,
    string? ArtifactDirectory = null,
    string? ArtifactPattern = null,
    bool IsReleaseGate = false)
{
    public override string ToString() => Title;

    public static IReadOnlyList<BuildAction> All { get; } =
    [
        new BuildAction(
            "Build the app",
            "Fast · onefile · skips release checks",
            "Builds CrimsonDesertModWorkbench.exe with Bazel: the five native helpers, both " +
            ".NET publishes, then PyInstaller. Onefile, release profile.\r\n\r\n" +
            "This is the fast inner loop. It does NOT run the release validation " +
            "(archive member checks, helper hashes, backend probes, startup smokes) and does " +
            "not publish to dist/. Use \"Release build\" for anything you ship.",
            CommandKind.Bazel,
            ["build", "//:CrimsonDesertModWorkbench"],
            ArtifactDirectory: Path.Combine(".bazel", "bin"),
            ArtifactPattern: "CrimsonDesertModWorkbench.exe"),

        new BuildAction(
            "Release build",
            "Slow · full checks · publishes to dist/",
            "Runs build.bat onefile release - the shipping path.\r\n\r\n" +
            "Rebuilds everything from clean and runs every gate: dependency pins, dirty-tree " +
            "preflight, embedded archive member validation, helper hashes, archive backend " +
            "probes and the packaged startup smokes. The result lands in dist/ under its " +
            "versioned name.\r\n\r\n" +
            "Takes several minutes.",
            CommandKind.Script,
            // First element is the script, resolved against the workspace root by
            // CommandRunner. It must not be left relative: this machine sets
            // NoDefaultCurrentDirectoryInExePath, so cmd.exe does not search the
            // working directory and a bare "build.bat" is simply not found.
            ["build.bat", "onefile", "release"],
            ArtifactDirectory: "dist",
            ArtifactPattern: "*-windows-portable.exe",
            IsReleaseGate: true),

        new BuildAction(
            "Native helpers",
            "The five C++ helpers only",
            "Builds the native C++ helpers and nothing else: cd-texture-dx, preview core, " +
            "mesh core, archive accelerator and the full archive core DLL.\r\n\r\n" +
            "The fastest loop when working on C++ - a no-op rebuild is well under a second.",
            CommandKind.Bazel,
            ["build", "//:native_helpers"]),

        new BuildAction(
            "Native tests",
            "Self-tests, against the real DLL",
            "Runs the native self-tests. The full archive core test links the DLL that actually " +
            "ships rather than a static copy of the same sources.",
            CommandKind.Bazel,
            ["test", "//native/..."]),

        new BuildAction(
            "Everything",
            "Every Bazel target",
            "Builds every target in the workspace, including the .NET publishes and this " +
            "launcher itself.",
            CommandKind.Bazel,
            ["build", "//..."]),

        new BuildAction(
            "Clean",
            "Discard Bazel's output tree",
            "Deletes Bazel's outputs. The next build starts cold - a few seconds for the native " +
            "helpers, about 90 seconds for the whole app.\r\n\r\n" +
            "Does not touch dist/ or the CMake build directories.",
            CommandKind.Bazel,
            ["clean"]),
    ];
}
