using System.ComponentModel;

namespace Cdmw.ArchiveLite.App.Services;

public sealed class LocalizedStringSource : INotifyPropertyChanged
{
    public static LocalizedStringSource Instance { get; } = new();

    private LocalizedStringSource()
    {
    }

    public string this[string key] => LocalizationManager.Get(key);

    public event PropertyChangedEventHandler? PropertyChanged;

    internal void Refresh() => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs("Item[]"));
}
