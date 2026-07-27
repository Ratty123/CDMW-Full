using System.Diagnostics;

namespace Cdmw.BazelLauncher;

/// <summary>
/// Runs a build command and streams its output line by line.
/// </summary>
internal sealed class CommandRunner
{
    private readonly string _bazelPath;
    private readonly string _workspaceRoot;
    private readonly string? _visualStudioVc;

    public CommandRunner(string bazelPath, string workspaceRoot, string? visualStudioVc)
    {
        _bazelPath = bazelPath;
        _workspaceRoot = workspaceRoot;
        _visualStudioVc = visualStudioVc;
    }

    /// <summary>
    /// Both streams are surfaced: Bazel reports progress on stderr, so watching
    /// stdout alone shows almost nothing.
    /// </summary>
    public async Task<int> RunAsync(
        BuildAction action,
        Action<string, bool> onOutput,
        CancellationToken cancellationToken)
    {
        var startInfo = new ProcessStartInfo
        {
            FileName = action.Kind == CommandKind.Bazel
                ? _bazelPath
                : Path.Combine(Environment.SystemDirectory, "cmd.exe"),
            WorkingDirectory = _workspaceRoot,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            RedirectStandardInput = true,
            CreateNoWindow = true,
        };

        if (action.Kind == CommandKind.Script)
        {
            // cmd.exe will not find a bare script name when
            // NoDefaultCurrentDirectoryInExePath is set, so anchor it explicitly.
            startInfo.ArgumentList.Add("/c");
            startInfo.ArgumentList.Add(Path.Combine(_workspaceRoot, action.Arguments[0]));
            for (var index = 1; index < action.Arguments.Count; index++)
            {
                startInfo.ArgumentList.Add(action.Arguments[index]);
            }
        }
        else
        {
            foreach (var argument in action.Arguments)
            {
                startInfo.ArgumentList.Add(argument);
            }
        }

        if (action.Kind == CommandKind.Bazel)
        {
            // Keep the output parseable: the curses renderer rewrites lines in
            // place, which turns the progress counter into noise once captured.
            startInfo.ArgumentList.Add("--curses=no");
            startInfo.ArgumentList.Add("--color=no");
        }

        if (!string.IsNullOrEmpty(_visualStudioVc))
        {
            startInfo.Environment["BAZEL_VC"] = _visualStudioVc;
        }

        using var process = new Process { StartInfo = startInfo, EnableRaisingEvents = true };

        process.OutputDataReceived += (_, e) =>
        {
            if (e.Data is not null)
            {
                onOutput(e.Data, false);
            }
        };
        process.ErrorDataReceived += (_, e) =>
        {
            if (e.Data is not null)
            {
                onOutput(e.Data, IsError(e.Data));
            }
        };

        var label = action.Kind == CommandKind.Bazel ? "bazel" : "cmd";
        onOutput($"> {label} {string.Join(' ', action.Arguments)}", false);

        if (!process.Start())
        {
            onOutput("Failed to start the build process.", true);
            return -1;
        }

        // build.bat prompts when it cannot read a selection; closing stdin makes
        // any such read return EOF instead of hanging with no console attached.
        process.StandardInput.Close();

        process.BeginOutputReadLine();
        process.BeginErrorReadLine();

        using var registration = cancellationToken.Register(() =>
        {
            try
            {
                if (!process.HasExited)
                {
                    // Kill the tree: both paths spawn compilers, MSBuild nodes and
                    // a Bazel client that outlive killing only the parent.
                    process.Kill(entireProcessTree: true);
                }
            }
            catch (InvalidOperationException)
            {
                // Exited between the check and the kill.
            }
        });

        try
        {
            await process.WaitForExitAsync(CancellationToken.None).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            return -1;
        }

        return process.ExitCode;
    }

    private static bool IsError(string line) =>
        line.StartsWith("ERROR", StringComparison.OrdinalIgnoreCase)
        || line.StartsWith("FAILED", StringComparison.OrdinalIgnoreCase)
        || line.Contains(": error ", StringComparison.OrdinalIgnoreCase);
}
