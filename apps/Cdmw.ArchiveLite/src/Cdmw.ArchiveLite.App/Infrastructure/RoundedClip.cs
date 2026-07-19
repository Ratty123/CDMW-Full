using System.Windows;
using System.Windows.Media;

namespace Cdmw.ArchiveLite.App.Infrastructure;

public static class RoundedClip
{
    public static readonly DependencyProperty RadiusProperty = DependencyProperty.RegisterAttached(
        "Radius",
        typeof(double),
        typeof(RoundedClip),
        new PropertyMetadata(0d, OnRadiusChanged),
        static value => value is double radius
            && radius >= 0d
            && !double.IsInfinity(radius)
            && !double.IsNaN(radius));

    public static double GetRadius(DependencyObject element) =>
        (double)element.GetValue(RadiusProperty);

    public static void SetRadius(DependencyObject element, double value) =>
        element.SetValue(RadiusProperty, value);

    private static void OnRadiusChanged(DependencyObject dependencyObject, DependencyPropertyChangedEventArgs eventArgs)
    {
        if (dependencyObject is not FrameworkElement element)
        {
            return;
        }

        element.SizeChanged -= OnElementSizeChanged;
        if ((double)eventArgs.NewValue <= 0d)
        {
            element.Clip = null;
            return;
        }

        element.SizeChanged += OnElementSizeChanged;
        ApplyClip(element);
    }

    private static void OnElementSizeChanged(object sender, SizeChangedEventArgs eventArgs)
    {
        if (sender is FrameworkElement element)
        {
            ApplyClip(element);
        }
    }

    private static void ApplyClip(FrameworkElement element)
    {
        if (element.ActualWidth <= 0d || element.ActualHeight <= 0d)
        {
            element.Clip = null;
            return;
        }

        var radius = Math.Min(
            GetRadius(element),
            Math.Min(element.ActualWidth, element.ActualHeight) / 2d);
        var clip = new RectangleGeometry(
            new Rect(0d, 0d, element.ActualWidth, element.ActualHeight),
            radius,
            radius);
        clip.Freeze();
        element.Clip = clip;
    }
}
