using System.Runtime.ExceptionServices;
using System.Runtime.InteropServices;
using System.Text;
using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.Core;

public sealed class NativeArchiveCore
{
    public const int ExpectedAbiVersion = 1;
    private const string LibraryName = "cdmw-archive-core";
    private const int DiagnosticCapacity = 4096;
    private const int MaximumDecodedEntryBytes = 1024 * 1024 * 1024;

    public int AbiVersion => checked((int)NativeMethods.GetAbiVersion());

    public long BuildIndex(
        string packageRoot,
        string indexPath,
        Action<ProgressUpdate>? progress = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(packageRoot);
        ArgumentException.ThrowIfNullOrWhiteSpace(indexPath);
        EnsureCompatible();
        var error = new StringBuilder(DiagnosticCapacity);
        Exception? callbackException = null;
        NativeMethods.BuildIndexProgressCallback callback = (completed, total, phasePointer, itemPointer, _) =>
        {
            if (cancellationToken.IsCancellationRequested)
            {
                return 1;
            }
            try
            {
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
        var status = NativeMethods.BuildIndexWithProgress(
            packageRoot,
            indexPath,
            out var entryCount,
            callback,
            IntPtr.Zero,
            error,
            error.Capacity);
        GC.KeepAlive(callback);
        if (callbackException is not null)
        {
            ExceptionDispatchInfo.Capture(callbackException).Throw();
        }
        if (status == NativeStatus.Cancelled || cancellationToken.IsCancellationRequested)
        {
            throw new OperationCanceledException("Archive index build was cancelled.", cancellationToken);
        }
        ThrowIfFailed(status, error.ToString());
        return checked((long)entryCount);
    }

    public DecodedArchiveEntry Decode(ArchiveEntryDto entry)
    {
        ArgumentNullException.ThrowIfNull(entry);
        EnsureCompatible();
        var expectedSize = entry.IsCompressed ? entry.OriginalSize : entry.StoredSize;
        if (expectedSize < 0 || expectedSize > MaximumDecodedEntryBytes || expectedSize > Array.MaxLength)
        {
            throw new InvalidDataException("Archive entry exceeds the one GiB decoded resource limit.");
        }

        var bytes = new byte[checked((int)expectedSize)];
        var note = new StringBuilder(256);
        var error = new StringBuilder(DiagnosticCapacity);
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
            note.Capacity,
            error,
            error.Capacity);
        if (status == NativeStatus.BufferTooSmall)
        {
            if (requiredSize > MaximumDecodedEntryBytes || requiredSize > (nuint)Array.MaxLength)
            {
                throw new InvalidDataException("Archive entry exceeds the one GiB decoded resource limit.");
            }
            bytes = new byte[checked((int)requiredSize)];
            error.Clear();
            note.Clear();
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
                note.Capacity,
                error,
                error.Capacity);
        }

        ThrowIfFailed(status, error.ToString());
        if (requiredSize < (nuint)bytes.Length)
        {
            Array.Resize(ref bytes, checked((int)requiredSize));
        }
        return new DecodedArchiveEntry(bytes, note.ToString());
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

    private static void ThrowIfFailed(NativeStatus status, string message)
    {
        if (status != NativeStatus.Ok)
        {
            throw new NativeArchiveException(status, string.IsNullOrWhiteSpace(message) ? "Native archive operation failed." : message);
        }
    }

    private static class NativeMethods
    {
        [DllImport(LibraryName, EntryPoint = "cdmw_archive_core_abi_version", CallingConvention = CallingConvention.Cdecl)]
        internal static extern uint GetAbiVersion();

        [DllImport(LibraryName, EntryPoint = "cdmw_archive_build_index_utf8", CallingConvention = CallingConvention.Cdecl)]
        internal static extern NativeStatus BuildIndex(
            [MarshalAs(UnmanagedType.LPUTF8Str)] string packageRoot,
            [MarshalAs(UnmanagedType.LPUTF8Str)] string indexPath,
            out ulong entryCount,
            StringBuilder errorMessage,
            int errorMessageCapacity);

        [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
        internal delegate int BuildIndexProgressCallback(
            ulong completed,
            ulong total,
            IntPtr phase,
            IntPtr currentItem,
            IntPtr userData);

        [DllImport(LibraryName, EntryPoint = "cdmw_archive_build_index_with_progress_utf8", CallingConvention = CallingConvention.Cdecl)]
        internal static extern NativeStatus BuildIndexWithProgress(
            [MarshalAs(UnmanagedType.LPUTF8Str)] string packageRoot,
            [MarshalAs(UnmanagedType.LPUTF8Str)] string indexPath,
            out ulong entryCount,
            BuildIndexProgressCallback progressCallback,
            IntPtr progressUserData,
            StringBuilder errorMessage,
            int errorMessageCapacity);

        [DllImport(LibraryName, EntryPoint = "cdmw_archive_decode_entry_utf8", CallingConvention = CallingConvention.Cdecl)]
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
            StringBuilder note,
            int noteCapacity,
            StringBuilder errorMessage,
            int errorMessageCapacity);

        [DllImport(LibraryName, EntryPoint = "cdmw_archive_decode_entry_with_context_utf8", CallingConvention = CallingConvention.Cdecl)]
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
            StringBuilder note,
            int noteCapacity,
            StringBuilder errorMessage,
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

public sealed class NativeArchiveException(NativeStatus status, string message) : Exception(message)
{
    public NativeStatus Status { get; } = status;
}
