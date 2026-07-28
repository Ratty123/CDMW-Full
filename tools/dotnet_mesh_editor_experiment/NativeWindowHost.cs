using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace Cdmw.MeshEditorExperiment;

internal static class NativeWindowHost
{
    private const int GwlStyle = -16;
    private const long WsChild = 0x40000000L;
    private const long WsPopup = 0x80000000L;
    private const long WsCaption = 0x00C00000L;
    private const long WsVisible = 0x10000000L;
    private const uint SwpNoMove = 0x0002;
    private const uint SwpNoZOrder = 0x0004;
    private const uint SwpNoActivate = 0x0010;
    private const uint SwpFrameChanged = 0x0020;
    private const uint SwpShowWindow = 0x0040;
    private static readonly IntPtr HwndTop = IntPtr.Zero;

    /// <summary>
    /// Puts <paramref name="form"/> inside <paramref name="parent"/>, and shows
    /// it there only when <paramref name="reveal"/> says the form is meant to be
    /// on screen. A form whose window was created as a child of the host is
    /// already parented, so the reparent is skipped and this only sizes it.
    /// </summary>
    public static bool Embed(Form form, IntPtr parent, bool reveal = true)
    {
        if (parent == IntPtr.Zero || !IsWindow(parent))
        {
            return false;
        }
        var child = form.Handle;
        if (GetParent(child) != parent)
        {
            var style = GetWindowLongPtrSafe(child, GwlStyle).ToInt64();
            style |= WsChild;
            style &= ~WsPopup;
            style &= ~WsCaption;
            SetWindowLongPtrSafe(child, GwlStyle, new IntPtr(style));
            SetParent(child, parent);
            if (GetParent(child) != parent)
            {
                return false;
            }
        }
        ResizeToParent(form, parent, forceFrameRefresh: true, show: reveal);
        if (reveal)
        {
            BringEmbeddedChildToFront(form, parent);
        }
        return true;
    }

    /// <summary>
    /// <paramref name="show"/> defaults to false: this also runs from the frame
    /// timer's host maintenance, which must never put a deliberately hidden
    /// window back on screen.
    /// </summary>
    public static void ResizeToParent(Form form, IntPtr parent, bool forceFrameRefresh = false, bool show = false)
    {
        if (parent == IntPtr.Zero || !IsWindow(parent) || !GetClientRect(parent, out var rect))
        {
            return;
        }
        var width = Math.Max(1, rect.Right - rect.Left);
        var height = Math.Max(1, rect.Bottom - rect.Top);
        if (!forceFrameRefresh
            && form.Left == 0
            && form.Top == 0
            && form.Width == width
            && form.Height == height)
        {
            return;
        }
        var flags = SwpNoActivate;
        if (show)
        {
            flags |= SwpShowWindow;
        }
        if (forceFrameRefresh)
        {
            flags |= SwpFrameChanged;
        }
        SetWindowPos(form.Handle, HwndTop, 0, 0, width, height, flags);
    }

    /// <summary>The window's own WS_VISIBLE bit, independent of WinForms state.</summary>
    public static bool IsWindowVisibleStyle(IntPtr window)
    {
        return window != IntPtr.Zero
            && (GetWindowLongPtrSafe(window, GwlStyle).ToInt64() & WsVisible) != 0;
    }

    public static long ParentOf(IntPtr window)
    {
        return window == IntPtr.Zero ? 0L : GetParent(window).ToInt64();
    }

    public static bool TryGetClientSize(IntPtr window, out Size size)
    {
        size = Size.Empty;
        if (window == IntPtr.Zero || !IsWindow(window) || !GetClientRect(window, out var rect))
        {
            return false;
        }
        size = new Size(
            Math.Max(1, rect.Right - rect.Left),
            Math.Max(1, rect.Bottom - rect.Top));
        return true;
    }

    public static void ResizeHidden(Form form, int width, int height)
    {
        SetWindowPos(
            form.Handle,
            HwndTop,
            0,
            0,
            Math.Max(1, width),
            Math.Max(1, height),
            SwpNoMove | SwpNoZOrder | SwpNoActivate | SwpFrameChanged);
    }

    private static void BringEmbeddedChildToFront(Form form, IntPtr parent)
    {
        if (parent == IntPtr.Zero || !IsWindow(parent) || !GetClientRect(parent, out var rect))
        {
            return;
        }
        var width = Math.Max(1, rect.Right - rect.Left);
        var height = Math.Max(1, rect.Bottom - rect.Top);
        EnableWindow(form.Handle, true);
        SetWindowPos(form.Handle, HwndTop, 0, 0, width, height, SwpFrameChanged | SwpShowWindow);
        SetFocus(form.Handle);
    }

    private static IntPtr GetWindowLongPtrSafe(IntPtr hwnd, int index)
    {
        return IntPtr.Size == 8 ? GetWindowLongPtr64(hwnd, index) : new IntPtr(GetWindowLong32(hwnd, index));
    }

    private static IntPtr SetWindowLongPtrSafe(IntPtr hwnd, int index, IntPtr value)
    {
        return IntPtr.Size == 8 ? SetWindowLongPtr64(hwnd, index, value) : new IntPtr(SetWindowLong32(hwnd, index, value.ToInt32()));
    }

    [DllImport("user32.dll", SetLastError = true)]
    private static extern IntPtr SetParent(IntPtr child, IntPtr parent);

    [DllImport("user32.dll")]
    private static extern IntPtr GetParent(IntPtr child);

    [DllImport("user32.dll")]
    private static extern bool IsWindow(IntPtr hwnd);

    [DllImport("user32.dll")]
    private static extern bool GetClientRect(IntPtr hwnd, out Rect rect);

    [DllImport("user32.dll")]
    private static extern bool SetWindowPos(IntPtr hwnd, IntPtr hwndInsertAfter, int x, int y, int cx, int cy, uint flags);

    [DllImport("user32.dll")]
    private static extern IntPtr SetFocus(IntPtr hwnd);

    [DllImport("user32.dll")]
    private static extern bool EnableWindow(IntPtr hwnd, bool enable);

    [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW")]
    private static extern IntPtr GetWindowLongPtr64(IntPtr hwnd, int index);

    [DllImport("user32.dll", EntryPoint = "SetWindowLongPtrW")]
    private static extern IntPtr SetWindowLongPtr64(IntPtr hwnd, int index, IntPtr value);

    [DllImport("user32.dll", EntryPoint = "GetWindowLongW")]
    private static extern int GetWindowLong32(IntPtr hwnd, int index);

    [DllImport("user32.dll", EntryPoint = "SetWindowLongW")]
    private static extern int SetWindowLong32(IntPtr hwnd, int index, int value);

    [StructLayout(LayoutKind.Sequential)]
    private struct Rect
    {
        public int Left;
        public int Top;
        public int Right;
        public int Bottom;
    }
}
