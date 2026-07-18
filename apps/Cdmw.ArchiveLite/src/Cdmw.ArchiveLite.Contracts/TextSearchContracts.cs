namespace Cdmw.ArchiveLite.Contracts;

public enum TextSearchSourceKind
{
    Archive,
    LooseFolder,
}

public sealed record TextSearchRequest(
    TextSearchSourceKind SourceKind,
    string Source,
    string Query,
    bool UseRegularExpression,
    bool CaseSensitive,
    string? PathFilter,
    IReadOnlyList<string> Extensions,
    int MaximumMatches = 2_000,
    int ContextCharacters = 160,
    int RegexTimeoutMilliseconds = 1_000);

public sealed record TextSearchMatchDto(
    long MatchId,
    long? EntryId,
    string Path,
    int Line,
    int Column,
    int Length,
    string Context);

public sealed record TextSearchResultBatch(
    long FilesScanned,
    long FilesMatched,
    long BytesRead,
    IReadOnlyList<TextSearchMatchDto> Matches,
    bool LimitReached,
    IReadOnlyList<string> TimedOutPaths,
    IReadOnlyList<string> Warnings);

public sealed record TextDocumentRequest(
    TextSearchSourceKind SourceKind,
    string Source,
    string Path,
    long? EntryId = null);
