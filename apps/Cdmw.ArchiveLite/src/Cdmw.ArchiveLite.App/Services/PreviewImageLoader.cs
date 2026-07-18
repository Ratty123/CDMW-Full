using System.Windows.Media.Imaging;

namespace Cdmw.ArchiveLite.App.Services;

public static class PreviewImageLoader
{
    public static Task<BitmapSource> LoadFrozenAsync(string path, CancellationToken cancellationToken) =>
        Task.Run(() => LoadFrozen(path, cancellationToken), cancellationToken);

    private static BitmapSource LoadFrozen(string path, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        using var stream = new FileStream(
            path,
            FileMode.Open,
            FileAccess.Read,
            FileShare.Read | FileShare.Delete,
            128 * 1024,
            FileOptions.SequentialScan);
        var decoder = BitmapDecoder.Create(stream, BitmapCreateOptions.PreservePixelFormat, BitmapCacheOption.OnLoad);
        if (decoder.Frames.Count == 0)
        {
            throw new InvalidDataException("The image contains no decodable frames.");
        }

        cancellationToken.ThrowIfCancellationRequested();
        var frame = decoder.Frames[0];
        frame.Freeze();
        return frame;
    }
}
