using System.Globalization;
using System.Windows.Data;
using Cdmw.ArchiveLite.App.Services;
using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.App.Infrastructure;

public sealed class ArchiveEntryFileTypeLabelConverter : IValueConverter
{
    public object Convert(object value, Type targetType, object parameter, CultureInfo culture) =>
        value is ArchiveEntryFileType fileType
            ? LocalizationManager.Get($"FileType{fileType}")
            : string.Empty;

    public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture) =>
        throw new NotSupportedException();
}
