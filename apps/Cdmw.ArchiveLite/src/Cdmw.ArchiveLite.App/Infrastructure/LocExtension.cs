using System.Windows.Markup;
using System.Windows.Data;
using Cdmw.ArchiveLite.App.Services;

namespace Cdmw.ArchiveLite.App.Infrastructure;

[MarkupExtensionReturnType(typeof(string))]
public sealed class LocExtension : MarkupExtension
{
    public string Key { get; set; } = string.Empty;

    public override object ProvideValue(IServiceProvider serviceProvider) => new Binding($"[{Key}]")
    {
        Source = LocalizedStringSource.Instance,
        Mode = BindingMode.OneWay,
    }.ProvideValue(serviceProvider);
}
