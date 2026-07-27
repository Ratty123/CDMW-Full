using System.Drawing;
using System.Windows.Forms;

namespace Cdmw.BazelLauncher;

/// <summary>Rounded flat button. WinForms' own button cannot round its corners.</summary>
internal sealed class FlatButton : Control
{
    private bool _hovered;
    private bool _pressed;
    private Font _font;

    public FlatButton()
    {
        SetStyle(
            ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.UserPaint,
            true);
        Cursor = Cursors.Hand;
        _font = Theme.UiFont(9.75f, DeviceDpi, FontStyle.Bold);
        ApplyMetrics();
    }

    public Color Base { get; set; } = Theme.Accent;

    public Color Hover { get; set; } = Theme.AccentHover;

    public Color Label { get; set; } = Color.White;

    public bool Outline { get; set; }

    /// <summary>Width the caption needs, gutters included.</summary>
    public int PreferredWidth => Theme.TextWidth(Text, _font) + Theme.Scale(34, DeviceDpi);

    /// <summary>Re-measures for the current DPI. Sets Height; callers own Width.</summary>
    public void ApplyMetrics()
    {
        var replaced = _font;
        _font = Theme.UiFont(9.75f, DeviceDpi, FontStyle.Bold);
        replaced.Dispose();
        Height = Theme.LineHeight(_font) + Theme.Scale(20, DeviceDpi);
        Invalidate();
    }

    protected override void OnDpiChangedAfterParent(EventArgs e)
    {
        ApplyMetrics();
        base.OnDpiChangedAfterParent(e);
    }

    protected override void OnTextChanged(EventArgs e)
    {
        Invalidate();
        base.OnTextChanged(e);
    }

    protected override void OnMouseEnter(EventArgs e)
    {
        _hovered = true;
        Invalidate();
        base.OnMouseEnter(e);
    }

    protected override void OnMouseLeave(EventArgs e)
    {
        _hovered = false;
        _pressed = false;
        Invalidate();
        base.OnMouseLeave(e);
    }

    protected override void OnMouseDown(MouseEventArgs e)
    {
        _pressed = true;
        Invalidate();
        base.OnMouseDown(e);
    }

    protected override void OnMouseUp(MouseEventArgs e)
    {
        _pressed = false;
        Invalidate();
        base.OnMouseUp(e);
    }

    protected override void OnEnabledChanged(EventArgs e)
    {
        Invalidate();
        base.OnEnabledChanged(e);
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        var g = e.Graphics;
        g.Clear(Parent?.BackColor ?? Theme.Background);

        var bounds = new Rectangle(0, 0, Width, Height);
        var radius = Theme.Scale(8, DeviceDpi);
        var background = !Enabled
            ? Theme.Surface
            : _pressed ? Base
            : _hovered ? Hover
            : Base;

        if (Outline)
        {
            Theme.FillRounded(g, bounds, radius, _hovered && Enabled ? Theme.SurfaceHover : Theme.Surface);
            Theme.DrawRoundedBorder(g, bounds, radius, Theme.Border);
        }
        else
        {
            Theme.FillRounded(g, bounds, radius, background);
        }

        var color = Enabled ? (Outline ? Theme.Text : Label) : Theme.Faint;
        TextRenderer.DrawText(
            g,
            Text,
            _font,
            bounds,
            color,
            TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.NoPrefix);
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            _font.Dispose();
        }

        base.Dispose(disposing);
    }
}

/// <summary>Small rounded status chip: Ready / Building / Succeeded / Failed.</summary>
internal sealed class StatusPill : Control
{
    private Color _tint = Theme.Muted;
    private Font _font;

    public StatusPill()
    {
        SetStyle(
            ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.UserPaint,
            true);
        _font = Theme.UiFont(8.25f, DeviceDpi, FontStyle.Bold);
        Text = "Ready";
        ApplyMetrics();
    }

    public void Set(string text, Color tint)
    {
        Text = text;
        _tint = tint;
        ApplyMetrics();
    }

    /// <summary>Re-measures for the current DPI and the current caption.</summary>
    public void ApplyMetrics()
    {
        var dpi = DeviceDpi;
        var replaced = _font;
        _font = Theme.UiFont(8.25f, dpi, FontStyle.Bold);
        replaced.Dispose();

        Height = Theme.LineHeight(_font) + Theme.Scale(8, dpi);
        // Dot gutter, caption, trailing gutter. The caption changes with state,
        // so a fixed width either clips "Succeeded" or leaves "Ready" adrift.
        Width = TextLeft(dpi) + Theme.TextWidth(Text, _font) + Theme.Scale(14, dpi);
        Invalidate();

        // Width changes as the state does; the header anchors it by its right edge.
        Parent?.PerformLayout();
    }

    protected override void OnDpiChangedAfterParent(EventArgs e)
    {
        ApplyMetrics();
        base.OnDpiChangedAfterParent(e);
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        var g = e.Graphics;
        var dpi = DeviceDpi;
        g.Clear(Parent?.BackColor ?? Theme.Background);

        var bounds = new Rectangle(0, 0, Width - 1, Height - 1);
        Theme.FillRounded(g, bounds, Height / 2, Color.FromArgb(28, _tint.R, _tint.G, _tint.B));
        Theme.DrawRoundedBorder(g, bounds, Height / 2, Color.FromArgb(90, _tint.R, _tint.G, _tint.B));

        var dotSize = Theme.Scale(6, dpi);
        var dot = new Rectangle(Theme.Scale(11, dpi), (Height - dotSize) / 2, dotSize, dotSize);
        using (var brush = new SolidBrush(_tint))
        {
            g.FillEllipse(brush, dot);
        }

        TextRenderer.DrawText(
            g,
            Text,
            _font,
            new Rectangle(TextLeft(dpi), 0, Width - TextLeft(dpi), Height),
            _tint,
            TextFormatFlags.VerticalCenter | TextFormatFlags.NoPrefix | TextFormatFlags.NoPadding);
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            _font.Dispose();
        }

        base.Dispose(disposing);
    }

    private static int TextLeft(int dpi) => Theme.Scale(24, dpi);
}
