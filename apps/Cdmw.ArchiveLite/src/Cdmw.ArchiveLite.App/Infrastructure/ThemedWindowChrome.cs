using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Interop;
using Cdmw.ArchiveLite.App.Services;

namespace Cdmw.ArchiveLite.App.Infrastructure;

public static class ThemedWindowChrome
{
    public static void Apply(Window window)
    {
        ArgumentNullException.ThrowIfNull(window);
        var handle = new WindowInteropHelper(window).Handle;
        if (handle == IntPtr.Zero)
        {
            return;
        }

        var dark = ThemeManager.Current.IsDark ? 1 : 0;
        if (DwmSetWindowAttribute(handle, 20, ref dark, sizeof(int)) != 0)
        {
            _ = DwmSetWindowAttribute(handle, 19, ref dark, sizeof(int));
        }

        const int roundedCornerPreference = 2;
        var corners = roundedCornerPreference;
        _ = DwmSetWindowAttribute(handle, 33, ref corners, sizeof(int));
    }

    [DllImport("dwmapi.dll")]
    private static extern int DwmSetWindowAttribute(
        IntPtr windowHandle,
        int attribute,
        ref int attributeValue,
        int attributeSize);
}
