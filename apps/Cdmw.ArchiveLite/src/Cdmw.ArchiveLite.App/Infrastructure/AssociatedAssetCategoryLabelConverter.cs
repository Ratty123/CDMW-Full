using System.Globalization;
using System.Windows.Data;
using Cdmw.ArchiveLite.App.Services;
using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.App.Infrastructure;

public sealed class AssociatedAssetCategoryLabelConverter : IValueConverter
{
    public object Convert(object value, Type targetType, object parameter, CultureInfo culture) =>
        value is AssociatedAssetCategory category
            ? LocalizationManager.Get($"AssociatedCategory{category}")
            : string.Empty;

    public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture) =>
        throw new NotSupportedException();
}
