using System.Text.Json;
using System.Text.Json.Serialization;

namespace Cdmw.FullArchive.Contracts;

public static class WorkerProtocol
{
    public const int Version = 3;
    public const int MaximumMessageBytes = 1024 * 1024;
    public const int DefaultPageSize = 256;
    public const int MaximumPageSize = 512;

    public const string Ping = "ping";
    public const string Shutdown = "shutdown";
    public const string Cancel = "cancel";
    public const string CacheHealth = "cache_health";
    public const string OpenArchive = "open_archive";
    public const string RefreshArchive = "refresh_archive";
    public const string CloseArchive = "close_archive";
    public const string CreateQuery = "create_query";
    public const string FetchPage = "fetch_page";
    public const string FetchChildren = "fetch_children";
    public const string Facets = "facets";
    public const string ResolveEntries = "resolve_entries";
    public const string FindAssociationCandidates = "find_association_candidates";
    public const string BuildNameIndex = "build_name_index";
    public const string SearchItemCatalog = "search_item_catalog";
    public const string LoadItemIcons = "load_item_icons";
    public const string ScopeItemCatalog = "scope_item_catalog";
    public const string PrepareEntry = "prepare_entry";
    public const string TextSearch = "text_search";
    public const string Export = "export";

    public static JsonSerializerOptions JsonOptions { get; } = CreateJsonOptions();

    public static WorkerMessage Request<T>(
        Guid requestId,
        long uiGeneration,
        string operation,
        T payload,
        string? sessionId = null) =>
        new(Version, requestId, uiGeneration, sessionId, operation, WorkerMessageStatus.Request, SerializePayload(payload));

    public static WorkerMessage Response<T>(
        WorkerMessage request,
        WorkerMessageStatus status,
        T payload,
        string? sessionId = null) =>
        new(
            Version,
            request.RequestId,
            request.UiGeneration,
            sessionId ?? request.SessionId,
            request.Operation,
            status,
            SerializePayload(payload));

    public static WorkerMessage Failure(WorkerMessage request, string code, string message, string? detail = null) =>
        new(
            Version,
            request.RequestId,
            request.UiGeneration,
            request.SessionId,
            request.Operation,
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
    Batch,
    Result,
    Cancelled,
    Error,
}

public sealed record WorkerMessage(
    int ProtocolVersion,
    Guid RequestId,
    long UiGeneration,
    string? SessionId,
    string Operation,
    WorkerMessageStatus Status,
    JsonElement? Payload = null,
    WorkerError? Error = null);

public sealed record WorkerError(string Code, string Message, string? Detail = null);

public sealed record PingRequest(string ClientVersion);

public sealed record PingResult(
    string WorkerVersion,
    int ProtocolVersion,
    int NativeAbiVersion,
    int IndexVersion,
    int ProcessId);

public sealed record CancelRequest(Guid TargetRequestId);
