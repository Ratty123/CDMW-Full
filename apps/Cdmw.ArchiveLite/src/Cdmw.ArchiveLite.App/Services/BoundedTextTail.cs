using System.Text;

namespace Cdmw.ArchiveLite.App.Services;

internal sealed class BoundedTextTail(int maximumBytes)
{
    private readonly object _gate = new();
    private readonly StringBuilder _text = new();

    public void Append(string? value)
    {
        if (string.IsNullOrEmpty(value))
        {
            return;
        }

        lock (_gate)
        {
            _text.Append(value);
            var excess = Encoding.UTF8.GetByteCount(_text.ToString()) - maximumBytes;
            while (excess > 0 && _text.Length > 0)
            {
                var remove = Math.Min(_text.Length, Math.Max(1, excess / 2));
                _text.Remove(0, remove);
                excess = Encoding.UTF8.GetByteCount(_text.ToString()) - maximumBytes;
            }
        }
    }

    public override string ToString()
    {
        lock (_gate)
        {
            return _text.ToString();
        }
    }
}
