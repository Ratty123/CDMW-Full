using System.Diagnostics;
using System.Drawing;
using System.Windows.Forms;

namespace Cdmw.BazelLauncher;

internal sealed class MainForm : Form
{
    private const int MaxConsoleLines = 4000;

    private readonly DirectoryInfo _workspaceRoot;
    private readonly CommandRunner _runner;
    private readonly List<OptionCard> _cards = [];
    private readonly List<Font> _fonts = [];

    private readonly Panel _rail = new();
    private readonly Label _heading = new();
    private readonly Label _subheading = new();
    private readonly Label _section = new();
    private readonly FlowLayoutPanel _list = new();
    private readonly Panel _buttonBar = new();

    private readonly Panel _pane = new();
    private readonly Panel _header = new();
    private readonly Panel _progressBlock = new();
    private readonly Panel _artifactBar = new();
    private readonly Panel _consoleFrame = new();

    private readonly Label _actionTitle = new();
    private readonly Label _actionDescription = new();
    private readonly StatusPill _pill = new();
    private readonly FlatProgressBar _progress = new();
    private readonly Label _percent = new();
    private readonly Label _stage = new();
    private readonly Label _elapsed = new();
    private readonly RichTextBox _console = new();
    private readonly FlatButton _run = new();
    private readonly FlatButton _stop = new();
    private readonly FlatButton _reveal = new();
    private readonly Label _artifact = new();
    private readonly System.Windows.Forms.Timer _clock = new() { Interval = 200 };

    private CancellationTokenSource? _cancellation;
    private Stopwatch? _stopwatch;
    private string? _lastArtifact;
    private BuildAction _selected = BuildAction.All[0];
    private bool _laying;
    private int _appliedDpi;

    public MainForm(DirectoryInfo workspaceRoot, string bazelPath, string? visualStudioVc)
    {
        _workspaceRoot = workspaceRoot;
        _runner = new CommandRunner(bazelPath, workspaceRoot.FullName, visualStudioVc);

        Text = "Build - Crimson Desert Mod Workbench";
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = Theme.Background;
        ForeColor = Theme.Text;
        DoubleBuffered = true;

        // Every measurement here is applied from DeviceDpi by ApplyMetrics, so the
        // framework must not scale a second time on top of it.
        AutoScaleMode = AutoScaleMode.None;

        Controls.Add(BuildRightPane());
        Controls.Add(BuildLeftRail());

        ApplyMetrics();
        Size = new Size(Theme.Scale(1220, DeviceDpi), Theme.Scale(800, DeviceDpi));

        _clock.Tick += (_, _) => UpdateElapsed();
        Select(BuildAction.All[0]);

        WriteLine($"Workspace   {workspaceRoot.FullName}", Theme.Faint);
        WriteLine($"Bazel       {bazelPath}", Theme.Faint);
        WriteLine(
            visualStudioVc is null
                ? "MSVC        not found - native builds will fail until Visual Studio is installed"
                : $"MSVC        {visualStudioVc}",
            visualStudioVc is null ? Theme.Danger : Theme.Faint);
        WriteLine(string.Empty, Theme.Faint);
        WriteLine("Pick what to build on the left, then press Build.", Theme.Muted);
    }

    private Control BuildLeftRail()
    {
        _rail.Dock = DockStyle.Left;
        _rail.BackColor = Theme.Background;

        _heading.Text = "Build";
        _heading.Dock = DockStyle.Top;
        _heading.ForeColor = Theme.Text;

        _subheading.Text = "Crimson Desert Mod Workbench";
        _subheading.Dock = DockStyle.Top;
        _subheading.ForeColor = Theme.Faint;

        _section.Text = "WHAT TO BUILD";
        _section.Dock = DockStyle.Top;
        _section.ForeColor = Theme.Faint;

        _list.Dock = DockStyle.Fill;
        _list.FlowDirection = FlowDirection.TopDown;
        _list.WrapContents = false;
        _list.AutoScroll = true;
        _list.BackColor = Theme.Background;
        _list.ClientSizeChanged += (_, _) => LayoutCards();

        foreach (var action in BuildAction.All)
        {
            var card = new OptionCard(action);
            card.Click += (_, _) => Select(action);
            _cards.Add(card);
            _list.Controls.Add(card);
        }

        _buttonBar.Dock = DockStyle.Bottom;
        _buttonBar.BackColor = Theme.Background;
        _buttonBar.Layout += (_, _) => LayoutButtons();

        _run.Text = "Build";
        _run.Click += async (_, _) => await RunSelectedAsync();

        _stop.Text = "Stop";
        _stop.Outline = true;
        _stop.Enabled = false;
        _stop.Click += (_, _) => _cancellation?.Cancel();

        _buttonBar.Controls.Add(_run);
        _buttonBar.Controls.Add(_stop);

        _rail.Controls.Add(_list);
        _rail.Controls.Add(_section);
        _rail.Controls.Add(_subheading);
        _rail.Controls.Add(_heading);
        _rail.Controls.Add(_buttonBar);
        return _rail;
    }

    private Control BuildRightPane()
    {
        _pane.Dock = DockStyle.Fill;
        _pane.BackColor = Theme.Background;

        // --- header -------------------------------------------------------
        _header.Dock = DockStyle.Top;
        _header.BackColor = Theme.Background;
        _header.Layout += (_, _) => LayoutHeader();

        _actionTitle.ForeColor = Theme.Text;
        _actionTitle.AutoEllipsis = true;

        _elapsed.ForeColor = Theme.Faint;
        _elapsed.TextAlign = ContentAlignment.MiddleRight;

        _header.Controls.Add(_actionTitle);
        _header.Controls.Add(_pill);
        _header.Controls.Add(_elapsed);

        // --- description --------------------------------------------------
        // Height follows the text: these run to four paragraphs, and a fixed box
        // silently swallowed everything past the second one.
        _actionDescription.Dock = DockStyle.Top;
        _actionDescription.ForeColor = Theme.Muted;
        _actionDescription.SizeChanged += (_, _) => LayoutDescription();

        // --- progress -----------------------------------------------------
        _progressBlock.Dock = DockStyle.Top;
        _progressBlock.BackColor = Theme.Background;
        _progressBlock.Layout += (_, _) => LayoutProgress();

        _percent.ForeColor = Theme.Muted;
        _percent.Text = string.Empty;
        _percent.TextAlign = ContentAlignment.MiddleLeft;

        _stage.ForeColor = Theme.Faint;
        _stage.AutoEllipsis = true;
        _stage.TextAlign = ContentAlignment.MiddleLeft;

        _progressBlock.Controls.Add(_progress);
        _progressBlock.Controls.Add(_percent);
        _progressBlock.Controls.Add(_stage);

        // --- artifact bar --------------------------------------------------
        _artifactBar.Dock = DockStyle.Bottom;
        _artifactBar.BackColor = Theme.Background;
        _artifactBar.Layout += (_, _) => LayoutArtifactBar();

        _reveal.Text = "Show in folder";
        _reveal.Outline = true;
        _reveal.Visible = false;
        _reveal.Click += (_, _) => RevealArtifact();

        _artifact.ForeColor = Theme.Muted;
        _artifact.TextAlign = ContentAlignment.MiddleLeft;
        _artifact.AutoEllipsis = true;

        _artifactBar.Controls.Add(_reveal);
        _artifactBar.Controls.Add(_artifact);

        // --- console -------------------------------------------------------
        _consoleFrame.Dock = DockStyle.Fill;
        _consoleFrame.BackColor = Theme.Surface;
        _consoleFrame.Paint += (_, e) =>
            Theme.DrawRoundedBorder(
                e.Graphics,
                new Rectangle(0, 0, _consoleFrame.Width, _consoleFrame.Height),
                Theme.Scale(10, DeviceDpi),
                Theme.Border);

        _console.Dock = DockStyle.Fill;
        _console.BackColor = Theme.Surface;
        _console.ForeColor = Theme.Muted;
        _console.BorderStyle = BorderStyle.None;
        _console.ReadOnly = true;
        _console.WordWrap = false;
        _console.ScrollBars = RichTextBoxScrollBars.Both;
        _consoleFrame.Controls.Add(_console);

        _pane.Controls.Add(_consoleFrame);
        _pane.Controls.Add(_artifactBar);
        _pane.Controls.Add(_progressBlock);
        _pane.Controls.Add(_actionDescription);
        _pane.Controls.Add(_header);
        return _pane;
    }

    /// <summary>
    /// Sizes every font and box from the window's current DPI. Called once at
    /// startup and again whenever the window crosses to a display with different
    /// scaling, which is what a 150% monitor used to break.
    /// </summary>
    private void ApplyMetrics()
    {
        var dpi = DeviceDpi;
        _appliedDpi = dpi;
        var retired = _fonts.ToArray();
        _fonts.Clear();

        SuspendLayout();

        MinimumSize = new Size(Theme.Scale(940, dpi), Theme.Scale(620, dpi));

        SetFont(this, Theme.UiFont(9.5f, dpi));

        // --- rail ----------------------------------------------------------
        _rail.Padding = Theme.Scale(new Padding(20, 22, 14, 18), dpi);
        _rail.Width = RailWidth(dpi);

        SizeLabel(_heading, Theme.UiFont(15f, dpi, FontStyle.Bold), Theme.Scale(6, dpi));
        SizeLabel(_subheading, Theme.UiFont(8.5f, dpi), Theme.Scale(10, dpi));
        _section.Padding = new Padding(Theme.Scale(2, dpi), Theme.Scale(8, dpi), 0, Theme.Scale(4, dpi));
        SizeLabel(_section, Theme.UiFont(7.75f, dpi, FontStyle.Bold), 0);

        foreach (var card in _cards)
        {
            card.Margin = new Padding(0, 0, 0, Theme.Scale(6, dpi));
            card.ApplyMetrics();
        }

        _run.ApplyMetrics();
        _stop.ApplyMetrics();
        _buttonBar.Height = _run.Height + Theme.Scale(26, dpi);

        // --- pane ----------------------------------------------------------
        _pane.Padding = Theme.Scale(new Padding(6, 22, 22, 18), dpi);

        SetFont(_actionTitle, Theme.UiFont(13f, dpi, FontStyle.Bold));
        SetFont(_elapsed, Theme.UiFont(8.5f, dpi));
        _pill.ApplyMetrics();
        _header.Height = Math.Max(Theme.LineHeight(_actionTitle.Font) + Theme.Scale(6, dpi), _pill.Height);

        SetFont(_actionDescription, Theme.UiFont(9f, dpi));
        _actionDescription.Padding = new Padding(0, Theme.Scale(10, dpi), 0, Theme.Scale(12, dpi));

        _progress.ApplyMetrics();
        SetFont(_percent, Theme.UiFont(8.5f, dpi, FontStyle.Bold));
        SetFont(_stage, Theme.UiFont(8.5f, dpi));
        _progressBlock.Height = _progress.Height
            + Theme.Scale(12, dpi)
            + Theme.LineHeight(_stage.Font)
            + Theme.Scale(18, dpi);

        _reveal.ApplyMetrics();
        SetFont(_artifact, Theme.UiFont(8.5f, dpi));
        _artifactBar.Height = _reveal.Height + Theme.Scale(16, dpi);

        _consoleFrame.Padding = Theme.Scale(new Padding(12, 10, 8, 10), dpi);
        SetFont(_console, Theme.MonoFont(8.75f, dpi));

        ResumeLayout(performLayout: true);
        LayoutCards();
        LayoutDescription();

        foreach (var font in retired)
        {
            font.Dispose();
        }
    }

    /// <summary>Rail width: wide enough that no card subtitle has to ellipsize.</summary>
    private int RailWidth(int dpi)
    {
        var widest = _cards.Count == 0 ? 0 : _cards.Max(card => card.PreferredTextWidth);
        var content = widest + Theme.Scale(14 + 12, dpi) + SystemInformation.VerticalScrollBarWidth;
        return Math.Max(Theme.Scale(300, dpi), content + _rail.Padding.Horizontal);
    }

    protected override void OnShown(EventArgs e)
    {
        base.OnShown(e);

        // Only now is the window on its final monitor: a form created while the
        // pointer is on a 150% display but shown on a 100% one reports the new
        // DPI here and nowhere earlier.
        if (_appliedDpi != DeviceDpi)
        {
            ApplyMetrics();
        }

        var working = Screen.FromHandle(Handle).WorkingArea;
        var wanted = new Size(
            Math.Min(Theme.Scale(1220, DeviceDpi), working.Width),
            Math.Min(Theme.Scale(800, DeviceDpi), working.Height));
        Size = wanted;
        Location = new Point(
            working.Left + ((working.Width - wanted.Width) / 2),
            working.Top + ((working.Height - wanted.Height) / 2));
    }

    protected override void OnDpiChanged(DpiChangedEventArgs e)
    {
        base.OnDpiChanged(e);
        ApplyMetrics();

        if (WindowState != FormWindowState.Normal || e.DeviceDpiOld <= 0)
        {
            return;
        }

        // Dragged across displays: keep the window the same apparent size, and
        // inside the display it landed on.
        var ratio = e.DeviceDpiNew / (double)e.DeviceDpiOld;
        var working = Screen.FromHandle(Handle).WorkingArea;
        var size = new Size(
            Math.Min((int)Math.Round(Width * ratio), working.Width),
            Math.Min((int)Math.Round(Height * ratio), working.Height));
        Size = size;
        Location = new Point(
            Math.Clamp(Left, working.Left, Math.Max(working.Left, working.Right - size.Width)),
            Math.Clamp(Top, working.Top, Math.Max(working.Top, working.Bottom - size.Height)));
    }

    private void LayoutCards()
    {
        var width = _list.ClientSize.Width;
        if (width <= 0)
        {
            return;
        }

        foreach (var card in _cards)
        {
            card.Width = Math.Max(Theme.Scale(120, DeviceDpi), width - card.Margin.Horizontal);
        }
    }

    private void LayoutButtons()
    {
        if (!Guard(out var release))
        {
            return;
        }

        using (release)
        {
            var dpi = DeviceDpi;
            var gap = Theme.Scale(8, dpi);
            var top = Theme.Scale(14, dpi);
            var stopWidth = Math.Max(_stop.PreferredWidth, Theme.Scale(84, dpi));
            var runWidth = Math.Max(
                Math.Max(_run.PreferredWidth, Theme.Scale(150, dpi)),
                _buttonBar.ClientSize.Width - stopWidth - gap);

            _run.SetBounds(0, top, runWidth, _run.Height);
            _stop.SetBounds(runWidth + gap, top, stopWidth, _stop.Height);
        }
    }

    private void LayoutHeader()
    {
        if (!Guard(out var release))
        {
            return;
        }

        using (release)
        {
            var dpi = DeviceDpi;
            var width = _header.ClientSize.Width;
            var elapsedWidth = Theme.Scale(84, dpi);
            var gap = Theme.Scale(10, dpi);

            _pill.SetBounds(width - _pill.Width, 0, _pill.Width, _pill.Height);
            _elapsed.SetBounds(
                width - _pill.Width - gap - elapsedWidth,
                0,
                elapsedWidth,
                Math.Max(_pill.Height, Theme.LineHeight(_elapsed.Font)));
            _actionTitle.SetBounds(
                0,
                0,
                Math.Max(Theme.Scale(80, dpi), _elapsed.Left - gap),
                Theme.LineHeight(_actionTitle.Font) + Theme.Scale(4, dpi));
        }
    }

    private void LayoutProgress()
    {
        if (!Guard(out var release))
        {
            return;
        }

        using (release)
        {
            var dpi = DeviceDpi;
            var width = _progressBlock.ClientSize.Width;
            var labelTop = _progress.Height + Theme.Scale(12, dpi);
            var labelHeight = Theme.LineHeight(_stage.Font) + Theme.Scale(4, dpi);
            var percentWidth = Theme.TextWidth("100%", _percent.Font) + Theme.Scale(14, dpi);

            _progress.SetBounds(0, Theme.Scale(6, dpi), width, _progress.Height);
            _percent.SetBounds(0, labelTop, percentWidth, labelHeight);
            _stage.SetBounds(percentWidth, labelTop, Math.Max(Theme.Scale(40, dpi), width - percentWidth), labelHeight);
        }
    }

    private void LayoutArtifactBar()
    {
        if (!Guard(out var release))
        {
            return;
        }

        using (release)
        {
            var dpi = DeviceDpi;
            var revealWidth = _reveal.PreferredWidth;
            var gap = Theme.Scale(12, dpi);
            var top = Theme.Scale(8, dpi);

            _reveal.SetBounds(0, top, revealWidth, _reveal.Height);
            _artifact.SetBounds(
                revealWidth + gap,
                top,
                Math.Max(Theme.Scale(80, dpi), _artifactBar.ClientSize.Width - revealWidth - gap),
                _reveal.Height);
        }
    }

    private void LayoutDescription()
    {
        var width = _actionDescription.ClientSize.Width - _actionDescription.Padding.Horizontal;
        if (width <= 0)
        {
            return;
        }

        var measured = Theme.WrappedHeight(_actionDescription.Text, _actionDescription.Font, width);
        var wanted = measured + _actionDescription.Padding.Vertical + Theme.Scale(4, DeviceDpi);

        // The console keeps the majority of the pane no matter how long the blurb is.
        var ceiling = Math.Max(Theme.Scale(80, DeviceDpi), (int)(_pane.ClientSize.Height * 0.42));
        var height = Math.Min(wanted, ceiling);
        if (_actionDescription.Height != height)
        {
            _actionDescription.Height = height;
        }
    }

    /// <summary>
    /// Re-entrancy guard: these run from Layout, and they move child controls,
    /// which raises Layout again.
    /// </summary>
    private bool Guard(out IDisposable release)
    {
        if (_laying)
        {
            release = NullScope.Instance;
            return false;
        }

        _laying = true;
        release = new Scope(this);
        return true;
    }

    private void SetFont(Control control, Font font)
    {
        _fonts.Add(font);
        control.Font = font;
    }

    private void SizeLabel(Label label, Font font, int extra)
    {
        SetFont(label, font);
        label.Height = Theme.LineHeight(font) + label.Padding.Vertical + extra;
    }

    private void Select(BuildAction action)
    {
        _selected = action;
        foreach (var card in _cards)
        {
            card.Selected = ReferenceEquals(card.Action, action);
        }

        _actionTitle.Text = action.Title;
        _actionDescription.Text = action.Description;
        LayoutDescription();
        _run.Text = action.IsReleaseGate ? "Run release build" : "Build";
        _run.Base = action.IsReleaseGate ? Theme.Warning : Theme.Accent;
        _run.Hover = action.IsReleaseGate ? Color.FromArgb(232, 184, 96) : Theme.AccentHover;
        _buttonBar.PerformLayout();
    }

    private async Task RunSelectedAsync()
    {
        if (_cancellation is not null)
        {
            return;
        }

        var action = _selected;
        _console.Clear();
        _lastArtifact = null;
        _reveal.Visible = false;
        _artifact.Text = string.Empty;
        _progress.Reset(0);
        _progress.Fill = Theme.Accent;
        _progress.Indeterminate = true;
        _percent.Text = string.Empty;
        _stage.Text = "Starting...";

        _cancellation = new CancellationTokenSource();
        _stopwatch = Stopwatch.StartNew();
        _clock.Start();
        SetRunning(true);

        int exitCode;
        try
        {
            exitCode = await _runner.RunAsync(
                action,
                (line, isError) =>
                {
                    if (IsHandleCreated)
                    {
                        BeginInvoke(() => OnOutputLine(line, isError));
                    }
                },
                _cancellation.Token);
        }
        finally
        {
            _stopwatch.Stop();
            _clock.Stop();
            UpdateElapsed();
            _cancellation.Dispose();
            _cancellation = null;
            SetRunning(false);
        }

        _progress.Indeterminate = false;
        _progress.Stop();
        _stage.Text = string.Empty;

        if (exitCode == 0)
        {
            _progress.Fill = Theme.Success;
            _progress.Reset(100);
            _percent.Text = "100%";
            _pill.Set("Succeeded", Theme.Success);
            WriteLine(string.Empty, Theme.Muted);
            WriteLine($"Done in {Format(_stopwatch.Elapsed)}.", Theme.Success);
            ResolveArtifact(action);
        }
        else if (exitCode == -1)
        {
            _progress.Fill = Theme.Warning;
            _pill.Set("Stopped", Theme.Warning);
            WriteLine(string.Empty, Theme.Muted);
            WriteLine("Stopped.", Theme.Warning);
        }
        else
        {
            _progress.Fill = Theme.Danger;
            _pill.Set("Failed", Theme.Danger);
            WriteLine(string.Empty, Theme.Muted);
            WriteLine($"Failed with exit code {exitCode} after {Format(_stopwatch.Elapsed)}.", Theme.Danger);
        }
    }

    private void OnOutputLine(string line, bool isError)
    {
        var signal = ProgressParser.Parse(line);
        if (signal.Percent is { } percent)
        {
            _progress.Indeterminate = false;
            _progress.Value = percent;
            _percent.Text = $"{percent}%";
        }

        if (signal.Stage is { } stage)
        {
            _stage.Text = stage;
        }

        WriteLine(line, isError ? Theme.Danger : Theme.Muted);
    }

    private void SetRunning(bool running)
    {
        _run.Enabled = !running;
        _stop.Enabled = running;
        foreach (var card in _cards)
        {
            card.Enabled = !running;
        }

        if (running)
        {
            _pill.Set("Building", Theme.Accent);
        }
    }

    private void UpdateElapsed() =>
        _elapsed.Text = _stopwatch is null ? string.Empty : Format(_stopwatch.Elapsed);

    private static string Format(TimeSpan elapsed) =>
        elapsed.TotalMinutes >= 1
            ? $"{(int)elapsed.TotalMinutes}m {elapsed.Seconds:D2}s"
            : $"{elapsed.TotalSeconds:N1}s";

    private void ResolveArtifact(BuildAction action)
    {
        if (action.ArtifactDirectory is null || action.ArtifactPattern is null)
        {
            return;
        }

        var directory = Path.Combine(_workspaceRoot.FullName, action.ArtifactDirectory);
        if (!Directory.Exists(directory))
        {
            return;
        }

        var newest = new DirectoryInfo(directory)
            .EnumerateFiles(action.ArtifactPattern)
            .OrderByDescending(file => file.LastWriteTimeUtc)
            .FirstOrDefault();

        if (newest is null)
        {
            return;
        }

        _lastArtifact = newest.FullName;
        _reveal.Visible = true;
        _artifact.Text = $"{newest.FullName}  ·  {newest.Length / (1024d * 1024d):N1} MB";
        WriteLine($"Output: {newest.FullName} ({newest.Length / (1024d * 1024d):N1} MB)", Theme.Muted);
    }

    private void WriteLine(string line, Color color)
    {
        // A long release build emits a lot; trimming keeps the box responsive.
        if (_console.Lines.Length > MaxConsoleLines)
        {
            _console.ReadOnly = false;
            _console.Select(0, _console.GetFirstCharIndexFromLine(MaxConsoleLines / 4));
            _console.SelectedText = string.Empty;
            _console.ReadOnly = true;
        }

        _console.SelectionStart = _console.TextLength;
        _console.SelectionLength = 0;
        _console.SelectionColor = color;
        _console.AppendText(line + Environment.NewLine);
        _console.SelectionColor = _console.ForeColor;
        _console.ScrollToCaret();
    }

    private void RevealArtifact()
    {
        if (_lastArtifact is null || !File.Exists(_lastArtifact))
        {
            return;
        }

        // Selected in Explorer, not launched: starting a 220 MB application by
        // accident from a build tool would be rude.
        Process.Start(new ProcessStartInfo
        {
            FileName = "explorer.exe",
            Arguments = $"/select,\"{_lastArtifact}\"",
            UseShellExecute = true,
        });
    }

    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        _cancellation?.Cancel();
        base.OnFormClosing(e);
    }

    private sealed class Scope(MainForm owner) : IDisposable
    {
        public void Dispose() => owner._laying = false;
    }

    private sealed class NullScope : IDisposable
    {
        public static readonly NullScope Instance = new();

        public void Dispose()
        {
        }
    }
}
