using System.Windows.Forms;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
    /// <summary>
    /// A deep layout suspension. Disposing it is what performs the deferred
    /// layout; <see cref="Include"/> brings a control created after the
    /// suspension began under it as well.
    /// </summary>
    private interface ILayoutTreeSuspension : IDisposable
    {
        void Include(Control? control);
    }

    /// <summary>
    /// Suspends layout on an entire subtree, not just on the root.
    /// </summary>
    /// <remarks>
    /// <see cref="Control.SuspendLayout"/> only defers the layout of the
    /// control it is called on. The tool flanks are AutoSize table layouts four
    /// levels deep, so building them with only the outer containers suspended
    /// still laid out every section, body and button row on every append,
    /// re-parent, dock change and visibility flip along the way: 332 table
    /// layouts before the window was ever shown, most of them measuring the
    /// same unchanged content. Nothing is on screen during hidden startup, so
    /// the only layout worth paying for is the one that runs when this is
    /// disposed: every suspended container resumes with a real layout, children
    /// before parents, which is one pass per container instead of one per
    /// mutation.
    /// </remarks>
    private sealed class LayoutTreeSuspension : ILayoutTreeSuspension
    {
        private readonly List<Control> _suspended = new();
        private readonly HashSet<Control> _seen = new(ReferenceEqualityComparer.Instance);
        private readonly HashSet<Control> _excluded = new(ReferenceEqualityComparer.Instance);
        private readonly Action? _onDisposed;
        private bool _disposed;

        public LayoutTreeSuspension(IEnumerable<Control?> roots, IEnumerable<Control?> excluded, Action? onDisposed)
        {
            _onDisposed = onDisposed;
            foreach (var control in excluded)
            {
                if (control is not null)
                {
                    _excluded.Add(control);
                }
            }
            foreach (var root in roots)
            {
                Suspend(root);
            }
        }

        private void Suspend(Control? control)
        {
            if (control is null || control.IsDisposed || _excluded.Contains(control) || !_seen.Add(control))
            {
                return;
            }
            control.SuspendLayout();
            _suspended.Add(control);
            foreach (Control child in control.Controls)
            {
                Suspend(child);
            }
        }

        public void Include(Control? control)
        {
            if (!_disposed)
            {
                Suspend(control);
            }
        }

        public void Dispose()
        {
            if (_disposed)
            {
                return;
            }
            _disposed = true;
            try
            {
                // Children first. A parent's closing layout then measures
                // children whose own layout has already settled and whose
                // preferred sizes are cached, and a child's resume cannot dirty
                // an already finished parent. Parents first was measured at
                // roughly twice the cost: every unsettled child is re-measured
                // from scratch for each constraint its parent tries.
                for (var index = _suspended.Count - 1; index >= 0; index--)
                {
                    var control = _suspended[index];
                    if (!control.IsDisposed)
                    {
                        control.ResumeLayout(performLayout: true);
                    }
                }
                _suspended.Clear();
            }
            finally
            {
                _onDisposed?.Invoke();
            }
        }
    }

    /// <summary>
    /// The suspension handed out while an outer one is already open. It adds
    /// its roots to the outer suspension and defers to it for the closing
    /// layout, so nested startup phases still produce a single pass.
    /// </summary>
    private sealed class NestedLayoutTreeSuspension : ILayoutTreeSuspension
    {
        private readonly LayoutTreeSuspension _outer;

        public NestedLayoutTreeSuspension(LayoutTreeSuspension outer, IEnumerable<Control?> roots)
        {
            _outer = outer;
            foreach (var root in roots)
            {
                _outer.Include(root);
            }
        }

        public void Include(Control? control) => _outer.Include(control);

        public void Dispose()
        {
        }
    }

    private LayoutTreeSuspension? _ambientLayoutSuspension;

    /// <summary>
    /// Suspend layout under <paramref name="roots"/> until the returned token
    /// is disposed. The resident renderer's region is never suspended: it is not
    /// part of the tool chrome and its surface sizing has its own timing.
    /// </summary>
    private ILayoutTreeSuspension SuspendLayoutTree(params Control?[] roots)
    {
        if (_ambientLayoutSuspension is { } outer)
        {
            return new NestedLayoutTreeSuspension(outer, roots);
        }
        var suspension = new LayoutTreeSuspension(
            roots,
            new Control?[] { _presentationViewportRegion },
            onDisposed: () => _ambientLayoutSuspension = null);
        _ambientLayoutSuspension = suspension;
        return suspension;
    }
}
