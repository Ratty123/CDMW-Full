using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace Cdmw.MeshEditorExperiment;

internal static class NativeWindowHost
{
    private const int GwlStyle = -16;
    private const long WsChild = 0x40000000L;
    private const long WsPopup = 0x80000000L;
    private const long WsCaption = 0x00C00000L;
    private const uint SwpNoZOrder = 0x0004;
    private const uint SwpNoActivate = 0x0010;
    private const uint SwpFrameChanged = 0x0020;
    private const uint SwpShowWindow = 0x0040;

    public static bool Embed(Form form, IntPtr parent)
    {
        if (parent == IntPtr.Zero || !IsWindow(parent))
        {
            return false;
        }
        SetParent(form.Handle, parent);
        var style = GetWindowLongPtrSafe(form.Handle, GwlStyle).ToInt64();
        style |= WsChild;
        style &= ~WsPopup;
        style &= ~WsCaption;
        SetWindowLongPtrSafe(form.Handle, GwlStyle, new IntPtr(style));
        ResizeToParent(form, parent);
        return true;
    }

    public static void ResizeToParent(Form form, IntPtr parent)
    {
        if (parent == IntPtr.Zero || !IsWindow(parent) || !GetClientRect(parent, out var rect))
        {
            return;
        }
        var width = Math.Max(1, rect.Right - rect.Left);
        var height = Math.Max(1, rect.Bottom - rect.Top);
        SetWindowPos(form.Handle, IntPtr.Zero, 0, 0, width, height, SwpNoZOrder | SwpNoActivate | SwpFrameChanged | SwpShowWindow);
    }

    private static IntPtr GetWindowLongPtrSafe(IntPtr hwnd, int index)
    {
        return IntPtr.Size == 8 ? GetWindowLongPtr64(hwnd, index) : new IntPtr(GetWindowLong32(hwnd, index));
    }

    private static IntPtr SetWindowLongPtrSafe(IntPtr hwnd, int index, IntPtr value)
    {
        return IntPtr.Size == 8 ? SetWindowLongPtr64(hwnd, index, value) : new IntPtr(SetWindowLong32(hwnd, index, value.ToInt32()));
    }

    [DllImport("user32.dll")]
    private static extern IntPtr SetParent(IntPtr child, IntPtr parent);

    [DllImport("user32.dll")]
    private static extern bool IsWindow(IntPtr hwnd);

    [DllImport("user32.dll")]
    private static extern bool GetClientRect(IntPtr hwnd, out Rect rect);

    [DllImport("user32.dll")]
    private static extern bool SetWindowPos(IntPtr hwnd, IntPtr hwndInsertAfter, int x, int y, int cx, int cy, uint flags);

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
