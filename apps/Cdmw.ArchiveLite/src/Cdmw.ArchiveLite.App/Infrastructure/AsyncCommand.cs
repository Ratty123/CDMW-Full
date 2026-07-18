using System.Windows.Input;

namespace Cdmw.ArchiveLite.App.Infrastructure;

public sealed class AsyncCommand(
    Func<CancellationToken, Task> execute,
    Func<bool>? canExecute = null) : ICommand
{
    private CancellationTokenSource? _operation;
    private bool _isExecuting;

    public event EventHandler? CanExecuteChanged;

    public bool CanExecute(object? parameter) => !_isExecuting && (canExecute?.Invoke() ?? true);

    public async void Execute(object? parameter)
    {
        if (!CanExecute(parameter))
        {
            return;
        }

        _isExecuting = true;
        _operation = new CancellationTokenSource();
        RaiseCanExecuteChanged();
        try
        {
            await execute(_operation.Token).ConfigureAwait(true);
        }
        catch (OperationCanceledException)
        {
            // Cancellation is represented by the owning view model's state.
        }
        finally
        {
            _operation.Dispose();
            _operation = null;
            _isExecuting = false;
            RaiseCanExecuteChanged();
        }
    }

    public void Cancel()
    {
        try
        {
            _operation?.Cancel();
        }
        catch (ObjectDisposedException)
        {
            // The awaited operation can complete and dispose between the read and cancellation.
        }
    }

    public void RaiseCanExecuteChanged() => CanExecuteChanged?.Invoke(this, EventArgs.Empty);
}
