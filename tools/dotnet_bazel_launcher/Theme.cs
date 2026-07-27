using System.Drawing;
using System.Drawing.Drawing2D;
using System.Windows.Forms;

namespace Cdmw.BazelLauncher;

/// <summary>Flat dark palette and drawing helpers shared by the custom controls.</summary>
internal static class Theme
{
    /// <summary>The DPI every hardcoded measurement in this app is written for.</summary>
    public const int BaseDpi = 96;

    public static readonly Color Background = Color.FromArgb(15, 17, 21);
    public static readonly Color Surface = Color.FromArgb(22, 25, 31);
    public static readonly Color SurfaceHover = Color.FromArgb(28, 32, 41);
    public static readonly Color SurfaceActive = Color.FromArgb(33, 41, 58);
    public static readonly Color Border = Color.FromArgb(38, 43, 54);

    public static readonly Color Text = Color.FromArgb(230, 233, 239);
    public static readonly Color Muted = Color.FromArgb(138, 147, 163);
    public static readonly Color Faint = Color.FromArgb(98, 106, 120);

    public static readonly Color Accent = Color.FromArgb(76, 141, 255);
    public static readonly Color AccentHover = Color.FromArgb(99, 158, 255);
    public static readonly Color Success = Color.FromArgb(63, 185, 80);
    public static readonly Color Danger = Color.FromArgb(240, 97, 109);
    public static readonly Color Warning = Color.FromArgb(214, 164, 74);

    /// <summary>A length authored at 96 DPI, in pixels for <paramref name="dpi"/>.</summary>
    public static int Scale(int value, int dpi) => (int)Math.Round(value * (dpi / (double)BaseDpi));

    public static Padding Scale(Padding padding, int dpi) =>
        new(
            Scale(padding.Left, dpi),
            Scale(padding.Top, dpi),
            Scale(padding.Right, dpi),
            Scale(padding.Bottom, dpi));

    /// <summary>
    /// Fonts are built in pixels, not points, so that glyph size and layout are
    /// two readings of the same DPI. A point-sized font is resolved against a DPI
    /// this code does not choose, which is how the layout came apart on a 150%
    /// display: the text grew and the boxes holding it did not.
    /// </summary>
    public static Font UiFont(float points, int dpi, FontStyle style = FontStyle.Regular) =>
        new("Segoe UI", Pixels(points, dpi), style, GraphicsUnit.Pixel);

    public static Font MonoFont(float points, int dpi)
    {
        // Cascadia Mono ships with modern Windows and Visual Studio; Consolas is
        // the universal fallback so the console never lands on a proportional face.
        foreach (var family in new[] { "Cascadia Mono", "Consolas" })
        {
            try
            {
                using var probe = new FontFamily(family);
                return new Font(probe, Pixels(points, dpi), FontStyle.Regular, GraphicsUnit.Pixel);
            }
            catch (ArgumentException)
            {
                // Family not installed; try the next one.
            }
        }

        return new Font(FontFamily.GenericMonospace, Pixels(points, dpi), FontStyle.Regular, GraphicsUnit.Pixel);
    }

    /// <summary>Height of one line of <paramref name="font"/>, descenders included.</summary>
    public static int LineHeight(Font font) =>
        TextRenderer.MeasureText("Ag", font, new Size(int.MaxValue, int.MaxValue), MeasureFlags).Height;

    /// <summary>Width <paramref name="text"/> needs in <paramref name="font"/>, with no padding of its own.</summary>
    public static int TextWidth(string text, Font font) =>
        TextRenderer.MeasureText(text, font, new Size(int.MaxValue, int.MaxValue), MeasureFlags).Width;

    /// <summary>Height <paramref name="text"/> needs when wrapped to <paramref name="width"/>.</summary>
    public static int WrappedHeight(string text, Font font, int width) =>
        TextRenderer.MeasureText(
            text,
            font,
            new Size(Math.Max(1, width), int.MaxValue),
            TextFormatFlags.WordBreak | TextFormatFlags.NoPrefix).Height;

    public static GraphicsPath RoundedRect(Rectangle bounds, int radius)
    {
        var diameter = Math.Max(1, radius * 2);
        var path = new GraphicsPath();

        if (radius <= 0 || bounds.Width <= diameter || bounds.Height <= diameter)
        {
            path.AddRectangle(bounds);
            return path;
        }

        var arc = new Rectangle(bounds.Location, new Size(diameter, diameter));
        path.AddArc(arc, 180, 90);
        arc.X = bounds.Right - diameter;
        path.AddArc(arc, 270, 90);
        arc.Y = bounds.Bottom - diameter;
        path.AddArc(arc, 0, 90);
        arc.X = bounds.Left;
        path.AddArc(arc, 90, 90);
        path.CloseFigure();
        return path;
    }

    public static void FillRounded(Graphics g, Rectangle bounds, int radius, Color color)
    {
        g.SmoothingMode = SmoothingMode.AntiAlias;
        using var path = RoundedRect(bounds, radius);
        using var brush = new SolidBrush(color);
        g.FillPath(brush, path);
    }

    public static void DrawRoundedBorder(Graphics g, Rectangle bounds, int radius, Color color)
    {
        g.SmoothingMode = SmoothingMode.AntiAlias;
        var inset = new Rectangle(bounds.X, bounds.Y, bounds.Width - 1, bounds.Height - 1);
        using var path = RoundedRect(inset, radius);
        using var pen = new Pen(color);
        g.DrawPath(pen, path);
    }

    private const TextFormatFlags MeasureFlags =
        TextFormatFlags.NoPrefix | TextFormatFlags.NoPadding | TextFormatFlags.SingleLine;

    private static float Pixels(float points, int dpi) => points * dpi / 72f;
}
