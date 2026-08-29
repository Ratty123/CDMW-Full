using System.Drawing;
using System.Windows.Forms;

namespace Cdmw.MeshEditorExperiment;

[Flags]
internal enum MeshPointerButtons
{
    None = 0,
    Left = 1,
    Right = 2,
    Middle = 4,
}

internal sealed record MeshPointerInput(
    Point Location,
    MeshPointerButtons ChangedButton,
    MeshPointerButtons HeldButtons,
    bool Shift,
    bool Control,
    bool Alt,
    int WheelDelta,
    int Clicks,
    bool HasCapture,
    bool HasFocus)
{
    public bool IsHeld(MeshPointerButtons button) => (HeldButtons & button) == button;
    public bool Changed(MeshPointerButtons button) => ChangedButton == button;
    public MeshPointerInput At(Point location) => this with { Location = location };
}

/// <summary>
/// Converts WinForms state into the platform-neutral pointer contract consumed
/// by edit and camera logic. It never scans geometry, mutates the mesh, reads
/// the GPU, or calls the host.
/// </summary>
internal sealed class MeshViewportInputAdapter
{
    private MeshPointerButtons _heldButtons;

    public MeshPointerInput Normalize(
        MouseEventArgs source,
        Keys modifiers,
        bool hasCapture,
        bool hasFocus) => Build(
            source,
            modifiers,
            Button(source.Button),
            Buttons(source.Button),
            hasCapture,
            hasFocus);

    public MeshPointerInput NormalizeDown(
        MouseEventArgs source,
        Keys modifiers,
        bool hasCapture,
        bool hasFocus)
    {
        var changed = Button(source.Button);
        _heldButtons |= changed;
        return Build(source, modifiers, changed, _heldButtons, hasCapture, hasFocus);
    }

    public MeshPointerInput NormalizeMove(
        MouseEventArgs source,
        Keys modifiers,
        bool hasCapture,
        bool hasFocus)
    {
        // MouseEventArgs.Button can be None for a posted or capture-routed move
        // even though the viewport received the matching down and still owns
        // the gesture. Preserve the boundary-observed button state; real mouse
        // moves that do carry button bits can only add currently held buttons.
        _heldButtons |= Buttons(source.Button);
        return Build(
            source,
            modifiers,
            MeshPointerButtons.None,
            _heldButtons,
            hasCapture,
            hasFocus);
    }

    public MeshPointerInput NormalizeUp(
        MouseEventArgs source,
        Keys modifiers,
        bool hasCapture,
        bool hasFocus)
    {
        var changed = Button(source.Button);
        _heldButtons &= ~changed;
        return Build(source, modifiers, changed, _heldButtons, hasCapture, hasFocus);
    }

    public MeshPointerInput NormalizeWheel(
        MouseEventArgs source,
        Keys modifiers,
        bool hasCapture,
        bool hasFocus) => Build(
            source,
            modifiers,
            MeshPointerButtons.None,
            _heldButtons | Buttons(source.Button),
            hasCapture,
            hasFocus);

    public void Reset() => _heldButtons = MeshPointerButtons.None;

    private static MeshPointerInput Build(
        MouseEventArgs source,
        Keys modifiers,
        MeshPointerButtons changedButton,
        MeshPointerButtons heldButtons,
        bool hasCapture,
        bool hasFocus) => new(
            source.Location,
            changedButton,
            heldButtons,
            (modifiers & Keys.Shift) == Keys.Shift,
            (modifiers & Keys.Control) == Keys.Control,
            (modifiers & Keys.Alt) == Keys.Alt,
            source.Delta,
            source.Clicks,
            hasCapture,
            hasFocus);

    private static MeshPointerButtons Button(MouseButtons button) => button switch
    {
        MouseButtons.Left => MeshPointerButtons.Left,
        MouseButtons.Right => MeshPointerButtons.Right,
        MouseButtons.Middle => MeshPointerButtons.Middle,
        _ => MeshPointerButtons.None,
    };

    private static MeshPointerButtons Buttons(MouseButtons buttons)
    {
        var normalized = MeshPointerButtons.None;
        if ((buttons & MouseButtons.Left) == MouseButtons.Left)
        {
            normalized |= MeshPointerButtons.Left;
        }
        if ((buttons & MouseButtons.Right) == MouseButtons.Right)
        {
            normalized |= MeshPointerButtons.Right;
        }
        if ((buttons & MouseButtons.Middle) == MouseButtons.Middle)
        {
            normalized |= MeshPointerButtons.Middle;
        }
        return normalized;
    }
}
