using System.Runtime.ExceptionServices;
using System.Runtime.InteropServices;
using System.Text;
using Cdmw.FullArchive.Contracts;

namespace Cdmw.FullArchive.Core;

public sealed class NativeArchiveCore
{
    public const int ExpectedAbiVersion = 1;
    private const string LibraryName = "cdmw-full-archive-core";
    private const int DiagnosticCapacity = 4096;
    private const int MaximumDecodedEntryBytes = 1024 * 1024 * 1024;

    public int AbiVersion => checked((int)NativeMethods.GetAbiVersion());

    public long BuildIndex(
        string packageRoot,
        string indexPath,
        Action<ProgressUpdate>? progress = null,
        CancellationToken cancellationToken = default,
        string[]? sourcePamtPaths = null)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(packageRoot);
        ArgumentException.ThrowIfNullOrWhiteSpace(indexPath);
        EnsureCompatible();
        var error = new byte[DiagnosticCapacity];
        Exception? callbackException = null;
        string? sourcePath = null;
        NativeMethods.BuildIndexProgressCallback callback = (completed, total, phasePointer, itemPointer, _) =>
        {
            if (cancellationToken.IsCancellationRequested)
            {
                return 1;
            }
            try
            {
                if (Marshal.PtrToStringUTF8(phasePointer) == "index_parse_failed")
                    sourcePath = Marshal.PtrToStringUTF8(itemPointer);
                progress?.Invoke(new ProgressUpdate(
                    checked((long)Math.Min(completed, (ulong)long.MaxValue)),
                    checked((long)Math.Min(total, (ulong)long.MaxValue)),
                    Marshal.PtrToStringUTF8(phasePointer) ?? string.Empty,
                    Marshal.PtrToStringUTF8(itemPointer)));
                return 0;
            }
            catch (Exception exception)
            {
                callbackException = exception;
                return 1;
            }
        };
        ulong entryCount;
        NativeStatus status;
        if (sourcePamtPaths is null)
        {
            status = NativeMethods.BuildIndexWithProgress(packageRoot, indexPath, out entryCount,
                callback, IntPtr.Zero, error, error.Length);
        }
        else
        {
            var pointers = new IntPtr[sourcePamtPaths.Length];
            try
            {
                for (var index = 0; index < sourcePamtPaths.Length; index++)
                    pointers[index] = Marshal.StringToCoTaskMemUTF8(sourcePamtPaths[index]);
                status = NativeMethods.BuildIndexFromSources(packageRoot, indexPath, pointers,
                    checked((nuint)pointers.Length), out entryCount, callback, IntPtr.Zero, error, error.Length);
            }
            finally
            {
                foreach (var pointer in pointers) Marshal.FreeCoTaskMem(pointer);
            }
        }
        GC.KeepAlive(callback);
        if (callbackException is not null)
        {
            ExceptionDispatchInfo.Capture(callbackException).Throw();
        }
        if (status == NativeStatus.Cancelled || cancellationToken.IsCancellationRequested)
        {
            throw new OperationCanceledException("Archive index build was cancelled.", cancellationToken);
        }
        ThrowIfFailed(status, DecodeUtf8NullTerminated(error), sourcePath);
        return checked((long)entryCount);
    }

    public DecodedArchiveEntry Decode(ArchiveEntryDto entry)
    {
        ArgumentNullException.ThrowIfNull(entry);
        EnsureCompatible();
        var expectedSize = entry.IsCompressed ? entry.OriginalSize : entry.StoredSize;
        // The core reads the stored bytes into a buffer of their own first, so they
        // are bounded as the output is (the review of rr/parity-deps-p20, F2).
        if (expectedSize < 0 || expectedSize > MaximumDecodedEntryBytes || expectedSize > Array.MaxLength
            || entry.StoredSize < 0 || entry.StoredSize > MaximumDecodedEntryBytes)
        {
            throw new InvalidDataException("Archive entry exceeds the one GiB decoded resource limit.");
        }

        var bytes = new byte[checked((int)expectedSize)];
        var note = new byte[256];
        var error = new byte[DiagnosticCapacity];
        var status = NativeMethods.DecodeEntryWithContext(
            entry.Path,
            entry.SourcePamt,
            entry.PazFile,
            checked((ulong)entry.Offset),
            checked((ulong)entry.StoredSize),
            checked((ulong)entry.OriginalSize),
            checked((uint)entry.Flags),
            bytes,
            checked((nuint)bytes.Length),
            out var requiredSize,
            note,
            note.Length,
            error,
            error.Length);
        if (status == NativeStatus.BufferTooSmall)
        {
            if (requiredSize > MaximumDecodedEntryBytes || requiredSize > (nuint)Array.MaxLength)
            {
                throw new InvalidDataException("Archive entry exceeds the one GiB decoded resource limit.");
            }
            bytes = new byte[checked((int)requiredSize)];
            Array.Clear(error);
            Array.Clear(note);
            status = NativeMethods.DecodeEntryWithContext(
                entry.Path,
                entry.SourcePamt,
                entry.PazFile,
                checked((ulong)entry.Offset),
                checked((ulong)entry.StoredSize),
                checked((ulong)entry.OriginalSize),
                checked((uint)entry.Flags),
                bytes,
                checked((nuint)bytes.Length),
                out requiredSize,
                note,
                note.Length,
                error,
                error.Length);
        }

        ThrowIfFailed(status, DecodeUtf8NullTerminated(error));
        if (requiredSize < (nuint)bytes.Length)
        {
            Array.Resize(ref bytes, checked((int)requiredSize));
        }
        return new DecodedArchiveEntry(bytes, DecodeUtf8NullTerminated(note));
    }

    public void EnsureCompatible()
    {
        if (AbiVersion != ExpectedAbiVersion)
        {
            throw new NativeArchiveException(
                NativeStatus.Unsupported,
                $"Archive core ABI {AbiVersion} does not match required ABI {ExpectedAbiVersion}.");
        }
    }

    internal static string DecodeUtf8NullTerminated(byte[] buffer)
    {
        var length = Array.IndexOf(buffer, (byte)0);
        return Encoding.UTF8.GetString(buffer, 0, length < 0 ? buffer.Length : length);
    }

    private static void ThrowIfFailed(NativeStatus status, string message, string? sourcePath = null)
    {
        if (status != NativeStatus.Ok)
        {
            throw new NativeArchiveException(status, string.IsNullOrWhiteSpace(message) ? "Native archive operation failed." : message, sourcePath);
        }
    }

    private static class NativeMethods
    {
        [DllImport(LibraryName, EntryPoint = "cdmw_full_archive_core_abi_version", CallingConvention = CallingConvention.Cdecl)]
        internal static extern uint GetAbiVersion();

        [DllImport(LibraryName, EntryPoint = "cdmw_full_archive_build_index_utf8", CallingConvention = CallingConvention.Cdecl)]
        internal static extern NativeStatus BuildIndex(
            [MarshalAs(UnmanagedType.LPUTF8Str)] string packageRoot,
            [MarshalAs(UnmanagedType.LPUTF8Str)] string indexPath,
            out ulong entryCount,
            [Out] byte[] errorMessage,
            int errorMessageCapacity);

        [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
        internal delegate int BuildIndexProgressCallback(
            ulong completed,
            ulong total,
            IntPtr phase,
            IntPtr currentItem,
            IntPtr userData);

        [DllImport(LibraryName, EntryPoint = "cdmw_full_archive_build_index_with_progress_utf8", CallingConvention = CallingConvention.Cdecl)]
        internal static extern NativeStatus BuildIndexWithProgress(
            [MarshalAs(UnmanagedType.LPUTF8Str)] string packageRoot,
            [MarshalAs(UnmanagedType.LPUTF8Str)] string indexPath,
            out ulong entryCount,
            BuildIndexProgressCallback progressCallback,
            IntPtr progressUserData,
            [Out] byte[] errorMessage,
            int errorMessageCapacity);

        [DllImport(LibraryName, EntryPoint = "cdmw_full_archive_build_index_from_sources_utf8", CallingConvention = CallingConvention.Cdecl)]
        internal static extern NativeStatus BuildIndexFromSources(
            [MarshalAs(UnmanagedType.LPUTF8Str)] string packageRoot,
            [MarshalAs(UnmanagedType.LPUTF8Str)] string indexPath,
            [In, MarshalAs(UnmanagedType.LPArray, SizeParamIndex = 3)] IntPtr[] pamtPaths,
            nuint pamtCount,
            out ulong entryCount,
            BuildIndexProgressCallback progressCallback,
            IntPtr progressUserData,
            [Out] byte[] errorMessage,
            int errorMessageCapacity);

        [DllImport(LibraryName, EntryPoint = "cdmw_full_archive_decode_entry_utf8", CallingConvention = CallingConvention.Cdecl)]
        internal static extern NativeStatus DecodeEntry(
            [MarshalAs(UnmanagedType.LPUTF8Str)] string virtualPath,
            [MarshalAs(UnmanagedType.LPUTF8Str)] string pazPath,
            ulong archiveOffset,
            ulong storedSize,
            ulong originalSize,
            uint flags,
            [Out] byte[] output,
            nuint outputCapacity,
            out nuint requiredSize,
            [Out] byte[] note,
            int noteCapacity,
            [Out] byte[] errorMessage,
            int errorMessageCapacity);

        [DllImport(LibraryName, EntryPoint = "cdmw_full_archive_decode_entry_with_context_utf8", CallingConvention = CallingConvention.Cdecl)]
        internal static extern NativeStatus DecodeEntryWithContext(
            [MarshalAs(UnmanagedType.LPUTF8Str)] string virtualPath,
            [MarshalAs(UnmanagedType.LPUTF8Str)] string pamtPath,
            [MarshalAs(UnmanagedType.LPUTF8Str)] string pazPath,
            ulong archiveOffset,
            ulong storedSize,
            ulong originalSize,
            uint flags,
            [Out] byte[] output,
            nuint outputCapacity,
            out nuint requiredSize,
            [Out] byte[] note,
            int noteCapacity,
            [Out] byte[] errorMessage,
            int errorMessageCapacity);
    }
}

public sealed record DecodedArchiveEntry(byte[] Bytes, string Note);

public enum NativeStatus
{
    Ok = 0,
    InvalidArgument = 1,
    IoError = 2,
    FormatError = 3,
    Unsupported = 4,
    BufferTooSmall = 5,
    Cancelled = 6,
}

public sealed class NativeArchiveException(NativeStatus status, string message, string? sourcePath = null) : Exception(message)
{
    public NativeStatus Status { get; } = status;
    public string? SourcePath { get; } = sourcePath;
}
