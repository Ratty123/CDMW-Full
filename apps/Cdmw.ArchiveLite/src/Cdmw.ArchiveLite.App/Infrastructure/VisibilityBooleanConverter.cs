using System.Globalization;
using System.Windows;
using System.Windows.Data;

namespace Cdmw.ArchiveLite.App.Infrastructure;

public sealed class VisibilityBooleanConverter : IValueConverter
{
    public object Convert(object value, Type targetType, object parameter, CultureInfo culture) =>
        value is Visibility.Visible;

    public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture) =>
        value is true ? Visibility.Visible : Visibility.Collapsed;
}
