using System.Windows.Markup;
using Cdmw.ArchiveLite.App.Services;

namespace Cdmw.ArchiveLite.App.Infrastructure;

[MarkupExtensionReturnType(typeof(string))]
public sealed class LocExtension : MarkupExtension
{
    public string Key { get; set; } = string.Empty;

    public override object ProvideValue(IServiceProvider serviceProvider) => LocalizationManager.Get(Key);
}
