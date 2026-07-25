using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
    private const int WmSetRedraw = 0x000B;

    [DllImport("user32.dll", EntryPoint = "SendMessageW")]
    private static extern IntPtr SendRedrawMessage(IntPtr hWnd, int message, IntPtr wParam, IntPtr lParam);

    /// <summary>
    /// Freezes painting while a batch of control-tree changes is applied.
    /// </summary>
    /// <remarks>
    /// SuspendLayout only defers measurement; it does not stop WinForms from
    /// painting. Attaching a large subtree to a window that is already on screen
    /// therefore shows every intermediate step: unpainted buttons, group boxes
    /// drawn as bare outlines before their captions, combo boxes clipping their
    /// text to a not-yet-final width, and drop-downs painting detached from
    /// their owner. Holding WM_SETREDRAW off for the whole batch and repainting
    /// once on release makes the first frame the reader sees the settled one.
    /// </remarks>
    private int _redrawBatchDepth;

    private RedrawBatch BeginRedrawBatch() => new(this);

    /// <summary>
    /// Refcounted so batches can nest: the layout activations each hold one, and
    /// the callers that drive a mode change hold one around the pair. WM_SETREDRAW
    /// is not itself refcounted, so an inner release would otherwise thaw the
    /// window while the outer batch still expects it frozen.
    /// </summary>
    internal readonly struct RedrawBatch : IDisposable
    {
        private readonly ExperimentForm? _form;

        internal RedrawBatch(ExperimentForm form)
        {
            // Without a handle there is no window to freeze, and forcing one
            // here would change the control's creation order.
            _form = form.IsHandleCreated ? form : null;
            if (_form is null)
            {
                return;
            }
            if (_form._redrawBatchDepth++ == 0)
            {
                _ = SendRedrawMessage(_form.Handle, WmSetRedraw, IntPtr.Zero, IntPtr.Zero);
            }
        }

        public void Dispose()
        {
            if (_form is null || !_form.IsHandleCreated)
            {
                return;
            }
            if (--_form._redrawBatchDepth > 0)
            {
                return;
            }
            _form._redrawBatchDepth = 0;
            // Settle the tree before anything is allowed to paint, so the single
            // repaint below draws final geometry rather than the transitional
            // sizes the frozen layout passes left behind.
            _form.PerformLayout();
            _ = SendRedrawMessage(_form.Handle, WmSetRedraw, new IntPtr(1), IntPtr.Zero);
            _form.Invalidate(invalidateChildren: true);
            _form.Update();
        }
    }
}
