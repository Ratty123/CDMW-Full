using System.Drawing;
using System.Windows.Forms;

namespace Cdmw.BazelLauncher;

/// <summary>
/// Thin rounded progress bar. Eases toward the target so the jitter of Bazel's
/// action counter does not read as flicker, and falls back to a sweeping band
/// while a phase reports no percentage.
/// </summary>
internal sealed class FlatProgressBar : Control
{
    private readonly System.Windows.Forms.Timer _animator = new() { Interval = 16 };
    private double _displayed;
    private int _target;
    private bool _indeterminate;
    private int _sweep;
    private Color _fill = Theme.Accent;

    public FlatProgressBar()
    {
        SetStyle(
            ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.UserPaint,
            true);
        ApplyMetrics();
        _animator.Tick += (_, _) => Advance();
    }

    /// <summary>Re-measures for the current DPI. Sets Height; callers own Width.</summary>
    public void ApplyMetrics()
    {
        Height = Theme.Scale(6, DeviceDpi);
        Invalidate();
    }

    protected override void OnDpiChangedAfterParent(EventArgs e)
    {
        ApplyMetrics();
        base.OnDpiChangedAfterParent(e);
    }

    public int Value
    {
        get => _target;
        set
        {
            var clamped = Math.Clamp(value, 0, 100);
            if (_target == clamped)
            {
                return;
            }

            _target = clamped;
            EnsureAnimating();
        }
    }

    public bool Indeterminate
    {
        get => _indeterminate;
        set
        {
            if (_indeterminate == value)
            {
                return;
            }

            _indeterminate = value;
            EnsureAnimating();
            Invalidate();
        }
    }

    /// <summary>Length of the sweeping band shown while a phase reports no percentage.</summary>
    private int BandWidth => Theme.Scale(180, DeviceDpi);

    public Color Fill
    {
        get => _fill;
        set
        {
            _fill = value;
            Invalidate();
        }
    }

    /// <summary>Jump to a value with no easing, for resets between runs.</summary>
    public void Reset(int value)
    {
        _target = Math.Clamp(value, 0, 100);
        _displayed = _target;
        _sweep = 0;
        Invalidate();
    }

    public void Stop()
    {
        _indeterminate = false;
        _animator.Stop();
        Invalidate();
    }

    private void EnsureAnimating()
    {
        if (!_animator.Enabled)
        {
            _animator.Start();
        }
    }

    private void Advance()
    {
        var changed = false;

        if (_indeterminate)
        {
            var step = Math.Max(1, Theme.Scale(6, DeviceDpi));
            _sweep = (_sweep + step) % Math.Max(1, Width + BandWidth + Theme.Scale(40, DeviceDpi));
            changed = true;
        }

        var delta = _target - _displayed;
        if (Math.Abs(delta) > 0.05)
        {
            _displayed += delta * 0.18;
            changed = true;
        }
        else if (Math.Abs(delta) > 0)
        {
            _displayed = _target;
            changed = true;
        }

        if (changed)
        {
            Invalidate();
        }
        else if (!_indeterminate)
        {
            _animator.Stop();
        }
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        var g = e.Graphics;
        g.Clear(Parent?.BackColor ?? Theme.Background);

        var track = new Rectangle(0, 0, Width, Height);
        var radius = Height / 2;
        Theme.FillRounded(g, track, radius, Theme.Border);

        if (Width <= 2)
        {
            return;
        }

        if (_indeterminate)
        {
            var bandWidth = BandWidth;
            var x = _sweep - bandWidth;
            var band = new Rectangle(Math.Max(0, x), 0, Math.Min(bandWidth, Width - Math.Max(0, x)), Height);
            if (band.Width > 0)
            {
                Theme.FillRounded(g, band, radius, _fill);
            }

            return;
        }

        var filled = (int)Math.Round(Width * (_displayed / 100.0));
        if (filled > 1)
        {
            Theme.FillRounded(g, new Rectangle(0, 0, filled, Height), radius, _fill);
        }
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            _animator.Dispose();
        }

        base.Dispose(disposing);
    }
}
