namespace Cdmw.FullArchive.Worker;

internal static class Program
{
    public static Task<int> Main(string[] args) => WorkerProgram.RunAsync(args);
}
