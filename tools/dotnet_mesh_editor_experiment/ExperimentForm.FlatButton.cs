using System.Drawing;
using System.Drawing.Drawing2D;
using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace Cdmw.MeshEditorExperiment;

// The flat button every tool panel is made of. Split from
// ExperimentForm.Controls.cs to keep that file inside the owned-file line
// cap; same partial class.
internal sealed partial class ExperimentForm
{
    /// <summary>
    /// Flat, rounded, accent-driven button. Replaces the beveled highlight and
    /// shadow border, which is the single strongest "old Windows" cue in the
    /// editor and does not exist anywhere in the Qt shell.
    /// </summary>
    private sealed class MeshEditorFlatButton : Button
    {
        private const int CornerRadius = 4;
        private bool _accent;

        public MeshEditorFlatButton()
        {
            ResizeRedraw = true;
            SetStyle(ControlStyles.OptimizedDoubleBuffer | ControlStyles.AllPaintingInWmPaint, true);
            FlatStyle = FlatStyle.Flat;
            FlatAppearance.BorderSize = 0;
        }

        // The tool flanks are AutoSize table layouts nested four deep, and the
        // table layout engine measures every AutoSize child several times per
        // pass. At startup that came to ~200,000 preferred-size queries for 73
        // buttons, and each of them laid the caption out again from scratch.
        // The answer only depends on the text, font, padding and the proposed
        // constraints, so it is computed once per distinct question and reused
        // until one of those inputs changes.
        private readonly Dictionary<Size, Size> _preferredSizeCache = new();
        private Size _preferredSizeCacheMinimum;
        private Size _preferredSizeCacheMaximum;

        public override Size GetPreferredSize(Size proposedSize)
        {
            // Size constraints are applied inside the base measurement and have
            // no change notification of their own, so they are part of the key.
            if (_preferredSizeCacheMinimum != MinimumSize || _preferredSizeCacheMaximum != MaximumSize)
            {
                _preferredSizeCache.Clear();
                _preferredSizeCacheMinimum = MinimumSize;
                _preferredSizeCacheMaximum = MaximumSize;
            }
            if (_preferredSizeCache.TryGetValue(proposedSize, out var cached))
            {
                StartupTiming.Account("flat_button_get_preferred_size_cached", 0);
                return cached;
            }
            var started = System.Diagnostics.Stopwatch.GetTimestamp();
            var size = base.GetPreferredSize(proposedSize);
            StartupTiming.Account("flat_button_get_preferred_size", System.Diagnostics.Stopwatch.GetTimestamp() - started);
            if (_preferredSizeCache.Count > 64)
            {
                _preferredSizeCache.Clear();
            }
            _preferredSizeCache[proposedSize] = size;
            return size;
        }

        protected override void OnTextChanged(EventArgs e)
        {
            _preferredSizeCache.Clear();
            base.OnTextChanged(e);
        }

        protected override void OnFontChanged(EventArgs e)
        {
            _preferredSizeCache.Clear();
            base.OnFontChanged(e);
        }

        protected override void OnPaddingChanged(EventArgs e)
        {
            _preferredSizeCache.Clear();
            base.OnPaddingChanged(e);
        }

        protected override void OnDpiChangedAfterParent(EventArgs e)
        {
            _preferredSizeCache.Clear();
            base.OnDpiChangedAfterParent(e);
        }

        public void SetAccent(bool accent)
        {
            _accent = accent;
            BackColor = accent ? ThemeAccent : ThemeButtonBackground;
            ForeColor = accent ? Color.White : ThemeText;
            FlatAppearance.MouseOverBackColor = accent ? ThemeAccentHover : ThemeButtonHover;
            FlatAppearance.MouseDownBackColor = accent ? ThemeAccentPressed : ThemeButtonPressed;
            Invalidate();
        }

        internal static GraphicsPath RoundedPath(Rectangle bounds, int radius)
        {
            var path = new GraphicsPath();
            var d = Math.Max(1, radius * 2);
            if (bounds.Width <= d || bounds.Height <= d)
            {
                path.AddRectangle(bounds);
                return path;
            }
            path.AddArc(bounds.X, bounds.Y, d, d, 180, 90);
            path.AddArc(bounds.Right - d, bounds.Y, d, d, 270, 90);
            path.AddArc(bounds.Right - d, bounds.Bottom - d, d, d, 0, 90);
            path.AddArc(bounds.X, bounds.Bottom - d, d, d, 90, 90);
            path.CloseFigure();
            return path;
        }

        protected override void OnResize(EventArgs e)
        {
            base.OnResize(e);
            ApplyRoundedRegion();
        }

        protected override void OnHandleCreated(EventArgs e)
        {
            base.OnHandleCreated(e);
            ApplyRoundedRegion();
        }

        private Size _appliedRegionSize = Size.Empty;

        private void ApplyRoundedRegion()
        {
            if (!IsHandleCreated || Width < 4 || Height < 4)
            {
                return;
            }
            var size = new Size(Width, Height);
            if (size == _appliedRegionSize && Region is not null)
            {
                // An embedded host resize delivers a burst of WM_WINDOWPOSCHANGED
                // at the same final size. Rebuilding an identical region per
                // message churns a GDI region handle per button per message for
                // no visual change.
                return;
            }
            try
            {
                using var path = RoundedPath(new Rectangle(0, 0, size.Width, size.Height), CornerRadius);
                var previous = Region;
                Region = new Region(path);
                previous?.Dispose();
                _appliedRegionSize = size;
            }
            catch (Exception ex) when (ex is ExternalException or ArgumentException)
            {
                // GDI can refuse the region mid-resize. The rounded corner is
                // cosmetic, but this runs inside WndProc: letting it escape
                // reaches Application.ThreadException and takes down the
                // renderer the host is embedding. Square corners are the
                // correct fallback.
                _appliedRegionSize = Size.Empty;
            }
        }

        protected override void OnPaint(PaintEventArgs pevent)
        {
            base.OnPaint(pevent);
            if (Width < 4 || Height < 4)
            {
                return;
            }
            pevent.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            using var path = RoundedPath(new Rectangle(0, 0, Width - 1, Height - 1), CornerRadius);
            using var pen = new Pen(
                !Enabled ? ThemeBorder : _accent ? ThemeAccent : ThemeButtonBorder);
            pevent.Graphics.DrawPath(pen, path);
        }
    }

    /// <summary>
    /// A flat card instead of the Win32 etched group frame: hairline rounded
    /// border, uppercase caption, no notch.
    /// </summary>
}
