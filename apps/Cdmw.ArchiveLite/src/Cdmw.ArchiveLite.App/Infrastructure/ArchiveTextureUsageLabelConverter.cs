using System.Globalization;
using System.Windows.Data;
using Cdmw.ArchiveLite.App.Services;
using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.App.Infrastructure;

public sealed class ArchiveTextureUsageLabelConverter : IValueConverter
{
    public object Convert(object value, Type targetType, object parameter, CultureInfo culture) =>
        value is ArchiveTextureUsage.None
            ? string.Empty
            : value is ArchiveTextureUsage usage
                ? LocalizationManager.Get($"TextureUsage{usage}")
                : string.Empty;

    public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture) =>
        throw new NotSupportedException();
}
