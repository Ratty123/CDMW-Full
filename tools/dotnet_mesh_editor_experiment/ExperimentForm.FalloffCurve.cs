using System.Drawing.Drawing2D;

namespace Cdmw.MeshEditorExperiment;

/// <summary>
/// The brush falloff preview: the profile the current falloff and strength
/// actually apply, drawn across the brush diameter.
/// </summary>
internal sealed partial class ExperimentForm
{
    private MeshEditorFalloffCurve? _falloffCurve;

    /// <summary>
    /// Builds the curve and keeps it in step with the two controls that change
    /// its shape. Radius is deliberately not one of them: the profile is
    /// normalised over the radius, so widening the brush moves the same curve
    /// further apart rather than reshaping it. The radius is named on the axis
    /// caption instead, where it answers "how wide is this" without implying it
    /// changes the falloff.
    /// </summary>
    private Control BuildFalloffCurve()
    {
        _falloffCurve = new MeshEditorFalloffCurve
        {
            Name = "DotNetMeshEditorFalloffCurve",
            Dock = DockStyle.Top,
            Height = ScaleToolPanelWidth(FalloffCurveHeight),
            Margin = new Padding(0, 2, 0, 0),
        };
        _falloffCurve.AccessibleName = "Brush falloff preview";
        // One literal, not a concatenation: the manifest keys adjacent string
        // literals separately, and half a sentence is not translatable.
        SetHelpText(
            _falloffCurve,
            "The weight the brush applies across its diameter. Strength scales the height; the falloff sets the shape.");
        _falloff.SelectedIndexChanged += (_, _) => RefreshFalloffCurve();
        _strength.ValueChanged += (_, _) => RefreshFalloffCurve();
        RefreshFalloffCurve();
        return _falloffCurve;
    }

    private void RefreshFalloffCurve()
    {
        if (_falloffCurve is null)
        {
            return;
        }
        _falloffCurve.SetProfile(
            SelectionText(_falloff, "smooth"),
            (double)_strength.Value,
            (double)_radius.Value);
    }

    private const int FalloffCurveHeight = 72;

    /// <summary>
    /// Draws <c>brush_falloff_weight</c> rather than an artist's impression of
    /// it. A preview that disagreed with the brush would be worse than none.
    /// </summary>
    private sealed class MeshEditorFalloffCurve : Control
    {
        private string _falloffKey = "smooth";
        private double _strength = 0.5;
        private double _radius = 24.0;

        public MeshEditorFalloffCurve()
        {
            ResizeRedraw = true;
            TabStop = false;
            DoubleBuffered = true;
            SetStyle(ControlStyles.OptimizedDoubleBuffer | ControlStyles.AllPaintingInWmPaint, true);
            BackColor = ThemeInputBackground;
            ForeColor = ThemeMutedText;
        }

        public void SetProfile(string falloffKey, double strength, double radius)
        {
            var normalized = (falloffKey ?? string.Empty).Trim().ToLowerInvariant();
            if (normalized.Length == 0)
            {
                normalized = "smooth";
            }
            if (string.Equals(_falloffKey, normalized, StringComparison.Ordinal)
                && Math.Abs(_strength - strength) < 1e-6
                && Math.Abs(_radius - radius) < 1e-6)
            {
                return;
            }
            _falloffKey = normalized;
            _strength = strength;
            _radius = radius;
            Invalidate();
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            var g = e.Graphics;
            g.Clear(BackColor);
            var width = Width;
            var height = Height;
            if (width < 8 || height < 8)
            {
                return;
            }

            var inset = Math.Max(4, height / 10);
            var plotTop = inset + Font.Height;
            var plotBottom = height - inset;
            var plotLeft = inset;
            var plotRight = width - inset;
            if (plotBottom - plotTop < 4 || plotRight - plotLeft < 4)
            {
                return;
            }

            using (var border = new Pen(ThemeBorder))
            {
                g.DrawRectangle(border, 0, 0, width - 1, height - 1);
            }

            // The centre line is where the cursor is, so it is worth marking:
            // the curve is symmetric about it and that is the reader's anchor.
            var centreX = (plotLeft + plotRight) / 2f;
            using (var guide = new Pen(ThemeBorder) { DashStyle = DashStyle.Dash })
            {
                g.DrawLine(guide, centreX, plotTop, centreX, plotBottom);
            }

            var strength = Math.Clamp(_strength, 0.0, 1.0);
            var span = plotRight - plotLeft;
            var points = new PointF[span + 1];
            for (var step = 0; step <= span; step++)
            {
                // Signed position across the diameter, so the profile is drawn
                // the way the brush sits on the mesh rather than as a half.
                var offset = (step / (double)span) * 2.0 - 1.0;
                var weight = BrushFalloffProfile.Weight(Math.Abs(offset), 1.0, _falloffKey) * strength;
                var y = plotBottom - (float)(weight * (plotBottom - plotTop));
                points[step] = new PointF(plotLeft + step, y);
            }

            g.SmoothingMode = SmoothingMode.AntiAlias;
            using (var curve = new Pen(ThemeAccent, 1.6f))
            {
                // Constant falloff steps from 0 to full at the rim, and an
                // antialiased polyline is the honest way to show that edge.
                g.DrawLines(curve, points);
            }
            g.SmoothingMode = SmoothingMode.Default;

            TextRenderer.DrawText(
                g,
                $"FALLOFF · RADIUS {_radius:0.#} PX",
                Font,
                new Rectangle(inset + 2, inset - 1, Math.Max(0, width - (inset * 2) - 4), Font.Height + 2),
                ThemeMutedText,
                TextFormatFlags.Left | TextFormatFlags.NoPrefix | TextFormatFlags.EndEllipsis);
        }
    }
}
