using System.Globalization;
using System.Text;
using System.Text.Json;
using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.Core;

internal sealed class ExportManifestWriter : IAsyncDisposable
{
    private readonly string _stagingPath;
    private readonly ExportManifestFormat _format;
    private readonly FileStream _stream;
    private readonly Utf8JsonWriter? _json;
    private readonly StreamWriter? _text;
    private bool _looseArrayStarted;
    private bool _completed;

    private ExportManifestWriter(
        string destinationPath,
        string stagingPath,
        ExportManifestFormat format,
        FileStream stream,
        string? fingerprint)
    {
        DestinationPath = destinationPath;
        _stagingPath = stagingPath;
        _format = format;
        _stream = stream;
        if (format == ExportManifestFormat.Json)
        {
            _json = new Utf8JsonWriter(stream, new JsonWriterOptions { Indented = true });
            _json.WriteStartObject();
            _json.WriteString("schema", "cdmw_archive_lite_manifest_v1");
            _json.WriteString("product_version", typeof(ArchiveExportService).Assembly.GetName().Version?.ToString() ?? "0.0.0");
            _json.WriteString("created_utc", DateTimeOffset.UtcNow);
            if (fingerprint is null) _json.WriteNull("archive_fingerprint");
            else _json.WriteString("archive_fingerprint", fingerprint);
            _json.WritePropertyName("entries");
            _json.WriteStartArray();
        }
        else
        {
            _text = new StreamWriter(stream, new UTF8Encoding(false), 16 * 1024, leaveOpen: true);
            if (format == ExportManifestFormat.Csv)
            {
                _text.WriteLine("source_kind,path,package,source_pamt,paz_file,paz_index,offset,stored_size,original_size,flags,compression_type,encryption_type,role,output_path");
            }
        }
    }

    public string DestinationPath { get; }

    public static ExportManifestWriter? Create(
        string destination,
        ExportManifestFormat format,
        string? fingerprint)
    {
        if (format == ExportManifestFormat.None) return null;
        var extension = format switch
        {
            ExportManifestFormat.Csv => ".csv",
            ExportManifestFormat.Text => ".txt",
            _ => ".json",
        };
        var destinationPath = Path.Combine(destination, "cdmw-archive-lite-manifest" + extension);
        ExportPathPolicy.PrepareContainedOutputPath(destination, destinationPath);
        var stagingPath = Path.Combine(destination, $".cdmw-archive-lite-manifest.{Guid.NewGuid():N}.tmp");
        var stream = new FileStream(
            stagingPath,
            FileMode.CreateNew,
            FileAccess.Write,
            FileShare.None,
            128 * 1024,
            FileOptions.SequentialScan);
        try
        {
            return new ExportManifestWriter(destinationPath, stagingPath, format, stream, fingerprint);
        }
        catch
        {
            stream.Dispose();
            File.Delete(stagingPath);
            throw;
        }
    }

    public void AddArchive(ArchiveLiteManifestEntry entry)
    {
        if (_completed) throw new InvalidOperationException("Manifest is already complete.");
        if (_looseArrayStarted) throw new InvalidOperationException("Archive rows must precede loose rows.");
        if (_format == ExportManifestFormat.Json)
        {
            JsonSerializer.Serialize(_json!, entry, WorkerProtocol.JsonOptions);
        }
        else if (_format == ExportManifestFormat.Csv)
        {
            _text!.WriteLine(string.Join(',',
                Csv("archive"), Csv(entry.Path), Csv(entry.Package), Csv(entry.SourcePamt), Csv(entry.PazFile),
                entry.PazIndex.ToString(CultureInfo.InvariantCulture), entry.Offset.ToString(CultureInfo.InvariantCulture),
                entry.StoredSize.ToString(CultureInfo.InvariantCulture), entry.OriginalSize.ToString(CultureInfo.InvariantCulture),
                entry.Flags.ToString(CultureInfo.InvariantCulture), entry.CompressionType.ToString(CultureInfo.InvariantCulture),
                entry.EncryptionType.ToString(CultureInfo.InvariantCulture), Csv(entry.Role.ToString()), Csv(entry.OutputPath ?? string.Empty)));
        }
        else
        {
            _text!.WriteLine(entry.Path);
        }
    }

    public void AddLoose(ArchiveLiteLooseManifestEntry entry)
    {
        if (_completed) throw new InvalidOperationException("Manifest is already complete.");
        BeginLooseRows();
        if (_format == ExportManifestFormat.Json)
        {
            JsonSerializer.Serialize(_json!, entry, WorkerProtocol.JsonOptions);
        }
        else if (_format == ExportManifestFormat.Csv)
        {
            _text!.WriteLine(string.Join(',',
                Csv("loose"), Csv(entry.SourcePath), Csv(string.Empty), Csv(string.Empty), Csv(string.Empty),
                string.Empty, string.Empty, string.Empty, entry.Size.ToString(CultureInfo.InvariantCulture),
                string.Empty, string.Empty, Csv(string.Empty), Csv(string.Empty), Csv(entry.OutputPath)));
        }
        else
        {
            _text!.WriteLine(entry.SourcePath);
        }
    }

    public Task CompleteAsync(CancellationToken cancellationToken)
    {
        if (_completed) return Task.CompletedTask;
        cancellationToken.ThrowIfCancellationRequested();
        if (_format == ExportManifestFormat.Json)
        {
            BeginLooseRows();
            _json!.WriteEndArray();
            _json.WriteEndObject();
            _json.Flush();
        }
        else
        {
            _text!.Flush();
        }
        _stream.Flush(flushToDisk: true);
        cancellationToken.ThrowIfCancellationRequested();
        _json?.Dispose();
        _text?.Dispose();
        _stream.Dispose();
        File.Move(_stagingPath, DestinationPath, overwrite: true);
        _completed = true;
        return Task.CompletedTask;
    }

    public ValueTask DisposeAsync()
    {
        if (!_completed)
        {
            _json?.Dispose();
            _text?.Dispose();
            _stream.Dispose();
            try
            {
                File.Delete(_stagingPath);
            }
            catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
            {
                // Cache/output cleanup can retry a locked staging file later.
            }
        }
        return ValueTask.CompletedTask;
    }

    private void BeginLooseRows()
    {
        if (_looseArrayStarted) return;
        if (_format == ExportManifestFormat.Json)
        {
            _json!.WriteEndArray();
            _json.WritePropertyName("loose_files");
            _json.WriteStartArray();
        }
        _looseArrayStarted = true;
    }

    private static string Csv(string value) => $"\"{value.Replace("\"", "\"\"", StringComparison.Ordinal)}\"";
}
