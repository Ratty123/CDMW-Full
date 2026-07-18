namespace Cdmw.ArchiveLite.App.ViewModels;

public sealed record LocalizedOption<T>(T Value, string Label)
{
    public override string ToString() => Label;
}
