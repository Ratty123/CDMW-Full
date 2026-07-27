using System.Drawing;
using System.Windows.Forms;

namespace Cdmw.BazelLauncher;

/// <summary>
/// A selectable card: title, one-line subtitle, and an accent bar when chosen.
/// Replaces a ListBox so each option can say what it actually does.
/// </summary>
internal sealed class OptionCard : Control
{
    private bool _selected;
    private bool _hovered;
    private Font _titleFont;
    private Font _subtitleFont;

    public OptionCard(BuildAction action)
    {
        Action = action;
        SetStyle(
            ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.UserPaint,
            true);
        Cursor = Cursors.Hand;
        TabStop = false;
        _titleFont = Theme.UiFont(9.75f, DeviceDpi, FontStyle.Bold);
        _subtitleFont = Theme.UiFont(8.25f, DeviceDpi);
        ApplyMetrics();
    }

    public BuildAction Action { get; }

    public bool Selected
    {
        get => _selected;
        set
        {
            if (_selected == value)
            {
                return;
            }

            _selected = value;
            Invalidate();
        }
    }

    /// <summary>Widest the subtitle can be before it has to ellipsize, for rail sizing.</summary>
    public int PreferredTextWidth =>
        Math.Max(Theme.TextWidth(Action.Title, _titleFont), Theme.TextWidth(Action.Subtitle, _subtitleFont));

    /// <summary>Re-measures for the current DPI. Sets Height; the rail owns Width.</summary>
    public void ApplyMetrics()
    {
        var dpi = DeviceDpi;
        var replacedTitle = _titleFont;
        var replacedSubtitle = _subtitleFont;
        _titleFont = Theme.UiFont(9.75f, dpi, FontStyle.Bold);
        _subtitleFont = Theme.UiFont(8.25f, dpi);
        replacedTitle.Dispose();
        replacedSubtitle.Dispose();

        Height = PadTop(dpi)
            + Theme.LineHeight(_titleFont)
            + Gap(dpi)
            + Theme.LineHeight(_subtitleFont)
            + PadBottom(dpi)
            + Theme.Scale(3, dpi); // the 1px inset and 2px gutter the frame is drawn in
        Invalidate();
    }

    protected override void OnDpiChangedAfterParent(EventArgs e)
    {
        ApplyMetrics();
        base.OnDpiChangedAfterParent(e);
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
        Invalidate();
        base.OnMouseLeave(e);
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        var g = e.Graphics;
        var dpi = DeviceDpi;
        g.Clear(Parent?.BackColor ?? Theme.Background);

        var bounds = new Rectangle(0, 1, Width, Height - 3);
        var radius = Theme.Scale(8, dpi);
        var background = _selected ? Theme.SurfaceActive : _hovered ? Theme.SurfaceHover : Theme.Surface;
        Theme.FillRounded(g, bounds, radius, background);

        if (_selected)
        {
            Theme.DrawRoundedBorder(g, bounds, radius, Theme.Accent);
            // Accent spine on the left edge, clipped to the rounded corners.
            using var clip = Theme.RoundedRect(bounds, radius);
            var previous = g.Clip;
            g.SetClip(clip);
            using (var brush = new SolidBrush(Theme.Accent))
            {
                g.FillRectangle(brush, new Rectangle(bounds.X, bounds.Y, Theme.Scale(3, dpi), bounds.Height));
            }

            g.Clip = previous;
        }
        else
        {
            Theme.DrawRoundedBorder(g, bounds, radius, Theme.Border);
        }

        var textLeft = bounds.X + Theme.Scale(14, dpi);
        var textWidth = Math.Max(1, bounds.Right - textLeft - Theme.Scale(12, dpi));
        var titleHeight = Theme.LineHeight(_titleFont);
        var titleColor = Action.IsReleaseGate ? Theme.Warning : Theme.Text;

        const TextFormatFlags flags =
            TextFormatFlags.NoPrefix | TextFormatFlags.NoPadding | TextFormatFlags.EndEllipsis;

        TextRenderer.DrawText(
            g,
            Action.Title,
            _titleFont,
            new Rectangle(textLeft, bounds.Y + PadTop(dpi), textWidth, titleHeight),
            _selected ? Theme.Text : titleColor,
            flags);

        TextRenderer.DrawText(
            g,
            Action.Subtitle,
            _subtitleFont,
            new Rectangle(
                textLeft,
                bounds.Y + PadTop(dpi) + titleHeight + Gap(dpi),
                textWidth,
                Theme.LineHeight(_subtitleFont)),
            _selected ? Theme.Muted : Theme.Faint,
            flags);
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            _titleFont.Dispose();
            _subtitleFont.Dispose();
        }

        base.Dispose(disposing);
    }

    private static int PadTop(int dpi) => Theme.Scale(9, dpi);

    private static int PadBottom(int dpi) => Theme.Scale(9, dpi);

    private static int Gap(int dpi) => Theme.Scale(3, dpi);
}
