using System.Diagnostics;

namespace Cdmw.MeshEditorExperiment;

/// <summary>
/// Startup phase marks for one helper process, from process creation to the
/// published <c>ready</c>. The host's readiness watchdog is a fixed budget,
/// so the helper has to be able to say which startup phase spent it; the marks
/// are published as the <c>startup_timing</c> protocol event immediately
/// before <c>ready</c>, and the host records them in its flight recorder.
/// </summary>
internal static class StartupTiming
{
    private static readonly object Gate = new();
    private static readonly List<(string Phase, double AtMs, int Handles)> Marks = new();
    private static readonly Stopwatch Clock = Stopwatch.StartNew();
    private static readonly double ProcessStartOffsetMs = ResolveProcessStartOffsetMs();

    /// <summary>
    /// The form whose realised window handles each mark counts, once it exists.
    /// Diagnostic only; a mark taken on another thread counts nothing.
    /// </summary>
    public static System.Windows.Forms.Control? Root { get; set; }

    /// <summary>
    /// Receives every mark as it is taken, so the host can see a helper that is
    /// still building its window. The readiness watchdog on the host side is a
    /// liveness check, not a budget: the mark stream is what proves liveness
    /// while the UI thread is inside the constructor and pumps nothing.
    /// </summary>
    public static Action<string, double>? Reporter { get; set; }

    private static volatile bool _sealed;

    /// <summary>
    /// Stop recording. Startup is over once <c>ready</c> is published; the same
    /// code paths run again for resident package swaps and topology edits, and
    /// those are not startup.
    /// </summary>
    public static void Seal()
    {
        _sealed = true;
        Reporter = null;
    }

    /// <summary>Record that <paramref name="phase"/> has just finished.</summary>
    public static void Mark(string phase)
    {
        if (_sealed)
        {
            return;
        }
        var at = Clock.Elapsed.TotalMilliseconds + ProcessStartOffsetMs;
        var root = Root;
        var handles = root is not null && !root.InvokeRequired ? CountHandles(root) : -1;
        lock (Gate)
        {
            Marks.Add((phase, at, handles));
        }
        try
        {
            Reporter?.Invoke(phase, at);
        }
        catch (Exception exception) when (exception is InvalidOperationException or ObjectDisposedException or System.IO.IOException)
        {
            // Progress reporting is diagnostic; a closed protocol stream is
            // the process shutting down and never a reason to fail a mark.
        }
    }

    private static int CountHandles(System.Windows.Forms.Control? root)
    {
        if (root is null || root.IsDisposed)
        {
            return 0;
        }
        var count = root.IsHandleCreated ? 1 : 0;
        foreach (System.Windows.Forms.Control child in root.Controls)
        {
            count += CountHandles(child);
        }
        return count;
    }

    /// <summary>Milliseconds since process creation, as the marks are measured.</summary>
    public static double ElapsedMs => Clock.Elapsed.TotalMilliseconds + ProcessStartOffsetMs;

    private static readonly Dictionary<string, (long Count, long Ticks)> Counters = new(StringComparer.Ordinal);

    /// <summary>Accumulate one call of <paramref name="counter"/> that took <paramref name="ticks"/> Stopwatch ticks.</summary>
    public static void Account(string counter, long ticks)
    {
        lock (Gate)
        {
            Counters[counter] = Counters.TryGetValue(counter, out var current)
                ? (current.Count + 1, current.Ticks + ticks)
                : (1, ticks);
        }
    }

    private static Dictionary<string, object?> CounterPayload()
    {
        var rows = new Dictionary<string, object?>(StringComparer.Ordinal);
        lock (Gate)
        {
            foreach (var (name, (count, ticks)) in Counters)
            {
                rows[name] = new Dictionary<string, object?>
                {
                    ["count"] = count,
                    ["total_ms"] = Math.Round(ticks * 1000.0 / Stopwatch.Frequency, 1),
                };
            }
        }
        return rows;
    }

    /// <summary>Controls reachable from <paramref name="root"/>, itself included.</summary>
    public static int CountControls(System.Windows.Forms.Control? root)
    {
        if (root is null || root.IsDisposed)
        {
            return 0;
        }
        var count = 1;
        foreach (System.Windows.Forms.Control child in root.Controls)
        {
            count += CountControls(child);
        }
        return count;
    }

    public static Dictionary<string, object?> Payload(System.Windows.Forms.Control? root = null)
    {
        (string Phase, double AtMs, int Handles)[] marks;
        lock (Gate)
        {
            marks = Marks.ToArray();
        }
        var rows = new List<Dictionary<string, object?>>(marks.Length);
        var previous = 0.0;
        foreach (var (phase, at, handles) in marks)
        {
            rows.Add(new Dictionary<string, object?>
            {
                ["phase"] = phase,
                ["at_ms"] = Math.Round(at, 1),
                ["delta_ms"] = Math.Round(at - previous, 1),
                ["handles"] = handles,
            });
            previous = at;
        }
        return new Dictionary<string, object?>
        {
            ["process_start_offset_ms"] = Math.Round(ProcessStartOffsetMs, 1),
            ["total_ms"] = Math.Round(previous, 1),
            ["control_count"] = CountControls(root),
            ["counters"] = CounterPayload(),
            ["marks"] = rows,
        };
    }

    private static double ResolveProcessStartOffsetMs()
    {
        // The runtime's own startup (host resolution, assembly loading, JIT of
        // Main) happens before any mark can be taken. Measure it once so the
        // marks are relative to process creation rather than to the first call.
        try
        {
            using var process = Process.GetCurrentProcess();
            var offset = (DateTime.Now - process.StartTime).TotalMilliseconds;
            return offset is > 0 and < 600_000 ? offset : 0.0;
        }
        catch (Exception exception) when (exception is InvalidOperationException or System.ComponentModel.Win32Exception or PlatformNotSupportedException)
        {
            return 0.0;
        }
    }
}
