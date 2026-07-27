using System.Globalization;
using System.Text.RegularExpressions;

namespace Cdmw.BazelLauncher;

/// <summary>A progress reading recovered from one line of build output.</summary>
internal readonly record struct ProgressSignal(int? Percent, string? Stage)
{
    public bool HasValue => Percent is not null || Stage is not null;
}

/// <summary>
/// Turns build output into real progress. Nothing here is estimated: both build
/// systems already emit a progress signal, they just do it differently.
/// </summary>
internal static partial class ProgressParser
{
    // build_pyside6_app.ps1's Write-BuildProgress emits "::progress::42::Stage".
    [GeneratedRegex(@"^::progress::(?<percent>\d{1,3})::(?<stage>.*)$", RegexOptions.CultureInvariant)]
    private static partial Regex ScriptProgress();

    // Bazel action counter, e.g. "[38 / 54] Compiling foo.cpp; 1s local".
    [GeneratedRegex(@"^\[(?<done>[\d,]+)\s*/\s*(?<total>[\d,]+)\]\s*(?<stage>.*)$", RegexOptions.CultureInvariant)]
    private static partial Regex BazelActions();

    // Bazel's pre-execution phases have no counter, but are worth showing.
    [GeneratedRegex(@"^(?<stage>(Analyzing|Loading|Computing|Fetching|Extracting)\b.*)$", RegexOptions.CultureInvariant)]
    private static partial Regex BazelPhase();

    public static ProgressSignal Parse(string line)
    {
        var trimmed = line.Trim();
        if (trimmed.Length == 0)
        {
            return default;
        }

        var script = ScriptProgress().Match(trimmed);
        if (script.Success)
        {
            var percent = int.Parse(script.Groups["percent"].Value, CultureInfo.InvariantCulture);
            return new ProgressSignal(Math.Clamp(percent, 0, 100), Describe(script.Groups["stage"].Value));
        }

        var actions = BazelActions().Match(trimmed);
        if (actions.Success
            && long.TryParse(actions.Groups["done"].Value.Replace(",", ""), out var done)
            && long.TryParse(actions.Groups["total"].Value.Replace(",", ""), out var total)
            && total > 0)
        {
            // Bazel's total grows as the graph expands, so this can move
            // backwards. That is honest - it is what the build is actually doing.
            var percent = (int)Math.Clamp(done * 100 / total, 0, 100);
            return new ProgressSignal(percent, Describe(actions.Groups["stage"].Value));
        }

        var phase = BazelPhase().Match(trimmed);
        if (phase.Success)
        {
            return new ProgressSignal(null, Describe(phase.Groups["stage"].Value));
        }

        return default;
    }

    /// <summary>Trim the noise Bazel appends so the status line stays readable.</summary>
    private static string? Describe(string stage)
    {
        var text = stage.Trim();
        if (text.Length == 0)
        {
            return null;
        }

        var cut = text.IndexOf("; ", StringComparison.Ordinal);
        if (cut > 0)
        {
            text = text[..cut];
        }

        cut = text.IndexOf(" ... (", StringComparison.Ordinal);
        if (cut > 0)
        {
            text = text[..cut];
        }

        return text.Length > 110 ? text[..108] + "..." : text;
    }
}
