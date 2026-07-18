using System.Text.Json;
using System.Text.Json.Serialization;

namespace Cdmw.ArchiveLite.Contracts;

public static class WorkerProtocol
{
    public const int Version = 1;
    public const int MaximumMessageBytes = 1024 * 1024;

    public const string Ping = "ping";
    public const string Shutdown = "shutdown";
    public const string Cancel = "cancel";
    public const string OpenArchive = "open_archive";
    public const string QueryArchive = "query_archive";
    public const string ArchiveFacets = "archive_facets";
    public const string BuildNameIndex = "build_name_index";
    public const string Preview = "preview";
    public const string TextSearch = "text_search";
    public const string Export = "export";

    public static JsonSerializerOptions JsonOptions { get; } = CreateJsonOptions();

    public static WorkerMessage Request<T>(Guid requestId, long generation, string kind, T payload) =>
        new(Version, requestId, generation, kind, WorkerMessageStatus.Request, SerializePayload(payload));

    public static WorkerMessage Response<T>(WorkerMessage request, WorkerMessageStatus status, T payload) =>
        new(Version, request.RequestId, request.Generation, request.Kind, status, SerializePayload(payload));

    public static WorkerMessage Failure(WorkerMessage request, string code, string message, string? detail = null) =>
        new(
            Version,
            request.RequestId,
            request.Generation,
            request.Kind,
            WorkerMessageStatus.Error,
            null,
            new WorkerError(code, message, detail));

    public static T? ReadPayload<T>(WorkerMessage message) =>
        message.Payload is { } payload ? payload.Deserialize<T>(JsonOptions) : default;

    private static JsonElement SerializePayload<T>(T value) =>
        JsonSerializer.SerializeToElement(value, JsonOptions);

    private static JsonSerializerOptions CreateJsonOptions()
    {
        var options = new JsonSerializerOptions
        {
            PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
            PropertyNameCaseInsensitive = true,
            WriteIndented = false,
        };
        options.Converters.Add(new JsonStringEnumConverter(JsonNamingPolicy.SnakeCaseLower));
        return options;
    }
}

public enum WorkerMessageStatus
{
    Request,
    Started,
    Progress,
    Result,
    Cancelled,
    Error,
}

public sealed record WorkerMessage(
    int ProtocolVersion,
    Guid RequestId,
    long Generation,
    string Kind,
    WorkerMessageStatus Status,
    JsonElement? Payload = null,
    WorkerError? Error = null);

public sealed record WorkerError(string Code, string Message, string? Detail = null);

public sealed record PingRequest(string ClientVersion);

public sealed record PingResult(string WorkerVersion, int ProtocolVersion, int ProcessId);

public sealed record CancelRequest(Guid TargetRequestId);

public sealed record ProgressUpdate(long Completed, long Total, string Phase, string? CurrentItem = null);
