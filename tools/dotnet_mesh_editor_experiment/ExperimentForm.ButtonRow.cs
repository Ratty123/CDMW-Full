using System.Drawing;
using System.Windows.Forms;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
    /// <summary>
    /// A row of equally wide buttons that reflows onto extra rows when its
    /// column is too narrow to seat them side by side. Equal-percent columns
    /// alone cannot do this: a caption wider than its share pushes the button
    /// over its cell and paints on top of its neighbour, which is what the tool
    /// rail's 340 px property column did to "Bind Selected Parts".
    /// </summary>
    private sealed class MeshEditorButtonRow : TableLayoutPanel
    {
        private const int CellGap = 3;
        // A button may run this far past the row's right edge before the row is
        // worth breaking: the overhang lands in the panel's own padding, and
        // treating it as a break would rewrap rows that read correctly today.
        private const int TrailingSlack = 8;

        private readonly Control[] _cells;
        private int[] _cellWidths = Array.Empty<int>();
        private int _appliedColumns;
        private bool _reflowing;

        public MeshEditorButtonRow(Control[] cells)
        {
            _cells = cells;
            DoubleBuffered = true;
            SetStyle(ControlStyles.OptimizedDoubleBuffer | ControlStyles.AllPaintingInWmPaint, true);
            AutoSize = true;
            AutoSizeMode = AutoSizeMode.GrowAndShrink;
            BackColor = ThemeSectionBackground;
            Margin = new Padding(0, 0, 0, 6);
            Padding = new Padding(0);
        }

        /// <summary>
        /// Seats the buttons as a single row and records the widths the reflow
        /// measures against. Called once the caller has finished sizing the
        /// buttons, since those widths are read back off them.
        /// </summary>
        public void Configure(int[] cellWidths)
        {
            _cellWidths = cellWidths;
            ApplyColumns(Math.Max(1, _cells.Length));
        }

        protected override void OnLayout(LayoutEventArgs levent)
        {
            Reflow();
            base.OnLayout(levent);
        }

        protected override void OnSizeChanged(EventArgs e)
        {
            base.OnSizeChanged(e);
            // The column count is chosen from the row's width, and the row is
            // resized by its parent after that layout pass rather than during
            // it. Without this the decision keeps being made against the width
            // the row had one pass ago.
            Reflow();
        }

        private void Reflow()
        {
            var available = ClientSize.Width - Padding.Horizontal;
            // Before the first real measurement every width is zero; choosing a
            // column count then is a guess the next pass only has to undo.
            if (_reflowing || _cells.Length == 0 || available <= 0 || _cellWidths.Length == 0)
            {
                return;
            }
            var columns = ColumnsThatFit(available);
            if (columns == _appliedColumns)
            {
                return;
            }
            _reflowing = true;
            SuspendLayout();
            try
            {
                ApplyColumns(columns);
            }
            finally
            {
                ResumeLayout(performLayout: false);
                _reflowing = false;
            }
        }

        private int ColumnsThatFit(int available)
        {
            for (var columns = _cells.Length; columns > 1; columns--)
            {
                if (FitsWithColumns(columns, available))
                {
                    return columns;
                }
            }
            return 1;
        }

        /// <summary>
        /// Every column is an equal share of the row, so a button wider than its
        /// share runs into where the next button starts. This walks the cells a
        /// given column count would produce and reports whether any of them does.
        /// </summary>
        private bool FitsWithColumns(int columns, int available)
        {
            var columnWidth = available / columns;
            if (columnWidth <= 0)
            {
                return false;
            }
            for (var index = 0; index < _cellWidths.Length; index++)
            {
                var column = index % columns;
                var start = (column * columnWidth) + (column == 0 ? 0 : CellGap);
                var lastInRow = column == columns - 1 || index == _cellWidths.Length - 1;
                var limit = lastInRow
                    ? available + TrailingSlack
                    : ((column + 1) * columnWidth) + CellGap;
                if (start + _cellWidths[index] > limit)
                {
                    return false;
                }
            }
            return true;
        }

        private void ApplyColumns(int columns)
        {
            var rows = (int)Math.Ceiling(_cells.Length / (double)columns);
            ColumnStyles.Clear();
            RowStyles.Clear();
            ColumnCount = columns;
            RowCount = rows;
            for (var column = 0; column < columns; column++)
            {
                ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100.0f / columns));
            }
            for (var row = 0; row < rows; row++)
            {
                RowStyles.Add(new RowStyle(SizeType.AutoSize));
            }
            for (var index = 0; index < _cells.Length; index++)
            {
                var cell = _cells[index];
                var row = index / columns;
                var column = index % columns;
                cell.Margin = new Padding(
                    column == 0 ? 0 : CellGap,
                    0,
                    column == columns - 1 ? 0 : CellGap,
                    row == rows - 1 ? 0 : 6);
                if (cell.Parent != this)
                {
                    Controls.Add(cell, column, row);
                }
                else
                {
                    SetCellPosition(cell, new TableLayoutPanelCellPosition(column, row));
                }
            }
            _appliedColumns = columns;
        }
    }
}
